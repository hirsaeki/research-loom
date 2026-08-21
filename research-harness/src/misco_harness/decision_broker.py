from __future__ import annotations

from pathlib import Path
from typing import Any

from misco_harness.models import (
    DecisionRecord,
    DecisionRequest,
    DecisionKind,
    DesktopResearchHandoff,
    OrchestratorState,
    PublicationState,
)
from misco_harness.trace_store import TraceStore


class DecisionBrokerError(RuntimeError):
    pass


def method_selection_request(handoff: DesktopResearchHandoff, *, decision_id: str) -> DecisionRequest:
    options = [{
        "id": item.option_id,
        "method": item.method,
        "rationale": item.rationale,
        "addresses_gap_ids": item.addresses_gap_ids,
    } for item in handoff.candidate_next_method_options]
    reacquire_gap_ids = [item.gap_id for item in handoff.evidence_gaps if item.material and not item.resolved_by_evidence_ids]
    if reacquire_gap_ids:
        options.append({
            "id": "REACQUIRE_EXTERNAL_EVIDENCE",
            "method": "REACQUIRE_EXTERNAL_EVIDENCE",
            "rationale": "Reopen a bounded acquisition and citation protocol for evidence gaps without reusing the legacy statement as an answer.",
            "addresses_gap_ids": reacquire_gap_ids,
            "question": "Re-explore support, counterevidence, non-support, and null results for the gap.",
        })
    return DecisionRequest(
        decision_id=decision_id,
        decision_kind=DecisionKind.RESEARCH_ACTION,
        request="Select the next research method",
        status_scope="Desktop Research completed with unresolved Evidence Gaps",
        ai_recommendation="Review the candidate methods as non-binding options; do not infer selection from order",
        evidence=[item.model_dump(mode="json") for item in handoff.findings],
        counterevidence=handoff.counterevidence,
        unknowns=handoff.unknowns,
        options=options,
        downstream_impact=["The selected option authorizes protocol planning, not autonomous execution"],
        becomes_fixed=["Selected capability and any Human-specified conditions"],
        human_questions=["Which method option, if any, should be selected?", "What scope or conditions apply?"],
        resume_plan={"next_phase": "RESEARCH_PLANNING", "next_task": "DESKTOP_RESEARCH_PREPARATION"},
        references=handoff.back_references,
    )


class DecisionBroker:
    def __init__(self, store: TraceStore):
        self.store = store

    def create_packet(self, request: DecisionRequest) -> tuple[Path, Path]:
        base = Path("decisions") / request.decision_id
        json_path = self.store.write_immutable(base / "request.json", request)
        markdown_path = self.store.write_immutable_text(base / "request.md", render_decision_packet(request))
        return json_path, markdown_path

    def load_request(self, request: DecisionRequest) -> DecisionRequest:
        """Apply the immutable one-time legacy decision-kind sidecar, if any."""
        sidecar = self.store.root / "decisions" / request.decision_id / "decision_kind.json"
        if not sidecar.is_file():
            return request
        data = self.store.read_json(Path("decisions") / request.decision_id / "decision_kind.json")
        return request.model_copy(update={"decision_kind": DecisionKind(data["decision_kind"])})

    def migrate_legacy_kinds(self, mapping: dict[str, DecisionKind]) -> dict[str, object]:
        """Record a one-time typed discriminator for pre-P6 immutable requests."""
        marker_path = Path("migrations") / "decision-kind-v1.json"
        if (self.store.root / marker_path).is_file():
            return self.store.read_json(marker_path)
        if not mapping:
            raise DecisionBrokerError("legacy decision-kind migration requires a non-empty mapping")
        migrated: dict[str, str] = {}
        for decision_id, kind in mapping.items():
            request = self.store.read_json(Path("decisions") / decision_id / "request.json")
            if "decision_kind" in request and request["decision_kind"] != DecisionKind.LEGACY_UNCLASSIFIED.value:
                raise DecisionBrokerError(f"Decision {decision_id!r} already has an explicit decision_kind")
            self.store.write_immutable(
                Path("decisions") / decision_id / "decision_kind.json",
                {"decision_id": decision_id, "decision_kind": kind.value},
            )
            migrated[decision_id] = kind.value
        marker = {"migration": "decision-kind-v1", "status": "COMPLETED", "decisions": migrated}
        self.store.write_immutable(marker_path, marker)
        return marker

    def block(self, state: OrchestratorState, request: DecisionRequest, *, snapshot_id: str) -> OrchestratorState:
        if request.decision_id in state.pending_decision_ids:
            raise DecisionBrokerError(f"decision {request.decision_id!r} is already pending")
        blocked = state.model_copy(update={
            "state_id": snapshot_id,
            "pending_decision_ids": [*state.pending_decision_ids, request.decision_id],
            "prior_snapshot_id": state.state_id,
        })
        self.create_packet(request)
        self.store.snapshot("orchestrator", snapshot_id, blocked)
        self.store.write_head("state/orchestrator/head.json", blocked)
        return blocked

    def record(
        self,
        state: OrchestratorState,
        request: DecisionRequest,
        record: DecisionRecord,
        *,
        snapshot_id: str,
    ) -> OrchestratorState:
        if record.decision_id != request.decision_id:
            raise DecisionBrokerError("Decision Record does not match Decision Request")
        if record.decision_id not in state.pending_decision_ids:
            raise DecisionBrokerError(f"decision {record.decision_id!r} is not pending")
        valid_choices = {str(item.get("id")) for item in request.options if item.get("id") is not None}
        if valid_choices and record.choice not in valid_choices:
            raise DecisionBrokerError(f"choice {record.choice!r} is not a declared response option")
        record = record.model_copy(update={"decision_kind": request.decision_kind})
        self.store.write_immutable(Path("decisions") / record.decision_id / "record.json", record)
        completed_marker = f"DECISION:{record.decision_id}:{record.choice}"
        choice_plans = request.resume_plan.get("by_choice", {})
        selected_plan = choice_plans.get(record.choice, request.resume_plan) if isinstance(choice_plans, dict) else request.resume_plan
        next_phase = str(selected_plan.get("next_phase", state.phase))
        resumed = state.model_copy(update={
            "state_id": snapshot_id,
            "pending_decision_ids": [item for item in state.pending_decision_ids if item != record.decision_id],
            "completed_steps": [*state.completed_steps, completed_marker],
            "phase": next_phase,
            "terminal": next_phase == "TERMINAL",
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", snapshot_id, resumed)
        self.store.write_head("state/orchestrator/head.json", resumed)
        return resumed

    def block_publication(
        self,
        state: PublicationState,
        request: DecisionRequest,
        *,
        snapshot_id: str,
    ) -> PublicationState:
        """Create a Publication-only Human Decision without blocking Research."""
        if request.decision_id in state.pending_decision_ids:
            raise DecisionBrokerError(f"decision {request.decision_id!r} is already pending")
        blocked = state.model_copy(update={
            "state_id": snapshot_id,
            "pending_decision_ids": [*state.pending_decision_ids, request.decision_id],
            "prior_snapshot_id": state.state_id,
        })
        self.create_packet(request)
        self.store.snapshot("publication", snapshot_id, blocked)
        self.store.write_head("state/publication/head.json", blocked)
        return blocked

    def record_publication(
        self,
        state: PublicationState,
        request: DecisionRequest,
        record: DecisionRecord,
        *,
        snapshot_id: str,
    ) -> PublicationState:
        """Record a Publication-only decision without changing Research phase."""
        if record.decision_id != request.decision_id:
            raise DecisionBrokerError("Decision Record does not match Decision Request")
        if record.decision_id not in state.pending_decision_ids:
            raise DecisionBrokerError(f"decision {record.decision_id!r} is not pending")
        valid_choices = {str(item.get("id")) for item in request.options if item.get("id") is not None}
        if valid_choices and record.choice not in valid_choices:
            raise DecisionBrokerError(f"choice {record.choice!r} was not a declared response option")
        record = record.model_copy(update={"decision_kind": request.decision_kind})
        self.store.write_immutable(Path("decisions") / record.decision_id / "record.json", record)
        resumed = state.model_copy(update={
            "state_id": snapshot_id,
            "pending_decision_ids": [item for item in state.pending_decision_ids if item != record.decision_id],
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("publication", snapshot_id, resumed)
        self.store.write_head("state/publication/head.json", resumed)
        return resumed


def render_decision_packet(request: DecisionRequest) -> str:
    sections: list[tuple[str, Any]] = [
        ("Decision Request", {"decision_kind": request.decision_kind.value, "request": request.request}),
        ("Status & Scope", request.status_scope),
        ("AI Recommendation (non-binding)", request.ai_recommendation),
        ("Evidence Balance", {
            "proposed_question_baselines": [item.model_dump(mode="json") for item in request.proposed_question_baselines],
            "evidence": request.evidence, "counterevidence": request.counterevidence, "unknowns": request.unknowns,
        }),
        ("What becomes fixed", request.becomes_fixed),
        ("Issues & Risks", {"counterevidence": request.counterevidence, "unknowns": request.unknowns, "downstream_impact": request.downstream_impact}),
        ("Response Options", request.options),
        ("Human Questions / fields", request.human_questions),
        ("Resume Plan", request.resume_plan),
        ("References", request.references),
    ]
    lines = [f"# Human Decision Packet: {request.decision_id}", ""]
    for index, (title, value) in enumerate(sections, start=1):
        lines.extend([f"## {index}. {title}", "", *_markdown_value(value), ""])
    return "\n".join(lines).rstrip() + "\n"


def _markdown_value(value: Any) -> list[str]:
    if isinstance(value, dict):
        if not value:
            return ["None recorded."]
        output: list[str] = []
        for key, item in value.items():
            output.append(f"- **{str(key).replace('_', ' ').title()}**: {_inline(item)}")
        return output
    if isinstance(value, list):
        return [f"- {_inline(item)}" for item in value] or ["None recorded."]
    return [str(value)]


def _inline(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{key}={_inline(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(_inline(item) for item in value) or "none"
    return str(value)
