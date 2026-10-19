"""Characterization tests for ``plugins/sqlite_state_store/_diagnostics.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They pin the issue strings ``integrity_issues_for`` reports for each kind of
physical corruption, its error wrapping, and the ``debug_state`` shape.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.runtime import StateTransitionService, TransitionAction, TransitionKind, canonical_digest
from core.runtime.ports import RepositoryError
from core.runtime.transition_models import canonical_json
from plugins.sqlite_state_store import SQLiteResearchStateRepository
from plugins.sqlite_state_store._diagnostics import DiagnosticsMixin, integrity_issues_for
from tests.runtime.runtime_fixtures import (
    SCHEMA_VALIDATOR,
    decision,
    make_request,
    project,
    rq,
    seed_state,
)
from tests.runtime.test_sqlite_state_repository import _claim


class _FakeIntegrityCursor:
    """Delegate to a real cursor but report a fixed PRAGMA integrity_check result."""

    def __init__(self, cursor: sqlite3.Cursor, integrity_rows) -> None:
        self._cursor = cursor
        self._integrity_rows = integrity_rows

    @property
    def row_factory(self):
        return self._cursor.row_factory

    @row_factory.setter
    def row_factory(self, factory) -> None:
        self._cursor.row_factory = factory

    def execute(self, sql, *args):
        if sql.strip() == "PRAGMA integrity_check":
            return iter(self._integrity_rows)
        return self._cursor.execute(sql, *args)


class _FakeIntegrityConnection:
    """Delegate to a real connection but report a fixed PRAGMA integrity_check result."""

    def __init__(self, connection: sqlite3.Connection, integrity_rows) -> None:
        self._connection = connection
        self._integrity_rows = integrity_rows

    def cursor(self) -> _FakeIntegrityCursor:
        return _FakeIntegrityCursor(self._connection.cursor(), self._integrity_rows)


class IntegrityIssuesTests(unittest.TestCase):
    """One seeded repository with a committed transition, then raw corruption."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "state.sqlite3"
        seed = seed_state(
            objects=[project(), rq()],
            decisions=(decision("DEC-1", "scope", "approve", "research_question", "RQ-1"),),
        )
        repository = SQLiteResearchStateRepository(self.db_path)
        try:
            repository.initialize_from_validated_state_view(seed)
            receipt = StateTransitionService(repository, schema_validator=SCHEMA_VALIDATOR).apply(
                make_request(
                    seed,
                    [
                        TransitionAction(
                            TransitionKind.CREATE_OBJECT,
                            {"object": _claim("CLM-1", "diagnostics")},
                        )
                    ],
                    suffix="2",
                )
            )
            self.assertEqual(receipt.commit_id, "COM-2")
        finally:
            repository.close()
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = OFF")
        self.addCleanup(self.connection.close)

    def corrupt(self, sql: str, params=()) -> None:
        with self.connection:
            self.connection.execute(sql, params)

    def issues(self) -> tuple[str, ...]:
        return integrity_issues_for(self.connection)

    def object_row(self, kind: str, object_id: str) -> sqlite3.Row:
        return self.connection.execute(
            "SELECT * FROM object_revisions WHERE kind = ? AND object_id = ? AND revision = 0",
            (kind, object_id),
        ).fetchone()

    def rewrite_object(self, kind: str, object_id: str, payload: dict, **columns) -> None:
        text = canonical_json(payload)
        values = {
            "payload_json": text,
            "payload_digest": canonical_digest(payload),
            "content_digest": str(payload.get("content_digest") or canonical_digest(payload)),
        }
        values.update(columns)
        self.corrupt(
            "UPDATE object_revisions SET payload_json = ?, payload_digest = ?, content_digest = ? "
            "WHERE kind = ? AND object_id = ? AND revision = 0",
            (
                values["payload_json"],
                values["payload_digest"],
                values["content_digest"],
                kind,
                object_id,
            ),
        )

    def test_healthy_state_has_no_issues(self) -> None:
        self.assertEqual(self.issues(), ())

    def test_non_object_payload_is_reported(self) -> None:
        self.corrupt(
            "UPDATE object_revisions SET payload_json = '[]' "
            "WHERE kind = 'research_question' AND object_id = 'RQ-1'"
        )
        self.assertEqual(
            self.issues(),
            (
                "payload:research_question:RQ-1@0:"
                "stored canonical object payload is not a JSON object",
            ),
        )

    def test_payload_digest_mismatch_is_reported(self) -> None:
        self.corrupt(
            "UPDATE object_revisions SET payload_digest = 'sha256:bad' "
            "WHERE kind = 'claim' AND object_id = 'CLM-1'"
        )
        issues = self.issues()
        self.assertIn("payload:claim:CLM-1@0:stored canonical payload digest mismatch", issues)
        self.assertIn("snapshot-member-digest-mismatch:SNP-2:claim:CLM-1@0", issues)

    def test_content_digest_index_mismatch_is_reported(self) -> None:
        self.corrupt(
            "UPDATE object_revisions SET content_digest = 'sha256:other' "
            "WHERE kind = 'decision' AND object_id = 'DEC-1'"
        )
        self.assertEqual(
            self.issues(),
            ("payload:decision:DEC-1@0:stored object content digest index mismatch",),
        )

    def test_snapshot_embedded_content_digest_is_verified(self) -> None:
        payload = json.loads(self.object_row("snapshot", "SNP-0")["payload_json"])
        payload["content_digest"] = "sha256:" + "0" * 64
        self.rewrite_object("snapshot", "SNP-0", payload)
        self.assertEqual(
            self.issues(),
            (
                "payload:snapshot:SNP-0@0:Snapshot content_digest does not match canonical payload",
                "snapshot-content-digest-mismatch:SNP-0",
            ),
        )

    def test_snapshot_without_embedded_content_digest_is_reported(self) -> None:
        payload = json.loads(self.object_row("snapshot", "SNP-0")["payload_json"])
        del payload["content_digest"]
        self.rewrite_object("snapshot", "SNP-0", payload)
        self.assertEqual(
            self.issues(),
            (
                "payload:snapshot:SNP-0@0:Snapshot content_digest is missing",
                "snapshot-content-digest-mismatch:SNP-0",
            ),
        )

    def test_missing_snapshot_object_is_reported(self) -> None:
        self.corrupt("DELETE FROM object_revisions WHERE kind = 'snapshot' AND object_id = 'SNP-0'")
        self.assertEqual(self.issues(), ("snapshot-object-missing:SNP-0",))

    def test_undecodable_snapshot_object_is_reported_once_per_section(self) -> None:
        self.corrupt(
            "UPDATE object_revisions SET payload_digest = 'sha256:bad' "
            "WHERE kind = 'snapshot' AND object_id = 'SNP-2'"
        )
        self.assertEqual(
            self.issues(),
            (
                "payload:snapshot:SNP-2@0:stored canonical payload digest mismatch",
                "snapshot-payload:SNP-2:stored canonical payload digest mismatch",
            ),
        )

    def test_snapshot_member_index_and_digest_mismatch(self) -> None:
        self.corrupt(
            "UPDATE snapshot_members SET member_content_digest = 'sha256:wrong' "
            "WHERE snapshot_ref = 'SNP-0' AND member_kind = 'project'"
        )
        self.assertEqual(
            self.issues(),
            (
                "snapshot-member-digest-mismatch:SNP-0:project:PRJ-1@0",
                "snapshot-member-index-mismatch:SNP-0",
            ),
        )

    def test_missing_snapshot_member_index_row_is_reported(self) -> None:
        self.corrupt(
            "DELETE FROM snapshot_members WHERE snapshot_ref = 'SNP-2' AND member_kind = 'claim'"
        )
        self.assertEqual(self.issues(), ("snapshot-member-index-mismatch:SNP-2",))

    def test_missing_snapshot_member_object_is_reported(self) -> None:
        self.corrupt(
            "DELETE FROM object_revisions WHERE kind = 'research_question' AND object_id = 'RQ-1'"
        )
        issues = self.issues()
        self.assertIn("snapshot-member-object-missing:SNP-0:research_question:RQ-1@0", issues)
        self.assertIn("snapshot-member-object-missing:SNP-2:research_question:RQ-1@0", issues)
        self.assertTrue(any(issue.startswith("foreign-key:snapshot_members:") for issue in issues))

    def test_missing_decision_and_audit_objects_are_reported(self) -> None:
        self.corrupt(
            "DELETE FROM object_revisions WHERE kind IN ('decision', 'audit_event') "
            "AND object_id IN ('DEC-1', 'AUD-2')"
        )
        self.assertEqual(
            self.issues(),
            ("audit_event-object-missing:AUD-2", "decision-object-missing:DEC-1"),
        )

    def test_missing_lineage_head_is_reported(self) -> None:
        self.corrupt("UPDATE lineages SET head_snapshot_ref = 'SNP-NOPE'")
        issues = self.issues()
        self.assertIn("lineage-head-missing:LIN-1", issues)
        self.assertTrue(any(issue.startswith("foreign-key:lineages:") for issue in issues))

    def test_lineage_head_metadata_mismatch_is_reported(self) -> None:
        for column, value in (
            ("head_snapshot_digest", "'sha256:other'"),
            ("head_snapshot_revision", "head_snapshot_revision + 1"),
        ):
            with self.subTest(column=column):
                with self.connection:
                    self.connection.execute("SAVEPOINT probe")
                    self.connection.execute(f"UPDATE lineages SET {column} = {value}")
                    self.assertEqual(self.issues(), ("lineage-head-metadata-mismatch:LIN-1",))
                    self.connection.execute("ROLLBACK TO probe")
                    self.connection.execute("RELEASE probe")

    def test_missing_active_lineage_is_reported(self) -> None:
        self.corrupt("UPDATE project_active_lineage SET active_lineage_ref = 'LIN-NOPE'")
        issues = self.issues()
        self.assertIn("active-lineage-missing:PRJ-1", issues)
        self.assertTrue(
            any(issue.startswith("foreign-key:project_active_lineage:") for issue in issues)
        )

    def test_invalid_commit_receipt_is_reported(self) -> None:
        self.corrupt("UPDATE commits SET receipt_json = '{}'")
        self.assertEqual(
            self.issues(),
            ("commit-receipt:COM-2:stored CommitReceipt is invalid",),
        )

    def test_commit_receipt_column_mismatches_are_labelled(self) -> None:
        cases = (
            ("transition_id", "'TR-X'", "transition"),
            ("bundle_digest", "'sha256:x'", "bundle"),
            ("idempotency_key", "'IDEMP-X'", "idempotency"),
            ("prior_snapshot_digest", "'sha256:x'", "prior-digest"),
            ("new_snapshot_digest", "'sha256:x'", "new-digest"),
            ("new_snapshot_digest", "NULL", "new-digest"),
        )
        for column, value, label in cases:
            with self.subTest(column=column, value=value):
                with self.connection:
                    self.connection.execute("SAVEPOINT probe")
                    self.connection.execute(f"UPDATE commits SET {column} = {value}")
                    self.assertEqual(self.issues(), (f"commit-receipt-{label}-mismatch:COM-2",))
                    self.connection.execute("ROLLBACK TO probe")
                    self.connection.execute("RELEASE probe")

    def test_commit_snapshot_ref_mismatches_are_labelled(self) -> None:
        self.corrupt("UPDATE commits SET prior_snapshot_ref = 'SNP-2', new_snapshot_ref = NULL")
        self.assertEqual(
            self.issues(),
            (
                "commit-receipt-new-ref-mismatch:COM-2",
                "commit-receipt-prior-ref-mismatch:COM-2",
            ),
        )

    def test_commit_id_mismatch_is_labelled(self) -> None:
        row = self.connection.execute("SELECT receipt_json FROM commits").fetchone()
        receipt = json.loads(row["receipt_json"])
        receipt["commit_id"] = "COM-OTHER"
        self.corrupt("UPDATE commits SET receipt_json = ?", (canonical_json(receipt),))
        self.assertEqual(self.issues(), ("commit-receipt-id-mismatch:COM-2",))

    def test_non_canonical_receipt_json_is_reported(self) -> None:
        row = self.connection.execute("SELECT receipt_json FROM commits").fetchone()
        receipt = json.loads(row["receipt_json"])
        self.corrupt("UPDATE commits SET receipt_json = ?", (json.dumps(receipt, indent=1),))
        self.assertEqual(
            self.issues(),
            ("commit-receipt:COM-2:stored canonical JSON is not in deterministic form",),
        )

    def test_sqlite_integrity_rows_other_than_ok_are_reported(self) -> None:
        fake = _FakeIntegrityConnection(self.connection, [("OK",), ("row 7 missing from index",)])
        self.assertEqual(
            integrity_issues_for(fake),  # type: ignore[arg-type]
            ("sqlite-integrity:row 7 missing from index",),
        )

    def test_issues_are_sorted_and_deduplicated(self) -> None:
        fake = _FakeIntegrityConnection(
            self.connection, [("z problem",), ("a problem",), ("z problem",)]
        )
        self.assertEqual(
            integrity_issues_for(fake),  # type: ignore[arg-type]
            ("sqlite-integrity:a problem", "sqlite-integrity:z problem"),
        )

    def test_sqlite_errors_are_wrapped_in_repository_error(self) -> None:
        empty = sqlite3.connect(":memory:")
        empty.row_factory = sqlite3.Row
        self.addCleanup(empty.close)
        with self.assertRaisesRegex(RepositoryError, "SQLite integrity diagnostics failed") as ctx:
            integrity_issues_for(empty)
        self.assertIsInstance(ctx.exception.__cause__, sqlite3.OperationalError)

    def test_closed_connection_is_wrapped_in_repository_error(self) -> None:
        closed = sqlite3.connect(self.db_path)
        closed.close()
        with self.assertRaisesRegex(RepositoryError, "SQLite integrity diagnostics failed"):
            integrity_issues_for(closed)

    def test_connection_without_row_factory_is_supported(self) -> None:
        plain = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.addCleanup(plain.close)
        self.assertIsNone(plain.row_factory)
        self.assertEqual(integrity_issues_for(plain), ())
        self.assertIsNone(plain.row_factory, "the caller's row_factory must not change")
        # Exercises the row["..."] and row.keys() paths that needed sqlite3.Row.
        self.corrupt("UPDATE lineages SET head_snapshot_ref = 'SNP-NOPE'")
        self.assertEqual(integrity_issues_for(plain), self.issues())
        self.assertIn("lineage-head-missing:LIN-1", integrity_issues_for(plain))

    def test_read_only_connection_is_supported(self) -> None:
        read_only = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        read_only.row_factory = sqlite3.Row
        self.addCleanup(read_only.close)
        self.assertEqual(integrity_issues_for(read_only), ())


class DiagnosticsMixinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.seed = seed_state(
            objects=[project(), rq()],
            decisions=(decision("DEC-1", "scope", "approve", "research_question", "RQ-1"),),
        )
        self.repository = SQLiteResearchStateRepository(Path(self.tempdir.name) / "state.sqlite3")
        self.addCleanup(self.repository.close)
        self.repository.initialize_from_validated_state_view(self.seed)

    def test_repository_exposes_the_mixin(self) -> None:
        self.assertIsInstance(self.repository, DiagnosticsMixin)
        self.assertEqual(self.repository.integrity_issues(), ())

    def test_integrity_issues_never_repairs_state(self) -> None:
        self.repository._connection.execute("PRAGMA foreign_keys = OFF")
        self.repository._connection.execute(
            "UPDATE lineages SET head_snapshot_digest = 'sha256:other'"
        )
        before = self.repository.debug_state()
        self.assertEqual(
            self.repository.integrity_issues(), ("lineage-head-metadata-mismatch:LIN-1",)
        )
        self.assertEqual(
            self.repository.integrity_issues(), ("lineage-head-metadata-mismatch:LIN-1",)
        )
        self.assertEqual(self.repository.debug_state(), before)

    def test_debug_state_after_seed(self) -> None:
        state = self.repository.debug_state()
        self.assertEqual(
            sorted(state),
            [
                "active",
                "adoptions",
                "audits",
                "commits",
                "decisions",
                "lineages",
                "objects",
                "snapshots",
                "used_decisions",
            ],
        )
        self.assertEqual(
            [key for key, _ in state["objects"]],
            [
                ("decision", "DEC-1", 0),
                ("project", "PRJ-1", 0),
                ("research_question", "RQ-1", 0),
                ("snapshot", "SNP-0", 0),
            ],
        )
        decision_digest = dict(state["objects"])[("decision", "DEC-1", 0)]
        self.assertEqual(state["decisions"], [("DEC-1", decision_digest)])
        snapshot_digest = dict(state["objects"])[("snapshot", "SNP-0", 0)]
        self.assertEqual(state["snapshots"], [("SNP-0", snapshot_digest)])
        self.assertEqual(state["active"], "LIN-1")
        self.assertEqual(state["audits"], [])
        self.assertEqual(state["commits"], [])
        self.assertEqual(state["used_decisions"], [])
        self.assertEqual(state["adoptions"], [])
        [(lineage_id, lineage)] = state["lineages"]
        self.assertEqual(lineage_id, "LIN-1")
        self.assertEqual(lineage["head_snapshot_ref"], "SNP-0")
        self.assertEqual(
            lineage["head_snapshot_digest"], self.seed.current_snapshot["content_digest"]
        )
        self.assertEqual(lineage["status"], "active")

    def test_debug_state_after_commit_lists_audit_and_commit(self) -> None:
        StateTransitionService(self.repository, schema_validator=SCHEMA_VALIDATOR).apply(
            make_request(
                self.seed,
                [TransitionAction(TransitionKind.CREATE_OBJECT, {"object": _claim("CLM-1", "x")})],
                suffix="2",
            )
        )
        state = self.repository.debug_state()
        objects = dict(state["objects"])
        self.assertEqual(state["audits"], [("AUD-2", objects[("audit_event", "AUD-2", 0)])])
        [(key, request_digest)] = state["commits"]
        self.assertEqual(key, "IDEMP-2")
        self.assertTrue(request_digest.startswith("sha256:"))
        self.assertEqual([ref for ref, _ in state["snapshots"]], ["SNP-0", "SNP-2"])
        self.assertEqual(state["lineages"][0][1]["head_snapshot_ref"], "SNP-2")


if __name__ == "__main__":
    unittest.main()
