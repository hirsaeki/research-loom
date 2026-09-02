from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError
from test_external_desktop_research_intake import ExternalDesktopResearchIntakeTests


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
