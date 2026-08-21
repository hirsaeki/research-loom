import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from misco_harness.coordinator import InteractiveWorkResearchCoordinator
from misco_harness.models import DecisionRequest, ResearchState
from misco_harness.orchestrator import DiscoveryOrchestrator

PROJECT_ROOT = Path(__file__).parents[2]


def _workspace(tmp_path: Path) -> tuple[DiscoveryOrchestrator, Path]:
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
    return orchestrator, tmp_path


def _legacy_baseline(orchestrator: DiscoveryOrchestrator) -> tuple[ResearchState, list[dict[str, str]]]:
    targets = []
    evidence = []
    for index in range(28):
        evidence_id = f"E-LEGACY-{index + 1:02d}"
        source_id = f"SRC-{index + 1:02d}"
        locator = f"https://example.test/source/{index + 1}"
        statement = f"Legacy statement {index + 1}"
        targets.append({
            "evidence_id": evidence_id,
            "source_id": source_id,
            "source_type": "GOVERNMENT_PRIMARY",
            "support_scope": "DESCRIPTIVE_CONTEXT",
            "locator": locator,
        })
        evidence.append({
            "schema_version": "0.1",
            "evidence_id": evidence_id,
            "source_id": source_id,
            "source_type": "GOVERNMENT_PRIMARY",
            "locator": locator,
            "captured_statement": statement,
            "evidence_kind": "SUPPORTING",
            "support_scope": "DESCRIPTIVE_CONTEXT",
            "material": True,
            "independent_support_source_ids": [],
            "limitations": ["Legacy capture metadata is incomplete"],
        })
    # A later 0.2 record with a reused ID must not displace the planned 0.1
    # selection; the audit is closed over the legacy predicate, not ID alone.
    evidence.append({
        **evidence[0],
        "schema_version": "0.2",
        "source_quality": "HIGH",
        "text_snapshot": "Existing later snapshot",
        "snapshot_path": ".rh/runs/existing/evidence_snapshots/E-LEGACY-01.txt",
        "snapshot_sha256": "0" * 64,
    })
    baseline = ResearchState(state_id="research-legacy-28", evidence=evidence)
    path = orchestrator.runtime / "state" / "research" / "head.json"
    path.write_text(json.dumps(baseline.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return baseline, targets


def _plan(tmp_path: Path, baseline: ResearchState, targets: list[dict[str, str]]) -> Path:
    baseline_path = tmp_path / ".rh" / "state" / "research" / "head.json"
    baseline_hash = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    plan = {
        "manifest_kind": "PROVENANCE_REPAIR_RUN_PLAN",
        "schema_version": "0.1",
        "status": "PLANNED",
        "created_at": "2026-08-18T00:00:00Z",
        "proposed_run_id": "run-provenance-audit-28-test",
        "proposed_context_pack_id": "pack-provenance-audit-28-test",
        "event": "PROVENANCE_AUDIT",
        "lane": "IMPLEMENTATION",
        "objective": "Repair legacy Evidence capture metadata without changing research meaning.",
        "execution_boundary": "Explicit provenance-only Work boundary.",
        "baseline_snapshot": {
            "state_id": baseline.state_id,
            "path": ".rh/state/research/head.json",
            "sha256": baseline_hash,
        },
        "selection": {
            "predicate": "evidence.schema_version == '0.1'",
            "expected_count": 28,
            "actual_count": 28,
            "legacy_schema_version": "0.1",
            "missing_capture_fields": ["text_snapshot", "snapshot_path", "snapshot_sha256"],
            "selection_is_closed_world": True,
        },
        "target_evidence": targets,
        "allowed_context": {"include": [".rh/state/research/head.json"]},
        "forbidden_context": ["archive/provenance/**", "publication drafts"],
        "retrieval_rules": ["Only the exact target locator may be checked."],
        "required_outputs": {"result_file": "repair_result.json"},
        "invariants": ["The target set remains exactly 28 evidence IDs."],
        "human_decision_triggers": [],
    }
    path = tmp_path / ".rh" / "work_exchange" / "provenance-repair-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _result(orchestrator: DiscoveryOrchestrator, targets: list[dict[str, str]], request) -> Path:
    snapshot_root = Path(request.exchange_directory) / "evidence_snapshots"
    evidence = []
    for index, target in enumerate(targets):
        text = f"Verified snapshot text {index + 1}"
        snapshot = snapshot_root / f"{target['evidence_id']}.txt"
        snapshot.write_text(text, encoding="utf-8")
        evidence.append({
            "schema_version": "0.2",
            **target,
            "source_quality": "HIGH",
            "captured_statement": f"Legacy statement {index + 1}",
            "acquired_at": datetime(2026, 8, 18, 0, 0, index, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
            "text_snapshot": text,
            "snapshot_path": str(snapshot.resolve()),
            "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "excerpt_locator_pairs": [{"excerpt": text, "locator": target["locator"]}],
            "evidence_kind": "SUPPORTING",
            "material": True,
            "independent_support_source_ids": [],
            "limitations": ["Legacy capture metadata is incomplete"],
            "source_title": f"Source {index + 1}",
            "publisher_or_author": "Example publisher",
            "publication_or_update_date": "2026-01-01",
            "version_or_revision": "current",
            "verification_status": "VERIFIED",
            "metadata_confidence": "HIGH",
        })
    result = {
        "schema_version": "0.2",
        "run_id": request.run_id,
        "source_manifest_id": "provenance-audit-plan",
        "baseline_state_id": "research-legacy-28",
        "target_evidence_ids": [item["evidence_id"] for item in targets],
        "evidence": evidence,
        "unresolved": [],
        "back_references": [
            "provenance-audit-plan", "provenance-baseline", "harness-contract", "constitution",
            "desktop-research-contract", "desktop-research-source-policy", "runtime-artifact-policy",
            "desktop-research-evidence-schema", "provenance-audit-contract",
        ],
        "audit_notes": ["No substantive research meaning was changed."],
        "selected_method": None,
    }
    result_path = Path(request.expected_output_file)
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result_path


def test_provenance_audit_repairs_28_records_without_reducing_research_state(tmp_path: Path) -> None:
    orchestrator, root = _workspace(tmp_path)
    baseline, targets = _legacy_baseline(orchestrator)
    plan = _plan(root, baseline, targets)
    waiting = orchestrator.start_provenance_audit(plan)
    before = (root / ".rh" / "state" / "research" / "head.json").read_bytes()
    coordinator = InteractiveWorkResearchCoordinator(root, orchestrator=orchestrator)
    action = coordinator.next_action(advance=False)
    pack_manifest = json.loads(
        (Path(waiting.pending_work.context_pack) / "manifest.json").read_text(encoding="utf-8")
    )
    assert "archive/provenance/**" in pack_manifest["forbidden_context"]
    result = _result(orchestrator, targets, waiting.pending_work)
    resumed = coordinator.submit_result(result)

    assert action.state == "WORK_EXECUTION_REQUIRED"
    assert resumed.state == "WORK_EXECUTION_REQUIRED"
    assert resumed.run_id != waiting.pending_work.run_id
    assert (root / ".rh" / "state" / "research" / "head.json").read_bytes() == before
    run_dir = root / ".rh" / "runs" / waiting.pending_work.run_id
    repair = json.loads((run_dir / "repair_result.json").read_text(encoding="utf-8"))
    assert len(repair["evidence"]) == 28
    assert all(item["schema_version"] == "0.2" for item in repair["evidence"])
    assert all(Path(item["snapshot_path"]).parent == run_dir / "evidence_snapshots" for item in repair["evidence"])


def test_failed_provenance_submission_can_be_discarded_and_reacquired(tmp_path: Path) -> None:
    orchestrator, root = _workspace(tmp_path)
    baseline, targets = _legacy_baseline(orchestrator)
    plan = _plan(root, baseline, targets)
    waiting = orchestrator.start_provenance_audit(plan)
    result_path = Path(waiting.pending_work.expected_output_file)
    result_path.write_text("{}\n", encoding="utf-8")
    coordinator = InteractiveWorkResearchCoordinator(root, orchestrator=orchestrator)
    failure = coordinator.submit_result(result_path)
    assert failure.state == "ERROR"
    old_run = waiting.pending_work.run_id
    assert list((root / ".rh" / "runs" / old_run / "submissions").glob("*.json"))
    assert not (root / ".rh" / "runs" / old_run / "repair_result.json").exists()
    assert not (root / ".rh" / "runs" / old_run / "completion.json").exists()

    reacquired = coordinator.submit_result(reacquire=True)
    assert reacquired.state == "WORK_EXECUTION_REQUIRED"
    assert reacquired.run_id != old_run
    assert json.loads((root / ".rh" / "runs" / old_run / "discard.json").read_text(encoding="utf-8"))["status"] == "DISCARDED"


def test_provenance_audit_runs_beside_pending_research_decision(tmp_path: Path) -> None:
    orchestrator, root = _workspace(tmp_path)
    baseline, targets = _legacy_baseline(orchestrator)
    plan = _plan(root, baseline, targets)
    state = orchestrator.status().model_copy(update={"phase": "METHOD_REVIEW"})
    orchestrator.store.write_head("state/orchestrator/head.json", state)
    decision = DecisionRequest(
        decision_id="decision-method-pending",
        request="Select the next research method",
        status_scope="Research method review is pending",
        ai_recommendation="Review the non-binding options",
        options=[{"id": "APPROVE", "label": "Approve"}],
        resume_plan={"by_choice": {"APPROVE": {"next_phase": "RESEARCH_PLANNING"}}},
    )
    pending = orchestrator.decisions.block(state, decision, snapshot_id="orchestrator-with-method-decision")
    waiting = orchestrator.start_provenance_audit(plan)
    assert waiting.pending_decision_ids == [decision.decision_id]

    coordinator = InteractiveWorkResearchCoordinator(root, orchestrator=orchestrator)
    action = coordinator.next_action(advance=False)
    assert action.state == "WORK_EXECUTION_REQUIRED"
    assert action.result_schema == "ProvenanceAuditHandoff"
    result = _result(orchestrator, targets, waiting.pending_work)
    resumed = coordinator.submit_result(result)

    assert resumed.state == "DECISION_REQUIRED"
    assert resumed.decision_id == decision.decision_id
    assert orchestrator.status().pending_decision_ids == [decision.decision_id]
    assert pending.pending_decision_ids == [decision.decision_id]
