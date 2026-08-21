from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from misco_harness.models import (
    ArtifactRecord,
    ArtifactRef,
    ArtifactRegistry,
    ContextPackManifest,
    DesktopResearchContextSpec,
    Lane,
    RuntimeAccessDecision,
    RuntimePolicyValue,
    SAFE_IDENTIFIER_PATTERN,
)
from misco_harness.trace_store import atomic_write_json, sha256_file, verify_hash


class ContextBuildError(RuntimeError):
    pass


class UnknownArtifact(ContextBuildError):
    pass


class AccessDenied(ContextBuildError):
    pass


class EvidencePolicyViolation(ContextBuildError):
    pass


class ModeContamination(ContextBuildError):
    pass


_SAFE_ID = re.compile(SAFE_IDENTIFIER_PATTERN)
_RESTRICTIVENESS = {
    RuntimePolicyValue.INCLUDE: 0,
    RuntimePolicyValue.RETRIEVE: 1,
    RuntimePolicyValue.EXPLICIT_INCLUDE: 2,
    RuntimePolicyValue.HUMAN_ONLY: 3,
    RuntimePolicyValue.DENY: 4,
}
_EVENT_LANES = {
    "QUESTION_FORMATION": Lane.RESEARCH,
    "SEED_COMPARISON": Lane.RESEARCH,
    "RESEARCH_PLANNING": Lane.RESEARCH,
    "RESEARCH_RUN": Lane.RESEARCH,
    "DESKTOP_RESEARCH": Lane.RESEARCH,
    "PUBLICATION_DRAFT": Lane.PUBLICATION,
    "PUBLICATION_FINALIZATION": Lane.PUBLICATION,
    "CONTRACT_MIGRATION_REVIEW": Lane.IMPLEMENTATION,
    "EVIDENCE_MODEL_MIGRATION": Lane.IMPLEMENTATION,
    "PROVENANCE_AUDIT": Lane.IMPLEMENTATION,
    "ATTENTION_DISTILLATION": Lane.CONTROL_PLANE,
}


class ArtifactAccessPolicy:
    def __init__(self, policy_path: Path):
        with policy_path.open("r", encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
        self.roles: dict[str, dict[str, object]] = document["roles"]
        self.runtime_events: list[str] = document["runtime_events"]

    def is_known_role(self, role: str) -> bool:
        return role in self.roles

    def runtime_policy_for_role(self, role: str) -> dict[str, RuntimePolicyValue]:
        role_policy = self.roles.get(role)
        if role_policy is None:
            raise AccessDenied(f"unknown role {role!r}")
        event_policy = role_policy.get("runtime_policy", {})
        default = role_policy.get("default_runtime_policy", "DENY")
        return {
            event: RuntimePolicyValue(event_policy.get(event, default))
            for event in self.runtime_events
        }

    def denied_roles(self, event: str) -> set[str]:
        """Return roles denied by the policy authority for a runtime event."""
        denied: set[str] = set()
        for role, role_policy in self.roles.items():
            event_policy = role_policy.get("runtime_policy", {})
            default = role_policy.get("default_runtime_policy", "DENY")
            if RuntimePolicyValue(event_policy.get(event, default)) is RuntimePolicyValue.DENY:
                denied.add(role)
        return denied

    def resolve(self, artifact: ArtifactRecord, event: str, explicit: bool = False) -> RuntimeAccessDecision:
        role_policy = self.roles.get(artifact.role)
        if role_policy is None:
            return RuntimeAccessDecision(
                artifact_id=artifact.artifact_id,
                event=event,
                decision=RuntimePolicyValue.DENY,
                reason=f"unknown role {artifact.role!r}; unknown roles fail closed",
            )

        event_policy = role_policy.get("runtime_policy", {})
        baseline_raw = event_policy.get(event, role_policy.get("default_runtime_policy", "DENY"))
        baseline = RuntimePolicyValue(baseline_raw)
        record_value = artifact.runtime_policy.get(event)
        decision = baseline
        reason = f"role {artifact.role} policy for {event} is {baseline.value}"
        if record_value is not None and _RESTRICTIVENESS[record_value] > _RESTRICTIVENESS[decision]:
            decision = record_value
            reason += f"; artifact record narrows it to {record_value.value}"
        elif record_value is not None and _RESTRICTIVENESS[record_value] < _RESTRICTIVENESS[decision]:
            reason += f"; ignored broader artifact override {record_value.value}"

        if decision is RuntimePolicyValue.EXPLICIT_INCLUDE:
            if explicit:
                decision = RuntimePolicyValue.INCLUDE
                reason += "; explicit inclusion authorized"
            else:
                reason += "; explicit inclusion was not authorized"
        return RuntimeAccessDecision(
            artifact_id=artifact.artifact_id,
            event=event,
            decision=decision,
            reason=reason,
        )


class ContextBuilder:
    def __init__(self, project_root: Path, output_root: Path, policy: ArtifactAccessPolicy):
        self.project_root = project_root.resolve()
        self.output_root = output_root.resolve()
        self.policy = policy

    def build(
        self,
        *,
        pack_id: str,
        run_id: str,
        event: str,
        lane: Lane,
        registry: ArtifactRegistry,
        artifact_ids: list[str],
        required_ids: set[str] | None = None,
        explicit_include_ids: set[str] | None = None,
        evidence_input_ids: set[str] | None = None,
        mode_bridge_artifact_id: str | None = None,
        desktop_research_spec: DesktopResearchContextSpec | None = None,
        extra_forbidden_context: list[str] | None = None,
    ) -> Path:
        self._validate_id(pack_id, "pack_id")
        expected_lane = _EVENT_LANES.get(event)
        if expected_lane is None:
            raise ContextBuildError(f"unknown runtime event: {event!r}")
        if lane is not expected_lane:
            raise ContextBuildError(f"event {event} requires lane {expected_lane.value}, got {lane.value}")
        if event == "DESKTOP_RESEARCH" and desktop_research_spec is None:
            raise ContextBuildError("DESKTOP_RESEARCH requires a bounded DesktopResearchContextSpec")
        if event != "DESKTOP_RESEARCH" and desktop_research_spec is not None:
            raise ContextBuildError("DesktopResearchContextSpec is valid only for DESKTOP_RESEARCH")
        required = required_ids or set()
        explicit = explicit_include_ids or set()
        evidence = evidence_input_ids or set()
        records = {item.artifact_id: item for item in registry.artifacts}
        selected: list[ArtifactRecord] = []
        for artifact_id in artifact_ids:
            if artifact_id not in records:
                raise UnknownArtifact(f"artifact {artifact_id!r} is not registered")
            artifact = records[artifact_id]
            if artifact.status in {"INVALIDATED", "SUPERSEDED"}:
                raise AccessDenied(
                    f"artifact {artifact_id!r} is {artifact.status} and excluded from normal Context Packs"
                )
            selected.append(artifact)
        missing_required = required.difference(artifact_ids)
        if missing_required:
            raise ContextBuildError(f"required artifacts are not in the candidate set: {sorted(missing_required)}")

        decisions = [
            self.policy.resolve(item, event, item.artifact_id in explicit)
            for item in selected
        ]
        decision_by_id = {item.artifact_id: item for item in decisions}
        denied_required = [
            artifact_id
            for artifact_id in required
            if decision_by_id[artifact_id].decision not in {RuntimePolicyValue.INCLUDE, RuntimePolicyValue.RETRIEVE}
        ]
        if denied_required:
            raise AccessDenied(f"required artifacts are denied: {sorted(denied_required)}")

        for artifact_id in evidence:
            artifact = records.get(artifact_id)
            if artifact is None:
                raise UnknownArtifact(f"evidence artifact {artifact_id!r} is not registered")
            if artifact_id not in artifact_ids:
                raise EvidencePolicyViolation(f"evidence artifact {artifact_id!r} is not in the Context Pack")
            if not artifact.evidence_eligible or artifact.lane is not Lane.RESEARCH:
                raise EvidencePolicyViolation(
                    f"artifact {artifact_id!r} with role {artifact.role!r} is not eligible as Research Evidence"
                )

        accessible = [
            item for item in selected
            if decision_by_id[item.artifact_id].decision in {RuntimePolicyValue.INCLUDE, RuntimePolicyValue.RETRIEVE}
        ]
        if desktop_research_spec is not None:
            forbidden_roles = self.policy.denied_roles(event).union(desktop_research_spec.forbidden_roles)
            contaminated_roles = sorted({item.role for item in accessible if item.role in forbidden_roles})
            if contaminated_roles:
                raise AccessDenied(f"Desktop Research Context Pack contains forbidden roles: {contaminated_roles}")
            if len(accessible) > desktop_research_spec.max_context_artifacts:
                raise ContextBuildError(
                    "Desktop Research Context Pack exceeds max_context_artifacts "
                    f"({len(accessible)} > {desktop_research_spec.max_context_artifacts})"
                )
        self._validate_modes(accessible, records, mode_bridge_artifact_id)

        target = self.output_root / "context_packs" / pack_id
        if target.exists():
            raise ContextBuildError(f"immutable Context Pack already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{pack_id}.", dir=target.parent))
        try:
            included_refs: list[ArtifactRef] = []
            retrieve_refs: list[ArtifactRef] = []
            for artifact in accessible:
                source = self._source_path(artifact)
                digest = self._verified_digest(artifact, source)
                decision = decision_by_id[artifact.artifact_id].decision
                if decision is RuntimePolicyValue.INCLUDE:
                    relative = Path("artifacts") / artifact.artifact_id / source.name
                    destination = staging / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    verify_hash(destination, digest)
                    included_refs.append(ArtifactRef(artifact_id=artifact.artifact_id, path=relative.as_posix(), sha256=digest))
                else:
                    retrieve_refs.append(ArtifactRef(artifact_id=artifact.artifact_id, path=str(source), sha256=digest))

            forbidden = [
                item.artifact_id for item in selected
                if decision_by_id[item.artifact_id].decision not in {RuntimePolicyValue.INCLUDE, RuntimePolicyValue.RETRIEVE}
            ]
            if desktop_research_spec is not None:
                forbidden.extend(
                    item.artifact_id
                    for item in selected
                    if decision_by_id[item.artifact_id].decision is RuntimePolicyValue.DENY
                )
            forbidden.extend(item for item in (extra_forbidden_context or []) if item not in forbidden)
            manifest = ContextPackManifest(
                pack_id=pack_id,
                run_id=run_id,
                event=event,
                lane=lane,
                must_include=included_refs,
                retrieve_on_demand=retrieve_refs,
                forbidden_context=forbidden,
                access_decisions=decisions,
                desktop_research_spec=desktop_research_spec,
            )
            atomic_write_json(staging / "manifest.json", manifest)
            os.replace(staging, target)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    @staticmethod
    def _validate_id(value: str, label: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ContextBuildError(f"unsafe {label}: {value!r}")

    def _source_path(self, artifact: ArtifactRecord) -> Path:
        candidate = Path(artifact.path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        source = candidate.resolve()
        if not source.is_file():
            raise ContextBuildError(f"artifact source is not a file: {source}")
        return source

    @staticmethod
    def _verified_digest(artifact: ArtifactRecord, source: Path) -> str:
        digest = sha256_file(source)
        if artifact.sha256 is None:
            raise ContextBuildError(f"artifact {artifact.artifact_id!r} has no registered SHA-256")
        verify_hash(source, artifact.sha256)
        return digest

    @staticmethod
    def _validate_modes(
        artifacts: list[ArtifactRecord],
        records: dict[str, ArtifactRecord],
        bridge_artifact_id: str | None,
    ) -> None:
        modes = {item.mode for item in artifacts if item.mode is not None}
        if len(modes) < 2:
            return
        bridge = records.get(bridge_artifact_id) if bridge_artifact_id else None
        if bridge is None or bridge.role != "MODE_BRIDGE_CONTRACT" or bridge not in artifacts:
            raise ModeContamination(f"Context Pack mixes modes {sorted(modes)} without an included mode bridge contract")
