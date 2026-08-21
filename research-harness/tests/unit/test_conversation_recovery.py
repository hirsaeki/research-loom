import json
from pathlib import Path

import pytest

from misco_harness.conversation import WorkConversationCoordinator
from misco_harness.models import ChatTurnInput, RecoveryRequest
from misco_harness.orchestrator import OrchestratorError
from misco_harness.recovery import RecoveryService
from misco_harness.trace_store import sha256_file
from tests.integration.test_discovery_cycle import prepare_workspace


def test_chat_text_is_read_only_and_unknown_actions_fail_closed(tmp_path: Path) -> None:
    prepare_workspace(tmp_path, worker_backend="interactive-work")
    client = WorkConversationCoordinator(tmp_path)
    before = (tmp_path / ".rh" / "state" / "orchestrator" / "head.json").read_bytes()

    text_result = client.propose_action("NOT_AN_ACTION", actor="human", parameters={})
    assert text_result.receipt is not None
    assert text_result.receipt.status == "REJECTED"
    assert (tmp_path / ".rh" / "state" / "orchestrator" / "head.json").read_bytes() == before

    natural = client.propose(ChatTurnInput(turn_id="turn-1", actor="human", text="Please change the research question"))
    assert natural.proposal is None
    assert (tmp_path / ".rh" / "state" / "orchestrator" / "head.json").read_bytes() == before


def test_confirmation_is_state_bound_single_use_and_receipted(tmp_path: Path) -> None:
    prepare_workspace(tmp_path, worker_backend="interactive-work")
    client = WorkConversationCoordinator(tmp_path)
    proposed = client.propose_action(
        "STOP_AT_BOUNDARY", actor="human", parameters={"reason": "review boundary"}
    )
    assert proposed.confirmation_request is not None
    confirmation_id = proposed.confirmation_request.confirmation_id

    accepted = client.confirm(confirmation_id, actor="human")
    assert accepted.receipt is not None
    assert accepted.receipt.status == "ACCEPTED"
    duplicate = client.confirm(confirmation_id, actor="human")
    assert duplicate.receipt is not None
    assert duplicate.receipt.status == "REJECTED"
    assert "single-use" in duplicate.receipt.reason

    stale = client.propose_action("STOP_AT_BOUNDARY", actor="human", parameters={})
    assert stale.confirmation_request is not None
    state_path = tmp_path / ".rh" / "state" / "orchestrator" / "head.json"
    current = json.loads(state_path.read_text(encoding="utf-8"))
    current["state_id"] = "manually-changed-for-stale-test"
    state_path.write_text(json.dumps(current), encoding="utf-8")
    rejected = client.confirm(stale.confirmation_request.confirmation_id, actor="human")
    assert rejected.receipt is not None
    assert rejected.receipt.status == "REJECTED"
    assert "stale" in rejected.receipt.reason


def test_pending_run_abort_preserves_trace_replaces_run_and_rejects_late_result(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="interactive-work")
    waiting = orchestrator.continue_until_stop(run_limit=1)
    assert waiting.pending_work is not None
    old_run = waiting.pending_work.run_id
    replacement = RecoveryService(tmp_path).abort_pending_run(
        old_run, reason="operator requested clean replacement", actor="human", replacement=True
    )
    assert replacement.status == "ABORTED"
    assert (tmp_path / ".rh" / "runs" / old_run / "manifest.json").is_file()
    assert (tmp_path / ".rh" / "runs" / old_run / "abort.json").is_file()
    resumed = orchestrator.status()
    assert resumed.pending_work is not None
    assert resumed.pending_work.run_id != old_run
    with pytest.raises(OrchestratorError, match="late result rejected"):
        orchestrator.collect_work_result(old_run, Path("missing-result.json"))


def test_recovery_approval_creates_new_lineage_and_replay_run(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="mock")
    stopped = orchestrator.continue_until_stop(run_limit=10)
    decision_id = stopped.pending_decision_ids[0]
    orchestrator.record_decision(decision_id, choice="ADOPT_PROPOSED_BASELINES", decided_by="human")
    current_research = json.loads((tmp_path / ".rh" / "state" / "research" / "head.json").read_text(encoding="utf-8"))
    research_head = tmp_path / ".rh" / "state" / "research" / "head.json"
    run_id = orchestrator.status().run_refs[0]
    recovery_id = "recovery-test"
    request = RecoveryRequest(
        recovery_id=recovery_id, requested_by="human", reason_code="REDUCER_DEFECT",
        affected_run_ids=[run_id], affected_state_ids=[current_research["state_id"]],
        known_good_baseline_state_id=current_research["state_id"], known_good_baseline_sha256=sha256_file(research_head),
        defect_summary="focused reducer failure injection", proposed_replay_phase="RESEARCH_PLANNING",
        current_head_state_id=current_research["state_id"], current_head_sha256=sha256_file(research_head),
    )
    assessment = RecoveryService(tmp_path).request(request)
    assert assessment.bounded is True
    plan = RecoveryService(tmp_path).approve(
        recovery_id, decided_by="human",
        decision_treatments={item.decision_id: "PRESERVE" for item in assessment.decision_impacts},
    )
    assert plan.recovery_state_id != current_research["state_id"]
    assert json.loads(research_head.read_text(encoding="utf-8"))["recovery_id"] == recovery_id
    result = RecoveryService(tmp_path).replay(recovery_id)
    assert result.status == "REPLAYED"
    assert result.new_run_ids
    assert all(item != run_id for item in result.new_run_ids)


def test_recovery_rejects_baseline_hash_mismatch(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="mock")
    orchestrator.continue_until_stop(run_limit=1)
    head = tmp_path / ".rh" / "state" / "research" / "head.json"
    state = json.loads(head.read_text(encoding="utf-8"))
    request = RecoveryRequest(
        recovery_id="hash-mismatch", requested_by="human", reason_code="SCHEMA_DEFECT",
        affected_run_ids=[orchestrator.status().run_refs[0]], affected_state_ids=[state["state_id"]],
        known_good_baseline_state_id=state["state_id"], known_good_baseline_sha256="0" * 64,
        defect_summary="hash mismatch", proposed_replay_phase="QUESTION_FORMATION",
        current_head_state_id=state["state_id"], current_head_sha256=sha256_file(head),
    )
    with pytest.raises(Exception, match="hash mismatch"):
        RecoveryService(tmp_path).request(request)
