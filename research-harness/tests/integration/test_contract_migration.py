import json
import shutil
from pathlib import Path

import pytest

from misco_harness.models import ArtifactRegistry, DecisionRequest, RuntimePolicyValue
from misco_harness.orchestrator import DiscoveryOrchestrator, OrchestratorError
from misco_harness.trace_store import sha256_file

PROJECT_ROOT = Path(__file__).parents[2]


def _workspace(tmp_path: Path) -> DiscoveryOrchestrator:
    for relative in (
        "contracts/runtime_artifact_policy.yaml",
        "contracts/research_harness_v0.4.md",
        "contracts/research_constitution.md",
        "contracts/capabilities/desktop-research/desktop_research_contract.md",
        "contracts/capabilities/desktop-research/source_policy.yaml",
        "contracts/capabilities/desktop-research/evidence_capture.schema.yaml",
        "contracts/capabilities/desktop-research/provenance_audit_contract.md",
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
    theme.write_text("Theme", encoding="utf-8")
    expectations.write_text("Expectations", encoding="utf-8")
    orchestrator = DiscoveryOrchestrator(tmp_path)
    orchestrator.initialize(theme=theme, expectations=expectations, worker_backend="interactive-work")
    return orchestrator


def test_refresh_migrates_stale_live_registry_without_touching_research_or_decisions(tmp_path: Path) -> None:
    orchestrator = _workspace(tmp_path)
    registry = orchestrator._registry()
    stale = registry.model_copy(update={
        "artifacts": [
            item.model_copy(update={
                "runtime_policy": {
                    **item.runtime_policy,
                    "CONTRACT_MIGRATION_REVIEW": RuntimePolicyValue.DENY,
                    "PROVENANCE_AUDIT": RuntimePolicyValue.DENY,
                },
            }) if item.artifact_id in {"desktop-research-contract", "desktop-research-source-policy"} else item
            for item in registry.artifacts
        ],
    })
    orchestrator.store.write_head("registry/artifact_registry.json", stale)

    state = orchestrator.status()
    decision = DecisionRequest(
        decision_id="decision-contract-migration-pending",
        request="Keep this pending while contracts refresh",
        status_scope="Research decision remains open",
        ai_recommendation="No semantic choice is made by migration",
        options=[{"id": "WAIT", "label": "Wait"}],
        resume_plan={"next_phase": state.phase},
    )
    pending = orchestrator.decisions.block(state, decision, snapshot_id="orchestrator-contract-migration-pending")
    research_before = (tmp_path / ".rh" / "state" / "research" / "head.json").read_bytes()
    receipt = orchestrator.refresh_contract_registry()

    assert receipt.event == "CONTRACT_MIGRATION_REVIEW"
    assert set(receipt.changed_policy_artifact_ids) >= {
        "desktop-research-contract",
        "desktop-research-source-policy",
    }
    assert receipt.pending_decision_ids == pending.pending_decision_ids
    assert sha256_file(tmp_path / ".rh" / "registry" / "artifact_registry.json") == receipt.registry_after_sha256
    assert (tmp_path / ".rh" / "state" / "research" / "head.json").read_bytes() == research_before
    run_dir = tmp_path / ".rh" / "runs" / receipt.run_id
    assert (run_dir / "registry_before.json").is_file()
    assert (run_dir / "registry_after.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "audit.json").is_file()
    assert (run_dir / "contract_registry_refresh.json").is_file()
    assert (run_dir / "trace.json").is_file()
    assert json.loads((run_dir / "completion.json").read_text(encoding="utf-8"))["status"] == "COMPLETED"
    assert json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))["passed"] is True
    context = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / ".rh" / "context_packs").glob("*/manifest.json")
        if json.loads(path.read_text(encoding="utf-8"))["run_id"] == receipt.run_id
    )
    assert context["event"] == "CONTRACT_MIGRATION_REVIEW"
    assert context["lane"] == "IMPLEMENTATION"

    migrated = ArtifactRegistry.model_validate_json(
        (tmp_path / ".rh" / "registry" / "artifact_registry.json").read_text(encoding="utf-8")
    )
    records = {item.artifact_id: item for item in migrated.artifacts}
    assert {
        "runtime-artifact-policy",
        "desktop-research-evidence-schema",
        "provenance-audit-contract",
    } <= records.keys()
    assert records["desktop-research-contract"].runtime_policy["CONTRACT_MIGRATION_REVIEW"] == "INCLUDE"
    assert records["desktop-research-source-policy"].runtime_policy["PROVENANCE_AUDIT"] == "INCLUDE"
    assert orchestrator.status().pending_decision_ids == pending.pending_decision_ids

    second = orchestrator.refresh_contract_registry()
    assert second.added_artifact_ids == []
    assert second.refreshed_artifact_ids == []
    assert set(second.unchanged_artifact_ids) >= set(receipt.canonical_artifact_ids)


def test_refresh_rejects_pending_work_without_changing_registry(tmp_path: Path) -> None:
    orchestrator = _workspace(tmp_path)
    before = (tmp_path / ".rh" / "registry" / "artifact_registry.json").read_bytes()
    waiting = orchestrator.continue_until_stop(run_limit=1)
    assert waiting.pending_work is not None
    with pytest.raises(OrchestratorError, match="pending"):
        orchestrator.refresh_contract_registry()
    assert (tmp_path / ".rh" / "registry" / "artifact_registry.json").read_bytes() == before
