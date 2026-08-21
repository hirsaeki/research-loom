import json
import shutil
from pathlib import Path

import pytest

from misco_harness.cli import main
from misco_harness.models import ResearchState
from misco_harness.orchestrator import DiscoveryOrchestrator

PROJECT_ROOT = Path(__file__).parents[2]


def _prepare_workspace(tmp_path: Path, *, worker_backend: str = "interactive-work") -> DiscoveryOrchestrator:
    """Create the minimum real-interactive workspace without a provisional Seed."""

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
    theme.write_text("MISCO research theme", encoding="utf-8")
    expectations.write_text("Generate independent questions first", encoding="utf-8")

    orchestrator = DiscoveryOrchestrator(tmp_path)
    # Deliberately omit seed: initialization must not synthesize a placeholder
    # PRIOR_SEED artifact.
    orchestrator.initialize(
        theme=theme,
        expectations=expectations,
        worker_backend=worker_backend,
    )
    return orchestrator


def _independent_result(run_id: str, question: str) -> dict:
    return {
        "run_id": run_id,
        "candidates": [{
            "candidate_id": "candidate-1",
            "question": question,
            "rationale": "formed from the bounded intake context",
            "uncertainty": ["candidate scope remains provisional"],
            "scope_limits": ["bounded discovery only"],
        }],
        "counterevidence": ["candidate may not generalize"],
        "uncertainty": ["source availability is unknown"],
        "scope_limits": ["no method selection"],
        "question_overlaps": ["candidate dimensions may overlap"],
        "evidence_gap_hypotheses": [{
            "gap_id": "gap-1",
            "hypothesis": "relevant sources may be sparse",
            "why_material": "source scarcity could narrow the question",
        }],
        "back_references": ["theme", "expectations", "harness-contract", "constitution", "attention-map"],
        "attention_map_authority": "GUIDANCE_ONLY",
        "selected_method": None,
    }


def _seed_comparison_result(run_id: str, question: str) -> dict:
    return {
        "run_id": run_id,
        "matches": ["shared framing dimension"],
        "mismatches": ["different scope boundary"],
        "missing": ["boundary evidence"],
        "over_scoped": ["seed population"],
        "proposed_baselines": [{
            "proposal_id": "baseline-1",
            "question": question,
            "rationale": "retained after bounded comparison",
            "uncertainty": ["human scope choice remains"],
            "scope_limits": ["bounded discovery only"],
            "overlaps": ["partial overlap with the Seed"],
            "evidence_gap_hypotheses": [{
                "gap_id": "gap-2",
                "hypothesis": "context boundary remains unresolved",
                "why_material": "it affects baseline scope",
            }],
        }],
        "counterevidence": ["Seed framing bias"],
        "uncertainty": ["human scope choice remains"],
        "scope_limits": ["no method selection"],
        "question_overlaps": ["partial overlap with the Seed"],
        "evidence_gap_hypotheses": [{
            "gap_id": "gap-2",
            "hypothesis": "context boundary remains unresolved",
            "why_material": "it affects baseline scope",
        }],
        "back_references": ["rq-seed"],
        "attention_map_authority": "GUIDANCE_ONLY",
        "selected_method": None,
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_no_seed_discovery_skips_comparison_and_reaches_question_review(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path)

    waiting = orchestrator.continue_until_stop(run_limit=1)
    assert waiting.phase == "QUESTION_FORMATION"
    assert waiting.execution_state == "WORK_EXECUTION_REQUIRED"
    request = waiting.pending_work
    assert request is not None
    assert request.expected_output_schema == "IndependentQuestionFormationHandoff"

    context_pack = Path(request.context_pack)
    before = _tree_bytes(context_pack)
    manifest = json.loads((context_pack / "manifest.json").read_text(encoding="utf-8"))
    included = {item["artifact_id"] for item in manifest["must_include"]}
    forbidden = set(manifest["forbidden_context"])
    assert "rq-seed" not in included
    assert "rq-seed" not in forbidden

    registry = json.loads(
        (tmp_path / ".rh" / "registry" / "artifact_registry.json").read_text(encoding="utf-8")
    )
    assert not any(item["role"] == "PRIOR_SEED" for item in registry["artifacts"])
    assert not (tmp_path / "quarantine" / "seed.md").exists()

    result_path = Path(request.expected_output_file)
    result_path.write_text(
        json.dumps(_independent_result(request.run_id, "How do independently formed boundaries affect recovery?")),
        encoding="utf-8",
    )
    stopped = orchestrator.collect_work_result(request.run_id, result_path, run_limit=10)

    assert stopped.phase == "QUESTION_REVIEW"
    assert stopped.execution_state == "READY"
    assert stopped.total_run_count == 1
    assert stopped.pending_decision_ids
    assert _tree_bytes(context_pack) == before
    assert not any(
        json.loads((path / "manifest.json").read_text(encoding="utf-8"))["event"] == "SEED_COMPARISON"
        for path in (tmp_path / ".rh" / "context_packs").iterdir()
    )
    decision_id = stopped.pending_decision_ids[0]
    decision = json.loads(
        (tmp_path / ".rh" / "decisions" / decision_id / "request.json").read_text(encoding="utf-8")
    )
    proposal = decision["proposed_question_baselines"][0]
    assert proposal["question"] == "How do independently formed boundaries affect recovery?"
    assert proposal["scope_limits"]
    assert proposal["uncertainty"]
    assert proposal["overlaps"]
    assert proposal["evidence_gap_hypotheses"]

    orchestrator.record_decision(
        decision_id,
        choice="ADOPT_PROPOSED_BASELINES",
        decided_by="human",
    )
    research = ResearchState.model_validate_json(
        (tmp_path / ".rh" / "state" / "research" / "head.json").read_text(encoding="utf-8")
    )
    adopted = research.questions[0]
    assert adopted.text == "How do independently formed boundaries affect recovery?"
    assert adopted.decision_id == decision_id
    assert adopted.scope_limits
    assert adopted.uncertainty
    assert adopted.overlaps
    assert adopted.evidence_gap_hypotheses


def test_transition_lock_is_reentrant_and_orphan_requires_explicit_release(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path)

    with orchestrator._discovery_transition_lock():
        with orchestrator._discovery_transition_lock():
            assert orchestrator.transition_lock_status()["locks"]["discovery-transition"]["status"] == "HELD"
    assert orchestrator.transition_lock_status()["locks"]["discovery-transition"]["status"] == "FREE"

    lock_path = tmp_path / ".rh" / "locks" / "discovery-transition.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        '{"lock_name":"discovery-transition","owner_token":"orphan-token","pid":99999,'
        '"acquired_at":"2020-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    status = orchestrator.transition_lock_status()
    assert status["reclaim_policy"] == "EXPLICIT_OPERATOR_RELEASE_ONLY"
    assert status["locks"]["discovery-transition"]["status"] == "HELD"
    with pytest.raises(Exception, match="explicitly release"):
        with orchestrator._discovery_transition_lock():
            pass

    released = orchestrator.release_transition_lock(
        "discovery-transition", actor="operator", reason="confirmed orphaned process", owner_token="orphan-token",
    )
    assert released["status"] == "RELEASED"
    assert not lock_path.exists()
    assert list((tmp_path / ".rh" / "locks" / "releases").glob("*.json"))


def test_late_attached_seed_comparison_uses_frozen_independent_snapshot(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path)
    waiting = orchestrator.continue_until_stop(run_limit=1)
    request = waiting.pending_work
    assert request is not None
    context_pack = Path(request.context_pack)
    before = _tree_bytes(context_pack)
    manifest = json.loads((context_pack / "manifest.json").read_text(encoding="utf-8"))
    assert "rq-seed" not in {item["artifact_id"] for item in manifest["must_include"]}

    seed = tmp_path / "quarantine" / "late-seed.md"
    seed.parent.mkdir(parents=True)
    seed.write_text("A human-attached provisional prior RQ", encoding="utf-8")
    # The late registration occurs only after the independent Context Pack was
    # materialized/frozen, and must not rewrite that pack.
    orchestrator.attach_prior_seed(seed)
    assert _tree_bytes(context_pack) == before

    result_path = Path(request.expected_output_file)
    question = "How do independently formed boundaries affect recovery?"
    result_path.write_text(json.dumps(_independent_result(request.run_id, question)), encoding="utf-8")
    comparison_wait = orchestrator.collect_work_result(request.run_id, result_path, run_limit=10)

    assert comparison_wait.phase == "SEED_COMPARISON"
    assert comparison_wait.execution_state == "WORK_EXECUTION_REQUIRED"
    assert comparison_wait.total_run_count == 1
    comparison_request = comparison_wait.pending_work
    assert comparison_request is not None
    assert comparison_request.expected_output_schema == "SeedComparisonHandoff"
    snapshot_id = comparison_wait.current_question_snapshot_id
    assert snapshot_id is not None
    snapshot_path = tmp_path / ".rh" / "state" / "research" / "snapshots" / f"{snapshot_id}.json"
    snapshot_before = snapshot_path.read_bytes()

    comparison_manifest = json.loads(Path(comparison_request.manifest).read_text(encoding="utf-8"))
    comparison_ids = {item["artifact_id"] for item in comparison_manifest["must_include"]}
    assert {"rq-seed", snapshot_id} <= comparison_ids
    assert _tree_bytes(context_pack) == before

    comparison_result = Path(comparison_request.expected_output_file)
    comparison_result.write_text(
        json.dumps(_seed_comparison_result(comparison_request.run_id, question)),
        encoding="utf-8",
    )
    stopped = orchestrator.collect_work_result(comparison_request.run_id, comparison_result, run_limit=10)

    assert stopped.phase == "QUESTION_REVIEW"
    assert stopped.pending_decision_ids
    assert snapshot_path.read_bytes() == snapshot_before
    assert _tree_bytes(context_pack) == before
    registry = json.loads(
        (tmp_path / ".rh" / "registry" / "artifact_registry.json").read_text(encoding="utf-8")
    )
    seed_record = next(item for item in registry["artifacts"] if item["artifact_id"] == "rq-seed")
    assert seed_record["role"] == "PRIOR_SEED"
    assert Path(seed_record["path"]).read_text(encoding="utf-8") == "A human-attached provisional prior RQ"


def test_cli_initializes_without_seed_and_registers_one_later(tmp_path: Path, capsys) -> None:
    orchestrator = _prepare_workspace(tmp_path)
    shutil.rmtree(tmp_path / ".rh")

    assert main([
        "--root", str(tmp_path), "init",
        "--theme", str(tmp_path / "theme.md"),
        "--expectations", str(tmp_path / "expectations.md"),
        "--worker-backend", "interactive-work",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "INITIALIZED"
    registry = orchestrator._registry()
    assert not any(item.role == "PRIOR_SEED" for item in registry.artifacts)

    seed = tmp_path / "late-seed.md"
    seed.write_text("Late human seed", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "seed", "register", "--path", str(seed),
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "SEED_REGISTERED"
    seed_record = next(item for item in orchestrator._registry().artifacts if item.artifact_id == "rq-seed")
    assert seed_record.role == "PRIOR_SEED"


def test_seed_registration_refuses_an_overlapping_discovery_transition(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path)
    seed = tmp_path / "late-seed.md"
    seed.write_text("Late human seed", encoding="utf-8")

    with (
        orchestrator._discovery_transition_lock(),
    ):
        orchestrator.attach_prior_seed(seed)

    assert any(item.role == "PRIOR_SEED" for item in orchestrator._registry().artifacts)
