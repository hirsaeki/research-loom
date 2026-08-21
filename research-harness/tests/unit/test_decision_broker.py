from pathlib import Path

import pytest

from misco_harness.decision_broker import DecisionBroker, DecisionBrokerError
from misco_harness.models import DecisionRecord, DecisionRequest, OrchestratorState
from misco_harness.trace_store import ImmutableArtifactExists, TraceStore


def request() -> DecisionRequest:
    return DecisionRequest(
        decision_id="decision-question-1",
        request="Select the Question Baseline",
        status_scope="Independent candidates and Seed comparison complete",
        ai_recommendation="Adopt option A with the stated scope limit",
        evidence=["candidate coverage"], counterevidence=["limited source diversity"],
        unknowns=["feasibility in one market"],
        options=[{"id": "A", "label": "Adopt A"}, {"id": "REVISE", "label": "Request revision"}],
        downstream_impact=["Desktop Research planning can start"],
        becomes_fixed=["Question Baseline v1"],
        human_questions=["Choice", "Conditions", "Rationale"],
        resume_plan={"next_phase": "RESEARCH_PLANNING", "next_task": "desktop-research-plan"},
        references=["run-independent", "run-comparison"],
    )


def test_packet_has_json_and_all_fixed_markdown_sections(tmp_path: Path) -> None:
    broker = DecisionBroker(TraceStore(tmp_path))
    json_path, markdown_path = broker.create_packet(request())
    assert json_path.is_file()
    text = markdown_path.read_text(encoding="utf-8")
    headings = [
        "Decision Request", "Status & Scope", "AI Recommendation (non-binding)", "Evidence Balance",
        "What becomes fixed", "Issues & Risks", "Response Options", "Human Questions / fields",
        "Resume Plan", "References",
    ]
    for index, heading in enumerate(headings, start=1):
        assert f"## {index}. {heading}" in text
    with pytest.raises(ImmutableArtifactExists):
        broker.create_packet(request())


def test_decision_block_and_record_resume_without_repackaging(tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    broker = DecisionBroker(store)
    initial = OrchestratorState(state_id="os-1", phase="QUESTION_REVIEW", run_refs=["run-independent", "run-comparison"])
    pending = broker.block(initial, request(), snapshot_id="os-2")
    assert pending.pending_decision_ids == ["decision-question-1"]
    assert pending.run_refs == initial.run_refs
    resumed = broker.record(
        pending, request(),
        DecisionRecord(decision_id="decision-question-1", choice="A", conditions=["retain scope limit"], decided_by="human"),
        snapshot_id="os-3",
    )
    assert resumed.pending_decision_ids == []
    assert resumed.phase == "RESEARCH_PLANNING"
    assert resumed.run_refs == initial.run_refs
    assert resumed.prior_snapshot_id == "os-2"
    assert store.read_json("state/orchestrator/snapshots/os-2.json")["pending_decision_ids"] == ["decision-question-1"]
    assert store.read_json("decisions/decision-question-1/record.json")["choice"] == "A"


def test_record_rejects_non_pending_or_undeclared_choice(tmp_path: Path) -> None:
    broker = DecisionBroker(TraceStore(tmp_path))
    with pytest.raises(DecisionBrokerError):
        broker.record(
            OrchestratorState(state_id="os-1"), request(),
            DecisionRecord(decision_id="decision-question-1", choice="A", decided_by="human"),
            snapshot_id="os-2",
        )
    pending = OrchestratorState(state_id="os-2", pending_decision_ids=["decision-question-1"])
    with pytest.raises(DecisionBrokerError):
        broker.record(
            pending, request(),
            DecisionRecord(decision_id="decision-question-1", choice="INVENTED", decided_by="human"),
            snapshot_id="os-3",
        )
