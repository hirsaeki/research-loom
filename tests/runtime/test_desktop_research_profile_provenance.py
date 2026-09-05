from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from core.execution import (
    CapabilityContextExtensionRegistry,
    CapabilityExecutionService,
    CapabilityRegistry,
)
from core.execution.testing import AllowListedAuthorizationProvider, StaticClock
from core.runtime import (
    CapabilityNormalizationBoundary,
    CommitReceipt,
    StateTransitionRejected,
)
from plugins.desktop_research import (
    DesktopResearchAttemptRecorder,
    DesktopResearchCaptureService,
    DesktopResearchContextValidator,
    DesktopResearchExternalAdapter,
    DesktopResearchNormalizer,
    with_context_extension_digest,
)
from plugins.desktop_research.digest import canonical_extension_digest
from plugins.local_application import LocalApplicationFacade
from plugins.local_execution_store import (
    LocalCapabilityContextExtensionStore,
    LocalExecutionStore,
    LocalOperationalTraceStore,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository
from runtime_fixtures import make_request, project, rq, seed_state
from tests.runtime.test_desktop_research import (
    DR_DESCRIPTOR,
    Flow,
    build_context,
    build_context_extension,
    build_invocation,
    refresh,
)
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


def _resource_flow(run_id: str) -> tuple[Flow, object]:
    flow = Flow.__new__(Flow)
    flow.temp = tempfile.TemporaryDirectory()
    flow.root = Path(flow.temp.name)
    flow.seed = seed_state(
        objects=[project(), rq(state="approved")],
        mode="real",
        snapshot_id="SNP-DR-RESOURCE-0",
    )
    flow.state_repo = SQLiteResearchStateRepository(flow.root / "state.sqlite3")
    flow.state_repo.initialize_from_validated_state_view(flow.seed)
    flow.exec_store = LocalExecutionStore(flow.root / "execution")
    flow.context_store = LocalCapabilityContextExtensionStore(flow.exec_store.root)
    flow.ops = LocalOperationalTraceStore(flow.exec_store.root, flow.exec_store)
    flow.clock = StaticClock("2026-08-27T00:00:00Z")

    record = flow.exec_store.register_input_bytes(
        "REF-SOURCE-1",
        b"registered source resource bytes",
        media_type="text/plain",
    )
    flow.context = build_context(flow.seed)
    flow.context["resources"] = [{
        "reference_id": "REF-SOURCE-1",
        "reference_type": "source",
        "object_id": "SRC-1",
        "digest": record.digest,
        "locator": record.storage_locator,
        "access_mode": "read",
        "evidentiary_use": "candidate_source",
    }]
    flow.context["bounds"]["max_resources"] = 1
    refresh(flow.context, "context_pack_digest")

    flow.invocation = build_invocation(flow.context, run_id=run_id)
    flow.invocation["runtime_authorization_evidence"]["resource_reference_ids"] = [
        "REF-SOURCE-1"
    ]
    refresh(flow.invocation, "invocation_digest")

    flow.context_extension = build_context_extension(flow.context)
    flow.context_extension["resource_role_bindings"] = [{
        "reference_id": "REF-SOURCE-1",
        "role": "candidate_source",
    }]
    flow.context_extension["budget"]["max_total_resources"] = 1
    flow.context_extension["budget"]["max_candidate_source_resources"] = 1
    flow.context_extension = with_context_extension_digest(flow.context_extension)

    registry = CapabilityRegistry()
    registry.register(DesktopResearchExternalAdapter(), DR_DESCRIPTOR)
    flow.normalizer = DesktopResearchNormalizer(
        flow.exec_store,
        flow.context_store,
        flow.exec_store,
        flow.ops,
    )
    flow.service = CapabilityExecutionService(
        registry,
        flow.exec_store,
        flow.state_repo,
        AllowListedAuthorizationProvider((
            flow.invocation["runtime_authorization_evidence"]["authorization_digest"],
        )),
        flow.exec_store,
        CapabilityNormalizationBoundary((flow.normalizer,)),
        flow.clock,
        artifact_store=flow.exec_store,
        context_extension_registry=CapabilityContextExtensionRegistry((
            DesktopResearchContextValidator(),
        )),
        context_extension_store=flow.context_store,
    )
    flow.prepared = flow.service.prepare_external(
        DR_DESCRIPTOR,
        flow.invocation,
        flow.context,
        lineage_ref="LIN-1",
        context_extension=flow.context_extension,
    )
    flow.recorder = DesktopResearchAttemptRecorder(
        flow.prepared.run,
        flow.exec_store,
        flow.ops,
        flow.clock,
    )
    flow.capture = DesktopResearchCaptureService(flow.exec_store)
    return flow, record


def _use_resource_basis(flow: Flow):
    handoff, extension = flow.build_golden()
    handoff["outputs"]["evidence_candidates"][0]["source_basis"] = {
        "basis_type": "resource_reference",
        "resource_reference_id": "REF-SOURCE-1",
    }
    refresh(handoff, "handoff_digest")
    extension["handoff_binding"]["handoff_digest"] = handoff["handoff_digest"]
    extension["citation_details"] = [
        item
        for item in extension["citation_details"]
        if item["handoff_output_id"] != "EVC-1"
    ]
    extension["extension_digest"] = canonical_extension_digest(extension)
    return handoff, extension


class DesktopResearchProfileProvenanceTests(unittest.TestCase):
    def test_capture_provenance_satisfies_resolved_profile_and_ablation_reproduces_rejection(self):
        flow = Flow(run_id="RUN-DR-PROFILE-PROVENANCE")
        try:
            handoff, extension = flow.build_golden()
            result = flow.service.collect_external(
                flow.prepared.run.run_id,
                handoff,
                extension,
            )
            self.assertIsNotNone(result.state_delta_proposal)
            evidence = _objects(result.state_delta_proposal, "evidence")
            expected_digests = {
                detail["original_capture"]["content_digest"]
                for detail in extension["source_capture_details"]
            }
            self.assertEqual(
                {item["capture_digest"] for item in evidence},
                expected_digests,
            )

            with tempfile.TemporaryDirectory() as temp:
                with _open_workspace(Path(temp)) as opened:
                    state = opened.application.state_repository.load_state_view(
                        opened.project_id,
                        opened.application.state_repository.load_active_lineage_ref(
                            opened.project_id
                        ),
                    )
                    actions = tuple(
                        action
                        for action in result.state_delta_proposal.proposed_actions
                        if action.payload["object"].get("kind") in {"source", "evidence"}
                    )
                    accepted = opened.application.state_transition_service.apply(
                        make_request(state, actions, suffix="29")
                    )
                    self.assertIsInstance(accepted, CommitReceipt)

            with tempfile.TemporaryDirectory() as temp:
                with _open_workspace(Path(temp)) as opened:
                    state = opened.application.state_repository.load_state_view(
                        opened.project_id,
                        opened.application.state_repository.load_active_lineage_ref(
                            opened.project_id
                        ),
                    )
                    before = deepcopy(state.current_snapshot)
                    ablated_actions = []
                    for action in result.state_delta_proposal.proposed_actions:
                        obj = action.payload["object"]
                        if obj.get("kind") not in {"source", "evidence"}:
                            continue
                        changed = deepcopy(obj)
                        if changed.get("kind") == "evidence":
                            changed.pop("capture_digest", None)
                        ablated_actions.append(
                            type(action)(
                                action.kind,
                                {"object": changed},
                                source_refs=action.source_refs,
                            )
                        )
                    rejected = opened.application.state_transition_service.apply(
                        make_request(state, ablated_actions, suffix="30")
                    )
                    self.assertIsInstance(rejected, StateTransitionRejected)
                    self.assertIn(
                        "RT-PROFILE-002",
                        {issue.error_code for issue in rejected.issues},
                    )
                    after = opened.application.state_repository.load_state_view(
                        opened.project_id,
                        opened.application.state_repository.load_active_lineage_ref(
                            opened.project_id
                        ),
                    ).current_snapshot
                    self.assertEqual(after, before)
        finally:
            flow.close()

    def test_registered_resource_digest_is_verified_and_tamper_is_rejected(self):
        normal, record = _resource_flow("RUN-DR-PROFILE-RESOURCE-OK")
        try:
            handoff, extension = _use_resource_basis(normal)
            result = normal.service.collect_external(
                normal.prepared.run.run_id,
                handoff,
                extension,
            )
            self.assertIsNotNone(result.state_delta_proposal)
            self.assertEqual(result.issues, ())
            supporting = next(
                item
                for item in _objects(result.state_delta_proposal, "evidence")
                if item["evidence_kind"] == "supporting"
            )
            self.assertEqual(supporting["source_id"], "SRC-1")
            self.assertEqual(supporting["capture_digest"], record.digest)
        finally:
            normal.close()

        tampered, record = _resource_flow("RUN-DR-PROFILE-RESOURCE-TAMPER")
        try:
            handoff, extension = _use_resource_basis(tampered)
            hex_digest = record.digest.split(":", 1)[1]
            blob = tampered.exec_store.blob_root / hex_digest[:2] / hex_digest
            content = bytearray(blob.read_bytes())
            content[0] ^= 1
            blob.write_bytes(bytes(content))
            artifacts_before = tuple(
                tampered.exec_store.artifacts_for(tampered.prepared.run.run_id)
            )

            result = tampered.service.collect_external(
                tampered.prepared.run.run_id,
                handoff,
                extension,
            )
            self.assertIsNone(result.state_delta_proposal)
            self.assertTrue(result.issues)
            self.assertTrue(any(
                "failed integrity verification" in issue.message
                for issue in result.issues
            ))
            self.assertEqual(
                tuple(tampered.exec_store.artifacts_for(tampered.prepared.run.run_id)),
                artifacts_before,
            )
        finally:
            tampered.close()

    def test_public_external_intake_stores_profile_complete_candidate_without_extra_decision_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_workspace_inputs(root)
            workspace = root / "workspace"
            initialized = LocalApplicationFacade.initialize_workspace(
                workspace,
                config_path,
                profile_path,
            )
            self.assertEqual(initialized["status"], "INITIALIZED")

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = adopt_rq(facade)
                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {
                        "question_id": rq_id,
                        "purpose": "Issue #89 public acceptance.",
                    },
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
                text.write_text(
                    "Source A contains the exact supporting excerpt used here.",
                    encoding="utf-8",
                )
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

                handoff, extension = golden_submission(
                    facade._application,
                    run_id,
                    captured,
                )
                run = facade._application.execution_store.load_run(run_id)
                self.assertIsNotNone(run)
                context = facade._application.execution_store.load_context_pack(
                    run.context_pack_id
                )
                self.assertIsNotNone(context)
                handoff["preserved_context"]["effective_constraint_paths"] = [
                    str(item["path"])
                    for item in context["effective_constraints"]
                ]
                refresh(handoff, "handoff_digest")
                extension["handoff_binding"]["handoff_digest"] = handoff[
                    "handoff_digest"
                ]
                extension["extension_digest"] = canonical_extension_digest(extension)

                collected = facade.collect_external(
                    run_id,
                    {"handoff": handoff, "extension": extension},
                )
                self.assertEqual(collected["status"], "CAPABILITY_RESULT_COLLECTED")
                execution = collected["execution_result"]
                self.assertEqual(execution["issues"], [])
                self.assertEqual(execution["run"]["status"], "COMPLETED")
                proposal = execution["state_delta_proposal"]
                self.assertIsNotNone(proposal)
                self.assertTrue(proposal["candidate_only"])
                self.assertEqual(facade.status()["snapshot"], before)
                normalized_evidence = [
                    action["payload"]["object"]
                    for action in proposal["proposed_actions"]
                    if action["payload"]["object"].get("kind") == "evidence"
                ]
                self.assertTrue(normalized_evidence)
                self.assertEqual(
                    {item["capture_digest"] for item in normalized_evidence},
                    {captured["original_capture"]["content_digest"]},
                )

                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {
                        "state_delta_proposal_id": proposal["proposal_id"],
                    },
                    "actor_id": "HUMAN-89",
                })
                self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"][
                        "confirmation_request_id"
                    ],
                    "actor_id": "HUMAN-89",
                })
                self.assertEqual(confirmed["status"], "SUCCEEDED")
                self.assertNotEqual(facade.status()["snapshot"], before)

                status = facade.submit_action({
                    "action_type": "research.status",
                    "payload": {"kinds": ["evidence"]},
                })
                self.assertEqual(status["status"], "SUCCEEDED")
                stored_evidence = status["data"]["objects"]
                self.assertTrue(stored_evidence)
                self.assertEqual(
                    {item["capture_digest"] for item in stored_evidence},
                    {captured["original_capture"]["content_digest"]},
                )


if __name__ == "__main__":
    unittest.main()
