from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.cli import main as cli_main
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue134_writer_composition as issue134_writer


class FindingCandidateRecoveryTests(ResearchPackageAcceptanceSupport):
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
        serialized = facade._application.conversation_store._json(legacy)
        db = facade._application.conversation_store._db
        db.execute(
            "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
            (serialized, legacy["proposal_id"]),
        )
        return legacy

    def _advance_head(self, facade):
        proposed = facade.submit_action({
            "action_type": "research_question.propose",
            "payload": {
                "text": "Which later condition advances the recovery-test head?",
                "acceptance_criteria": ["The condition can be inspected."],
                "scope_limits": ["Recovery-test only."],
            },
            "actor_id": "HUMAN-FCR",
        })
        pending = facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
            "actor_id": "HUMAN-FCR",
        })
        confirmed = facade.submit_confirmation({
            "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
            "actor_id": "HUMAN-FCR",
        })
        request = confirmed["decision_request"]
        facade.resolve_human_decision({
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_exact",
            "actor_id": "HUMAN-FCR",
        })

    def test_public_cli_recovers_by_run_id_only(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
        finally:
            facade.close()
        input_path = self.root / "recover-input.json"
        input_path.write_text(json.dumps({
            "action_type": "desktop_research.finding.recover",
            "payload": {"run_id": case["run_id"]},
            "actor_id": "HUMAN-FCR-CLI",
        }), encoding="utf-8")
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = cli_main([
                "action", "submit",
                "--workspace", str(self.workspace),
                "--json", str(input_path),
            ])
        self.assertEqual(code, 0)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["status"], "SUCCEEDED")
        self.assertEqual(payload["data"]["status"], "RECOVERED")
        self.assertEqual(payload["data"]["run_id"], case["run_id"])
        self.assertFalse(payload["action_receipt"]["research_state_mutation_performed"])

    def test_fcr1_fcr2_public_run_recovery_is_candidate_only_immutable_and_idempotent(self):
        facade, case = self._prepare_case()
        try:
            historical = self._legacyize(facade, case["proposal"])
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            before = (state.current_snapshot["id"], state.current_snapshot["content_digest"])

            first = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            second = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertFalse(first["research_state_mutation_performed"])
            self.assertFalse(first["idempotent_reuse"])
            self.assertTrue(second["idempotent_reuse"])
            self.assertEqual(first["state_delta_proposal_id"], second["state_delta_proposal_id"])
            self.assertEqual(
                facade._application.conversation_store.load_state_delta_proposal(historical["proposal_id"]),
                historical,
            )
            recovered = facade._application.conversation_store.load_state_delta_proposal(
                first["state_delta_proposal_id"]
            )
            old_actions = deepcopy(historical["proposed_actions"])
            new_actions = deepcopy(recovered["proposed_actions"])
            for old, new in zip(old_actions, new_actions, strict=True):
                old_obj = old["payload"]["object"]
                new_obj = new["payload"]["object"]
                if old_obj["kind"] == "finding":
                    self.assertEqual(old_obj.pop("adoption_state"), "candidate")
                    self.assertEqual(new_obj.pop("adoption_state"), "approved")
                self.assertEqual(old, new)
            after_state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(before, (after_state.current_snapshot["id"], after_state.current_snapshot["content_digest"]))
        finally:
            facade.close()

    def test_fcr3_recovered_candidate_uses_existing_confirmation_and_human_decision_flow(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            recovered = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": recovered["state_delta_proposal_id"]},
                "actor_id": "HUMAN-FCR3",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-FCR3",
            })
            self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-FCR3",
            })
            facade.close()
            facade = LocalApplicationFacade.open_workspace(self.workspace)
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            finding = next(obj for obj in state.effective_objects() if obj.get("kind") == "finding")
            self.assertEqual(finding["adoption_state"], "approved")
            public = facade.submit_action({
                "action_type": "research.status",
                "payload": {"kinds": ["finding"]},
                "actor_id": "HUMAN-FCR3",
            })
            public_finding = next(
                obj for obj in public["data"]["objects"] if obj.get("kind") == "finding"
            )
            self.assertEqual(public_finding["adoption_state"], "approved")
        finally:
            facade.close()

    def test_fcr4_stale_candidate_is_rejected_and_ablation_shows_guard_is_necessary(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            self._advance_head(facade)
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(caught.exception.code, "APPLICATION-FINDING-RECOVERY-STALE-001")

            # Ablation: disabling only the exact-current-Snapshot eligibility guard
            # lets the same stale historical proposal enter recovery. Restoring the
            # guard above is therefore necessary, not decorative.
            with patch("plugins.local_application.finding_recovery_facade._require_exact_current_snapshot"):
                ablated = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(ablated["status"], "RECOVERED")
        finally:
            facade.close()

    def test_fcr4_mismatched_candidate_provenance_fails_closed(self):
        facade, case = self._prepare_case()
        try:
            legacy = self._legacyize(facade, case["proposal"])
            tampered = deepcopy(legacy)
            tampered["provenance"]["implementation_version"] = "tampered-version"
            tampered.pop("proposal_digest", None)
            tampered["proposal_digest"] = canonical_digest(tampered)
            facade._application.conversation_store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (facade._application.conversation_store._json(tampered), tampered["proposal_id"]),
            )
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-PROVENANCE-001"
            )
        finally:
            facade.close()

    def test_fcr4_corrupt_handoff_fails_closed(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            run = facade._application.execution_store.load_run(case["run_id"])
            db = facade._application.execution_store._connection
            row = db.execute(
                "SELECT payload_json FROM execution_documents "
                "WHERE document_type='handoff' AND identity=?",
                (run.handoff_ref,),
            ).fetchone()
            handoff = json.loads(str(row["payload_json"]))
            handoff["project_id"] = "PRJ-TAMPERED"
            db.execute(
                "UPDATE execution_documents SET payload_json=? "
                "WHERE document_type='handoff' AND identity=?",
                (json.dumps(handoff, sort_keys=True, separators=(",", ":")), run.handoff_ref),
            )
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-INTEGRITY-001"
            )
        finally:
            facade.close()

    def test_fcr4_ambiguous_run_derived_candidates_fail_closed(self):
        facade, case = self._prepare_case()
        try:
            legacy = self._legacyize(facade, case["proposal"])
            duplicate = deepcopy(legacy)
            duplicate["proposal_id"] = "SDP-LEGACY-DUPLICATE"
            duplicate.pop("proposal_digest", None)
            duplicate["proposal_digest"] = canonical_digest(duplicate)
            facade._application.conversation_store.store_state_delta_proposal(
                duplicate["proposal_id"], duplicate
            )
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(caught.exception.code, "APPLICATION-FINDING-RECOVERY-CANDIDATE-001")
        finally:
            facade.close()

    def test_fcr4_corrupt_unrecognized_and_missing_candidates_fail_closed(self):
        facade, case = self._prepare_case()
        try:
            legacy = self._legacyize(facade, case["proposal"])
            db = facade._application.conversation_store._db
            broken = deepcopy(legacy)
            broken["rationale"] = "tampered"
            db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (facade._application.conversation_store._json(broken), broken["proposal_id"]),
            )
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(caught.exception.code, "APPLICATION-FINDING-RECOVERY-INTEGRITY-001")

            db.execute("DELETE FROM state_delta_proposals WHERE proposal_id=?", (legacy["proposal_id"],))
            with self.assertRaises(LocalApplicationError) as missing:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(missing.exception.code, "APPLICATION-FINDING-RECOVERY-CANDIDATE-001")
        finally:
            facade.close()

    def test_fcr5_recovered_finding_continues_through_argument_package_and_sec_g1_05(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            recovered = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": recovered["state_delta_proposal_id"]},
                "actor_id": "HUMAN-FCR5",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-FCR5",
            })
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-FCR5",
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
                "actor_id": "HUMAN-FCR5",
            })
            arg_pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                "actor_id": "HUMAN-FCR5",
            })
            committed = facade.submit_confirmation({
                "confirmation_request_id": arg_pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-FCR5",
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
            output = self.root / "fcr5-sec-g1-05"
            facade.export_writer_section_input(
                composition["composition_id"], "SEC-G1-05", output
            )
            detached = json.loads((output / "section-writer-input.json").read_text(encoding="utf-8"))
            self.assertIn(argument_id, detached["resolved_object_ids"])
            self.assertIn(finding["id"], detached["resolved_object_ids"])
        finally:
            facade.close()

    def test_fcr6_current_approved_shape_is_not_rewritten(self):
        facade, case = self._prepare_case()
        try:
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(caught.exception.code, "APPLICATION-FINDING-RECOVERY-SHAPE-001")
        finally:
            facade.close()
