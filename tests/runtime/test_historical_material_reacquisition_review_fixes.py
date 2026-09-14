from __future__ import annotations

from dataclasses import replace
from threading import Event, Thread
from unittest.mock import patch
from urllib import request

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.material_reacquisition_facade import (
    HistoricalMaterialReacquisitionService,
    MaterialReacquisitionRetrievalError,
    RetrievedMaterial,
    _PublicHttpsRedirectHandler,
    _retrieve_exact_locator,
)
from plugins.local_execution_store import child_runs_for_parent
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class HistoricalMaterialReacquisitionReviewFixTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    @staticmethod
    def _missing_original(facade, case):
        store = facade._application.execution_store
        original = next(
            artifact
            for artifact in store.artifacts_for(case["run_id"])
            if artifact.role == "desktop_research.original_capture"
            and artifact.provenance.get("capture_id") == "CAP-1"
        )
        store._locator_path(original.storage_locator, original.digest).unlink()
        return original

    @staticmethod
    def _exact_result():
        return RetrievedMaterial(
            b"<html>fixed source body</html>",
            "text/html",
            "https://example.test/source-a#section-1",
            "fake-http",
            200,
        )

    def test_completed_success_is_reused_only_while_backing_content_is_verified(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            service = HistoricalMaterialReacquisitionService(
                facade._application.execution_store,
                facade.project_id,
                self.workspace,
                retriever=lambda _locator: self._exact_result(),
            )
            first = service.reacquire(case["run_id"], "CAP-1", kind="original")
            self.assertEqual(first["status"], "IDENTICAL_REACQUISITION")
            child_id = first["reacquisition_run_id"]

            store = facade._application.execution_store
            restored = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.artifact_id == original.artifact_id
            )
            store._locator_path(restored.storage_locator, restored.digest).unlink()

            second = service.reacquire(case["run_id"], "CAP-1", kind="original")
            self.assertEqual(second["status"], "IDENTICAL_REACQUISITION")
            self.assertNotEqual(second["reacquisition_run_id"], child_id)
        finally:
            facade.close()

    def test_parallel_same_target_reacquisition_creates_only_one_child(self):
        facade, case = self._prepare_case()
        first = second = None
        release = Event()
        started = Event()
        second_started = Event()
        outcome = {}
        try:
            self._remove_producer_candidate(facade, case)
            self._missing_original(facade, case)
            facade.close()
            facade = None
            first = LocalApplicationFacade.open_workspace(self.workspace)
            second = LocalApplicationFacade.open_workspace(self.workspace)

            def blocked(_locator):
                started.set()
                self.assertTrue(release.wait(5))
                return self._exact_result()

            service1 = HistoricalMaterialReacquisitionService(
                first._application.execution_store,
                first.project_id,
                self.workspace,
                retriever=blocked,
            )
            service2 = HistoricalMaterialReacquisitionService(
                second._application.execution_store,
                second.project_id,
                self.workspace,
                retriever=lambda _locator: (_ for _ in ()).throw(
                    AssertionError("parallel repeat must not retrieve")
                ),
            )
            thread1 = Thread(
                target=lambda: outcome.setdefault(
                    "first", service1.reacquire(case["run_id"], "CAP-1", kind="original")
                )
            )
            thread1.start()
            self.assertTrue(started.wait(5))

            def run_second():
                second_started.set()
                outcome["second"] = service2.reacquire(
                    case["run_id"], "CAP-1", kind="original"
                )

            thread2 = Thread(target=run_second)
            thread2.start()
            self.assertTrue(second_started.wait(5))
            thread2.join(0.2)
            self.assertTrue(thread2.is_alive())
            release.set()
            thread1.join(5)
            thread2.join(5)
            self.assertFalse(thread1.is_alive())
            self.assertFalse(thread2.is_alive())
            self.assertEqual(outcome["first"]["status"], "IDENTICAL_REACQUISITION")
            self.assertEqual(outcome["second"]["status"], "ALREADY_VERIFIED")
            self.assertEqual(
                len(
                    child_runs_for_parent(
                        second._application.execution_store, case["run_id"], limit=100
                    )
                ),
                1,
            )
        finally:
            release.set()
            if first is not None:
                first.close()
            if second is not None:
                second.close()
            if facade is not None:
                facade.close()

    def test_builtin_retrieval_rejects_non_public_targets_and_redirects(self):
        with patch(
            "plugins.local_application.material_reacquisition_facade.request.build_opener"
        ) as opener:
            with self.assertRaisesRegex(
                MaterialReacquisitionRetrievalError, "public HTTPS"
            ):
                _retrieve_exact_locator("file:///etc/passwd", max_bytes=1024)
            opener.assert_not_called()

        with patch(
            "plugins.local_application.material_reacquisition_facade.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ), patch(
            "plugins.local_application.material_reacquisition_facade.request.build_opener"
        ) as opener:
            with self.assertRaisesRegex(MaterialReacquisitionRetrievalError, "non-public"):
                _retrieve_exact_locator("https://internal.example/secret", max_bytes=1024)
            opener.assert_not_called()

        handler = _PublicHttpsRedirectHandler()
        with self.assertRaisesRegex(MaterialReacquisitionRetrievalError, "non-public"):
            handler.redirect_request(
                request.Request("https://public.example/start"),
                None,
                302,
                "Found",
                {},
                "https://127.0.0.1/metadata",
            )

    def test_oversized_historical_material_fails_before_network(self):
        facade, case = self._prepare_case()
        original_config = None
        try:
            self._remove_producer_candidate(facade, case)
            self._missing_original(facade, case)
            store = facade._application.execution_store
            original_config = store.config
            store.config = replace(original_config, max_artifact_bytes=8)
            calls = []
            service = HistoricalMaterialReacquisitionService(
                store,
                facade.project_id,
                self.workspace,
                retriever=lambda locator: calls.append(locator),
            )
            result = service.reacquire(case["run_id"], "CAP-1", kind="original")
            self.assertEqual(result["status"], "REACQUISITION_FAILED")
            self.assertIn("size limit", result["failure_reason"])
            self.assertEqual(calls, [])
        finally:
            if original_config is not None:
                facade._application.execution_store.config = original_config
            facade.close()
