from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .ports import AtomicCommitError, IdempotencyConflictError, StaleHeadError
from .transition_models import CommitBundle, CommitReceipt, LineageView, StateView, canonical_digest


class InMemoryResearchStateRepository:
    """Test-only transactional repository for exercising the runtime boundary.

    This is deliberately not a production persistence implementation. It exists
    to prove that the reducer/service contract is storage-neutral before a later
    SQLite adapter selects schemas, SQL, migrations, or an ORM.
    """

    def __init__(self, seed: StateView) -> None:
        self._project_ref = seed.project_ref
        self._project_config_ref = seed.project_config_ref
        self._project_config_digest = seed.project_config_digest
        self._effective_profile_set_ref = seed.effective_profile_set_ref
        self._effective_profile_set_digest = seed.effective_profile_set_digest
        self._project_config = deepcopy(dict(seed.project_config))
        self._effective_constraints = deepcopy(dict(seed.effective_constraints))
        self._source_modes = deepcopy(dict(seed.source_modes))
        self._non_reusable_refs = set(seed.non_reusable_refs)

        self._objects: dict[tuple[str, str, int], Mapping[str, Any]] = {}
        for obj in seed.objects:
            self._objects[_object_key(obj)] = deepcopy(dict(obj))
        self._snapshots: dict[str, Mapping[str, Any]] = {
            str(seed.current_snapshot["id"]): deepcopy(dict(seed.current_snapshot))
        }
        for obj in seed.objects:
            if obj.get("kind") == "snapshot":
                self._snapshots[str(obj["id"])] = deepcopy(dict(obj))

        self._decisions: dict[str, Mapping[str, Any]] = {
            str(item["id"]): deepcopy(dict(item)) for item in seed.decisions
        }
        self._lineages: dict[str, LineageView] = {item.lineage_id: item for item in seed.lineages}
        self._active_lineage_ref = seed.active_lineage_ref
        self._used_decision_ids = set(seed.used_decision_ids)
        self._adoption_refs = set(seed.adoption_refs)
        self._audit_events: dict[str, Mapping[str, Any]] = {}
        self._commits: dict[str, tuple[str, CommitReceipt]] = {}
        self.fail_next_commit = False

    def load_state_view(self, project_ref: str, lineage_ref: str) -> StateView:
        if project_ref != self._project_ref:
            raise KeyError(f"project {project_ref!r} does not resolve")
        lineage = self._lineages.get(lineage_ref)
        if lineage is None:
            raise KeyError(f"lineage {lineage_ref!r} does not resolve")
        snapshot = self._snapshots.get(lineage.head_snapshot_ref)
        if snapshot is None:
            raise KeyError(f"lineage head snapshot {lineage.head_snapshot_ref!r} does not resolve")
        objects = tuple(
            deepcopy(obj)
            for _, obj in sorted(self._objects.items(), key=lambda item: item[0])
        )
        decisions = tuple(
            deepcopy(obj)
            for _, obj in sorted(self._decisions.items())
        )
        return StateView(
            project_ref=self._project_ref,
            lineage_ref=lineage_ref,
            current_snapshot=deepcopy(snapshot),
            objects=objects,
            decisions=decisions,
            used_decision_ids=tuple(sorted(self._used_decision_ids)),
            lineages=tuple(sorted(self._lineages.values(), key=lambda item: item.lineage_id)),
            active_lineage_ref=self._active_lineage_ref,
            project_config_ref=self._project_config_ref,
            project_config_digest=self._project_config_digest,
            effective_profile_set_ref=self._effective_profile_set_ref,
            effective_profile_set_digest=self._effective_profile_set_digest,
            project_config=deepcopy(self._project_config),
            effective_constraints=deepcopy(self._effective_constraints),
            adoption_refs=tuple(sorted(self._adoption_refs)),
            non_reusable_refs=tuple(sorted(self._non_reusable_refs)),
            source_modes=deepcopy(self._source_modes),
        )

    def load_snapshot(self, snapshot_ref: str) -> Mapping[str, Any] | None:
        value = self._snapshots.get(snapshot_ref)
        return deepcopy(value) if value is not None else None

    def load_object_revision(self, kind: str, object_id: str, revision: int) -> Mapping[str, Any] | None:
        value = self._objects.get((kind, object_id, revision))
        return deepcopy(value) if value is not None else None

    def resolve_refs(self, refs: Sequence[tuple[str, str]]) -> Mapping[tuple[str, str], bool]:
        known = {(kind, object_id) for kind, object_id, _ in self._objects}
        known.update(("snapshot", snapshot_id) for snapshot_id in self._snapshots)
        known.update(("research_lineage", lineage_id) for lineage_id in self._lineages)
        return {tuple(ref): tuple(ref) in known for ref in refs}

    def find_commit_by_idempotency_key(self, idempotency_key: str) -> tuple[str, CommitReceipt] | None:
        return self._commits.get(idempotency_key)

    def commit(self, bundle: CommitBundle, *, expected_head_snapshot_digest: str) -> CommitReceipt:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise AtomicCommitError("simulated atomic persistence failure")
        if bundle.receipt is None:
            raise AtomicCommitError("CommitBundle must contain its immutable receipt")
        existing_commit = self._commits.get(bundle.idempotency_key)
        if existing_commit is not None:
            prior_digest, prior_receipt = existing_commit
            if prior_digest == bundle.request_digest:
                return prior_receipt
            raise IdempotencyConflictError("idempotency key collides with a different committed request")

        source_lineage = self._lineages.get(bundle.lineage_ref)
        if source_lineage is None:
            raise AtomicCommitError(f"source lineage {bundle.lineage_ref!r} does not resolve")
        if source_lineage.head_snapshot_digest != expected_head_snapshot_digest:
            raise StaleHeadError("Research Lineage HEAD changed before atomic commit")
        if source_lineage.head_snapshot_ref != bundle.previous_snapshot_ref or source_lineage.head_snapshot_digest != bundle.previous_snapshot_digest:
            raise StaleHeadError("CommitBundle previous Snapshot no longer matches Research Lineage HEAD")

        staged_objects = deepcopy(self._objects)
        staged_snapshots = deepcopy(self._snapshots)
        staged_decisions = deepcopy(self._decisions)
        staged_lineages = deepcopy(self._lineages)
        staged_used = set(self._used_decision_ids)
        staged_adoptions = set(self._adoption_refs)
        staged_audits = deepcopy(self._audit_events)
        staged_active = self._active_lineage_ref

        for obj in bundle.object_revisions:
            key = _object_key(obj)
            existing = staged_objects.get(key)
            if existing is not None and canonical_digest(existing) != canonical_digest(obj):
                raise AtomicCommitError(f"immutable object revision collision at {key}")
            staged_objects[key] = deepcopy(dict(obj))
        for decision in bundle.decision_records:
            decision_id = str(decision["id"])
            existing = staged_decisions.get(decision_id)
            if existing is not None and canonical_digest(existing) != canonical_digest(decision):
                raise AtomicCommitError(f"immutable Decision collision at {decision_id}")
            staged_decisions[decision_id] = deepcopy(dict(decision))

        if bundle.new_snapshot is not None:
            snapshot_id = str(bundle.new_snapshot["id"])
            if snapshot_id in staged_snapshots:
                raise AtomicCommitError(f"immutable Snapshot identity already exists: {snapshot_id}")
            staged_snapshots[snapshot_id] = deepcopy(dict(bundle.new_snapshot))
            staged_objects[_object_key(bundle.new_snapshot)] = deepcopy(dict(bundle.new_snapshot))

        for lineage in bundle.lineage_updates:
            if lineage.lineage_id not in staged_lineages:
                raise AtomicCommitError(f"cannot update unknown lineage {lineage.lineage_id}")
            staged_lineages[lineage.lineage_id] = lineage
        for lineage in bundle.new_lineages:
            if lineage.lineage_id in staged_lineages:
                raise AtomicCommitError(f"lineage identity already exists: {lineage.lineage_id}")
            if lineage.head_snapshot_ref not in staged_snapshots:
                raise AtomicCommitError("new lineage HEAD snapshot must be in the same atomic bundle")
            staged_lineages[lineage.lineage_id] = lineage

        if bundle.active_lineage_update is not None:
            if bundle.active_lineage_update not in staged_lineages:
                raise AtomicCommitError("active lineage target does not resolve")
            staged_active = bundle.active_lineage_update

        for audit in bundle.audit_events:
            audit_id = str(audit["id"])
            if audit_id in staged_audits:
                raise AtomicCommitError(f"AuditEvent identity already exists: {audit_id}")
            staged_audits[audit_id] = deepcopy(dict(audit))
            staged_objects[_object_key(audit)] = deepcopy(dict(audit))

        staged_used.update(bundle.used_decision_refs)
        staged_adoptions.update(bundle.adoption_refs)

        self._objects = staged_objects
        self._snapshots = staged_snapshots
        self._decisions = staged_decisions
        self._lineages = staged_lineages
        self._used_decision_ids = staged_used
        self._adoption_refs = staged_adoptions
        self._audit_events = staged_audits
        self._active_lineage_ref = staged_active
        self._commits[bundle.idempotency_key] = (bundle.request_digest, bundle.receipt)
        return bundle.receipt

    def debug_state(self) -> Mapping[str, Any]:
        """Stable test snapshot used only to assert all-or-nothing behavior."""
        return {
            "objects": sorted((key, canonical_digest(value)) for key, value in self._objects.items()),
            "snapshots": sorted((key, canonical_digest(value)) for key, value in self._snapshots.items()),
            "decisions": sorted((key, canonical_digest(value)) for key, value in self._decisions.items()),
            "lineages": sorted((key, asdict(value)) for key, value in self._lineages.items()),
            "active": self._active_lineage_ref,
            "used_decisions": sorted(self._used_decision_ids),
            "adoptions": sorted(self._adoption_refs),
            "audits": sorted((key, canonical_digest(value)) for key, value in self._audit_events.items()),
            "commits": sorted((key, value[0]) for key, value in self._commits.items()),
        }


def _object_key(obj: Mapping[str, Any]) -> tuple[str, str, int]:
    return (str(obj["kind"]), str(obj["id"]), int(obj.get("revision", 0)))
