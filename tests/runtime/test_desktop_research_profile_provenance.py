from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from unittest.mock import patch

from core.runtime import CommitReceipt, StateTransitionRejected
from runtime_fixtures import make_request
from tests.runtime.test_desktop_research import Flow
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
            except ValueError as exc:
                assert "lacks object_id or digest" in str(exc)
            else:
                raise AssertionError("missing source resource digest must fail closed")
    finally:
        flow.close()
