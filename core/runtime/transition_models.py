from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence


DIGEST_PREFIX = "sha256:"


class TransitionKind(str, Enum):
    """Closed runtime vocabulary expressed in Research State semantics."""

    CREATE_OBJECT = "CREATE_OBJECT"
    REVISE_OBJECT = "REVISE_OBJECT"
    ADOPT_OBJECT = "ADOPT_OBJECT"
    REJECT_OBJECT = "REJECT_OBJECT"
    VERIFY_EVIDENCE = "VERIFY_EVIDENCE"
    RECLASSIFY_EVIDENCE = "RECLASSIFY_EVIDENCE"
    RECORD_DECISION = "RECORD_DECISION"
    APPLY_LINEAGE_PLAN = "APPLY_LINEAGE_PLAN"
    SWITCH_ACTIVE_LINEAGE = "SWITCH_ACTIVE_LINEAGE"
    RECORD_RUN_RESULT_ADOPTION = "RECORD_RUN_RESULT_ADOPTION"
    REGISTER_WRITING_FEEDBACK_ACTION = "REGISTER_WRITING_FEEDBACK_ACTION"


class ValidationStage(str, Enum):
    SCHEMA = "A_SCHEMA"
    PINS = "B_INPUT_PINS"
    EXPECTED_HEAD = "C_EXPECTED_HEAD"
    AUTHORIZATION = "D_AUTHORIZATION"
    HUMAN_DECISION = "E_HUMAN_DECISION"
    REFERENCE_INTEGRITY = "F_REFERENCE_INTEGRITY"
    CORE_INVARIANTS = "G_CORE_INVARIANTS"
    PROFILE_CONSTRAINTS = "H_PROFILE_CONSTRAINTS"
    PROJECT_GUARDS = "I_PROJECT_GUARDS"
    ADOPTION_BOUNDARIES = "J_ADOPTION_BOUNDARIES"
    LINEAGE = "K_LINEAGE"
    EPISTEMIC_FIREWALL = "L_EPISTEMIC_FIREWALL"
    NEXT_STATE = "M_NEXT_STATE"
    COMMIT_BUNDLE = "N_COMMIT_BUNDLE"
    PERSISTENCE = "P_PERSISTENCE"


@dataclass(frozen=True)
class Actor:
    actor_id: str
    actor_type: str


@dataclass(frozen=True)
class SnapshotRef:
    snapshot_id: str
    revision: int
    content_digest: str
    mode: str

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "SnapshotRef":
        return cls(
            snapshot_id=str(snapshot["id"]),
            revision=int(snapshot.get("revision", 0)),
            content_digest=str(snapshot["content_digest"]),
            mode=str(snapshot.get("mode", "real")),
        )


@dataclass(frozen=True)
class ObjectRef:
    kind: str
    id: str


@dataclass(frozen=True)
class TransitionAction:
    kind: TransitionKind
    payload: Mapping[str, Any] = field(default_factory=dict)
    decision_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    def object_payload(self) -> Mapping[str, Any] | None:
        value = self.payload.get("object")
        return value if isinstance(value, Mapping) else None

    def target_ref(self) -> ObjectRef | None:
        obj = self.object_payload()
        if obj is not None and "kind" in obj and "id" in obj:
            return ObjectRef(str(obj["kind"]), str(obj["id"]))
        target = self.payload.get("target")
        if isinstance(target, Mapping) and "kind" in target and "id" in target:
            return ObjectRef(str(target["kind"]), str(target["id"]))
        return None


@dataclass(frozen=True)
class StateTransitionRequest:
    transition_id: str
    project_ref: str
    lineage_ref: str
    expected_head_snapshot_ref: str
    expected_head_snapshot_digest: str
    actor: Actor
    actions: tuple[TransitionAction, ...]
    project_config_ref: str
    project_config_digest: str
    effective_profile_set_ref: str
    effective_profile_set_digest: str
    authorization_evidence: tuple[str, ...]
    idempotency_key: str
    submitted_at: str
    new_snapshot_id: str
    commit_id: str
    audit_event_id: str
    source_refs: tuple[str, ...] = ()
    request_digest: str = ""

    def digest_basis(self) -> Mapping[str, Any]:
        data = asdict(self)
        data.pop("request_digest", None)
        return data

    def calculated_digest(self) -> str:
        return canonical_digest(self.digest_basis())

    def with_calculated_digest(self) -> "StateTransitionRequest":
        return replace(self, request_digest=self.calculated_digest())


@dataclass(frozen=True)
class StateDeltaProposal:
    proposal_id: str
    project_ref: str
    lineage_ref: str
    source_refs: tuple[str, ...]
    proposed_actions: tuple[TransitionAction, ...]
    affected_refs: tuple[ObjectRef, ...]
    rationale: str
    required_human_decision_kinds: tuple[str, ...]
    current_snapshot_ref: str
    current_snapshot_digest: str
    provenance: Mapping[str, Any]
    candidate_only: bool = True
    proposal_digest: str = ""

    def calculated_digest(self) -> str:
        data = asdict(self)
        data.pop("proposal_digest", None)
        return canonical_digest(data)

    def with_calculated_digest(self) -> "StateDeltaProposal":
        return replace(self, proposal_digest=self.calculated_digest())


@dataclass(frozen=True)
class LineageView:
    lineage_id: str
    lineage_kind: str
    head_snapshot_ref: str
    head_snapshot_digest: str
    head_snapshot_revision: int
    execution_mode: str
    status: str = "active"
    parent_lineage_ref: str | None = None
    baseline_snapshot_ref: str | None = None
    project_config_ref: str | None = None
    project_config_digest: str | None = None
    effective_profile_set_ref: str | None = None
    effective_profile_set_digest: str | None = None


@dataclass(frozen=True)
class StateView:
    project_ref: str
    lineage_ref: str
    current_snapshot: Mapping[str, Any]
    objects: tuple[Mapping[str, Any], ...]
    decisions: tuple[Mapping[str, Any], ...]
    used_decision_ids: tuple[str, ...]
    lineages: tuple[LineageView, ...]
    active_lineage_ref: str
    project_config_ref: str
    project_config_digest: str
    effective_profile_set_ref: str
    effective_profile_set_digest: str
    project_config: Mapping[str, Any] = field(default_factory=dict)
    effective_constraints: Mapping[str, Any] = field(default_factory=dict)
    adoption_refs: tuple[str, ...] = ()
    non_reusable_refs: tuple[str, ...] = ()
    source_modes: Mapping[str, str] = field(default_factory=dict)

    @property
    def current_snapshot_ref(self) -> SnapshotRef:
        return SnapshotRef.from_snapshot(self.current_snapshot)

    def lineage(self, lineage_id: str) -> LineageView | None:
        for lineage in self.lineages:
            if lineage.lineage_id == lineage_id:
                return lineage
        return None

    def exact_object(self, kind: str, object_id: str, revision: int) -> Mapping[str, Any] | None:
        for obj in self.objects:
            if obj.get("kind") == kind and obj.get("id") == object_id and int(obj.get("revision", -1)) == revision:
                return obj
        return None

    def latest_object(self, kind: str, object_id: str) -> Mapping[str, Any] | None:
        matches = [
            obj for obj in self.objects
            if obj.get("kind") == kind and obj.get("id") == object_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda obj: int(obj.get("revision", -1)))

    def decision(self, decision_id: str) -> Mapping[str, Any] | None:
        matches = [obj for obj in self.decisions if obj.get("id") == decision_id]
        if not matches:
            return None
        return max(matches, key=lambda obj: int(obj.get("revision", -1)))

    def snapshot_members(self) -> tuple[Mapping[str, Any], ...]:
        members = self.current_snapshot.get("members", ())
        return tuple(member for member in members if isinstance(member, Mapping))

    def effective_objects(self) -> tuple[Mapping[str, Any], ...]:
        result: list[Mapping[str, Any]] = []
        for member in self.snapshot_members():
            obj = self.exact_object(str(member["kind"]), str(member["id"]), int(member["revision"]))
            if obj is not None:
                result.append(obj)
        return tuple(result)


@dataclass(frozen=True)
class ValidationIssue:
    error_code: str
    stage: ValidationStage
    message: str
    affected_refs: tuple[str, ...] = ()
    retryable: bool = False


@dataclass(frozen=True)
class ReductionResult:
    object_revisions: tuple[Mapping[str, Any], ...]
    decision_records: tuple[Mapping[str, Any], ...]
    new_snapshot: Mapping[str, Any] | None
    lineage_updates: tuple[LineageView, ...]
    new_lineages: tuple[LineageView, ...]
    active_lineage_update: str | None
    adoption_refs: tuple[str, ...]
    used_decision_refs: tuple[str, ...]
    audit_events: tuple[Mapping[str, Any], ...]
    applied_actions: tuple[str, ...]


@dataclass(frozen=True)
class CommitReceipt:
    transition_id: str
    commit_id: str
    prior_snapshot_ref: str
    prior_snapshot_digest: str
    new_snapshot_ref: str | None
    new_snapshot_digest: str | None
    lineage_ref: str
    applied_typed_actions: tuple[str, ...]
    resolving_decision_refs: tuple[str, ...]
    bundle_digest: str
    timestamp: str
    actor: Actor
    idempotency_key: str


@dataclass(frozen=True)
class CommitBundle:
    transition_id: str
    commit_id: str
    project_ref: str
    lineage_ref: str
    idempotency_key: str
    request_digest: str
    previous_snapshot_ref: str
    previous_snapshot_digest: str
    object_revisions: tuple[Mapping[str, Any], ...]
    decision_records: tuple[Mapping[str, Any], ...]
    new_snapshot: Mapping[str, Any] | None
    lineage_updates: tuple[LineageView, ...]
    new_lineages: tuple[LineageView, ...]
    active_lineage_update: str | None
    adoption_refs: tuple[str, ...]
    audit_events: tuple[Mapping[str, Any], ...]
    used_decision_refs: tuple[str, ...]
    applied_actions: tuple[str, ...]
    receipt: CommitReceipt | None = None
    bundle_digest: str = ""

    def calculated_digest(self) -> str:
        data = asdict(self)
        data.pop("bundle_digest", None)
        data.pop("receipt", None)
        return canonical_digest(data)

    def with_digest_and_receipt(self, request: StateTransitionRequest) -> "CommitBundle":
        digest = self.calculated_digest()
        snapshot = self.new_snapshot
        receipt = CommitReceipt(
            transition_id=self.transition_id,
            commit_id=self.commit_id,
            prior_snapshot_ref=self.previous_snapshot_ref,
            prior_snapshot_digest=self.previous_snapshot_digest,
            new_snapshot_ref=str(snapshot["id"]) if snapshot is not None else None,
            new_snapshot_digest=str(snapshot["content_digest"]) if snapshot is not None else None,
            lineage_ref=self.lineage_ref,
            applied_typed_actions=self.applied_actions,
            resolving_decision_refs=self.used_decision_refs,
            bundle_digest=digest,
            timestamp=request.submitted_at,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        )
        return replace(self, bundle_digest=digest, receipt=receipt)


@dataclass(frozen=True)
class StateTransitionRejected:
    transition_id: str
    issues: tuple[ValidationIssue, ...]
    current_head_snapshot_ref: str | None = None
    current_head_snapshot_digest: str | None = None

    @property
    def retryable(self) -> bool:
        return bool(self.issues) and all(issue.retryable for issue in self.issues)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_digest(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


def with_content_digest(payload: Mapping[str, Any], field_name: str = "content_digest") -> dict[str, Any]:
    data = dict(payload)
    data.pop(field_name, None)
    data[field_name] = canonical_digest(data)
    return data


def stable_sorted_objects(objects: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        sorted(
            objects,
            key=lambda obj: (
                str(obj.get("kind", "")),
                str(obj.get("id", "")),
                int(obj.get("revision", -1)),
            ),
        )
    )
