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
from plugins.local_application.facade import LocalApplicationFacade as PreAttemptGuardFacade
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
                app.close()

    def test_collect_serializes_attempt_start_through_completed_transition(self):
        helper = ExternalDesktopResearchIntakeTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            setup_app, setup_facade = helper.make_facade(root)
            try:
                run_id = helper.prepare(setup_facade)["run_id"]
                setup_facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                })
                helper.write_capture_files(root)
                capture = setup_facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1",
                    "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                    "provenance": {},
                })["capture"]
                setup_facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "outcome": "source_captured",
                    "target_locator": "https://example.test/source-a#section-1",
                    "resulting_capture_id": "CAP-1",
                })
                setup_facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                })
                setup_facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "outcome": "no_relevant_source",
                })
                handoff, extension = golden_submission(setup_app, run_id, capture)
            finally:
                setup_app.close()

            entered_check = Event()
            release_check = Event()
            real_reconstruct = reconstruct_attempts

            def open_facade():
                app = LocalResearchApplication(
                    root / ".research-loom",
                    resolver=NullResolver(),
                    effective_profile_set_provider=profile_provider,
                )
                return LocalApplicationFacade(app, "PRJ-1", workspace_root=root, owns_application=True)

            def collect_in_worker():
                facade = open_facade()
                try:
                    return facade.collect_external(
                        run_id,
                        {"handoff": handoff, "extension": extension},
                    )
                finally:
                    facade.close()

            def start_attempt_in_worker():
                facade = open_facade()
                try:
                    return facade.start_external_retrieval_attempt(
                        run_id,
                        {
                            "attempt_id": "ATT-RACE",
                            "strategy": "late race search",
                            "coverage_dimension_ids": ["COV-SUPPORT"],
                        },
                    )
                finally:
                    facade.close()

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
                    collect_future = pool.submit(collect_in_worker)
                    self.assertTrue(entered_check.wait(timeout=5))
                    attempt_future = pool.submit(start_attempt_in_worker)
                    with self.assertRaises(FutureTimeout):
                        attempt_future.result(timeout=0.1)
                    release_check.set()
                    result = collect_future.result(timeout=5)
                    with self.assertRaises(LocalApplicationError) as blocked:
                        attempt_future.result(timeout=5)

            self.assertEqual(result["status"], "CAPABILITY_RESULT_COLLECTED")
            self.assertEqual(blocked.exception.code, "APPLICATION-EXTERNAL-RUN-STATE-001")

            inspect_facade = open_facade()
            try:
                self.assertEqual(
                    inspect_facade._application.execution_store.load_run(run_id).status.value,
                    "COMPLETED",
                )
                attempts = reconstruct_attempts(inspect_facade._application.operational_store, run_id)
                self.assertNotIn("ATT-RACE", attempts)
                self.assertTrue(all(item["completed_at"] is not None for item in attempts.values()))
            finally:
                inspect_facade.close()

    def test_replay_completed_historical_run_carries_only_unresolved_attempts(self):
        helper = ExternalDesktopResearchIntakeTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                run_id = helper.prepare(facade)["run_id"]
                helper.write_capture_files(root)
                capture = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1",
                    "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                    "provenance": {},
                })["capture"]
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-DONE",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                })
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-DONE",
                    "outcome": "source_captured",
                    "target_locator": "https://example.test/source-a#section-1",
                    "resulting_capture_id": "CAP-1",
                })
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-OPEN",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                    "query_or_target": "missing counter source",
                })
                handoff, extension = golden_submission(app, run_id, capture)

                # Simulate a historical pre-guard Run without rewriting its provenance.
                historical = PreAttemptGuardFacade.collect_external(
                    facade,
                    run_id,
                    {"handoff": handoff, "extension": extension},
                )
                self.assertEqual(historical["status"], "CAPABILITY_RESULT_COLLECTED")
                self.assertEqual(app.execution_store.load_run(run_id).status.value, "COMPLETED")

                replay = facade.replay_completed_desktop_research_run(run_id)
                child_run_id = replay["run_id"]
                child = app.execution_store.load_run(child_run_id)
                self.assertEqual(replay["status"], "RUN_REPLAY_PREPARED")
                self.assertEqual(child.parent_run_id, run_id)
                self.assertEqual(child.attempt, 2)
                self.assertEqual(child.status.value, "RUNNING")

                original_attempts = reconstruct_attempts(app.operational_store, run_id)
                child_attempts = reconstruct_attempts(app.operational_store, child_run_id)
                self.assertEqual(set(original_attempts), {"ATT-DONE", "ATT-OPEN"})
                self.assertEqual(set(child_attempts), {"ATT-OPEN"})
                self.assertIsNone(child_attempts["ATT-OPEN"]["completed_at"])
                self.assertEqual(
                    child_attempts["ATT-OPEN"]["provenance"]["replayed_from_run_id"],
                    run_id,
                )
                self.assertEqual(
                    child_attempts["ATT-OPEN"]["provenance"]["replayed_from_attempt_id"],
                    "ATT-OPEN",
                )

                shown = facade.show_run(child_run_id)
                self.assertEqual(shown["run"]["parent_run_id"], run_id)
                self.assertEqual(
                    shown["desktop_research"]["retrieval_attempt_summary"]["in_progress"],
                    1,
                )
            finally:
                app.close()



if __name__ == "__main__":
    unittest.main()
