"""Optional-tier writes take the write lock before reading (ADR 0001, #530)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.local_attention_store import LocalAttentionStore, LocalAttentionStoreError
from plugins.local_survey_store import LocalSurveyStore, LocalSurveyStoreError


def _traced(store, opener: str, statements: list[str]):
    original = getattr(store, opener)

    def open_traced():
        connection = original()
        connection.set_trace_callback(statements.append)
        return connection

    return patch.object(store, opener, side_effect=open_traced)


def _begin_precedes_lookup(statements: list[str], table: str) -> bool:
    begin = statements.index("BEGIN IMMEDIATE")
    lookup = next(
        i for i, sql in enumerate(statements) if sql.startswith("SELECT") and table in sql
    )
    return begin < lookup


class OptionalStoreWriteTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_survey_capture_locks_before_checking_for_an_existing_revision(self):
        store = LocalSurveyStore(self.root / "survey.sqlite3")

        def capture(content_digest: str) -> bool:
            return store._capture(
                table="survey_designs",
                id_column="survey_design_id",
                payload_field="design",
                payload_id_field="survey_design_id",
                identity="DESIGN-1",
                project_id="PROJECT-1",
                version="1",
                content_digest=content_digest,
                captured_at="2026-10-17T00:00:00Z",
                document={"design": {"survey_design_id": "DESIGN-1", "body": content_digest}},
                validator=lambda _document: None,
            )

        statements: list[str] = []
        with _traced(store, "_write", statements):
            self.assertTrue(capture("sha256:a"))
        self.assertTrue(_begin_precedes_lookup(statements, "survey_designs"))

        with (
            patch.object(store, "_decode_and_validate", return_value={"body": "sha256:a"}),
            self.assertRaises(LocalSurveyStoreError) as raised,
        ):
            capture("sha256:b")
        self.assertEqual(raised.exception.code, "SURVEY-IMMUTABLE-001")

    def test_attention_store_map_locks_before_checking_for_an_existing_map(self):
        store = LocalAttentionStore(self.root / "attention.sqlite3")
        document = {"map_id": "MAP-1", "project_id": "PROJECT-1", "map_digest": "sha256:a"}

        statements: list[str] = []
        with (
            patch("plugins.local_attention_store.validate_attention_map"),
            _traced(store, "_connect_write", statements),
        ):
            store.store_map(document)
        self.assertTrue(_begin_precedes_lookup(statements, "attention_maps"))

        with (
            patch("plugins.local_attention_store.validate_attention_map"),
            self.assertRaises(LocalAttentionStoreError) as raised,
        ):
            store.store_map(document)
        self.assertEqual(raised.exception.code, "ATTENTION-MAP-IMMUTABLE-001")


if __name__ == "__main__":
    unittest.main()
