from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.material_reacquisition_facade import RetrievedMaterial
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class Issue171NewMaterialContinuationTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _snapshot(facade):
        repo = facade._application.state_repository
        return deepcopy(
            repo.load_state_view(
                facade.project_id, repo.load_active_lineage_ref(facade.project_id)
            ).current_snapshot
        )

    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    @staticmethod
    def _make_rendition_missing(facade, case):
        store = facade._application.execution_store
        rendition = next(
            item
            for item in store.artifacts_for(case["run_id"])
            if item.role == "desktop_research.text_rendition"
            and item.provenance.get("capture_id") == "CAP-1"
        )
        exact = store.load_artifact(rendition.artifact_id).content
        store._locator_path(rendition.storage_locator, rendition.digest).unlink()
        return rendition, exact

    def _make_new_version(self, facade, case, *, changed_bytes=None):
        self._remove_producer_candidate(facade, case)
        rendition, exact = self._make_rendition_missing(facade, case)
        # Ensure #170's provider has been installed, then patch the provider seam.
        facade.list_actions()
        changed = changed_bytes if changed_bytes is not None else exact + b"\r\n"
        with patch(
            "plugins.local_application.material_reacquisition_facade._regenerate_text_rendition",
            return_value=RetrievedMaterial(
                changed,
                "text/plain",
                "https://example.test/source-a#section-1",
                "fixture-rendition-generator",
                None,
            ),
        ):
            reacquired = facade.submit_action(
                {
                    "action_type": "desktop_research.material.reacquire",
                    "payload": {
                        "historical_run_id": case["run_id"],
                        "capture_id": "CAP-1",
                        "kind": "rendition",
                    },
                }
            )["data"]
        self.assertEqual(reacquired["status"], "NEW_MATERIAL_VERSION")
        self.assertTrue(reacquired["requires_new_canonical_research_result"])
        return rendition, reacquired

    def test_public_continuation_creates_new_candidate_result_without_historical_mutation(self):
        facade, case = self._prepare_case()
        try:
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            state_before = self._snapshot(facade)
            rendition, reacquired = self._make_new_version(facade, case)
            reacq_run_id = reacquired["reacquisition_run_id"]
            result = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": reacq_run_id},
                }
            )
            self.assertEqual(result["status"], "SUCCEEDED")
            data = result["data"]
            self.assertEqual(data["status"], "COMPLETED")
            self.assertTrue(data["candidate_only"])
            self.assertFalse(data["research_state_mutation_performed"])
            self.assertNotEqual(data["new_run_id"], case["run_id"])
            self.assertNotEqual(data["new_run_id"], reacq_run_id)
            self.assertIsNotNone(data["state_delta_proposal_id"])

            store = facade._application.execution_store
            self.assertEqual(store.load_run(case["run_id"]), historical_before)
            self.assertEqual(self._snapshot(facade), state_before)
            self.assertEqual(
                store.diagnose_artifact_content(rendition.artifact_id)["status"],
                "content_missing",
            )
            new_run = store.load_run(data["new_run_id"])
            self.assertEqual(new_run.status.value, "COMPLETED")
            self.assertIsNone(new_run.parent_run_id)
            artifacts = store.artifacts_for(data["new_run_id"])
            self.assertEqual(
                {item.role for item in artifacts},
                {"desktop_research.original_capture", "desktop_research.text_rendition"},
            )
            text = next(item for item in artifacts if item.role == "desktop_research.text_rendition")
            self.assertEqual(text.provenance["reacquisition_run_id"], reacq_run_id)
            self.assertEqual(text.provenance["historical_run_id"], case["run_id"])
            self.assertEqual(text.provenance["historical_capture_id"], "CAP-1")

            old = facade.show_run(case["run_id"])
            self.assertEqual(old["finding_recovery"]["recovery_class"], "material_recovery_required")
            reacq_shown = facade.show_run(reacq_run_id)
            self.assertEqual(reacq_shown["new_material_continuation"]["status"], "completed")
            self.assertEqual(reacq_shown["new_material_continuation"]["new_run_id"], data["new_run_id"])
            self.assertFalse(reacq_shown["new_material_continuation"]["historical_recovery_satisfied"])
            new_shown = facade.show_run(data["new_run_id"])
            self.assertEqual(new_shown["run"]["status"], "COMPLETED")
            self.assertIsNotNone(new_shown["run"]["handoff"]["ref"])
            summary = new_shown["desktop_research"]["retrieval_attempt_summary"]
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["source_captured"], 1)
            self.assertEqual(summary["no_relevant_source"], 1)
            lineage = new_shown["new_material_continuation"]
            self.assertEqual(lineage["historical_run_id"], case["run_id"])
            self.assertEqual(lineage["historical_capture_id"], "CAP-1")
            self.assertEqual(lineage["reacquisition_run_id"], reacq_run_id)
            self.assertEqual(lineage["new_material_artifact_id"], reacquired["new_artifact_id"])
            self.assertEqual(lineage["exact_locator"], "https://example.test/source-a#section-1")
            self.assertEqual(lineage["historical_acquired_at"], reacquired["historical_acquired_at"])
            self.assertEqual(lineage["reacquired_at"], reacquired["reacquired_at"])
            self.assertNotIn("storage_locator", str(lineage))

            repeated = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": reacq_run_id},
                }
            )["data"]
            self.assertTrue(repeated["idempotent_reuse"])
            self.assertEqual(repeated["new_run_id"], data["new_run_id"])
        finally:
            facade.close()

    def test_wrong_class_artifact_fails_closed_and_ablation_shows_guard_is_material(self):
        facade, case = self._prepare_case()
        try:
            _rendition, reacquired = self._make_new_version(facade, case)
            run_id = reacquired["reacquisition_run_id"]
            artifact_id = reacquired["new_artifact_id"]
            db = facade._application.execution_store._connection
            db.execute(
                "UPDATE execution_artifacts SET role=? WHERE artifact_id=?",
                ("desktop_research.reacquired_original", artifact_id),
            )
            rejected = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": run_id},
                }
            )
            self.assertEqual(rejected["status"], "FAILED")
            self.assertIn(
                "persisted new material does not match",
                rejected["issues"][0]["message"],
            )

            # Bounded test-local ablation: removing only the class/binding guard
            # admits the otherwise wrong-class persisted bytes far enough to create
            # the new canonical candidate result. Restoring the guard above rejects it.
            with patch(
                "plugins.local_application.new_material_continuation_admission._require_new_material_artifact_class",
                return_value=None,
            ):
                admitted = facade.submit_action(
                    {
                        "action_type": "desktop_research.material.continue_new_version",
                        "payload": {"reacquisition_run_id": run_id},
                    }
                )["data"]
            self.assertEqual(admitted["status"], "COMPLETED")
        finally:
            facade.close()


    def test_missing_persisted_new_material_fails_before_new_execution(self):
        facade, case = self._prepare_case()
        try:
            _rendition, reacquired = self._make_new_version(facade, case)
            run_id = reacquired["reacquisition_run_id"]
            artifact_id = reacquired["new_artifact_id"]
            store = facade._application.execution_store
            metadata = next(
                item for item in store.artifacts_for(run_id) if item.artifact_id == artifact_id
            )
            store._locator_path(metadata.storage_locator, metadata.digest).unlink()
            rejected = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": run_id},
                }
            )
            self.assertEqual(rejected["status"], "FAILED")
            self.assertIn(
                "persisted new material cannot be verified",
                rejected["issues"][0]["message"],
            )
            shown = facade.show_run(run_id)
            self.assertEqual(shown["new_material_continuation"]["status"], "blocked")
            self.assertEqual(
                shown["new_material_continuation"]["failure_code"],
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
            )
            self.assertEqual(
                facade._application.execution_store.diagnose_artifact_content(artifact_id)[
                    "status"
                ],
                "content_missing",
            )
        finally:
            facade.close()

    def test_changed_rendition_without_historical_excerpt_does_not_rematerialize_old_result(self):
        facade, case = self._prepare_case()
        try:
            rendition, reacquired = self._make_new_version(
                facade,
                case,
                changed_bytes=b"A genuinely different material version without the cited supporting text.\n",
            )
            rejected = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {
                        "reacquisition_run_id": reacquired["reacquisition_run_id"]
                    },
                }
            )
            self.assertEqual(rejected["status"], "FAILED")
            self.assertIn(
                "new canonical Desktop Research result did not complete",
                rejected["issues"][0]["message"],
            )
            reacq_shown = facade.show_run(reacquired["reacquisition_run_id"])
            child_id = reacq_shown["new_material_continuation"]["new_run_id"]
            self.assertIsNotNone(child_id)
            child = facade.show_run(child_id)
            self.assertNotEqual(child["run"]["status"], "COMPLETED")
            self.assertEqual(
                facade._application.execution_store.diagnose_artifact_content(
                    rendition.artifact_id
                )["status"],
                "content_missing",
            )
            repeated = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {
                        "reacquisition_run_id": reacquired["reacquisition_run_id"]
                    },
                }
            )
            self.assertEqual(repeated["status"], "FAILED")
            self.assertIn(
                "bound prior new-material continuation",
                repeated["issues"][0]["message"],
            )
        finally:
            facade.close()

    def test_unrelated_completed_desktop_run_cannot_be_reused_as_continuation(self):
        facade, case = self._prepare_case()
        try:
            _rendition, reacquired = self._make_new_version(facade, case)
            run_id = reacquired["reacquisition_run_id"]
            binding = {
                "relation": "new_material_version_continuation",
                "reacquisition_run_id": run_id,
                "historical_run_id": case["run_id"],
                "historical_capture_id": "CAP-1",
                "new_material_artifact_id": reacquired["new_artifact_id"],
                "new_run_id": case["run_id"],
            }
            store = facade._application.execution_store
            from plugins.local_application import new_material_continuation_admission as admission

            store.store_diagnostic(
                run_id, admission._CONTINUATION_BINDING_DIAGNOSTIC, binding
            )
            store.store_diagnostic(
                case["run_id"], admission._CONTINUATION_BINDING_DIAGNOSTIC, binding
            )

            rejected = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": run_id},
                }
            )
            self.assertEqual(rejected["status"], "FAILED")
            self.assertIn(
                "does not contain the bound new material capture",
                rejected["issues"][0]["message"],
            )
        finally:
            facade.close()

    def test_continuation_binding_is_not_hidden_by_unrelated_diagnostics(self):
        facade, case = self._prepare_case()
        try:
            _rendition, reacquired = self._make_new_version(facade, case)
            run_id = reacquired["reacquisition_run_id"]
            store = facade._application.execution_store
            for index in range(12):
                store.store_diagnostic(run_id, f"fixture.noise.{index}", {"index": index})

            first = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": run_id},
                }
            )["data"]
            self.assertEqual(first["status"], "COMPLETED")

            repeated = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": run_id},
                }
            )["data"]
            self.assertTrue(repeated["idempotent_reuse"])
            self.assertEqual(repeated["new_run_id"], first["new_run_id"])
        finally:
            facade.close()

    def test_public_payload_rejects_caller_supplied_artifact_authority(self):
        facade, _case = self._prepare_case()
        try:
            with self.assertRaises(LocalApplicationError):
                facade.submit_action(
                    {
                        "action_type": "desktop_research.material.continue_new_version",
                        "payload": {
                            "reacquisition_run_id": "RUN-MRA-X",
                            "artifact_id": "caller-controlled",
                        },
                    }
                )
        finally:
            facade.close()
