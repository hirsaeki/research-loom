from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue134_writer_composition as issue134_writer
import test_external_desktop_research_intake as intake


class HistoricalFindingLineageRecoveryTests(ResearchPackageAcceptanceSupport):
    def _legacyize(self, facade, proposal):
        legacy = deepcopy(proposal)
        finding_count = 0
        for action in legacy["proposed_actions"]:
            obj = action.get("payload", {}).get("object", {})
            if obj.get("kind") == "finding":
                finding_count += 1
                obj["adoption_state"] = "candidate"
        self.assertGreater(finding_count, 0)
        legacy.pop("proposal_digest", None)
        legacy["proposal_digest"] = canonical_digest(legacy)
        store = facade._application.conversation_store
        store._db.execute(
            "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
            (store._json(legacy), legacy["proposal_id"]),
        )
        return legacy

    def _advance_head(self, facade):
        proposed = facade.submit_action({
            "action_type": "research_question.propose",
            "payload": {
                "text": "Which later condition advances the lineage-test head?",
                "acceptance_criteria": ["The condition can be inspected."],
                "scope_limits": ["Lineage-test only."],
            },
            "actor_id": "HUMAN-HCL",
        })
        pending = facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
            "actor_id": "HUMAN-HCL",
        })
        confirmed = facade.submit_confirmation({
            "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
            "actor_id": "HUMAN-HCL",
        })
        request = confirmed["decision_request"]
        facade.resolve_human_decision({
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_exact",
            "actor_id": "HUMAN-HCL",
        })

    def _prepare_replay_child_case(self):
        facade, case = self._prepare_case()
        parent_run_id = case["run_id"]
        child_run_id = facade.submit_action({
            "action_type": "desktop_research.investigate",
            "payload": {
                "question_id": case["rq_id"],
                "purpose": "RP1 fixed-source acceptance.",
                "parent_run_id": parent_run_id,
            },
            "actor_id": "HUMAN-HCL",
        })["run_id"]
        facade.start_external_retrieval_attempt(child_run_id, {
            "attempt_id": "ATT-CHILD-1",
            "strategy": "support search",
            "coverage_dimension_ids": ["COV-SUPPORT"],
            "target_locator": "https://example.test/source-a",
        })
        raw = self.workspace / "captures/raw/source-a.html"
        text = self.workspace / "captures/text/source-a.txt"
        raw.write_bytes(b"<html>fixed source body</html>")
        text.write_text(
            "Source A contains the exact supporting excerpt used here.",
            encoding="utf-8",
        )
        capture = facade.capture_external_source(child_run_id, {
            "capture_id": "CAP-1",
            "source_category": "other",
            "exact_locator": "https://example.test/source-a#section-1",
            "acquired_at": "2026-09-14T00:00:00Z",
            "original_file": "captures/raw/source-a.html",
            "original_media_type": "text/html",
            "text_rendition_file": "captures/text/source-a.txt",
        })["capture"]
        facade.complete_external_retrieval_attempt(child_run_id, {
            "attempt_id": "ATT-CHILD-1",
            "outcome": "source_captured",
            "resulting_capture_id": "CAP-1",
        })
        facade.start_external_retrieval_attempt(child_run_id, {
            "attempt_id": "ATT-CHILD-2",
            "strategy": "counter search",
            "coverage_dimension_ids": ["COV-COUNTER"],
        })
        facade.complete_external_retrieval_attempt(child_run_id, {
            "attempt_id": "ATT-CHILD-2",
            "outcome": "no_relevant_source",
        })
        handoff, extension = intake.golden_submission(
            facade._application, child_run_id, capture
        )
        collected = facade.collect_external(
            child_run_id, {"handoff": handoff, "extension": extension}
        )
        child_proposal = deepcopy(collected["execution_result"]["state_delta_proposal"])
        self._legacyize(facade, child_proposal)
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )
        case.update({
            "parent_run_id": parent_run_id,
            "child_run_id": child_run_id,
            "child_proposal": child_proposal,
        })
        return facade, case

    def _tamper_child_action_question(self, facade, child_run_id: str):
        store = facade._application.conversation_store
        correlation = store.load_run_correlation(child_run_id)
        proposal = store.load_proposal(correlation["proposal_id"])
        tampered = deepcopy(proposal)
        tampered["action"]["payload"]["question_id"] = "RQ-WRONG-LINEAGE"
        tampered["action"]["payload_digest"] = canonical_digest(
            tampered["action"]["payload"]
        )
        tampered.pop("proposal_digest", None)
        tampered["proposal_digest"] = canonical_digest(tampered)
        store._db.execute(
            "UPDATE documents SET digest=?,payload_json=? "
            "WHERE message_type='action_proposal' AND document_id=?",
            (
                tampered["proposal_digest"],
                store._json(tampered),
                correlation["proposal_id"],
            ),
        )

    def test_hcl1_run_show_classifies_missing_candidate_without_mutation(self):
        facade, case = self._prepare_case()
        try:
            store = facade._application.conversation_store
            store._db.execute(
                "DELETE FROM state_delta_proposals WHERE proposal_id=?",
                (case["proposal"]["proposal_id"],),
            )
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            before = (state.current_snapshot["id"], state.current_snapshot["content_digest"])
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["status"], "NOT_RECOVERABLE")
            self.assertEqual(diagnosis["stage"], "producer_candidate_lookup")
            self.assertEqual(diagnosis["failure_class"], "producer_candidate_not_found")
            after = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(
                before,
                (after.current_snapshot["id"], after.current_snapshot["content_digest"]),
            )
        finally:
            facade.close()

    def test_hcl1_run_show_classifies_integrity_stale_and_shape_failures(self):
        facade, case = self._prepare_case()
        try:
            legacy = self._legacyize(facade, case["proposal"])
            store = facade._application.conversation_store
            broken = deepcopy(legacy)
            broken["rationale"] = "tampered"
            store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (store._json(broken), broken["proposal_id"]),
            )
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["stage"], "candidate_integrity")
            self.assertEqual(diagnosis["failure_class"], "candidate_integrity_failure")

            store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (store._json(legacy), legacy["proposal_id"]),
            )
            self._advance_head(facade)
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["stage"], "state_binding")
            self.assertEqual(diagnosis["failure_class"], "state_binding_mismatch")
        finally:
            facade.close()

        facade, case = self._prepare_case()
        try:
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["stage"], "candidate_shape")
            self.assertEqual(diagnosis["failure_class"], "candidate_shape_not_recoverable")
            self.assertNotIn("proposed_actions", diagnosis)
        finally:
            facade.close()

    def test_hcl2_replay_child_linkage_recovers_exact_persisted_candidate(self):
        facade, case = self._prepare_replay_child_case()
        try:
            historical = facade._application.conversation_store.load_state_delta_proposal(
                case["child_proposal"]["proposal_id"]
            )
            diagnosis = facade.show_run(case["parent_run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["status"], "RECOVERABLE")
            self.assertEqual(diagnosis["producer_relation"], "replay_child")
            self.assertEqual(diagnosis["producer_run_id"], case["child_run_id"])
            recovered = facade.recover_legacy_desktop_research_finding_candidate(
                case["parent_run_id"]
            )
            self.assertEqual(recovered["producer_relation"], "replay_child")
            self.assertEqual(recovered["producer_run_id"], case["child_run_id"])
            self.assertEqual(
                facade._application.conversation_store.load_state_delta_proposal(
                    case["child_proposal"]["proposal_id"]
                ),
                historical,
            )
            direct = facade.recover_legacy_desktop_research_finding_candidate(
                case["child_run_id"]
            )
            self.assertEqual(
                recovered["state_delta_proposal_id"], direct["state_delta_proposal_id"]
            )
            self.assertTrue(direct["idempotent_reuse"])
        finally:
            facade.close()

    def test_hcl3_ambiguous_replay_child_candidates_fail_closed(self):
        facade, case = self._prepare_replay_child_case()
        try:
            store = facade._application.conversation_store
            legacy = store.load_state_delta_proposal(case["child_proposal"]["proposal_id"])
            duplicate = deepcopy(legacy)
            duplicate["proposal_id"] = "SDP-HCL-DUPLICATE"
            duplicate.pop("proposal_digest", None)
            duplicate["proposal_digest"] = canonical_digest(duplicate)
            store.store_state_delta_proposal(duplicate["proposal_id"], duplicate)
            diagnosis = facade.show_run(case["parent_run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["failure_class"], "multiple_producer_candidates")
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(
                    case["parent_run_id"]
                )
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-CANDIDATE-001"
            )
        finally:
            facade.close()

    def test_hcl4_wrong_replay_binding_is_rejected_and_ablation_proves_guard(self):
        facade, case = self._prepare_replay_child_case()
        try:
            self._tamper_child_action_question(facade, case["child_run_id"])
            diagnosis = facade.show_run(case["parent_run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["stage"], "producer_lineage")
            self.assertEqual(
                diagnosis["failure_class"], "legacy_replay_lineage_unresolved"
            )
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(
                    case["parent_run_id"]
                )
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-PROVENANCE-001"
            )

            with patch(
                "plugins.local_application.finding_recovery_lineage._validate_replay_relation"
            ):
                ablated = facade.recover_legacy_desktop_research_finding_candidate(
                    case["parent_run_id"]
                )
            self.assertEqual(ablated["status"], "RECOVERED")
            self.assertEqual(ablated["producer_run_id"], case["child_run_id"])
        finally:
            facade.close()

    def test_hcl6_replay_recovery_continues_through_argument_package_and_sec_g1_05(self):
        facade, case = self._prepare_replay_child_case()
        try:
            recovered = facade.recover_legacy_desktop_research_finding_candidate(
                case["parent_run_id"]
            )
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": recovered["state_delta_proposal_id"]},
                "actor_id": "HUMAN-HCL6",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-HCL6",
            })
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-HCL6",
            })
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            finding = next(obj for obj in state.effective_objects() if obj.get("kind") == "finding")
            evidence = next(obj for obj in state.effective_objects() if obj.get("kind") == "evidence")
            source = next(obj for obj in state.effective_objects() if obj.get("kind") == "source")
            proposed = facade.submit_action({
                "action_type": "research.argument.propose",
                "payload": {
                    "conclusion": "The recovered Finding supports the bounded validation conclusion.",
                    "warrant": "The approved Finding and Evidence resolve in the exact current Snapshot.",
                    "question_ids": [case["rq_id"]],
                    "finding_ids": [finding["id"]],
                    "evidence_ids": [evidence["id"]],
                    "qualifier": "Within the captured source scope.",
                },
                "actor_id": "HUMAN-HCL6",
            })
            arg_pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                "actor_id": "HUMAN-HCL6",
            })
            committed = facade.submit_confirmation({
                "confirmation_request_id": arg_pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-HCL6",
            })
            self.assertEqual(committed["status"], "SUCCEEDED")
            argument_id = proposed["data"]["argument_candidate"]["id"]
            current = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            built = facade.build_research_package({
                **case["build_input"],
                "snapshot_id": current.current_snapshot["id"],
                "snapshot_digest": current.current_snapshot["content_digest"],
                "lineage_ref": current.active_lineage_ref,
                "object_ids": [source["id"], evidence["id"], finding["id"], argument_id],
            })["package"]
            composition = facade.capture_writer_composition(
                built["package_id"],
                issue134_writer.Issue134WriterCompositionRecoveryTests._proposal(
                    case, argument_id, finding["id"], evidence["id"]
                ),
            )["composition"]
            self.assertFalse(any(
                item.get("section_id") == "SEC-G1-05"
                and item.get("code") == "WRITER-COMPOSITION-NARRATIVE-UNMET"
                for item in composition["validation"]["diagnostics"]
            ))
            facade.select_writer_composition(
                composition["composition_id"], 1, composition["composition_digest"]
            )
            output = self.root / "hcl6-sec-g1-05"
            facade.export_writer_section_input(
                composition["composition_id"], "SEC-G1-05", output
            )
            detached = json.loads(
                (output / "section-writer-input.json").read_text(encoding="utf-8")
            )
            self.assertIn(argument_id, detached["resolved_object_ids"])
            self.assertIn(finding["id"], detached["resolved_object_ids"])
        finally:
            facade.close()
