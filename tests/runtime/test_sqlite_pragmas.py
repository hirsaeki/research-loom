"""Behavior of the shared SQLite PRAGMA helper (plugins/_infra/sqlite.py, #488)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from plugins._infra.sqlite import apply_pragmas, foreign_keys_enabled


class ApplyPragmasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.connection = sqlite3.connect(Path(self._tmp.name) / "x.db", isolation_level=None)

    def tearDown(self):
        self.connection.close()
        self._tmp.cleanup()

    def _pragma(self, name):
        return self.connection.execute(f"PRAGMA {name}").fetchone()[0]

    def test_applies_requested_settings_and_reports_journal_mode(self):
        actual = apply_pragmas(
            self.connection,
            foreign_keys=True,
            busy_timeout_ms=1234,
            journal_mode="wal",
            synchronous="full",
        )
        self.assertEqual(actual, "WAL")
        self.assertTrue(foreign_keys_enabled(self.connection))
        self.assertEqual(self._pragma("busy_timeout"), 1234)
        self.assertEqual(self._pragma("synchronous"), 2)  # FULL

    def test_query_only_blocks_writes(self):
        apply_pragmas(self.connection, query_only=True)
        with self.assertRaises(sqlite3.OperationalError):
            self.connection.execute("CREATE TABLE t(x)")

    def test_defaults_issue_nothing(self):
        self.assertIsNone(apply_pragmas(self.connection))
        self.assertFalse(foreign_keys_enabled(self.connection))
        self.assertEqual(str(self._pragma("journal_mode")).upper(), "DELETE")

    def test_rejects_unsupported_values_before_issuing_any_pragma(self):
        for kwargs in (
            {"journal_mode": "MEMORY"},
            {"synchronous": "OFF"},
            {"busy_timeout_ms": -1},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                apply_pragmas(self.connection, foreign_keys=True, **kwargs)
        self.assertFalse(foreign_keys_enabled(self.connection))


if __name__ == "__main__":
    unittest.main()
