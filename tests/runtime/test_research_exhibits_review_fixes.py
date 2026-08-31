from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_research_exhibit_store import LocalResearchExhibitStore
from test_research_exhibits import exhibit_payload, make_app


class ResearchExhibitReviewFixTests(unittest.TestCase):
    def test_capture_rejects_state_change_after_reference_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                state = facade._current_state()
                latest = SimpleNamespace(
                    active_lineage_ref=state.active_lineage_ref,
                    current_snapshot={
                        "id": "SNP-CHANGED",
                        "content_digest": "sha256:" + "f" * 64,
                    },
                )
                with patch.object(
                    facade,
                    "_current_state",
                    side_effect=[state, latest],
                ):
                    with self.assertRaises(LocalApplicationError) as stale:
                        facade.capture_exhibit(exhibit_payload())
                self.assertEqual(
                    stale.exception.code,
                    "APPLICATION-EXHIBIT-STATE-STALE-001",
                )
                self.assertFalse((Path(temp) / "research-exhibits.sqlite3").exists())
            finally:
                app.close()

    def test_list_reads_content_free_metadata_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                captured = facade.capture_exhibit(exhibit_payload())
                exhibit_id = captured["exhibit"]["exhibit_id"]
                database = Path(temp) / "research-exhibits.sqlite3"

                connection = sqlite3.connect(database)
                try:
                    columns = {
                        str(row[1])
                        for row in connection.execute(
                            "PRAGMA table_info(research_exhibits)"
                        )
                    }
                    self.assertIn("metadata_json", columns)
                    row = connection.execute(
                        "SELECT metadata_json FROM research_exhibits WHERE exhibit_id=?",
                        (exhibit_id,),
                    ).fetchone()
                finally:
                    connection.close()
                metadata = json.loads(str(row[0]))
                self.assertNotIn("content", metadata)
                self.assertEqual(metadata["exhibit_id"], exhibit_id)
                self.assertEqual(metadata["content_representation"], "markdown")

                with patch.object(
                    LocalResearchExhibitStore,
                    "_decode_document",
                    side_effect=AssertionError("list must not decode document_json"),
                ):
                    listed = facade.list_exhibits(rq_id="RQ-1")
                self.assertEqual(
                    [item["exhibit_id"] for item in listed["exhibits"]],
                    [exhibit_id],
                )
                self.assertNotIn("content", listed["exhibits"][0])
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
