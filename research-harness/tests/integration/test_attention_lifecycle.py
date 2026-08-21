import hashlib
import json
import shutil
from pathlib import Path

import pytest

from misco_harness.cli import main
from misco_harness.attention import AttentionIntakeError
from misco_harness.models import AttentionDistillationHandoff
from misco_harness.orchestrator import DiscoveryOrchestrator
from misco_harness.state_reducer import ReductionBlocked
from misco_harness.workspace import new_workspace, verify_archive

from tests.integration.test_discovery_cycle import PROJECT_ROOT


def prepare_attention_workspace(tmp_path: Path, *, worker_backend: str = "mock") -> DiscoveryOrchestrator:
    (tmp_path / "contracts").mkdir()
    for relative in (
        "contracts/runtime_artifact_policy.yaml",
        "contracts/research_harness_v0.4.md",
        "contracts/research_constitution.md",
        "contracts/capabilities/desktop-research/desktop_research_contract.md",
        "contracts/capabilities/desktop-research/source_policy.yaml",
        "contracts/capabilities/attention-intake/attention_distillation_contract.md",
        "contracts/capabilities/workspace-lifecycle/workspace_lifecycle_contract.md",
        "contracts/publication_parallel_lane.md",
        "contracts/publication_structure.schema.yaml",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, destination)
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    theme.write_text("Theme", encoding="utf-8")
    expectations.write_text("Expectations", encoding="utf-8")
    orchestrator = DiscoveryOrchestrator(tmp_path)
    orchestrator.initialize(theme=theme, expectations=expectations, worker_backend=worker_backend)
    return orchestrator


def test_mock_attention_drop_requires_human_adoption_and_creates_new_map_version(tmp_path: Path) -> None:
    orchestrator = prepare_attention_workspace(tmp_path)
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "note.md").write_text("raw note", encoding="utf-8")

    manifest = orchestrator.register_attention_drop(drop, registered_by="human")
    assert orchestrator.plan().task_type == "ATTENTION_MAP_DISTILLATION"
    stopped = orchestrator.continue_until_stop(run_limit=1)
    assert len(stopped.pending_decision_ids) == 1
    decision_id = stopped.pending_decision_ids[0]
    decision = json.loads((tmp_path / ".rh" / "decisions" / decision_id / "request.json").read_text(encoding="utf-8"))
    assert decision["decision_kind"] == "ATTENTION_MAP_ADOPTION"
    assert {item["id"] for item in decision["options"]} == {
        "ADOPT_CANDIDATE_MAP", "KEEP_CURRENT_MAP", "REQUEST_REVISION",
    }

    old_map_id = stopped.active_attention_map_id
    adopted = orchestrator.record_decision(decision_id, choice="ADOPT_CANDIDATE_MAP", decided_by="human")
    assert adopted.active_attention_map_id != old_map_id
    registry = json.loads((tmp_path / ".rh" / "registry" / "artifact_registry.json").read_text(encoding="utf-8"))
    by_id = {item["artifact_id"]: item for item in registry["artifacts"]}
    assert by_id[adopted.active_attention_map_id]["status"] == "ACTIVE"
    if old_map_id:
        assert by_id[old_map_id]["status"] == "SUPERSEDED"
    assert Path(by_id[adopted.active_attention_map_id]["path"]).is_file()
    assert manifest.drop_id not in adopted.pending_attention_drop_ids


def test_interactive_attention_work_exchange_is_bounded(tmp_path: Path) -> None:
    orchestrator = prepare_attention_workspace(tmp_path, worker_backend="interactive-work")
    drop = tmp_path / "drop.md"
    drop.write_text("raw note", encoding="utf-8")
    manifest = orchestrator.register_attention_drop(drop, registered_by="human")
    waiting = orchestrator.continue_until_stop(run_limit=1)
    request = waiting.pending_work
    assert request is not None
    assert request.expected_output_schema == "AttentionDistillationHandoff"
    drop_ids = [
        item.artifact_id
        for item in orchestrator._registry().artifacts
        if item.artifact_id.startswith(f"{manifest.drop_id}-")
    ]
    markdown = "# Candidate Attention Map\n\n- Human review required.\n"
    handoff = AttentionDistillationHandoff(
        run_id=request.run_id,
        drop_id=manifest.drop_id,
        basis_attention_map_id=waiting.active_attention_map_id,
        used_artifact_ids=drop_ids,
        items=[{
            "attention_id": "candidate-1",
            "title": "Review",
            "statement": "Human review required.",
            "operation": "ADD",
            "source_refs": drop_ids,
        }],
        candidate_map_markdown=markdown,
        candidate_map_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        back_references=drop_ids,
    )
    result_path = Path(request.expected_output_file)
    result_path.write_text(handoff.model_dump_json(indent=2), encoding="utf-8")
    stopped = orchestrator.collect_work_result(request.run_id, result_path, run_limit=1)
    assert stopped.pending_decision_ids
    assert stopped.pending_work is None


def test_attention_intake_rejects_duplicate_and_symlink_batches(tmp_path: Path) -> None:
    orchestrator = prepare_attention_workspace(tmp_path)
    drop = tmp_path / "drop"
    drop.mkdir()
    source = drop / "note.md"
    source.write_text("raw", encoding="utf-8")
    manifest = orchestrator.register_attention_drop(drop, registered_by="human")
    stored = next(item for item in manifest.files if item.relative_path == "note.md")
    assert Path(stored.stored_path).read_text(encoding="utf-8") == "raw"
    assert len(stored.sha256) == 64
    with pytest.raises(AttentionIntakeError, match="already registered"):
        orchestrator.register_attention_drop(drop, registered_by="human")

    symlink = tmp_path / "symlink-drop"
    symlink.mkdir()
    try:
        (symlink / "link.md").symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this Windows runner")
    with pytest.raises(AttentionIntakeError, match="symlink"):
        orchestrator.register_attention_drop(symlink, registered_by="human")


def test_failed_attention_submission_keeps_pending_work_and_trace(tmp_path: Path) -> None:
    orchestrator = prepare_attention_workspace(tmp_path, worker_backend="interactive-work")
    drop = tmp_path / "drop.md"
    drop.write_text("raw", encoding="utf-8")
    manifest = orchestrator.register_attention_drop(drop, registered_by="human")
    waiting = orchestrator.continue_until_stop(run_limit=1)
    request = waiting.pending_work
    assert request is not None
    markdown = "# Candidate Attention Map\n"
    handoff = AttentionDistillationHandoff(
        run_id=request.run_id,
        drop_id=manifest.drop_id,
        items=[{
            "attention_id": "candidate-1",
            "title": "Review",
            "statement": "Human review required.",
            "operation": "ADD",
        }],
        candidate_map_markdown=markdown,
        candidate_map_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
    result_path = Path(request.expected_output_file)
    result_path.write_text(handoff.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(ReductionBlocked):
        orchestrator.collect_work_result(request.run_id, result_path, run_limit=1)
    assert orchestrator.status().pending_work is not None
    assert list((tmp_path / ".rh" / "runs" / request.run_id / "submissions").iterdir())


def test_archive_freezes_source_after_bundle_verification(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    orchestrator = prepare_attention_workspace(workspace)
    destination = tmp_path / "archive"
    manifest = orchestrator.archive(destination, created_by="human", reason="research complete")
    assert manifest.status == "COMPLETE"
    assert verify_archive(destination).archive_id == manifest.archive_id
    assert orchestrator.status().lifecycle_status == "ARCHIVED"
    with pytest.raises(Exception, match="archived"):
        orchestrator.register_attention_drop(workspace / "missing.md", registered_by="human")


def test_new_creates_mapless_workspace_and_optional_drop(tmp_path: Path) -> None:
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    drop = tmp_path / "drop.md"
    theme.write_text("new theme", encoding="utf-8")
    expectations.write_text("new expectations", encoding="utf-8")
    drop.write_text("new raw attention", encoding="utf-8")
    target = tmp_path / "new-workspace"

    result = new_workspace(
        target,
        template_root=PROJECT_ROOT,
        theme=theme,
        expectations=expectations,
        worker_backend="mock",
        initial_drop=drop,
    )
    assert result["status"] == "INITIALIZED"
    state = json.loads((target / ".rh" / "state" / "orchestrator" / "head.json").read_text(encoding="utf-8"))
    assert state["active_attention_map_id"] is None
    assert state["pending_attention_drop_ids"]


def test_publication_refresh_supports_mapless_state(tmp_path: Path) -> None:
    orchestrator = prepare_attention_workspace(tmp_path)
    question_stop = orchestrator.continue_until_stop(run_limit=1)
    assert question_stop.pending_decision_ids
    question_run = json.loads(
        (tmp_path / ".rh" / "runs" / question_stop.run_refs[-1] / "manifest.json").read_text(encoding="utf-8")
    )
    assert "attention-map" not in {item["artifact_id"] for item in question_run["input_refs"]}
    publication = orchestrator.request_publication_eligibility()
    decision_id = publication.pending_decision_ids[0]
    orchestrator.record_decision(decision_id, choice="ALLOW_PUBLICATION", decided_by="human")
    refreshed = orchestrator.refresh_publication()
    assert refreshed.source_attention_map_id is None
    assert refreshed.structure is not None
    assert refreshed.structure.source_attention_map_id is None


def test_cli_exposes_new_attention_and_archive_commands(tmp_path: Path, capsys) -> None:
    theme = tmp_path / "theme.md"
    expectations = tmp_path / "expectations.md"
    theme.write_text("theme", encoding="utf-8")
    expectations.write_text("expectations", encoding="utf-8")
    target = tmp_path / "target"
    assert main([
        "--root", str(target), "new", "--template-root", str(PROJECT_ROOT),
        "--theme", str(theme), "--expectations", str(expectations),
        "--worker-backend", "mock",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "INITIALIZED"
    drop = target / "loose" / "note.md"
    drop.parent.mkdir()
    drop.write_text("raw", encoding="utf-8")
    assert main([
        "--root", str(target), "attention", "ingest", "--path", str(drop), "--by", "human",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["drop_id"].startswith("drop-")
    destination = tmp_path / "archive-cli"
    assert main([
        "--root", str(target), "archive", "--destination", str(destination),
        "--by", "human", "--reason", "close", "--allow-incomplete",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "INCOMPLETE"
    assert main([
        "--root", str(tmp_path / "not-a-workspace"), "archive", "--verify", str(destination),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["archive_id"].startswith("archive-")
