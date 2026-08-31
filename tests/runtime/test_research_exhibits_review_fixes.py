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

    def test_final_capture_holds_state_writer_guard_through_exhibit_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                original_capture = LocalResearchExhibitStore.capture
                writer_was_blocked: list[bool] = []

                def capture_with_competing_state_writer(store, document):
                    contender = sqlite3.connect(
                        Path(temp) / "research-state.sqlite3",
                        timeout=0.01,
                        isolation_level=None,
                    )
                    try:
                        with self.assertRaises(sqlite3.OperationalError):
                            contender.execute("BEGIN IMMEDIATE")
                        writer_was_blocked.append(True)
                    finally:
                        try:
                            contender.execute("ROLLBACK")
                        except sqlite3.Error:
                            pass
                        contender.close()
                    return original_capture(store, document)

                with patch.object(
                    LocalResearchExhibitStore,
                    "capture",
                    new=capture_with_competing_state_writer,
                ):
                    captured = facade.capture_exhibit(exhibit_payload())

                self.assertEqual(captured["status"], "CAPTURED")
                self.assertEqual(writer_was_blocked, [True])
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
                    base_columns = {
                        str(row[1])
                        for row in connection.execute(
                            "PRAGMA table_info(research_exhibits)"
                        )
                    }
                    self.assertNotIn("metadata_json", base_columns)
                    self.assertIsNotNone(connection.execute(
                        """
                        SELECT 1 FROM sqlite_master
                        WHERE type='table' AND name='research_exhibit_metadata'
                        """
                    ).fetchone())
                    row = connection.execute(
                        """
                        SELECT metadata_json FROM research_exhibit_metadata
                        WHERE exhibit_id=?
                        """,
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

    def test_preoptimization_0_1_store_stays_readable_and_backfills_on_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                first = facade.capture_exhibit(exhibit_payload(title="legacy exhibit"))
                exhibit_id = first["exhibit"]["exhibit_id"]
                document = facade.show_exhibit(exhibit_id)["exhibit"]
                database = Path(temp) / "research-exhibits.sqlite3"
                database.unlink()

                connection = sqlite3.connect(database)
                try:
                    connection.executescript("""
                    CREATE TABLE exhibit_store_meta (schema_version TEXT PRIMARY KEY);
                    CREATE TABLE research_exhibits (
                        exhibit_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        captured_at TEXT NOT NULL,
                        content_digest TEXT NOT NULL,
                        document_json TEXT NOT NULL
                    );
                    CREATE TABLE research_exhibit_rqs (
                        exhibit_id TEXT NOT NULL,
                        rq_id TEXT NOT NULL,
                        PRIMARY KEY(exhibit_id, rq_id),
                        FOREIGN KEY(exhibit_id) REFERENCES research_exhibits(exhibit_id)
                    );
                    """)
                    connection.execute(
                        "INSERT INTO exhibit_store_meta(schema_version) VALUES ('0.1.0')"
                    )
                    connection.execute(
                        """
                        INSERT INTO research_exhibits(
                            exhibit_id, project_id, captured_at, content_digest, document_json
                        ) VALUES (?,?,?,?,?)
                        """,
                        (
                            document["exhibit_id"],
                            document["project_id"],
                            document["provenance"]["captured_at"],
                            document["content_digest"],
                            json.dumps(
                                document,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO research_exhibit_rqs(exhibit_id, rq_id) VALUES (?,?)",
                        [(document["exhibit_id"], rq_id) for rq_id in document["rq_ids"]],
                    )
                    connection.commit()
                finally:
                    connection.close()

                listed = facade.list_exhibits(rq_id="RQ-1")
                self.assertEqual(
                    [item["exhibit_id"] for item in listed["exhibits"]],
                    [exhibit_id],
                )
                connection = sqlite3.connect(database)
                try:
                    self.assertIsNone(connection.execute(
                        """
                        SELECT 1 FROM sqlite_master
                        WHERE type='table' AND name='research_exhibit_metadata'
                        """
                    ).fetchone())
                finally:
                    connection.close()

                second = facade.capture_exhibit(exhibit_payload(title="new exhibit"))
                connection = sqlite3.connect(database)
                try:
                    self.assertIsNotNone(connection.execute(
                        """
                        SELECT 1 FROM sqlite_master
                        WHERE type='table' AND name='research_exhibit_metadata'
                        """
                    ).fetchone())
                    metadata_ids = {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT exhibit_id FROM research_exhibit_metadata"
                        )
                    }
                finally:
                    connection.close()
                self.assertEqual(
                    metadata_ids,
                    {exhibit_id, second["exhibit"]["exhibit_id"]},
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
