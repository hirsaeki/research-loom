from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import sqlite3
from types import SimpleNamespace
from threading import RLock
import unittest

from plugins.local_application.cli import _emit_external_materials_human
from plugins.local_application.facade import LocalApplicationError
from plugins.local_application.material_inventory_facade import (
    LocalApplicationFacade,
    _decode_material_cursor,
    _encode_material_cursor,
)
from plugins.local_execution_store.material_inventory import (
    external_capture_artifact_metadata_for_project,
)


_ORIGINAL_ROLE = "desktop_research.original_capture"
_TEXT_ROLE = "desktop_research.text_rendition"


def _store_fixture():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE runs(
            run_id TEXT PRIMARY KEY,
            project_ref TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            function_id TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            prepared_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE execution_artifacts(
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            role TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size INTEGER NOT NULL,
            digest TEXT NOT NULL,
            storage_locator TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            provenance_json TEXT NOT NULL
        )
        """
    )
    return SimpleNamespace(_connection=connection, _lock=RLock())


def _insert_capture(
    store,
    *,
    run_id: str,
    prepared_at: str,
    capture_id: str,
    original_digest: str,
    stored_at: str,
) -> None:
    store._connection.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
        (
            run_id,
            "PROJECT-1",
            "desktop-research",
            "investigate",
            "real",
            prepared_at,
        ),
    )
    shared = {"capture_id": capture_id, "stored_at": stored_at}
    store._connection.execute(
        "INSERT INTO execution_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
        (
            f"{run_id}.{capture_id}.original",
            run_id,
            _ORIGINAL_ROLE,
            "application/pdf",
            1,
            original_digest,
            "artifact://original",
            "real",
            json.dumps({**shared, "rendition_role": "original"}),
        ),
    )
    store._connection.execute(
        "INSERT INTO execution_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
        (
            f"{run_id}.{capture_id}.text",
            run_id,
            _TEXT_ROLE,
            "text/plain",
            1,
            f"sha256:text-{run_id}",
            "artifact://text",
            "real",
            json.dumps({**shared, "rendition_role": "text"}),
        ),
    )


class ExternalMaterialInventoryGuardTests(unittest.TestCase):
    def test_storage_query_pages_by_material_before_loading_artifacts(self):
        store = _store_fixture()
        try:
            _insert_capture(
                store,
                run_id="RUN-A",
                prepared_at="2026-09-01T00:00:00Z",
                capture_id="CAP-A",
                original_digest="sha256:material-a",
                stored_at="2026-09-01T00:00:01Z",
            )
            _insert_capture(
                store,
                run_id="RUN-B",
                prepared_at="2026-09-01T00:00:02Z",
                capture_id="CAP-B",
                original_digest="sha256:material-a",
                stored_at="2026-09-01T00:00:03Z",
            )
            _insert_capture(
                store,
                run_id="RUN-C",
                prepared_at="2026-09-01T00:00:04Z",
                capture_id="CAP-C",
                original_digest="sha256:material-b",
                stored_at="2026-09-01T00:00:05Z",
            )

            first, next_after = external_capture_artifact_metadata_for_project(
                store,
                "PROJECT-1",
                limit=1,
            )
            self.assertEqual(len(first), 4)
            self.assertEqual(
                {item.digest for item in first if item.role == _ORIGINAL_ROLE},
                {"sha256:material-a"},
            )
            self.assertEqual(
                next_after,
                ("2026-09-01T00:00:01Z", "sha256:material-a"),
            )

            second, final_after = external_capture_artifact_metadata_for_project(
                store,
                "PROJECT-1",
                limit=1,
                after=next_after,
            )
            self.assertEqual(len(second), 2)
            self.assertEqual(
                {item.digest for item in second if item.role == _ORIGINAL_ROLE},
                {"sha256:material-b"},
            )
            self.assertIsNone(final_after)
        finally:
            store._connection.close()

    def test_rendition_lookup_ignores_unselected_rows_without_capture_id(self):
        store = _store_fixture()
        try:
            _insert_capture(
                store,
                run_id="RUN-A",
                prepared_at="2026-09-01T00:00:00Z",
                capture_id="CAP-A",
                original_digest="sha256:material-a",
                stored_at="2026-09-01T00:00:01Z",
            )
            store._connection.execute(
                "INSERT INTO execution_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "RUN-A.unrelated.text",
                    "RUN-A",
                    _TEXT_ROLE,
                    "text/plain",
                    1,
                    "sha256:unrelated",
                    "artifact://unrelated",
                    "real",
                    json.dumps(
                        {
                            "stored_at": "2026-09-01T00:00:02Z",
                            "rendition_role": "text",
                        }
                    ),
                ),
            )

            artifacts, next_after = external_capture_artifact_metadata_for_project(
                store,
                "PROJECT-1",
                limit=1,
            )

            self.assertIsNone(next_after)
            self.assertEqual(
                [item.artifact_id for item in artifacts],
                ["RUN-A.CAP-A.original", "RUN-A.CAP-A.text"],
            )
        finally:
            store._connection.close()

    def test_human_material_output_escapes_terminal_controls(self):
        value = {
            "materials": [
                {
                    "source_locators": ["https://example.test/\x1b[31mspoof"],
                    "run_ids": ["RUN-\x1b]0;spoof\x07"],
                    "original_digest": "sha256:safe",
                    "original": {
                        "artifact_id": "ART-\x1b[2J",
                        "media_type": "application/pdf\x07",
                        "size_bytes": 7,
                    },
                    "renditions": [{"artifact_id": "TXT-\x1b[1m"}],
                }
            ],
            "truncated": False,
        }
        stream = io.StringIO()
        with redirect_stdout(stream):
            _emit_external_materials_human(value)
        output = stream.getvalue()

        self.assertNotIn("\x1b", output)
        self.assertNotIn("\x07", output)
        self.assertIn("\\u001b[31mspoof", output)
        self.assertIn("application/pdf\\u0007", output)

    def test_cursor_is_opaque_round_trip_and_limit_is_bounded(self):
        key = ("2026-09-01T00:00:01Z", "sha256:material-a")
        cursor = _encode_material_cursor(key)
        self.assertEqual(_decode_material_cursor(cursor), key)

        with self.assertRaises(LocalApplicationError):
            _decode_material_cursor("not-a-valid-cursor")

        facade = LocalApplicationFacade(SimpleNamespace(), "PROJECT-1")
        with self.assertRaises(LocalApplicationError):
            facade.list_external_materials(limit=101)


if __name__ == "__main__":
    unittest.main()
