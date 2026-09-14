from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from plugins.local_execution_store import result_extensions_for_run
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_external_desktop_research_attempt_lifecycle as attempt_lifecycle
import test_issue134_writer_composition as issue134_writer


class HistoricalResultRecoveryTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    def test_hgr1_hgr2_complete_result_rematerializes_candidate_only(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            before = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "proposal_rematerializable")
            self.assertEqual(diagnosis["recovery_route"], "canonical_result_rematerialization")

            action = facade.submit_action({
                "action_type": "desktop_research.finding.recover",
                "payload": {"run_id": case["run_id"]},
                "actor_id": "HUMAN-HGR2",
            })
            self.assertEqual(action["status"], "SUCCEEDED")
            recovered = action["data"]
            self.assertEqual(recovered["route"], "canonical_result_rematerialization")
            self.assertFalse(recovered["research_state_mutation_performed"])
            repeated = facade.submit_action({
                "action_type": "desktop_research.finding.recover",
                "payload": {"run_id": case["run_id"]},
                "actor_id": "HUMAN-HGR2",
            })["data"]
            self.assertEqual(repeated["state_delta_proposal_id"], recovered["state_delta_proposal_id"])
            self.assertTrue(repeated["idempotent_reuse"])

            proposal = facade._application.conversation_store.load_state_delta_proposal(
                recovered["state_delta_proposal_id"]
            )
            provenance = proposal["provenance"]["historical_recovery"]
            self.assertEqual(provenance["source_run_id"], case["run_id"])
            self.assertEqual(
                provenance["source_handoff_digest"], diagnosis["source_handoff_digest"]
            )
            findings = [
                action["payload"]["object"]
                for action in proposal["proposed_actions"]
                if action["payload"]["object"]["kind"] == "finding"
            ]
            self.assertTrue(findings)
            self.assertTrue(all(item["adoption_state"] == "approved" for item in findings))
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": recovered["state_delta_proposal_id"]},
                "actor_id": "HUMAN-HGR2",
            })
            self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")
            after = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot
            self.assertEqual(before, after)
        finally:
            facade.close()

    def test_hgr3_incomplete_historical_run_uses_existing_bounded_replay(self):
        helper = attempt_lifecycle.ExternalDesktopResearchAttemptLifecycleTests(methodName="runTest")
        app, facade, run_id = helper._completed_historical_run_with_open_attempt(
            self.root / "hgr3-replay"
        )
        try:
            diagnosis = facade.show_run(run_id)["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "replay_required")
            replay = facade.replay_completed_desktop_research_run(run_id)
            self.assertEqual(replay["status"], "RUN_REPLAY_PREPARED")
            self.assertEqual(replay["parent_run_id"], run_id)
        finally:
            app.close()

    def test_hgr4_unreadable_capture_requires_material_recovery(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            with patch.object(
                facade._application.execution_store,
                "load_artifact_verified_once",
                side_effect=FileNotFoundError("historical blob unavailable"),
            ):
                diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "material_recovery_required")
            self.assertEqual(
                diagnosis["recovery_failure_class"], "material_recovery_required"
            )
        finally:
            facade.close()

    def test_hgr5_ablation_result_binding_guard_blocks_mismatched_extension(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            extension = deepcopy(result_extensions_for_run(store, case["run_id"])[0])
            extension["handoff_binding"]["run_id"] = "RUN-WRONG"
            with patch(
                "plugins.local_application.historical_result_recovery_facade.result_extensions_for_run",
                return_value=(extension,),
            ):
                guarded = facade.show_run(case["run_id"])["finding_recovery"]
                self.assertEqual(guarded["recovery_class"], "not_recoverable")
                with patch(
                    "plugins.local_application.historical_result_recovery_facade.DesktopResearchNormalizer.validate_extension",
                    return_value=(),
                ):
                    ablated = facade.show_run(case["run_id"])["finding_recovery"]
                self.assertEqual(ablated["recovery_class"], "proposal_rematerializable")
                self.assertEqual(
                    ablated["recovery_route"], "canonical_result_rematerialization"
                )
        finally:
            facade.close()

    def test_hgr8_rematerialization_reaches_same_sec_g1_05(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            recovered = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": recovered["state_delta_proposal_id"]},
                "actor_id": "HUMAN-HGR8",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-HGR8",
            })
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-HGR8",
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
                "actor_id": "HUMAN-HGR8",
            })
            arg_pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                "actor_id": "HUMAN-HGR8",
            })
            committed = facade.submit_confirmation({
                "confirmation_request_id": arg_pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-HGR8",
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
            output = self.root / "hgr8-sec-g1-05"
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

    def test_review_corrupt_result_extension_shape_fails_closed(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            with patch(
                "plugins.local_application.historical_result_recovery_facade.result_extensions_for_run",
                return_value=("corrupt-extension",),
            ):
                diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "not_recoverable")
            self.assertEqual(
                diagnosis["recovery_failure_class"], "canonical_result_incomplete"
            )
        finally:
            facade.close()

    def test_review_corrupt_replay_action_shape_fails_closed(self):
        helper = attempt_lifecycle.ExternalDesktopResearchAttemptLifecycleTests(methodName="runTest")
        app, facade, run_id = helper._completed_historical_run_with_open_attempt(
            self.root / "review-corrupt-replay-action"
        )
        try:
            with patch.object(
                facade._application.conversation_store,
                "load_proposal",
                return_value={"action": None},
            ):
                diagnosis = facade.show_run(run_id)["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "not_recoverable")
        finally:
            app.close()
