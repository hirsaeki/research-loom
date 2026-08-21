from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from misco_harness.models import (
    ArtifactRegistry,
    DecisionKind,
    DecisionImpactProposal,
    DecisionImpactTreatment,
    InvalidatedLineage,
    Lane,
    PublicationState,
    RecoveryDecision,
    RecoveryImpactAssessment,
    RecoveryRecord,
    RecoveryRequest,
    RecoveryStatus,
    ReplayExecution,
    ReplayPlan,
    ResearchState,
    RunAbortRecord,
    SAFE_IDENTIFIER_PATTERN,
)
from misco_harness.trace_store import (
    TraceStore,
    atomic_write_text,
    sha256_file,
    verify_hash,
)


class RecoveryError(RuntimeError):
    pass


class LateRunResultRejected(RecoveryError):
    pass


def _validate_identifier(value: str, label: str) -> None:
    if re.fullmatch(SAFE_IDENTIFIER_PATTERN, value) is None:
        raise RecoveryError(f"unsafe {label}: {value!r}")


class RecoveryService:
    """Append-only abort and recovery application service.

    This service never copies an old snapshot over a head. A recovery head is
    always a newly identified snapshot with an explicit baseline and lineage
    reference.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.runtime = self.workspace / ".rh"
        self.store = TraceStore(self.runtime)

    def abort_pending_run(
        self,
        run_id: str,
        *,
        reason: str,
        actor: str,
        confirmation_id: str | None = None,
        decision_id: str | None = None,
        replacement: bool = True,
        semantic_change: bool = False,
    ) -> RunAbortRecord:
        self._ensure_active()
        _validate_identifier(run_id, "run_id")
        if semantic_change:
            raise RecoveryError("semantic Run changes require a Human Decision; operational abort was refused")
        run_dir = self.runtime / "runs" / run_id
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RecoveryError(f"Run does not exist: {run_id}")
        if (run_dir / "abort.json").exists() or (run_dir / "completion.json").exists():
            raise RecoveryError(f"Run is no longer pending: {run_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        state = self._orchestrator_state()
        pending_work = state.get("pending_work") or {}
        context_hash = pending_work.get("context_pack_sha256") or manifest.get("context_pack_sha256")
        requested = RunAbortRecord(
            record_id=self._id("abort-request"), run_id=run_id, status="ABORT_REQUESTED",
            reason=reason, actor=actor, confirmation_id=confirmation_id, decision_id=decision_id,
            harness_version="misco-research-harness/0.1.0", context_pack_sha256=context_hash,
        )
        self.store.write_immutable(Path("runs") / run_id / "abort_requested.json", requested)
        aborted = requested.model_copy(update={"record_id": self._id("abort"), "status": "ABORTED"})
        self.store.write_immutable(Path("runs") / run_id / "abort.json", aborted)
        if pending_work.get("run_id") == run_id:
            from misco_harness.models import OrchestratorState
            from misco_harness.orchestrator import DiscoveryOrchestrator

            current = OrchestratorState.model_validate(state)
            updated = current.model_copy(update={
                "state_id": self._id("orchestrator"),
                "execution_state": "READY",
                "pending_work": None,
                "prior_snapshot_id": current.state_id,
            })
            self.store.snapshot("orchestrator", updated.state_id, updated)
            self.store.write_head("state/orchestrator/head.json", updated)
            if replacement:
                try:
                    DiscoveryOrchestrator(self.workspace).continue_until_stop(run_limit=1)
                    next_state = self._orchestrator_state()
                    superseding = (next_state.get("pending_work") or {}).get("run_id")
                    if superseding:
                        superseded = aborted.model_copy(update={
                            "record_id": self._id("superseded"),
                            "status": "SUPERSEDED",
                            "superseding_run_id": superseding,
                        })
                        self.store.write_immutable(Path("runs") / run_id / "superseded.json", superseded)
                except Exception as error:  # noqa: BLE001 - preserve abort even if replacement is interrupted.
                    self.store.write_immutable(
                        Path("runs") / run_id / "replacement_interrupted.json",
                        {"run_id": run_id, "status": "REPLACEMENT_INTERRUPTED", "error": str(error)},
                    )
        return aborted

    def reject_late_result(self, run_id: str) -> None:
        _validate_identifier(run_id, "run_id")
        run_dir = self.runtime / "runs" / run_id
        if (run_dir / "abort.json").exists() or (run_dir / "superseded.json").exists():
            raise LateRunResultRejected(f"late result rejected for aborted or superseded Run {run_id}")

    def request(self, request: RecoveryRequest) -> RecoveryImpactAssessment:
        self._ensure_active()
        request_path = self.runtime / "recovery" / request.recovery_id / "request.json"
        if request_path.exists():
            raise RecoveryError(f"Recovery request already exists: {request.recovery_id}")
        current_id, current_hash = self._head_binding("research")
        if (request.current_head_state_id, request.current_head_sha256) != (current_id, current_hash):
            raise RecoveryError("Recovery request current Research head is stale")
        baseline_path = self._snapshot_path("research", request.known_good_baseline_state_id)
        verify_hash(baseline_path, request.known_good_baseline_sha256)
        for run_id in request.affected_run_ids:
            if not (self.runtime / "runs" / run_id / "manifest.json").is_file():
                raise RecoveryError(f"affected Run manifest does not exist: {run_id}")
        for state_id in request.affected_state_ids:
            self._snapshot_path("research", state_id)
        assessment = self._assess(request)
        self.store.write_immutable(Path("recovery") / request.recovery_id / "request.json", request)
        self.store.write_immutable(Path("recovery") / request.recovery_id / "impact_assessment.json", assessment)
        pending = RecoveryDecision(
            recovery_id=request.recovery_id, decision_id=f"decision-recovery-{request.recovery_id}",
            decided_by="PENDING_HUMAN", request_sha256=sha256_file(request_path),
            assessment_sha256=sha256_file(self.runtime / "recovery" / request.recovery_id / "impact_assessment.json"),
        )
        self.store.write_immutable(Path("recovery") / request.recovery_id / "recovery_decision.json", pending)
        self._write_packet(request, assessment, pending)
        self._record(request, RecoveryStatus.IMPACT_ASSESSED, assessment_ref="impact_assessment.json")
        return assessment

    def approve(
        self,
        recovery_id: str,
        *,
        decided_by: str,
        decision_treatments: dict[str, DecisionImpactTreatment | str],
        rationale: str | None = None,
    ) -> ReplayPlan:
        self._ensure_active()
        _validate_identifier(recovery_id, "recovery_id")
        request = RecoveryRequest.model_validate_json((self.runtime / "recovery" / recovery_id / "request.json").read_text(encoding="utf-8"))
        assessment = RecoveryImpactAssessment.model_validate_json((self.runtime / "recovery" / recovery_id / "impact_assessment.json").read_text(encoding="utf-8"))
        current_id, current_hash = self._head_binding("research")
        if (current_id, current_hash) != (request.current_head_state_id, request.current_head_sha256):
            raise RecoveryError("Recovery approval refused because the frozen current head changed")
        expected_ids = {item.decision_id for item in assessment.decision_impacts}
        treatments = {key: DecisionImpactTreatment(value) for key, value in decision_treatments.items()}
        if expected_ids != set(treatments):
            raise RecoveryError("Human Recovery Decision must classify every affected Decision")
        request_path = self.runtime / "recovery" / recovery_id / "request.json"
        assessment_path = self.runtime / "recovery" / recovery_id / "impact_assessment.json"
        decision = RecoveryDecision(
            recovery_id=recovery_id, decision_id=f"decision-recovery-{recovery_id}", status="APPROVED",
            decided_by=decided_by, decision_treatments=treatments, rationale=rationale,
            request_sha256=sha256_file(request_path), assessment_sha256=sha256_file(assessment_path),
        )
        self.store.write_immutable(Path("recovery") / recovery_id / "approved_decision.json", decision)
        for decision_id, treatment in treatments.items():
            self.store.write_immutable(
                Path("recovery") / recovery_id / "decision_impact" / f"{decision_id}.json",
                {
                    "recovery_id": recovery_id,
                    "decision_id": decision_id,
                    "treatment": treatment.value,
                    "back_reference": f"recovery/{recovery_id}/approved_decision.json",
                    "requires_new_human_review": treatment in {DecisionImpactTreatment.RECONFIRM, DecisionImpactTreatment.INVALIDATE},
                },
            )
        lineage_refs: list[str] = []
        artifact_ids = set(assessment.affected_artifact_ids)
        registry_roles: dict[str, str] = {}
        registry_path = self.runtime / "registry" / "artifact_registry.json"
        if registry_path.is_file():
            registry = ArtifactRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
            registry_roles = {item.artifact_id: item.role for item in registry.artifacts}
        for run_id in request.affected_run_ids:
            manifest_path = self.runtime / "runs" / run_id / "manifest.json"
            refs: list[str] = []
            original_hash: str | None = None
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                refs = [str(item.get("artifact_id")) for item in manifest.get("input_refs", []) if item.get("artifact_id")]
                artifact_ids.update(
                    item for item in refs
                    if registry_roles.get(item) in {"RESEARCH_STATE", "SOURCE_EVIDENCE"}
                )
                original_hash = sha256_file(manifest_path)
            lineage = InvalidatedLineage(
                lineage_id=self._id("lineage"), recovery_id=recovery_id, run_id=run_id,
                artifact_ids=sorted(refs), original_sha256=original_hash, status="INVALIDATED",
                reason_code=request.reason_code,
            )
            self.store.write_immutable(Path("recovery") / recovery_id / "lineage" / f"{lineage.lineage_id}.json", lineage)
            lineage_refs.append(str(Path("recovery") / recovery_id / "lineage" / f"{lineage.lineage_id}.json"))
        for state_id in request.affected_state_ids:
            lineage = InvalidatedLineage(
                lineage_id=self._id("lineage"), recovery_id=recovery_id, state_id=state_id,
                artifact_ids=[], status="INVALIDATED", reason_code=request.reason_code,
            )
            self.store.write_immutable(Path("recovery") / recovery_id / "lineage" / f"{lineage.lineage_id}.json", lineage)
            lineage_refs.append(str(Path("recovery") / recovery_id / "lineage" / f"{lineage.lineage_id}.json"))
        self._invalidate_registry(sorted(artifact_ids), recovery_id)
        baseline = ResearchState.model_validate_json(self._snapshot_path("research", request.known_good_baseline_state_id).read_text(encoding="utf-8"))
        recovery_state = baseline.model_copy(update={
            "state_id": self._id("research-recovery"), "prior_snapshot_id": current_id,
            "recovery_id": recovery_id, "recovery_baseline_state_id": baseline.state_id,
            "invalidated_lineage_ids": [Path(ref).stem for ref in lineage_refs],
            "recovery_uncertainty": assessment.unknowns,
        })
        recovery_path = self.store.snapshot("research", recovery_state.state_id, recovery_state)
        self.store.write_head("state/research/head.json", recovery_state)
        self._register_snapshot(recovery_state.state_id, recovery_path)
        self._mark_publication_stale(request, recovery_state.state_id)
        self._advance_orchestrator_head(current_id, recovery_state.state_id, treatments)
        plan = ReplayPlan(
            plan_id=self._id("replay-plan"), recovery_id=recovery_id, approved_decision_id=decision.decision_id,
            known_good_baseline_state_id=baseline.state_id, known_good_baseline_sha256=request.known_good_baseline_sha256,
            recovery_state_id=recovery_state.state_id, recovery_state_sha256=sha256_file(recovery_path),
            replay_phase=request.proposed_replay_phase,
        )
        self.store.write_immutable(Path("recovery") / recovery_id / "replay_plan.json", plan)
        self._record(request, RecoveryStatus.REPLAY_PLANNED, assessment_ref="impact_assessment.json", decision_ref="approved_decision.json", replay_plan_ref="replay_plan.json", lineage_refs=lineage_refs, new_head_state_id=recovery_state.state_id)
        return plan

    def replay(self, recovery_id: str) -> ReplayExecution:
        self._ensure_active()
        _validate_identifier(recovery_id, "recovery_id")
        plan = ReplayPlan.model_validate_json((self.runtime / "recovery" / recovery_id / "replay_plan.json").read_text(encoding="utf-8"))
        if plan.status != "APPROVED":
            raise RecoveryError("recovery replay requires an approved immutable Replay Plan")
        if (self.runtime / "recovery" / recovery_id / "replay_execution.json").exists():
            raise RecoveryError("the approved Replay Plan has already been executed")
        current_id, current_hash = self._head_binding("research")
        if (current_id, current_hash) != (plan.recovery_state_id, plan.recovery_state_sha256):
            raise RecoveryError("replay refused because the recovery snapshot changed")
        before = set(self._orchestrator_state().get("run_refs", []))
        try:
            from misco_harness.orchestrator import DiscoveryOrchestrator

            orchestrator = DiscoveryOrchestrator(self.workspace)
            if orchestrator.plan() is None:
                raise RecoveryError("no approved replay work is currently runnable")
            orchestrator.continue_until_stop(run_limit=1)
            after = set(self._orchestrator_state().get("run_refs", []))
            new_run_ids = sorted(after - before)
            if not new_run_ids:
                raise RecoveryError("replay did not create a new Run ID")
            execution = ReplayExecution(
                execution_id=self._id("replay"), recovery_id=recovery_id, plan_id=plan.plan_id,
                status="REPLAYED", new_run_ids=new_run_ids, resulting_state_id=self._head_binding("research")[0],
            )
            self.store.write_immutable(Path("recovery") / recovery_id / "replay_execution.json", execution)
            self._record_from_recovery_id(recovery_id, RecoveryStatus.REPLAYED, replay_plan_ref="replay_plan.json", new_head_state_id=execution.resulting_state_id)
            return execution
        except Exception as error:
            execution = ReplayExecution(
                execution_id=self._id("replay"), recovery_id=recovery_id, plan_id=plan.plan_id,
                status="INTERRUPTED", uncertainty=[f"replay interrupted: {type(error).__name__}: {error}"],
            )
            self.store.write_immutable(
                Path("recovery") / recovery_id / f"replay_interrupted-{execution.execution_id}.json",
                execution,
            )
            self._record_from_recovery_id(recovery_id, RecoveryStatus.INTERRUPTED, replay_plan_ref="replay_plan.json", uncertainty=execution.uncertainty)
            if isinstance(error, RecoveryError):
                raise
            raise RecoveryError(str(error)) from error

    def show(self, recovery_id: str) -> dict[str, Any]:
        _validate_identifier(recovery_id, "recovery_id")
        directory = self.runtime / "recovery" / recovery_id
        if not directory.is_dir():
            raise RecoveryError(f"Recovery does not exist: {recovery_id}")
        result: dict[str, Any] = {}
        for name in ("request.json", "impact_assessment.json", "approved_decision.json", "replay_plan.json", "replay_execution.json", "replay_interrupted.json"):
            path = directory / name
            if path.is_file():
                result[name] = json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("replay_interrupted-*.json"):
            result[path.name] = json.loads(path.read_text(encoding="utf-8"))
        return result

    def _assess(self, request: RecoveryRequest) -> RecoveryImpactAssessment:
        artifacts: set[str] = set()
        registry_path = self.runtime / "registry" / "artifact_registry.json"
        registry_roles: dict[str, str] = {}
        if registry_path.is_file():
            registry = ArtifactRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
            registry_roles = {item.artifact_id: item.role for item in registry.artifacts}
        for run_id in request.affected_run_ids:
            path = self.runtime / "runs" / run_id / "manifest.json"
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                artifacts.update(
                    str(item["artifact_id"])
                    for item in data.get("input_refs", [])
                    if item.get("artifact_id") and registry_roles.get(str(item["artifact_id"])) in {"RESEARCH_STATE", "SOURCE_EVIDENCE"}
                )
        # Affected state snapshots are lineage artifacts. Contract, policy,
        # and task inputs remain active unless a separate explicit defect says
        # they are affected; replay must not invalidate its own contracts.
        artifacts.update(request.affected_state_ids)
        decisions: list[DecisionImpactProposal] = []
        for path in (self.runtime / "decisions").glob("*/request.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            refs = {str(item) for item in data.get("references", [])}
            if refs.intersection(set(request.affected_run_ids) | set(request.affected_state_ids)) or data.get("decision_kind") not in {
                None,
                DecisionKind.LEGACY_UNCLASSIFIED.value,
            }:
                decisions.append(DecisionImpactProposal(
                    decision_id=str(data.get("decision_id")), proposed_treatment=DecisionImpactTreatment.RECONFIRM,
                    rationale="Recovery may change the admissible basis; Human must classify the treatment.",
                    basis_references=sorted(refs),
                ))
        publications: list[dict[str, Any]] = []
        pub_path = self.runtime / "state" / "publication" / "head.json"
        if pub_path.is_file():
            pub = json.loads(pub_path.read_text(encoding="utf-8"))
            if pub.get("source_research_state_id") in request.affected_state_ids or request.downstream_consumers:
                publications.append({"publication_state_id": pub.get("state_id"), "status": "REVIEW_REQUIRED", "reason": "affected Research lineage is a Publication dependency"})
        unknowns = ["Decision treatment remains a Human semantic choice."]
        if not publications:
            unknowns.append("No bounded Publication dependency was found in the current head.")
        return RecoveryImpactAssessment(
            recovery_id=request.recovery_id, affected_run_ids=request.affected_run_ids,
            affected_state_ids=request.affected_state_ids, affected_artifact_ids=sorted(artifacts),
            decision_impacts=decisions, publication_impacts=publications,
            invalidated_context_exclusions=sorted(artifacts), unknowns=unknowns,
        )

    def _invalidate_registry(self, artifact_ids: list[str], recovery_id: str) -> None:
        path = self.runtime / "registry" / "artifact_registry.json"
        if not path.is_file() or not artifact_ids:
            return
        registry = ArtifactRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        records = [item.model_copy(update={"status": "INVALIDATED", "superseded_by": recovery_id}) if item.artifact_id in artifact_ids else item for item in registry.artifacts]
        updated = ArtifactRegistry(artifacts=records)
        self.store.write_immutable(Path("registry") / "snapshots" / f"recovery-{recovery_id}.json", updated)
        self.store.write_head("registry/artifact_registry.json", updated)

    def _register_snapshot(self, state_id: str, path: Path) -> None:
        registry_path = self.runtime / "registry" / "artifact_registry.json"
        if not registry_path.is_file():
            return
        registry = ArtifactRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        if any(item.artifact_id == state_id for item in registry.artifacts):
            return
        from misco_harness.orchestrator import DiscoveryOrchestrator

        record = DiscoveryOrchestrator(self.workspace)._record(state_id, path, "RESEARCH_STATE", Lane.RESEARCH)
        self.store.write_head("registry/artifact_registry.json", ArtifactRegistry(artifacts=[*registry.artifacts, record]))

    def _mark_publication_stale(self, request: RecoveryRequest, recovery_state_id: str) -> None:
        path = self.runtime / "state" / "publication" / "head.json"
        if not path.is_file():
            return
        current = PublicationState.model_validate_json(path.read_text(encoding="utf-8"))
        affected = current.source_research_state_id in request.affected_state_ids or bool(request.downstream_consumers)
        if not affected:
            return
        updated = current.model_copy(update={"state_id": self._id("publication-stale"), "status": "STALE", "prior_snapshot_id": current.state_id})
        self.store.snapshot("publication", updated.state_id, updated)
        self.store.write_head("state/publication/head.json", updated)

    def _advance_orchestrator_head(
        self,
        prior_id: str,
        recovery_state_id: str,
        treatments: dict[str, DecisionImpactTreatment],
    ) -> None:
        path = self.runtime / "state" / "orchestrator" / "head.json"
        if not path.is_file():
            return
        from misco_harness.models import OrchestratorState

        current = OrchestratorState.model_validate_json(path.read_text(encoding="utf-8"))
        pending = list(current.pending_decision_ids)
        for decision_id, treatment in treatments.items():
            if treatment in {DecisionImpactTreatment.RECONFIRM, DecisionImpactTreatment.INVALIDATE} and decision_id not in pending:
                pending.append(decision_id)
        updated = current.model_copy(update={
            "state_id": self._id("orchestrator-recovery"),
            "current_question_snapshot_id": recovery_state_id,
            "pending_decision_ids": pending,
            "prior_snapshot_id": current.state_id,
        })
        self.store.snapshot("orchestrator", updated.state_id, updated)
        self.store.write_head("state/orchestrator/head.json", updated)

    def _write_packet(self, request: RecoveryRequest, assessment: RecoveryImpactAssessment, decision: RecoveryDecision) -> None:
        lines = [
            f"# Human Recovery Decision Packet: {request.recovery_id}", "",
            f"Reason: `{request.reason_code.value}`", f"Defect: {request.defect_summary}",
            f"Affected Runs: {', '.join(request.affected_run_ids)}", f"Baseline: `{request.known_good_baseline_state_id}`",
            "", "## Human treatment required", "",
        ]
        for item in assessment.decision_impacts:
            lines.append(f"- `{item.decision_id}`: choose `PRESERVE`, `RECONFIRM`, or `INVALIDATE`.")
        lines.extend(["", "Recovery approval does not authorize unlisted replay work. Publication impact remains Human review.", ""])
        atomic_write_text(self.runtime / "recovery" / request.recovery_id / "decision_packet.md", "\n".join(lines))

    def _record(self, request: RecoveryRequest, status: RecoveryStatus, *, assessment_ref: str | None = None, decision_ref: str | None = None, replay_plan_ref: str | None = None, lineage_refs: list[str] | None = None, new_head_state_id: str | None = None, uncertainty: list[str] | None = None) -> None:
        record = RecoveryRecord(
            record_id=self._id("recovery-record"), recovery_id=request.recovery_id, status=status,
            request_ref="request.json", assessment_ref=assessment_ref, decision_ref=decision_ref,
            replay_plan_ref=replay_plan_ref, invalidated_lineage_refs=lineage_refs or [],
            prior_head_state_id=request.current_head_state_id, new_head_state_id=new_head_state_id,
            uncertainty=uncertainty or [],
        )
        self.store.write_immutable(Path("recovery") / request.recovery_id / "records" / f"{record.record_id}.json", record)

    def _record_from_recovery_id(self, recovery_id: str, status: RecoveryStatus, *, replay_plan_ref: str | None = None, new_head_state_id: str | None = None, uncertainty: list[str] | None = None) -> None:
        request = RecoveryRequest.model_validate_json((self.runtime / "recovery" / recovery_id / "request.json").read_text(encoding="utf-8"))
        self._record(request, status, replay_plan_ref=replay_plan_ref, new_head_state_id=new_head_state_id, uncertainty=uncertainty)

    def _orchestrator_state(self) -> dict[str, Any]:
        path = self.runtime / "state" / "orchestrator" / "head.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _ensure_active(self) -> None:
        if self._orchestrator_state().get("lifecycle_status", "ACTIVE") == "ARCHIVED":
            raise RecoveryError("workspace is archived; Recovery state changes are disabled")

    def _head_binding(self, kind: str) -> tuple[str, str]:
        path = self.runtime / "state" / kind / "head.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["state_id"]), sha256_file(path)

    def _snapshot_path(self, kind: str, snapshot_id: str) -> Path:
        path = self.runtime / "state" / kind / "snapshots" / f"{snapshot_id}.json"
        if not path.is_file():
            raise RecoveryError(f"immutable {kind} snapshot does not exist: {snapshot_id}")
        return path

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
