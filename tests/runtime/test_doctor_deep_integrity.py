"""doctor --deep runs every store's full integrity check, read-only (ADR 0001, #533)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from plugins.local_application import LocalWorkspace
from plugins.local_application.cli import main
from tests.runtime.test_research_question_review import _workspace as make_workspace

CORE_STORES = [
    "research_state",
    "conversation",
    "decision",
    "execution",
    "context_extensions",
    "operational_trace",
]


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _deep_checks(result) -> dict[str, str]:
    return {
        row["store"]: row["status"] for row in result["checks"] if row["check"] == "deep_integrity"
    }


class DoctorDeepIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = make_workspace(Path(temporary.name))

    def test_deep_doctor_checks_every_core_store_without_writing(self):
        default = LocalWorkspace.doctor(self.workspace)
        before = _tree(self.workspace)
        deep = LocalWorkspace.doctor(self.workspace, deep=True)

        self.assertEqual(before, _tree(self.workspace))
        self.assertEqual(deep["status"], "OK")
        self.assertEqual(_deep_checks(deep), dict.fromkeys(CORE_STORES, "OK"))
        self.assertEqual(deep["checks"][: len(default["checks"])], default["checks"])
        self.assertEqual(_deep_checks(default), {})

    def test_deep_doctor_reports_state_inconsistency_the_default_doctor_misses(self):
        database = self.workspace / ".research-loom" / "research-state.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("DELETE FROM snapshot_members")
            db.commit()

        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")
        deep = LocalWorkspace.doctor(self.workspace, deep=True)
        self.assertEqual(deep["status"], "ERROR")
        self.assertEqual(_deep_checks(deep)["research_state"], "ERROR")
        self.assertTrue(
            any(
                issue["code"] == "WORKSPACE-DEEP-INTEGRITY-001"
                and issue["store"] == "research_state"
                and issue["message"].startswith("snapshot-member-index-mismatch:")
                for issue in deep["issues"]
            ),
            deep["issues"],
        )

    def test_cli_deep_flag(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["doctor", "--workspace", str(self.workspace), "--deep"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(_deep_checks(result), dict.fromkeys(CORE_STORES, "OK"))


if __name__ == "__main__":
    unittest.main()
