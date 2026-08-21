import hashlib
import json
import shutil
from pathlib import Path

import pytest

from misco_harness.orchestrator import DiscoveryOrchestrator
from misco_harness.state_reducer import ReductionBlocked

PROJECT_ROOT = Path(__file__).parents[2]


def prepare_workspace(tmp_path: Path, *, worker_backend: str = "mock") -> tuple[DiscoveryOrchestrator, Path]:
    (tmp_path / "contracts").mkdir()
    (tmp_path / "maps").mkdir()
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
        source = PROJECT_ROOT / relative
        if relative == "maps/research_attention_and_initial_publication_map.md":
            source = PROJECT_ROOT / "tests" / "fixtures" / "attention_map.md"
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    seed = tmp_path / "quarantine" / "seed.md"
    seed.parent.mkdir()
    theme.write_text("MISCO research theme", encoding="utf-8")
    expectations.write_text("Generate independent questions first", encoding="utf-8")
    seed.write_text("Provisional prior RQ", encoding="utf-8")
    orchestrator = DiscoveryOrchestrator(tmp_path)
    orchestrator.initialize(theme=theme, expectations=expectations, seed=seed, worker_backend=worker_backend)
    registry = json.loads((tmp_path / ".rh" / "registry" / "artifact_registry.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in registry["artifacts"]}
    assert {"DESKTOP_RESEARCH_CONTRACT", "DESKTOP_RESEARCH_SOURCE_POLICY"} <= roles
    return orchestrator, seed


def test_first_discovery_cycle_needs_no_manual_context_transport(tmp_path: Path) -> None:
    orchestrator, seed = prepare_workspace(tmp_path)
    first_stop = orchestrator.continue_until_stop(run_limit=10)
    assert first_stop.phase == "QUESTION_REVIEW"
    assert len(first_stop.run_refs) == 2
    assert first_stop.total_run_count == 2
    assert len(first_stop.pending_decision_ids) == 1

    independent_pack = next(
        path for path in (tmp_path / ".rh" / "context_packs").iterdir()
        if json.loads((path / "manifest.json").read_text(encoding="utf-8"))["event"] == "QUESTION_FORMATION"
    )
    independent_manifest = json.loads((independent_pack / "manifest.json").read_text(encoding="utf-8"))
    assert "rq-seed" in independent_manifest["forbidden_context"]
    assert not any(ref["artifact_id"] == "rq-seed" for ref in independent_manifest["must_include"])

    comparison_pack = next(
        path for path in (tmp_path / ".rh" / "context_packs").iterdir()
        if json.loads((path / "manifest.json").read_text(encoding="utf-8"))["event"] == "SEED_COMPARISON"
    )
    comparison_manifest = json.loads((comparison_pack / "manifest.json").read_text(encoding="utf-8"))
    assert "rq-seed" in {ref["artifact_id"] for ref in comparison_manifest["must_include"]}
    assert any(ref["artifact_id"].startswith("research-") for ref in comparison_manifest["must_include"])
    assert seed.read_text(encoding="utf-8") == "Provisional prior RQ"

    question_decision = first_stop.pending_decision_ids[0]
    resumed = orchestrator.record_decision(question_decision, choice="ADOPT_PROPOSED_BASELINES", decided_by="human")
    assert resumed.phase == "RESEARCH_PLANNING"
    research_head = json.loads((tmp_path / ".rh" / "state" / "research" / "head.json").read_text(encoding="utf-8"))
    assert research_head["questions"][0]["status"] == "BASELINE"
    assert research_head["questions"][0]["decision_id"] == question_decision
    second_stop = orchestrator.continue_until_stop(run_limit=10)
    assert second_stop.phase == "METHOD_REVIEW"
    assert len(second_stop.run_refs) == 3
    assert second_stop.total_run_count == 3
    assert len(second_stop.pending_decision_ids) == 1

    planning_pack = next(
        path for path in (tmp_path / ".rh" / "context_packs").iterdir()
        if json.loads((path / "manifest.json").read_text(encoding="utf-8"))["event"] == "RESEARCH_PLANNING"
    )
    planning_manifest = json.loads((planning_pack / "manifest.json").read_text(encoding="utf-8"))
    assert "rq-seed" in planning_manifest["forbidden_context"]
    assert not any("PUBLICATION_DRAFT" in str(item) for item in planning_manifest["must_include"])

    method_decision = second_stop.pending_decision_ids[0]
    desktop_ready = orchestrator.record_decision(method_decision, choice="APPROVE", decided_by="human")
    assert desktop_ready.phase == "DESKTOP_RESEARCH"
    research_stop = orchestrator.continue_until_stop(run_limit=10)
    assert research_stop.phase == "DESKTOP_RESEARCH_REVIEW"
    assert research_stop.pending_decision_ids

    run_dirs = list((tmp_path / ".rh" / "runs").iterdir())
    assert len(run_dirs) == 4
    for run_dir in run_dirs:
        run_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert run_manifest["context_pack_id"]
        assert run_manifest["input_refs"]
        assert (run_dir / "worker_result.json").is_file() or (run_dir / "desktop_research_handoff.json").is_file()
        assert (run_dir / "audit.json").is_file()
        assert (run_dir / "state_delta_proposal.json").is_file()
        assert (run_dir / "research_handoff.json").is_file()
    desktop_run = next(
        run_dir
        for run_dir in run_dirs
        if json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["task_type"] == "DESKTOP_RESEARCH"
    )
    assert (desktop_run / "evidence_snapshots" / "mock-evidence-1.txt").is_file()
    mock_handoff = json.loads((desktop_run / "desktop_research_handoff.json").read_text(encoding="utf-8"))
    assert mock_handoff["evidence"][0]["snapshot_path"] == str(
        (desktop_run / "evidence_snapshots" / "mock-evidence-1.txt").resolve()
    )


def test_run_limit_stops_autonomy_after_one_run(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path)
    state = orchestrator.continue_until_stop(run_limit=1)
    assert state.phase == "SEED_COMPARISON"
    assert len(state.run_refs) == 1
    assert state.total_run_count == 1


def test_interactive_work_discovery_uses_same_transitions_and_isolation(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="interactive-work")
    first_wait = orchestrator.continue_until_stop(run_limit=10)
    assert first_wait.execution_state == "WORK_EXECUTION_REQUIRED"
    assert first_wait.phase == "QUESTION_FORMATION"
    assert first_wait.total_run_count == 0
    first_request = first_wait.pending_work
    assert first_request is not None
    assert first_request.expected_output_schema == "IndependentQuestionFormationHandoff"
    assert Path(first_request.task_file).is_file()
    assert Path(first_request.expected_output_schema_file).parent == Path(first_request.exchange_directory)
    first_pack_before = {str(path.relative_to(first_request.context_pack)): path.read_bytes() for path in Path(first_request.context_pack).rglob("*") if path.is_file()}
    first_manifest = json.loads(Path(first_request.manifest).read_text(encoding="utf-8"))
    assert "rq-seed" in first_manifest["forbidden_context"]
    assert "rq-seed" not in {item["artifact_id"] for item in first_manifest["must_include"]}
    first_result = Path(first_request.expected_output_file)
    first_result.write_text(json.dumps({
        "schema_version": "0.1", "run_id": first_request.run_id,
        "candidates": [{"schema_version": "0.1", "candidate_id": "q1", "question": "How do arbitrary coordination signals affect cross-team recovery?", "rationale": "formed without Seed", "uncertainty": ["feasibility"], "scope_limits": ["cross-team recovery only"]}],
        "counterevidence": ["candidate may be infeasible"], "uncertainty": ["source availability"],
        "scope_limits": ["no method selection"], "question_overlaps": ["candidate dimensions overlap"],
        "evidence_gap_hypotheses": [{"schema_version": "0.1", "gap_id": "g1", "hypothesis": "sources may be sparse", "why_material": "scope may change"}],
        "back_references": ["theme", "expectations", "attention-map"],
        "attention_map_authority": "GUIDANCE_ONLY", "selected_method": None,
    }), encoding="utf-8")
    second_wait = orchestrator.collect_work_result(first_request.run_id, first_result)
    first_pack_after = {str(path.relative_to(first_request.context_pack)): path.read_bytes() for path in Path(first_request.context_pack).rglob("*") if path.is_file()}
    assert first_pack_after == first_pack_before
    assert second_wait.execution_state == "WORK_EXECUTION_REQUIRED"
    assert second_wait.phase == "SEED_COMPARISON"
    assert second_wait.total_run_count == 1
    immutable_independent_id = second_wait.current_question_snapshot_id
    assert immutable_independent_id is not None
    immutable_path = tmp_path / ".rh" / "state" / "research" / "snapshots" / f"{immutable_independent_id}.json"
    immutable_bytes = immutable_path.read_bytes()
    second_request = second_wait.pending_work
    assert second_request is not None
    assert second_request.expected_output_schema == "SeedComparisonHandoff"
    second_manifest = json.loads(Path(second_request.manifest).read_text(encoding="utf-8"))
    included = {item["artifact_id"] for item in second_manifest["must_include"]}
    assert {"rq-seed", immutable_independent_id} <= included
    second_result = Path(second_request.expected_output_file)
    second_result.write_text(json.dumps({
        "schema_version": "0.1", "run_id": second_request.run_id,
        "matches": ["shared mechanism"], "mismatches": ["different scope"], "missing": ["boundary evidence"], "over_scoped": ["Seed population"],
        "proposed_baselines": [{
            "schema_version": "0.1", "proposal_id": "arbitrary-baseline",
            "question": "How do arbitrary coordination signals affect cross-team recovery?",
            "rationale": "retained after bounded Seed comparison", "uncertainty": ["human scope preference"],
            "scope_limits": ["cross-team recovery only"], "overlaps": ["partial overlap"],
            "evidence_gap_hypotheses": [{"schema_version": "0.1", "gap_id": "g2", "hypothesis": "context boundary is unknown", "why_material": "affects scope"}],
        }],
        "counterevidence": ["Seed framing bias"], "uncertainty": ["human scope preference"],
        "scope_limits": ["no baseline or method selected"], "question_overlaps": ["partial overlap"],
        "evidence_gap_hypotheses": [{"schema_version": "0.1", "gap_id": "g2", "hypothesis": "context boundary is unknown", "why_material": "affects scope"}],
        "back_references": [immutable_independent_id, "rq-seed"],
        "attention_map_authority": "GUIDANCE_ONLY", "selected_method": None,
    }), encoding="utf-8")
    stopped = orchestrator.collect_work_result(second_request.run_id, second_result)
    assert stopped.phase == "QUESTION_REVIEW"
    assert stopped.execution_state == "READY"
    assert stopped.total_run_count == 2
    assert stopped.pending_decision_ids
    assert immutable_path.read_bytes() == immutable_bytes
    research = json.loads((tmp_path / ".rh" / "state" / "research" / "head.json").read_text(encoding="utf-8"))
    assert research["question_overlaps"] == ["candidate dimensions overlap", "partial overlap"]
    assert [item["gap_id"] for item in research["evidence_gap_hypotheses"]] == ["g1", "g2"]
    decision_id = stopped.pending_decision_ids[0]
    packet = json.loads((tmp_path / ".rh" / "decisions" / decision_id / "request.json").read_text(encoding="utf-8"))
    proposal = packet["proposed_question_baselines"][0]
    assert proposal["question"] == "How do arbitrary coordination signals affect cross-team recovery?"
    assert proposal["scope_limits"] == ["cross-team recovery only"]
    assert proposal["uncertainty"] == ["human scope preference"]
    assert proposal["overlaps"] == ["partial overlap"]
    adopted = orchestrator.record_decision(decision_id, choice="ADOPT_PROPOSED_BASELINES", decided_by="human")
    assert adopted.phase == "RESEARCH_PLANNING"
    research = json.loads((tmp_path / ".rh" / "state" / "research" / "head.json").read_text(encoding="utf-8"))
    assert research["questions"][0]["text"] == "How do arbitrary coordination signals affect cross-team recovery?"
    assert research["questions"][0]["decision_id"] == decision_id

    planning_wait = orchestrator.continue_until_stop(run_limit=10)
    planning_request = planning_wait.pending_work
    assert planning_request is not None
    assert planning_request.expected_output_schema == "WorkerResult"
    planning_result = Path(planning_request.expected_output_file)
    planning_result.write_text(json.dumps({
        "schema_version": "0.1", "run_id": planning_request.run_id,
        "observed": ["Approved baseline loaded"], "derived": ["Bounded source protocol proposed"],
        "interpreted": [], "counterevidence": ["Coverage not executed"], "unknown": ["Source availability"],
        "scope_limits": ["Protocol preparation only"], "question_overlaps": [], "evidence_gap_hypotheses": [],
        "question_delta_candidate": [], "next_evidence_request": [],
        "back_references": [adopted.current_question_snapshot_id, "harness-contract", "constitution"],
        "issues": [], "selected_method": None,
    }), encoding="utf-8")
    method_stop = orchestrator.collect_work_result(planning_request.run_id, planning_result)
    assert method_stop.phase == "METHOD_REVIEW"
    method_decision = method_stop.pending_decision_ids[0]
    desktop_phase = orchestrator.record_decision(method_decision, choice="APPROVE", decided_by="human")
    assert desktop_phase.phase == "DESKTOP_RESEARCH"
    desktop_wait = orchestrator.continue_until_stop(run_limit=10)
    desktop_request = desktop_wait.pending_work
    assert desktop_request is not None
    assert desktop_request.expected_output_schema == "DesktopResearchHandoff"
    desktop_manifest = json.loads(Path(desktop_request.manifest).read_text(encoding="utf-8"))
    assert {
        "WORKING_PAPER", "PREPRINT", "INDUSTRY_REPORT", "CORPORATE_PUBLICATION",
        "SOCIAL_MEDIA", "ONLINE_FORUM", "OTHER",
    } <= set(
        desktop_manifest["desktop_research_spec"]["allowed_source_types"]
    )
    desktop_pack_before = {str(path.relative_to(desktop_request.context_pack)): path.read_bytes() for path in Path(desktop_request.context_pack).rglob("*") if path.is_file()}
    desktop_result = Path(desktop_request.expected_output_file)
    snapshot_text = "Candidate coordination pattern in the bounded source section."
    snapshot_path = Path(desktop_request.exchange_directory) / "evidence_snapshots" / "e-real-1.txt"
    snapshot_path.write_text(snapshot_text, encoding="utf-8")
    desktop_result.write_text(json.dumps({
        "schema_version": "0.1", "run_id": desktop_request.run_id,
        "question_impact": {"schema_version": "0.1", "status": "HUMAN_DECISION_REQUIRED", "rationale": "scope needs review"},
        "findings": [{"schema_version": "0.1", "finding_id": "f-real-1", "statement": "Candidate coordination pattern", "evidence_ids": ["e-real-1"], "status": "CANDIDATE", "decision_id": None}],
        "evidence": [{"schema_version": "0.1", "evidence_id": "e-real-1", "source_id": "source-real-1", "source_type": "PEER_REVIEWED_RESEARCH", "source_quality": "HIGH", "locator": "p. 12", "captured_statement": "Candidate coordination pattern", "acquired_at": "2026-08-17T01:02:03Z", "text_snapshot": snapshot_text, "snapshot_path": str(snapshot_path.resolve()), "snapshot_sha256": hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest(), "excerpt_locator_pairs": [{"schema_version": "0.1", "excerpt": "Candidate coordination pattern", "locator": "p. 12"}], "evidence_kind": "SUPPORTING", "support_scope": "DESCRIPTIVE_CONTEXT", "material": True, "independent_support_source_ids": [], "limitations": ["single context"]}],
        "counterevidence": ["Contrary context"], "counterevidence_search_summary": "Searched contrary and null findings",
        "unknowns": ["Boundary condition"],
        "evidence_gaps": [{"schema_version": "0.1", "gap_id": "dr-gap-1", "description": "Boundary evidence missing", "material": True}],
        "candidate_next_method_options": [{"schema_version": "0.1", "option_id": "method-hold", "method": "HOLD", "rationale": "Review gap before method choice", "addresses_gap_ids": ["dr-gap-1"], "selected": False}],
        "coverage": {"schema_version": "0.1", "dimensions": [{"schema_version": "0.1", "dimension": "counterevidence", "status": "PARTIAL", "rationale": "one contrary context"}], "saturation": "PARTIAL", "unresolved_material_evidence_gap_ids": ["dr-gap-1"], "remaining_information_value": "HIGH", "stop_recommended": False, "stopping_rationale": "material gap remains", "stopping_basis": ["COVERAGE", "REMAINING_INFORMATION_VALUE"], "fixed_source_count_reached": None},
        "back_references": ["source-real-1"],
        "publication_eligibility": {"schema_version": "0.1", "status": "NOT_ELIGIBLE", "approved_by": None, "decision_id": None, "scope": None},
        }), encoding="utf-8")
    valid_desktop_payload = json.loads(desktop_result.read_text(encoding="utf-8"))
    invalid_desktop_payload = json.loads(json.dumps(valid_desktop_payload))
    invalid_desktop_payload["evidence"][0]["snapshot_sha256"] = "b" * 64
    desktop_result.write_text(json.dumps(invalid_desktop_payload), encoding="utf-8")
    with pytest.raises(ReductionBlocked, match="snapshot validation failed"):
        orchestrator.collect_work_result(desktop_request.run_id, desktop_result)
    pending_after_failure = orchestrator.status()
    assert pending_after_failure.phase == "DESKTOP_RESEARCH"
    assert pending_after_failure.pending_work is not None
    failed_run_dir = tmp_path / ".rh" / "runs" / desktop_request.run_id
    assert not (failed_run_dir / "desktop_research_handoff.json").exists()
    assert not (failed_run_dir / "completion.json").exists()
    assert len(list((failed_run_dir / "submissions").glob("*.json"))) == 1
    desktop_result.write_text(json.dumps(valid_desktop_payload), encoding="utf-8")
    research_review = orchestrator.collect_work_result(desktop_request.run_id, desktop_result)
    desktop_pack_after = {str(path.relative_to(desktop_request.context_pack)): path.read_bytes() for path in Path(desktop_request.context_pack).rglob("*") if path.is_file()}
    assert desktop_pack_after == desktop_pack_before
    assert research_review.phase == "DESKTOP_RESEARCH_REVIEW"
    assert research_review.pending_decision_ids
    research = json.loads((tmp_path / ".rh" / "state" / "research" / "head.json").read_text(encoding="utf-8"))
    assert research["findings"][-1]["statement"] == "Candidate coordination pattern"
    assert research["counterevidence"][-1] == "Contrary context"
    assert research["evidence_gaps"][-1]["gap_id"] == "dr-gap-1"
    run_dir = tmp_path / ".rh" / "runs" / desktop_request.run_id
    canonical_snapshot = run_dir / "evidence_snapshots" / "e-real-1.txt"
    assert canonical_snapshot.is_file()
    canonical_handoff = json.loads((run_dir / "desktop_research_handoff.json").read_text(encoding="utf-8"))
    assert canonical_handoff["evidence"][0]["snapshot_path"] == str(canonical_snapshot.resolve())
    assert canonical_handoff["evidence"][0]["text_snapshot"] == snapshot_text
    assert canonical_handoff["evidence"][0]["excerpt_locator_pairs"][0]["locator"] == "p. 12"
    assert (run_dir / "completion.json").is_file()


def test_revision_choices_resume_the_proposal_phase_not_the_approval_path(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path)
    stopped = orchestrator.continue_until_stop(run_limit=10)
    revised = orchestrator.record_decision(stopped.pending_decision_ids[0], choice="REVISE", decided_by="human")
    assert revised.phase == "SEED_COMPARISON"
    assert not revised.terminal


def test_compact_orchestrator_state_stays_bounded_while_run_history_grows(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path)
    state = orchestrator.continue_until_stop(run_limit=10)
    while state.total_run_count < 23:
        state = orchestrator.record_decision(state.pending_decision_ids[0], choice="REVISE", decided_by="human")
        state = orchestrator.continue_until_stop(run_limit=1)
    assert state.total_run_count == 23
    assert len(state.run_refs) == 20
    assert len(set(state.run_refs)) == 20
    assert len(list((tmp_path / ".rh" / "runs").iterdir())) == 23
