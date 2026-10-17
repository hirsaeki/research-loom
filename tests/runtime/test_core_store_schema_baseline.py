"""Conversation and Decision stores record a schema_migrations baseline (ADR 0001, #532)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from plugins.local_application.workspace.workspace import LocalWorkspaceError
from plugins.local_application.workspace.workspace_initialization import (
    validate_required_store_schema,
)
from plugins.local_conversation_store import (
    LocalConversationStore,
    LocalConversationStoreError,
    validate_conversation_store_schema,
)
from plugins.local_conversation_store.store import SCHEMA_BASELINE as CONVERSATION_BASELINE
from plugins.local_decision_store import (
    SCHEMA_BASELINE as DECISION_BASELINE,
)
from plugins.local_decision_store import (
    LocalHumanDecisionStore,
    LocalHumanDecisionStoreError,
)

DECISION_CODE = "WORKSPACE-DECISION-DB-001"


def _history(path: Path) -> list[tuple[int, str]]:
    with closing(sqlite3.connect(path)) as db:
        return [tuple(row) for row in db.execute("SELECT version, name FROM schema_migrations")]


def _execute(path: Path, *statements: str) -> None:
    with closing(sqlite3.connect(path)) as db:
        for statement in statements:
            db.execute(statement)
        db.commit()


def _validate_decision(path: Path) -> None:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        validate_required_store_schema(db, DECISION_CODE)


class CoreStoreSchemaBaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_new_stores_record_the_baseline(self):
        conversation = self.root / "conversation.db"
        decision = self.root / "decision.db"
        LocalConversationStore(conversation).close()
        LocalHumanDecisionStore(decision).close()
        self.assertEqual(_history(conversation), [CONVERSATION_BASELINE])
        self.assertEqual(_history(decision), [DECISION_BASELINE])
        validate_conversation_store_schema(conversation)
        _validate_decision(decision)

    def test_store_from_before_the_record_is_read_as_is_and_recorded_on_open(self):
        conversation = self.root / "conversation.db"
        decision = self.root / "decision.db"
        LocalConversationStore(conversation).close()
        LocalHumanDecisionStore(decision).close()
        for path in (conversation, decision):
            _execute(path, "DROP TABLE schema_migrations")

        validate_conversation_store_schema(conversation)
        _validate_decision(decision)
        for path in (conversation, decision):
            with closing(sqlite3.connect(path)) as db:
                self.assertIsNone(
                    db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='schema_migrations'"
                    ).fetchone()
                )

        LocalConversationStore(conversation).close()
        LocalHumanDecisionStore(decision).close()
        self.assertEqual(_history(conversation), [CONVERSATION_BASELINE])
        self.assertEqual(_history(decision), [DECISION_BASELINE])

    def test_unknown_history_is_refused_without_changes(self):
        conversation = self.root / "conversation.db"
        decision = self.root / "decision.db"
        LocalConversationStore(conversation).close()
        LocalHumanDecisionStore(decision).close()
        for path in (conversation, decision):
            _execute(path, "INSERT INTO schema_migrations(version, name) VALUES (2, 'future')")

        with self.assertRaises(LocalConversationStoreError) as raised:
            LocalConversationStore(conversation)
        self.assertEqual(raised.exception.code, "CONVERSATION-STORE-SCHEMA-001")
        with self.assertRaises(LocalConversationStoreError):
            validate_conversation_store_schema(conversation)

        with self.assertRaises(LocalHumanDecisionStoreError) as raised:
            LocalHumanDecisionStore(decision)
        self.assertEqual(raised.exception.code, "DECISION-STORE-SCHEMA-001")
        with self.assertRaises(LocalWorkspaceError) as workspace_error:
            _validate_decision(decision)
        self.assertEqual(workspace_error.exception.code, DECISION_CODE)

        self.assertEqual(_history(conversation), [CONVERSATION_BASELINE, (2, "future")])
        self.assertEqual(_history(decision), [DECISION_BASELINE, (2, "future")])

    def test_decision_store_with_missing_columns_fails_closed(self):
        decision = self.root / "decision.db"
        _execute(decision, "CREATE TABLE decision_requests(request_id TEXT PRIMARY KEY)")

        with self.assertRaises(LocalHumanDecisionStoreError) as raised:
            LocalHumanDecisionStore(decision)
        self.assertEqual(raised.exception.code, "DECISION-STORE-SCHEMA-001")
        with closing(sqlite3.connect(decision)) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        self.assertNotIn("schema_migrations", names)
        self.assertNotIn("decision_requests_pending", names)


if __name__ == "__main__":
    unittest.main()
