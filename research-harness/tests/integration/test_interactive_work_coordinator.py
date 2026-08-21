"""Adversarial integration coverage for the Interactive Work coordinator.

These tests deliberately drive the coordinator through its public client-side
loop.  The fake executor represents human/Work execution: it can only write
the structured result in the exchange directory and cannot mutate Harness
state directly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from misco_harness.coordinator import InteractiveWorkResearchCoordinator
from misco_harness.orchestrator import DiscoveryOrchestrator

PROJECT_ROOT = Path(__file__).parents[2]


def prepare_workspace(tmp_path: Path) -> DiscoveryOrchestrator:
    """Create the smallest explicit real-workspace fixture for coordinator tests."""

    for relative in (
        "contracts/runtime_artifact_policy.yaml",
        "contracts/research_harness_v0.4.md",
        "contracts/research_constitution.md",
        "contracts/capabilities/desktop-research/desktop_research_contract.md",
        "contracts/capabilities/desktop-research/source_policy.yaml",
        "contracts/publication_parallel_lane.md",
        "contracts/publication_structure.schema.yaml",
        "maps/research_attention_and_initial_publication_map.md",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = PROJECT_ROOT / relative
        if relative == "maps/research_attention_and_initial_publication_map.md":
            source = PROJECT_ROOT / "tests" / "fixtures" / "attention_map.md"
        shutil.copyfile(source, destination)
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    seed = tmp_path / "quarantine" / "seed.md"
    seed.parent.mkdir(parents=True, exist_ok=True)
    theme.write_text("MISCO research theme", encoding="utf-8")
    expectations.write_text("Generate independent questions first", encoding="utf-8")
    seed.write_text("Provisional prior RQ", encoding="utf-8")
    orchestrator = DiscoveryOrchestrator(tmp_path)
    orchestrator.initialize(
        theme=theme,
        expectations=expectations,
        seed=seed,
        worker_backend="interactive-work",
    )
    return orchestrator


def independent_handoff(run_id: str, *, back_references: list[str] | None = None) -> dict[str, object]:
    return {
        "run_id": run_id,
        "candidates": [
            {
                "candidate_id": "q-arbitrary",
                "question": "How do arbitrary coordination signals affect cross-team recovery?",
                "rationale": "bounded independent formation",
                "uncertainty": ["source availability"],
                "scope_limits": ["cross-team recovery only"],
            }
        ],
        "counterevidence": ["candidate may be infeasible"],
        "uncertainty": ["source availability"],
        "scope_limits": ["no method selection"],
        "question_overlaps": ["candidate dimensions overlap"],
        "evidence_gap_hypotheses": [
            {
                "gap_id": "gap-independent",
                "hypothesis": "sources may be sparse",
                "why_material": "scope may change",
            }
        ],
        "back_references": back_references or ["theme", "expectations", "harness-contract", "constitution"],
        "attention_map_authority": "GUIDANCE_ONLY",
        "selected_method": None,
    }


def comparison_handoff(run_id: str, snapshot_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "matches": ["shared mechanism"],
        "mismatches": ["different scope"],
        "missing": ["boundary evidence"],
        "over_scoped": ["Seed population"],
        "proposed_baselines": [
            {
                "proposal_id": "baseline-arbitrary",
                "question": "How do arbitrary coordination signals affect cross-team recovery?",
                "rationale": "retained after bounded Seed comparison",
                "uncertainty": ["human scope preference"],
                "scope_limits": ["cross-team recovery only"],
                "overlaps": ["partial overlap"],
                "evidence_gap_hypotheses": [
                    {
                        "gap_id": "gap-comparison",
                        "hypothesis": "context boundary is unknown",
                        "why_material": "affects scope",
                    }
                ],
            }
        ],
        "counterevidence": ["Seed framing bias"],
        "uncertainty": ["human scope preference"],
        "scope_limits": ["no baseline or method selected"],
        "question_overlaps": ["partial overlap"],
        "evidence_gap_hypotheses": [
            {
                "gap_id": "gap-comparison",
                "hypothesis": "context boundary is unknown",
                "why_material": "affects scope",
            }
        ],
        "back_references": [snapshot_id, "rq-seed"],
        "attention_map_authority": "GUIDANCE_ONLY",
        "selected_method": None,
    }


def write_result(action, payload: dict[str, object]) -> Path:
    destination = Path(action.result_destination)
    destination.write_text(json.dumps(payload), encoding="utf-8")
    return destination


def test_coordinator_autonomously_continues_work_until_human_decision(tmp_path: Path) -> None:
    orchestrator = prepare_workspace(tmp_path)
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    executed: list[str] = []

    def fake_work(action):
        executed.append(action.task_type)
        if action.result_schema == "IndependentQuestionFormationHandoff":
            return write_result(action, independent_handoff(action.run_id))
        assert action.result_schema == "SeedComparisonHandoff"
        snapshot_id = orchestrator.status().current_question_snapshot_id
        assert snapshot_id is not None
        return write_result(action, comparison_handoff(action.run_id, snapshot_id))

    stopped = coordinator.run_until_stop(execute_work=fake_work, run_limit=5)

    assert stopped.state == "DECISION_REQUIRED"
    assert executed == ["INDEPENDENT_QUESTION_CANDIDATES", "SEED_COMPARISON"]
    assert orchestrator.status().phase == "QUESTION_REVIEW"
    assert len(orchestrator.status().pending_decision_ids) == 1
    assert len(list((tmp_path / ".rh" / "coordinator" / "traces").glob("*.json"))) >= 4


def test_decision_boundary_is_a_hard_stop_and_resume_needs_human_record(tmp_path: Path) -> None:
    orchestrator = prepare_workspace(tmp_path)
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    executed: list[str] = []

    def fake_work(action):
        executed.append(action.task_type)
        if action.result_schema == "IndependentQuestionFormationHandoff":
            return write_result(action, independent_handoff(action.run_id))
        snapshot_id = orchestrator.status().current_question_snapshot_id
        assert snapshot_id is not None
        return write_result(action, comparison_handoff(action.run_id, snapshot_id))

    pending = coordinator.run_until_stop(execute_work=fake_work, run_limit=5)
    assert pending.state == "DECISION_REQUIRED"
    decision_id = pending.decision_id
    assert decision_id is not None
    before = orchestrator.status()

    # An AI recommendation is presentation-only. Re-entering the loop cannot
    # select an option or execute a post-decision task.
    again = coordinator.run_until_stop(execute_work=fake_work, run_limit=5)
    assert again.state == "DECISION_REQUIRED"
    assert again.decision_id == decision_id
    assert orchestrator.status().state_id == before.state_id
    assert executed == ["INDEPENDENT_QUESTION_CANDIDATES", "SEED_COMPARISON"]

    resumed_state = orchestrator.record_decision(
        decision_id,
        choice="ADOPT_PROPOSED_BASELINES",
        decided_by="human",
        rationale="Human accepted the bounded proposal.",
    )
    assert resumed_state.phase == "RESEARCH_PLANNING"
    resumed = coordinator.next_action()
    assert resumed.state == "WORK_EXECUTION_REQUIRED"
    assert resumed.task_type == "DESKTOP_RESEARCH_PREPARATION"


def test_malformed_or_audit_violating_result_cannot_advance_state(tmp_path: Path) -> None:
    orchestrator = prepare_workspace(tmp_path)
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    first = coordinator.next_action()
    assert first.state == "WORK_EXECUTION_REQUIRED"
    before = orchestrator.status()
    result_path = Path(first.result_destination)

    result_path.write_text("{not valid json", encoding="utf-8")
    malformed = coordinator.submit_result(result_path)
    assert malformed.state == "ERROR"
    assert orchestrator.status().state_id == before.state_id
    assert orchestrator.status().pending_work is not None

    # This is schema-valid but violates the independent Context Pack's
    # forbidden Seed boundary. It must fail in audit and keep the same run
    # pending instead of silently reducing/advancing Research State.
    result_path.write_text(
        json.dumps(independent_handoff(first.run_id, back_references=["rq-seed"])),
        encoding="utf-8",
    )
    violating = coordinator.submit_result(result_path)
    assert violating.state == "ERROR"
    current = orchestrator.status()
    assert current.state_id == before.state_id
    assert current.total_run_count == 0
    assert current.phase == "QUESTION_FORMATION"
    assert current.pending_work is not None
    assert current.pending_work.run_id == first.run_id
    failed_submissions = list((tmp_path / ".rh" / "runs" / first.run_id / "submissions").glob("*.json"))
    assert len(failed_submissions) == 1
    assert not (tmp_path / ".rh" / "runs" / first.run_id / "worker_result.json").exists()

    # Harness-owned recovery accepts a corrected result for the same pending
    # run; the Coordinator neither skips ahead nor patches state directly.
    result_path.write_text(json.dumps(independent_handoff(first.run_id)), encoding="utf-8")
    recovered = coordinator.submit_result(result_path)
    assert recovered.state == "WORK_EXECUTION_REQUIRED"
    assert recovered.result_schema == "SeedComparisonHandoff"
    assert orchestrator.status().total_run_count == 1


def test_work_context_isolation_seed_and_publication_firewall_are_preserved(tmp_path: Path) -> None:
    orchestrator = prepare_workspace(tmp_path)
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    first = coordinator.next_action()
    assert first.state == "WORK_EXECUTION_REQUIRED"
    pack = Path(first.context_pack)
    before = {str(path.relative_to(pack)): path.read_bytes() for path in pack.rglob("*") if path.is_file()}
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))

    assert "rq-seed" in manifest["forbidden_context"]
    assert "rq-seed" not in {item["artifact_id"] for item in manifest["must_include"]}
    assert not any("PUBLICATION" in str(item) for item in manifest["must_include"])
    registry = json.loads(
        (tmp_path / ".rh" / "registry" / "artifact_registry.json").read_text(encoding="utf-8")
    )
    roles = {item["artifact_id"]: item["role"] for item in registry["artifacts"]}
    selected = {
        item["artifact_id"]
        for item in [*manifest["must_include"], *manifest["retrieve_on_demand"]]
    }
    assert not any(
        roles.get(artifact_id)
        in {
            "PUBLICATION_DRAFT",
            "PUBLICATION_FEEDBACK",
            "CLEAN_PUBLICATION_SOURCE",
            "FORMAL_PUBLICATION_SPEC",
        }
        for artifact_id in selected
    )

    write_result(first, independent_handoff(first.run_id))
    second = coordinator.submit_result()
    after = {str(path.relative_to(pack)): path.read_bytes() for path in pack.rglob("*") if path.is_file()}
    assert after == before
    assert second.state == "WORK_EXECUTION_REQUIRED"
    assert second.result_schema == "SeedComparisonHandoff"
    second_manifest = json.loads((Path(second.context_pack) / "manifest.json").read_text(encoding="utf-8"))
    included = {item["artifact_id"] for item in second_manifest["must_include"]}
    assert "rq-seed" in included
    snapshot_id = orchestrator.status().current_question_snapshot_id
    assert snapshot_id is not None
    assert snapshot_id in included


def test_context_pack_tampering_is_detected_before_execution_or_collection(tmp_path: Path) -> None:
    orchestrator = prepare_workspace(tmp_path)
    coordinator = InteractiveWorkResearchCoordinator(tmp_path, orchestrator=orchestrator)
    action = coordinator.next_action()
    before = orchestrator.status()
    manifest = Path(action.context_pack) / "manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    observed = coordinator.next_action()
    assert observed.state == "ERROR"
    assert "tree hash" in observed.message
    assert orchestrator.status().state_id == before.state_id

    result = Path(action.result_destination)
    result.write_text(json.dumps(independent_handoff(action.run_id)), encoding="utf-8")
    submitted = coordinator.submit_result(result)
    assert submitted.state == "ERROR"
    assert "tree hash" in submitted.message
    assert orchestrator.status().total_run_count == 0
