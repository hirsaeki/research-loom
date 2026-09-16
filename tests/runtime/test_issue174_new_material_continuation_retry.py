from __future__ import annotations

from unittest.mock import patch

from core.execution import ExecutionFailureCode, ExecutionIssue, RunStatus
from plugins.local_application import new_material_continuation_admission as admission
from plugins.local_application.material_reacquisition_facade import RetrievedMaterial
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class Issue174NewMaterialContinuationRetryTests(ResearchPackageAcceptanceSupport):
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
        _rendition, exact = self._make_rendition_missing(facade, case)
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
            result = facade.submit_action(
                {
                    "action_type": "desktop_research.material.reacquire",
                    "payload": {
                        "historical_run_id": case["run_id"],
                        "capture_id": "CAP-1",
                        "kind": "rendition",
                    },
                }
            )["data"]
        self.assertEqual(result["status"], "NEW_MATERIAL_VERSION")
        return result

    @staticmethod
    def _continue(facade, reacquisition_run_id):
        return facade.submit_action(
            {
                "action_type": "desktop_research.material.continue_new_version",
                "payload": {"reacquisition_run_id": reacquisition_run_id},
            }
        )

    def _make_correctable_running_attempt(self, facade, case):
        reacquired = self._make_new_version(
            facade,
            case,
            changed_bytes=b"A different version without the historical cited excerpt.\n",
        )
        first = self._continue(facade, reacquired["reacquisition_run_id"])
        self.assertEqual(first["status"], "FAILED")
        shown = facade.show_run(reacquired["reacquisition_run_id"])
        run_id = shown["new_material_continuation"]["new_run_id"]
        run = facade._application.execution_store.load_run(run_id)
        self.assertEqual(run.status, RunStatus.RUNNING)
        return reacquired, run_id

    def test_claim_only_history_does_not_poison_later_exact_continuation(self):
        facade, case = self._prepare_case()
        try:
            reacquired = self._make_new_version(facade, case)
            run_id = reacquired["reacquisition_run_id"]
            claim = {
                "relation": "new_material_version_continuation_claim",
                "reacquisition_run_id": run_id,
                "historical_run_id": case["run_id"],
                "historical_capture_id": "CAP-1",
                "new_material_artifact_id": reacquired["new_artifact_id"],
            }
            store = facade._application.execution_store
            self.assertTrue(
                store.claim_diagnostic_once(
                    run_id, admission._CONTINUATION_CLAIM_DIAGNOSTIC, claim
                )
            )

            completed = self._continue(facade, run_id)["data"]
            self.assertEqual(completed["status"], "COMPLETED")
            self.assertFalse(completed["idempotent_reuse"])
            self.assertEqual(admission._continuation_claim(store, run_id), claim)
        finally:
            facade.close()

    def test_correctable_running_attempt_is_observed_not_aborted_or_duplicated(self):
        facade, case = self._prepare_case()
        try:
            reacquired, first_run_id = self._make_correctable_running_attempt(facade, case)
            repeated = self._continue(facade, reacquired["reacquisition_run_id"])
            self.assertEqual(repeated["status"], "SUCCEEDED")
            self.assertEqual(repeated["data"]["status"], "RUNNING")
            self.assertTrue(repeated["data"]["in_progress"])
            self.assertEqual(repeated["data"]["new_run_id"], first_run_id)
            self.assertEqual(
                facade._application.execution_store.load_run(first_run_id).status,
                RunStatus.RUNNING,
            )
        finally:
            facade.close()

    def test_aborted_attempt_remains_terminal_and_explicit_retry_creates_child(self):
        facade, case = self._prepare_case()
        try:
            reacquired, first_run_id = self._make_correctable_running_attempt(facade, case)
            facade._application.capability_execution_service.abort(
                first_run_id, reason="fixture operator abort"
            )
            first_after = facade._application.execution_store.load_run(first_run_id)
            self.assertEqual(first_after.status, RunStatus.ABORTED)

            retried = self._continue(facade, reacquired["reacquisition_run_id"])
            self.assertEqual(retried["status"], "FAILED")
            shown = facade.show_run(reacquired["reacquisition_run_id"])
            retry_run_id = shown["new_material_continuation"]["new_run_id"]
            self.assertNotEqual(retry_run_id, first_run_id)
            retry = facade._application.execution_store.load_run(retry_run_id)
            self.assertEqual(retry.parent_run_id, first_run_id)
            self.assertEqual(retry.attempt, first_after.attempt + 1)
            self.assertEqual(
                facade._application.execution_store.load_run(first_run_id).status,
                RunStatus.ABORTED,
            )
        finally:
            facade.close()

    def test_failed_attempt_remains_terminal_and_exact_retry_creates_child(self):
        facade, case = self._prepare_case()
        try:
            reacquired, first_run_id = self._make_correctable_running_attempt(facade, case)
            service = facade._application.capability_execution_service
            first = facade._application.execution_store.load_run(first_run_id)
            service._fail(
                first,
                ExecutionIssue(
                    ExecutionFailureCode.EXECUTION_FAILED.value,
                    "fixture continuation failure",
                ),
            )
            self.assertEqual(
                facade._application.execution_store.load_run(first_run_id).status,
                RunStatus.FAILED,
            )

            retried = self._continue(facade, reacquired["reacquisition_run_id"])
            self.assertEqual(retried["status"], "FAILED")
            shown = facade.show_run(reacquired["reacquisition_run_id"])
            retry_run_id = shown["new_material_continuation"]["new_run_id"]
            self.assertNotEqual(retry_run_id, first_run_id)
            retry = facade._application.execution_store.load_run(retry_run_id)
            self.assertEqual(retry.parent_run_id, first_run_id)
            self.assertEqual(
                facade._application.execution_store.load_run(first_run_id).status,
                RunStatus.FAILED,
            )
        finally:
            facade.close()

    def test_interruption_after_run_prepare_before_binding_recovers_parent_lineage(self):
        facade, case = self._prepare_case()
        try:
            reacquired = self._make_new_version(facade, case)
            reacq_run_id = reacquired["reacquisition_run_id"]
            store = facade._application.execution_store
            original_store = store.store_diagnostic
            interrupted = {"done": False}

            def stop_before_binding(run_id, kind, payload):
                if (
                    not interrupted["done"]
                    and kind == admission._CONTINUATION_BINDING_DIAGNOSTIC
                ):
                    interrupted["done"] = True
                    raise KeyboardInterrupt("fixture process interruption before binding")
                return original_store(run_id, kind, payload)

            with patch.object(store, "store_diagnostic", side_effect=stop_before_binding):
                with self.assertRaises(KeyboardInterrupt):
                    self._continue(facade, reacq_run_id)

            correlations = facade._application.conversation_store.run_correlations_for_conversation(
                admission._continuation_conversation_id(reacq_run_id),
                limit=4,
            )
            self.assertEqual(len(correlations), 1)
            first_run_id = correlations[0]["run_id"]
            self.assertEqual(store.load_run(first_run_id).status, RunStatus.RUNNING)
            self.assertIsNone(admission._continuation_binding(store, reacq_run_id))

            completed = self._continue(facade, reacq_run_id)["data"]
            self.assertEqual(completed["status"], "COMPLETED")
            self.assertNotEqual(completed["new_run_id"], first_run_id)
            self.assertEqual(store.load_run(first_run_id).status, RunStatus.ABORTED)
            retry = store.load_run(completed["new_run_id"])
            self.assertEqual(retry.parent_run_id, first_run_id)
            self.assertEqual(retry.attempt, store.load_run(first_run_id).attempt + 1)
        finally:
            facade.close()

    def test_completed_correlated_attempt_without_binding_is_rebound_and_reused(self):
        facade, case = self._prepare_case()
        try:
            reacquired = self._make_new_version(facade, case)
            reacq_run_id = reacquired["reacquisition_run_id"]
            store = facade._application.execution_store
            original_store = store.store_diagnostic

            def drop_binding(run_id, kind, payload):
                if kind == admission._CONTINUATION_BINDING_DIAGNOSTIC:
                    return None
                return original_store(run_id, kind, payload)

            with patch.object(store, "store_diagnostic", side_effect=drop_binding):
                first = self._continue(facade, reacq_run_id)
            self.assertEqual(first["status"], "FAILED")

            correlations = facade._application.conversation_store.run_correlations_for_conversation(
                admission._continuation_conversation_id(reacq_run_id),
                limit=4,
            )
            self.assertEqual(len(correlations), 1)
            first_run_id = correlations[0]["run_id"]
            first_run = store.load_run(first_run_id)
            self.assertEqual(first_run.status, RunStatus.COMPLETED)
            self.assertIsNone(admission._continuation_binding(store, reacq_run_id))

            recovered = self._continue(facade, reacq_run_id)["data"]
            self.assertEqual(recovered["status"], "COMPLETED")
            self.assertTrue(recovered["idempotent_reuse"])
            self.assertEqual(recovered["new_run_id"], first_run_id)
            self.assertEqual(
                len(
                    facade._application.conversation_store.run_correlations_for_conversation(
                        admission._continuation_conversation_id(reacq_run_id),
                        limit=4,
                    )
                ),
                1,
            )
            binding = admission._continuation_binding(store, reacq_run_id)
            self.assertEqual(binding["new_run_id"], first_run_id)
            self.assertTrue(admission._continuation_mirror_complete(store, binding))
        finally:
            facade.close()

    def test_partial_binding_is_preserved_and_later_attempt_recovers(self):
        facade, case = self._prepare_case()
        try:
            reacquired = self._make_new_version(facade, case)
            reacq_run_id = reacquired["reacquisition_run_id"]
            store = facade._application.execution_store
            original_store = store.store_diagnostic
            interrupted = {"done": False}

            def fail_child_mirror(run_id, kind, payload):
                if (
                    not interrupted["done"]
                    and kind == admission._CONTINUATION_BINDING_DIAGNOSTIC
                    and run_id != reacq_run_id
                ):
                    interrupted["done"] = True
                    raise RuntimeError("fixture interruption between binding mirrors")
                return original_store(run_id, kind, payload)

            with patch.object(store, "store_diagnostic", side_effect=fail_child_mirror):
                first = self._continue(facade, reacq_run_id)
            self.assertEqual(first["status"], "FAILED")
            partial = admission._continuation_binding(store, reacq_run_id)
            first_run_id = partial["new_run_id"]
            self.assertEqual(store.load_run(first_run_id).status, RunStatus.ABORTED)

            completed = self._continue(facade, reacq_run_id)["data"]
            self.assertEqual(completed["status"], "COMPLETED")
            self.assertNotEqual(completed["new_run_id"], first_run_id)
            retry = store.load_run(completed["new_run_id"])
            self.assertEqual(retry.parent_run_id, first_run_id)
            self.assertEqual(store.load_run(first_run_id).status, RunStatus.ABORTED)
        finally:
            facade.close()

    def test_completed_lifecycle_without_candidate_closure_is_not_reused(self):
        facade, case = self._prepare_case()
        try:
            reacquired = self._make_new_version(facade, case)
            first = self._continue(facade, reacquired["reacquisition_run_id"])["data"]
            first_run_id = first["new_run_id"]
            self.assertEqual(first["status"], "COMPLETED")
            self.assertIsNotNone(first["state_delta_proposal_id"])

            facade._application.conversation_store._db.execute(
                "DELETE FROM state_delta_proposals WHERE proposal_id=?",
                (first["state_delta_proposal_id"],),
            )
            retry = self._continue(facade, reacquired["reacquisition_run_id"])["data"]
            self.assertEqual(retry["status"], "COMPLETED")
            self.assertFalse(retry["idempotent_reuse"])
            self.assertNotEqual(retry["new_run_id"], first_run_id)
            self.assertEqual(
                facade._application.execution_store.load_run(retry["new_run_id"]).parent_run_id,
                first_run_id,
            )
            self.assertEqual(
                facade._application.execution_store.load_run(first_run_id).status,
                RunStatus.COMPLETED,
            )
        finally:
            facade.close()
