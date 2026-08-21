from pathlib import Path

import pytest

from misco_harness.decision_broker import DecisionBroker
from misco_harness.models import DecisionKind, DecisionRequest, WorkerResult
from misco_harness.orchestrator import DiscoveryOrchestrator, OrchestratorError
from misco_harness.trace_store import TraceStore


def _legacy_request() -> DecisionRequest:
    return DecisionRequest(
        decision_id="decision-legacy-1",
        request="Classify the legacy decision",
        status_scope="Migration test",
        ai_recommendation="No binding recommendation",
        evidence=["bounded fixture"],
        counterevidence=[],
        unknowns=["legacy kind is absent"],
        options=[{"id": "APPROVE", "label": "Approve"}],
        downstream_impact=["Migration only"],
        becomes_fixed=["Typed decision kind"],
        human_questions=["Kind"],
        resume_plan={"next_phase": "TEST"},
        references=["fixture"],
    )


def test_legacy_decision_kind_migration_is_typed_and_one_time(tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    broker = DecisionBroker(store)
    request = _legacy_request()
    broker.create_packet(request)

    marker = broker.migrate_legacy_kinds({request.decision_id: DecisionKind.QUESTION_BASELINE})
    assert marker["status"] == "COMPLETED"
    assert broker.load_request(request).decision_kind is DecisionKind.QUESTION_BASELINE

    no_op = broker.migrate_legacy_kinds({request.decision_id: DecisionKind.METHOD_PROTOCOL})
    assert no_op == marker


def test_question_candidates_merge_by_identity_and_missing_identity_fails_closed() -> None:
    result = WorkerResult(
        run_id="run-candidates",
        observed=[
            {"candidate_id": "candidate-b", "question": "Question B", "rationale": "observed B"},
            {"candidate_id": "candidate-a", "question": "Question A", "rationale": "observed A"},
        ],
        question_delta_candidate=[
            {"candidate_id": "candidate-a", "question": "Question A", "reason": "delta A"},
            {"candidate_id": "candidate-b", "question": "Question B", "reason": "delta B"},
        ],
    )

    proposals = DiscoveryOrchestrator._proposed_baselines(result)

    assert [item.proposal_id for item in proposals] == ["candidate-a", "candidate-b"]
    assert [item.rationale for item in proposals] == ["observed A", "observed B"]

    with pytest.raises(OrchestratorError, match="stable proposal_id or candidate_id"):
        DiscoveryOrchestrator._proposed_baselines(WorkerResult(
            run_id="run-missing-identity",
            question_delta_candidate=[{"question": "No stable identity"}],
        ))

    with pytest.raises(OrchestratorError, match="duplicated"):
        DiscoveryOrchestrator._proposed_baselines(WorkerResult(
            run_id="run-duplicate-identity",
            question_delta_candidate=[
                {"candidate_id": "candidate-1", "question": "Duplicate one"},
                {"candidate_id": "candidate-1", "question": "Duplicate two"},
            ],
        ))
