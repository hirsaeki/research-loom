from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_issue92_external_submission_preflight as issue92
from plugins.local_execution_store.capture_query import artifacts_for_capture_ids


class Issue92CaptureQueryReviewTests(unittest.TestCase):
    def test_selected_capture_query_excludes_unrelated_run_artifacts(self):
        fixture = issue92.Issue92ExternalSubmissionPreflightTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = fixture.make_facade(root)
            try:
                run_id, valid, _ = fixture.prepared(root, facade)
                run = app.execution_store.load_run(run_id)
                self.assertIsNotNone(run)
                for index in range(8):
                    app.execution_store.put_bytes(
                        run,
                        role="issue92.unrelated_artifact",
                        media_type="application/octet-stream",
                        content=f"unrelated-{index}".encode("ascii"),
                        artifact_id=f"ART-UNRELATED-{index}",
                        provenance={"capture_id": f"CAP-UNRELATED-{index}"},
                    )
                selected = artifacts_for_capture_ids(app.execution_store, run_id, ["CAP-1"])
                self.assertEqual(len(selected), 2)
                self.assertEqual({item.provenance.get("capture_id") for item in selected}, {"CAP-1"})
                self.assertGreater(len(app.execution_store.artifacts_for(run_id)), len(selected))
                with patch(
                    "plugins.local_application.external_submission.artifacts_for_capture_ids",
                    wraps=artifacts_for_capture_ids,
                ) as selected_query:
                    self.assertEqual(
                        facade.preflight_external(run_id, {"research_result": valid})["status"],
                        "PREFLIGHT_OK",
                    )
                selected_query.assert_called_once_with(app.execution_store, run_id, ["CAP-1"])
            finally:
                facade.close()

    def test_selected_capture_query_chunks_below_sqlite_variable_limit(self):
        fixture = issue92.Issue92ExternalSubmissionPreflightTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = fixture.make_facade(root)
            try:
                run_id, _, _ = fixture.prepared(root, facade)
                connection = app.execution_store._connection
                original_limit = connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
                try:
                    connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 8)
                    capture_ids = ["CAP-1", *(f"CAP-MISSING-{index}" for index in range(20))]
                    selected = artifacts_for_capture_ids(app.execution_store, run_id, capture_ids)
                finally:
                    connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, original_limit)
                self.assertEqual(len(selected), 2)
                self.assertEqual({item.provenance.get("capture_id") for item in selected}, {"CAP-1"})
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
