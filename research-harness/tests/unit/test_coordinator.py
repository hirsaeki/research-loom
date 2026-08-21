from __future__ import annotations

import json
from pathlib import Path

from misco_harness.coordinator import InteractiveWorkResearchCoordinator
from tests.integration.test_discovery_cycle import prepare_workspace


def _question_result(run_id: str, question: str) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "candidates": [{
            "schema_version": "0.1",
            "candidate_id": "q1",
            "question": question,
            "rationale": "bounded independent formation",
            "uncertainty": ["source availability"],
            "scope_limits": ["discovery only"],
        }],
        "counterevidence": ["candidate may be infeasible"],
        "uncertainty": ["source availability"],
        "scope_limits": ["no method selection"],
        "question_overlaps": [],
        "evidence_gap_hypotheses": [],
        "back_references": ["theme", "expectations", "attention-map"],
        "attention_map_authority": "GUIDANCE_ONLY",
        "selected_method": None,
    }


def _comparison_result(run_id: str, question: str) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "matches": ["shared scope"],
        "mismatches": [],
        "missing": ["boundary evidence"],
        "over_scoped": [],
        "proposed_baselines": [{
            "schema_version": "0.1",
            "proposal_id": "q1-baseline",
            "question": question,
            "rationale": "retained after bounded comparison",
            "uncertainty": ["human scope preference"],
            "scope_limits": ["discovery only"],
            "overlaps": [],
            "evidence_gap_hypotheses": [],
        }],
        "counterevidence": ["Seed framing may bias comparison"],
        "uncertainty": ["human scope preference"],
        "scope_limits": ["no baseline or method selected"],
        "question_overlaps": [],
        "evidence_gap_hypotheses": [],
        "back_references": ["rq-seed"],
        "attention_map_authority": "GUIDANCE_ONLY",
        "selected_method": None,
    }


def test_next_action_materializes_only_interactive_work_and_traces_observation(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="interactive-work")
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)

    action = coordinator.next_action()

    assert action.state == "WORK_EXECUTION_REQUIRED"
    assert action.task_type == "INDEPENDENT_QUESTION_CANDIDATES"
    assert Path(action.task_file or "").is_file()
    assert Path(action.context_pack or "").is_dir()
    assert Path(action.result_schema_file or "").is_file()
    assert Path(action.result_destination or "").parent == Path(action.task_file or "").parent
    assert list((tmp_path / ".rh" / "coordinator" / "traces").glob("*.json"))


def test_coordinator_refuses_to_start_mock_backend(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="mock")
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)

    action = coordinator.next_action()

    assert action.state == "ERROR"
    assert "MockWorker" in action.message
    assert orchestrator.status().total_run_count == 0


def test_run_until_stop_continues_work_and_stops_at_human_decision(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="interactive-work")
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    question = "How do local recovery rituals affect incident learning?"
    calls = 0

    def execute(action):
        nonlocal calls
        calls += 1
        output = Path(action.result_destination or "")
        if action.result_schema == "IndependentQuestionFormationHandoff":
            output.write_text(json.dumps(_question_result(action.run_id or "", question)), encoding="utf-8")
        else:
            assert action.result_schema == "SeedComparisonHandoff"
            output.write_text(json.dumps(_comparison_result(action.run_id or "", question)), encoding="utf-8")
        return output

    stopped = coordinator.run_until_stop(execute_work=execute, run_limit=5)

    assert calls == 2
    assert stopped.state == "DECISION_REQUIRED"
    assert stopped.decision_id
    assert stopped.decision_options
    assert orchestrator.status().pending_decision_ids == [stopped.decision_id]


def test_coordinator_refuses_even_an_existing_mock_decision_boundary(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="mock")
    orchestrator.continue_until_stop(run_limit=10)
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)

    action = coordinator.next_action()

    assert action.state == "ERROR"
    assert "MockWorker" in action.message
    assert orchestrator.status().pending_decision_ids
    submitted = coordinator.submit_result()
    assert submitted.state == "ERROR"
    assert "MockWorker" in submitted.message


def test_malformed_result_does_not_advance_pending_work(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="interactive-work")
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    action = coordinator.next_action()
    destination = Path(action.result_destination or "")
    destination.write_text("{}", encoding="utf-8")

    failed = coordinator.submit_result(destination)

    assert failed.state == "ERROR"
    current = orchestrator.status()
    assert current.execution_state == "WORK_EXECUTION_REQUIRED"
    assert current.pending_work is not None
    assert current.total_run_count == 0
