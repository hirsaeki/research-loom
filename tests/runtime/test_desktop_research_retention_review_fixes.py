from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application.facade import LocalApplicationError
from plugins.local_execution_store import LocalExecutionStoreConfig
from test_external_desktop_research_intake_atomicity import (
    ExternalDesktopResearchAtomicityTests,
)


class DesktopResearchRetentionReviewFixTests(unittest.TestCase):
    def test_large_fallback_reuses_normal_capture_metadata_validation(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=32,
                )
                run_id = helper.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 1,
                        "max_capture_artifacts": 2,
                        "max_original_capture_bytes": 128,
                        "max_text_rendition_bytes": 16,
                    },
                )
                raw, text = helper.write_pair(
                    root,
                    "invalid-time",
                    b"large-original-for-validation",
                    b"text",
                )
                submission = helper.capture_input("CAP-INVALID-TIME", raw, text)
                submission["acquired_at"] = "2026-09-01T08:00:00"

                with self.assertRaises(LocalApplicationError) as caught:
                    facade.capture_external_source(run_id, submission)

                self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-CAPTURE-001")
                self.assertIn("RFC3339 UTC", caught.exception.message)
                self.assertEqual(app.execution_store.artifacts_for(run_id), ())
            finally:
                facade.close()

    def test_large_preflight_rejects_exhausted_quota_before_staging(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=64,
                )
                run_id = helper.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 1,
                        "max_capture_artifacts": 2,
                        "max_original_capture_bytes": 128,
                        "max_text_rendition_bytes": 16,
                    },
                )
                raw_a, text_a = helper.write_pair(
                    root,
                    "quota-a",
                    b"first-large-original",
                    b"aa",
                )
                facade.capture_external_source(
                    run_id,
                    helper.capture_input("CAP-A", raw_a, text_a),
                )
                raw_b, text_b = helper.write_pair(
                    root,
                    "quota-b",
                    b"second-large-original",
                    b"bb",
                )

                with patch.object(app.execution_store, "_stage_controlled_original") as stage:
                    with self.assertRaises(LocalApplicationError) as caught:
                        facade.capture_external_source(
                            run_id,
                            helper.capture_input("CAP-B", raw_b, text_b),
                        )

                stage.assert_not_called()
                self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-CAPTURE-001")
                self.assertIn("role count limit exceeded", caught.exception.message)
                self.assertEqual(len(app.execution_store.artifacts_for(run_id)), 2)
            finally:
                facade.close()

    def test_large_preflight_rejects_identity_collision_before_staging(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=64,
                )
                run_id = helper.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 2,
                        "max_capture_artifacts": 4,
                        "max_original_capture_bytes": 128,
                        "max_text_rendition_bytes": 16,
                    },
                )
                raw_a, text_a = helper.write_pair(
                    root,
                    "collision-a",
                    b"first-collision-original",
                    b"aa",
                )
                facade.capture_external_source(
                    run_id,
                    helper.capture_input("CAP-SAME", raw_a, text_a),
                )
                raw_b, text_b = helper.write_pair(
                    root,
                    "collision-b",
                    b"second-collision-original",
                    b"bb",
                )

                with patch.object(app.execution_store, "_stage_controlled_original") as stage:
                    with self.assertRaises(LocalApplicationError) as caught:
                        facade.capture_external_source(
                            run_id,
                            helper.capture_input("CAP-SAME", raw_b, text_b),
                        )

                stage.assert_not_called()
                self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-CAPTURE-001")
                self.assertIn("immutable artifact identity collision", caught.exception.message)
                self.assertEqual(len(app.execution_store.artifacts_for(run_id)), 2)
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
