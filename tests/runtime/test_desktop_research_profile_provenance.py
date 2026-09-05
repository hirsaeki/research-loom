from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from unittest.mock import patch

from core.runtime import CommitReceipt, NormalizationRejected, StateTransitionRejected
from plugins.local_application import LocalApplicationFacade
from runtime_fixtures import make_request
from tests.runtime.test_desktop_research import Flow
from tests.runtime.test_external_desktop_research_intake import (
    adopt_rq,
    golden_submission,
    write_workspace_inputs,
)
from tests.runtime.test_profile_constraint_enforcement import _open_workspace


def _objects(proposal, kind: str):
    return [
        action.payload["object"]
        for action in proposal.proposed_actions
        if action.payload["object"].get("kind") == kind
    ]


def test_capture_provenance_satisfies_resolved_profile_and_ablation_reproduces_rejection():
    flow = Flow(run_id="RUN-DR-PROFILE-PROVENANCE")
    try:
        handoff, extension = flow.build_golden()
        result = flow.service.collect_external(flow.prepared.run.run_id, handoff, extension)
        assert result.state_delta_proposal is not None
        evidence = _objects(result.state_delta_proposal, "evidence")
        expected_digests = {
            detail["original_capture"]["content_digest"]
            for detail in extension["source_capture_details"]
        }
        assert {item["capture_digest"] for item in evidence} == expected_digests

        with tempfile.TemporaryDirectory() as temp:
            with _open_workspace(Path(temp)) as opened:
                state = opened.application.state_repository.load_state_view(
                    opened.project_id,
                    opened.application.state_repository.load_active_lineage_ref(opened.project_id),
                )
                actions = tuple(
                    action
                    for action in result.state_delta_proposal.proposed_actions
                    if action.payload["object"].get("kind") in {"source", "evidence"}
                )
                accepted = opened.application.state_transition_service.apply(
                    make_request(state, actions, suffix="89")
                )
                assert isinstance(accepted, CommitReceipt)

        with tempfile.TemporaryDirectory() as temp:
            with _open_workspace(Path(temp)) as opened:
                state = opened.application.state_repository.load_state_view(
                    opened.project_id,
                    opened.application.state_repository.load_active_lineage_ref(opened.project_id),
                )
                ablated_actions = []
                for action in result.state_delta_proposal.proposed_actions:
                    obj = action.payload["object"]
                    if obj.get("kind") not in {"source", "evidence"}:
                        continue
                    changed = deepcopy(obj)
                    if changed.get("kind") == "evidence":
                        changed.pop("capture_digest", None)
                    ablated_actions.append(type(action)(action.kind, {"object": changed}, source_refs=action.source_refs))
                rejected = opened.application.state_transition_service.apply(
                    make_request(state, ablated_actions, suffix="90")
                )
                assert isinstance(rejected, StateTransitionRejected)
                assert "RT-PROFILE-002" in {issue.error_code for issue in rejected.issues}
    finally:
        flow.close()


def test_resource_reference_uses_registered_source_digest_and_missing_digest_fails_closed():
    flow = Flow(run_id="RUN-DR-PROFILE-RESOURCE")
    try:
        handoff, extension = flow.build_golden()
        handoff["outputs"]["evidence_candidates"][0]["source_basis"] = {
            "basis_type": "resource_reference",
            "resource_reference_id": "REF-SOURCE-1",
        }
        context = flow.exec_store.load_context_pack(flow.prepared.run.context_pack_id)
        assert context is not None
        resource_digest = "sha256:" + "9" * 64
        context["resources"] = [{
            "reference_id": "REF-SOURCE-1",
            "reference_type": "source",
            "object_id": "SRC-1",
            "digest": resource_digest,
            "access_mode": "read",
            "evidentiary_use": "candidate_source",
        }]
        normalize_context = {
            "project_ref": "PRJ-1",
            "lineage_ref": "LIN-1",
            "current_snapshot_ref": flow.seed.current_snapshot["id"],
            "current_snapshot_digest": flow.seed.current_snapshot["content_digest"],
        }
        with patch.object(flow.normalizer._traces, "load_context_pack", return_value=context):
            proposal = flow.normalizer.normalize(handoff, extension, normalize_context)
        supporting = next(
            item for item in _objects(proposal, "evidence")
            if item["evidence_kind"] == "supporting"
        )
        assert supporting["source_id"] == "SRC-1"
        assert supporting["capture_digest"] == resource_digest

        context["resources"][0].pop("digest")
        with patch.object(flow.normalizer._traces, "load_context_pack", return_value=context):
            try:
                flow.normalizer.normalize(handoff, extension, normalize_context)
            except NormalizationRejected as exc:
                assert "lacks object_id or digest" in str(exc)
            else:
                raise AssertionError("missing source resource digest must fail closed")
    finally:
        flow.close()


def test_public_external_intake_human_decision_accepts_profile_complete_evidence():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config_path, profile_path = write_workspace_inputs(root)
        workspace = root / "workspace"
        initialized = LocalApplicationFacade.initialize_workspace(workspace, config_path, profile_path)
        assert initialized["status"] == "INITIALIZED"

        with LocalApplicationFacade.open_workspace(workspace) as facade:
            rq_id = adopt_rq(facade)
            prepared = facade.submit_action({
                "action_type": "desktop_research.investigate",
                "payload": {"question_id": rq_id, "purpose": "Issue #89 public acceptance."},
            })
            run_id = prepared["run_id"]
            before = facade.status()["snapshot"]

            facade.start_external_retrieval_attempt(run_id, {
                "attempt_id": "ATT-1",
                "strategy": "support search",
                "coverage_dimension_ids": ["COV-SUPPORT"],
                "target_locator": "https://example.test/source-a",
            })
            raw = workspace / "captures/raw/source-a.html"
            text = workspace / "captures/text/source-a.txt"
            raw.parent.mkdir(parents=True, exist_ok=True)
            text.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"<html>original source A bytes</html>")
            text.write_text("Source A contains the exact supporting excerpt used here.", encoding="utf-8")
            captured = facade.capture_external_source(run_id, {
                "capture_id": "CAP-1",
                "source_category": "other",
                "exact_locator": "https://example.test/source-a#section-1",
                "acquired_at": "2026-08-31T00:00:00Z",
                "original_file": "captures/raw/source-a.html",
                "original_media_type": "text/html",
                "text_rendition_file": "captures/text/source-a.txt",
            })["capture"]
            facade.complete_external_retrieval_attempt(run_id, {
                "attempt_id": "ATT-1",
                "outcome": "source_captured",
                "target_locator": "https://example.test/source-a",
                "resulting_capture_id": "CAP-1",
            })
            facade.start_external_retrieval_attempt(run_id, {
                "attempt_id": "ATT-2",
                "strategy": "counter search",
                "coverage_dimension_ids": ["COV-COUNTER"],
            })
            facade.complete_external_retrieval_attempt(run_id, {
                "attempt_id": "ATT-2",
                "outcome": "no_relevant_source",
            })

            handoff, extension = golden_submission(facade._application, run_id, captured)
            collected = facade.collect_external(run_id, {"handoff": handoff, "extension": extension})
            proposal = collected["execution_result"]["state_delta_proposal"]
            assert proposal["candidate_only"] is True
            assert facade.status()["snapshot"] == before
            normalized_evidence = [
                action["payload"]["object"]
                for action in proposal["proposed_actions"]
                if action["payload"]["object"].get("kind") == "evidence"
            ]
            assert normalized_evidence
            assert {
                item["capture_digest"] for item in normalized_evidence
            } == {captured["original_capture"]["content_digest"]}

            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposal["proposal_id"]},
                "actor_id": "HUMAN-89",
            })
            assert pending["status"] == "CONFIRMATION_REQUIRED"
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-89",
            })
            assert confirmed["status"] == "HUMAN_DECISION_REQUIRED"
            request = confirmed["decision_request"]
            resolved = facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-89",
            })
            assert resolved["status"] == "RESOLVED"
            assert resolved["commit_receipt"] is not None
            assert facade.status()["snapshot"] != before
