from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from threading import Event
import tempfile
import unittest
from unittest.mock import patch

from plugins.desktop_research.attempts import reconstruct_attempts
from plugins.local_application import (
    LocalApplicationError,
    LocalApplicationFacade,
    LocalResearchApplication,
)
from test_external_desktop_research_intake import (
    ExternalDesktopResearchIntakeTests,
    NullResolver,
    golden_submission,
    profile_provider,
)


class ExternalDesktopResearchAttemptLifecycleTests(unittest.TestCase):
    def test_collect_rejects_in_progress_attempt_and_leaves_run_open_for_completion(self):
        helper = ExternalDesktopResearchIntakeTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as temp:
            app, facade = helper.make_facade(Path(temp))
            try:
                run_id = helper.prepare(facade)["run_id"]
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-IN-PROGRESS",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                })

                with self.assertRaises(LocalApplicationError) as blocked:
                    facade.collect_external(run_id, {"handoff": {"invalid": True}, "extension": {}})
                self.assertEqual(blocked.exception.code, "APPLICATION-EXTERNAL-ATTEMPT-001")
                self.assertIn("ATT-IN-PROGRESS", str(blocked.exception))
                self.assertEqual(app.execution_store.load_run(run_id).status.value, "RUNNING")

                completed = facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-IN-PROGRESS",
                    "outcome": "no_relevant_source",
                })
                self.assertEqual(completed["attempt"]["outcome"], "no_relevant_source")
            finally:
                facade.close()

    def test_collect_serializes_attempt_start_through_completed_transition(self):
        helper = ExternalDesktopResearchIntakeTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app1, facade1 = helper.make_facade(root)
            app2 = None
            facade2 = None
            try:
                run_id = helper.prepare(facade1)["run_id"]
                facade1.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                })
                helper.write_capture_files(root)
                capture = facade1.capture_external_source(run_id, {
                    "capture_id": "CAP-1",
                    "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                    "provenance": {},
                })["capture"]
                facade1.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "outcome": "source_captured",
                    "target_locator": "https://example.test/source-a#section-1",
                    "resulting_capture_id": "CAP-1",
                })
                facade1.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                })
                facade1.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "outcome": "no_relevant_source",
                })
                handoff, extension = golden_submission(app1, run_id, capture)

                app2 = LocalResearchApplication(
                    root / ".research-loom",
                    resolver=NullResolver(),
                    effective_profile_set_provider=profile_provider,
                )
                facade2 = LocalApplicationFacade(app2, "PRJ-1", workspace_root=root)
                entered_check = Event()
                release_check = Event()
                real_reconstruct = reconstruct_attempts

                def delayed_reconstruct(*args, **kwargs):
                    result = real_reconstruct(*args, **kwargs)
                    entered_check.set()
                    self.assertTrue(release_check.wait(timeout=5))
                    return result

                with patch(
                    "plugins.local_application.external_attempt_lifecycle_facade.reconstruct_attempts",
                    side_effect=delayed_reconstruct,
                ):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        collect_future = pool.submit(
                            facade1.collect_external,
                            run_id,
                            {"handoff": handoff, "extension": extension},
                        )
                        self.assertTrue(entered_check.wait(timeout=5))
                        attempt_future = pool.submit(
                            facade2.start_external_retrieval_attempt,
                            run_id,
                            {
                                "attempt_id": "ATT-RACE",
                                "strategy": "late race search",
                                "coverage_dimension_ids": ["COV-SUPPORT"],
                            },
                        )
                        with self.assertRaises(FutureTimeout):
                            attempt_future.result(timeout=0.1)
                        release_check.set()
                        result = collect_future.result(timeout=5)
                        with self.assertRaises(LocalApplicationError) as blocked:
                            attempt_future.result(timeout=5)

                self.assertEqual(result["status"], "CAPABILITY_RESULT_COLLECTED")
                self.assertEqual(app1.execution_store.load_run(run_id).status.value, "COMPLETED")
                self.assertEqual(blocked.exception.code, "APPLICATION-EXTERNAL-RUN-STATE-001")
                attempts = reconstruct_attempts(app1.operational_store, run_id)
                self.assertNotIn("ATT-RACE", attempts)
                self.assertTrue(all(item["completed_at"] is not None for item in attempts.values()))
            finally:
                if facade2 is not None:
                    facade2.close()
                facade1.close()


if __name__ == "__main__":
    unittest.main()
