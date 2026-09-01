from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from threading import Event
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.facade import LocalApplicationError
from plugins.local_execution_store import LocalExecutionStoreConfig
from test_external_desktop_research_intake import NullResolver, profile_provider
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

    def test_large_run_reservation_serializes_staging_across_connections(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app1, facade1 = helper.make_facade(root)
            app2 = None
            facade2 = None
            try:
                config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=64,
                )
                app1.execution_store.config = config
                run_id = helper.prepare(
                    facade1,
                    {
                        "max_acquired_source_captures": 1,
                        "max_capture_artifacts": 2,
                        "max_original_capture_bytes": 128,
                        "max_text_rendition_bytes": 16,
                    },
                )
                app2 = LocalResearchApplication(
                    root / ".research-loom",
                    resolver=NullResolver(),
                    effective_profile_set_provider=profile_provider,
                )
                app2.execution_store.config = config
                facade2 = LocalApplicationFacade(app2, "PRJ-1", workspace_root=root)

                raw_a, text_a = helper.write_pair(
                    root,
                    "reservation-a",
                    b"first-large-reservation-original",
                    b"aa",
                )
                raw_b, text_b = helper.write_pair(
                    root,
                    "reservation-b",
                    b"second-large-reservation-original",
                    b"bb",
                )
                entered_stage = Event()
                release_stage = Event()
                second_stage_called = Event()
                real_stage_a = app1.execution_store._stage_controlled_original
                real_stage_b = app2.execution_store._stage_controlled_original

                def delayed_stage(*args, **kwargs):
                    entered_stage.set()
                    self.assertTrue(release_stage.wait(timeout=5))
                    return real_stage_a(*args, **kwargs)

                def observed_second_stage(*args, **kwargs):
                    second_stage_called.set()
                    return real_stage_b(*args, **kwargs)

                def capture(facade, capture_id, raw, text):
                    try:
                        return facade.capture_external_source(
                            run_id,
                            helper.capture_input(capture_id, raw, text),
                        )["status"]
                    except LocalApplicationError as exc:
                        return exc.code

                with patch.object(
                    app1.execution_store,
                    "_stage_controlled_original",
                    side_effect=delayed_stage,
                ), patch.object(
                    app2.execution_store,
                    "_stage_controlled_original",
                    side_effect=observed_second_stage,
                ):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        first = pool.submit(
                            capture,
                            facade1,
                            "CAP-RESERVE-A",
                            raw_a,
                            text_a,
                        )
                        self.assertTrue(entered_stage.wait(timeout=5))
                        second = pool.submit(
                            capture,
                            facade2,
                            "CAP-RESERVE-B",
                            raw_b,
                            text_b,
                        )
                        try:
                            with self.assertRaises(FutureTimeout):
                                second.result(timeout=0.1)
                            self.assertFalse(second_stage_called.is_set())
                        finally:
                            release_stage.set()
                        values = [first.result(timeout=5), second.result(timeout=5)]

                self.assertEqual(values.count("EXTERNAL_SOURCE_CAPTURED"), 1)
                self.assertEqual(values.count("APPLICATION-EXTERNAL-CAPTURE-001"), 1)
                self.assertFalse(second_stage_called.is_set())
                self.assertEqual(len(app1.execution_store.artifacts_for(run_id)), 2)
            finally:
                if facade2 is not None:
                    facade2.close()
                facade1.close()


if __name__ == "__main__":
    unittest.main()
