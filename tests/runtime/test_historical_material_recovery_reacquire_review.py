from __future__ import annotations

from dataclasses import replace
import io
from unittest.mock import patch

import plugins.local_application.material_reacquisition_facade as reacquisition_module
from plugins.local_application.material_reacquisition_facade import (
    HistoricalMaterialReacquisitionService,
    MaterialReacquisitionRetrievalError,
    _regenerate_text_rendition,
    material_reacquisition_payload,
)
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class HistoricalMaterialReacquisitionReviewTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    @staticmethod
    def _missing_rendition(facade, case):
        store = facade._application.execution_store
        rendition = next(
            artifact
            for artifact in store.artifacts_for(case["run_id"])
            if artifact.role == "desktop_research.text_rendition"
            and artifact.provenance.get("capture_id") == "CAP-1"
        )
        store._locator_path(rendition.storage_locator, rendition.digest).unlink()

    def test_payload_rejects_unhashable_kind_as_value_error(self):
        for invalid_kind in ([], {}):
            with self.assertRaises(ValueError):
                material_reacquisition_payload(
                    {
                        "historical_run_id": "RUN-1",
                        "capture_id": "CAP-1",
                        "kind": invalid_kind,
                    }
                )

    def test_pdf_generator_kills_process_when_output_exceeds_bound(self):
        class FakeProcess:
            def __init__(self):
                self.stdout = io.BytesIO(b"x" * 2048)
                self.killed = False
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

        process = FakeProcess()
        with patch(
            "plugins.local_application.material_reacquisition_facade.shutil.which",
            return_value="pdftotext",
        ), patch(
            "plugins.local_application.material_reacquisition_facade.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaisesRegex(
                MaterialReacquisitionRetrievalError,
                "exceeds bounded material intake limit",
            ):
                _regenerate_text_rendition(
                    b"%PDF-1.7 fixture",
                    "application/pdf",
                    "https://example.test/source.pdf",
                    max_bytes=64,
                )
        self.assertTrue(process.killed)

    def test_large_original_is_rejected_before_loading_bytes(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            self._missing_rendition(facade, case)
            store = facade._application.execution_store
            real_pair = reacquisition_module._artifact_pair_for_capture

            def oversized_pair(*args, **kwargs):
                historical, original, rendition, capture = real_pair(*args, **kwargs)
                return (
                    historical,
                    replace(original, size=store.config.max_artifact_bytes + 1),
                    rendition,
                    capture,
                )

            service = HistoricalMaterialReacquisitionService(
                store, facade.project_id, self.workspace
            )
            with patch.object(
                reacquisition_module,
                "_artifact_pair_for_capture",
                side_effect=oversized_pair,
            ), patch.object(
                store,
                "load_artifact",
                side_effect=AssertionError("large original must be rejected before load"),
            ):
                result = service.reacquire(case["run_id"], "CAP-1", kind="rendition")
            self.assertEqual(result["status"], "REACQUISITION_FAILED")
            self.assertIn(
                "historical original exceeds bounded rendition regeneration limit",
                result["failure_reason"],
            )
        finally:
            facade.close()
