from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

import test_state_transition as runtime_suite
from core.runtime import StateTransitionService, TransitionAction, TransitionKind
from core.runtime.ports import AtomicCommitError, RepositoryError
from core.runtime.transition_models import CommitReceipt
from plugins.sqlite_state_store import SQLiteResearchStateRepository
from plugins.sqlite_state_store import adapter as sqlite_adapter
from plugins.sqlite_state_store import _support as sqlite_support
from runtime_fixtures import SCHEMA_VALIDATOR, make_request, project, rq, seed_state


class _ParitySQLiteRepository(SQLiteResearchStateRepository):
    """Test-only physical fault seam for the inherited PR20 runtime suite."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_next_commit = False

    def commit(self, bundle, *, expected_head_snapshot_digest):
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise AtomicCommitError("simulated atomic persistence failure")
        return super().commit(
            bundle,
            expected_head_snapshot_digest=expected_head_snapshot_digest,
        )


class _RaceSQLiteRepository(SQLiteResearchStateRepository):
    """Inject one competing commit after StateView load but before own CAS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.before_commit = None

    def commit(self, bundle, *, expected_head_snapshot_digest):
        callback = self.before_commit
        self.before_commit = None
        if callback is not None:
            callback()
        return super().commit(
            bundle,
            expected_head_snapshot_digest=expected_head_snapshot_digest,
        )


class SQLiteStateTransitionRuntimeParityTests(
    runtime_suite.StateTransitionRuntimeTests
):
    """Run the complete PR20 StateTransitionService suite against SQLite."""

    def setUp(self):
        self._prior_service = runtime_suite.service
        self._tempdirs = []
        self._repositories = []
        runtime_suite.service = self._sqlite_service

    def tearDown(self):
        runtime_suite.service = self._prior_service
        for repository in reversed(self._repositories):
            repository.close()
        for tempdir in reversed(self._tempdirs):
            tempdir.cleanup()

    def _sqlite_service(self, seed):
        tempdir = tempfile.TemporaryDirectory()
        repository = _ParitySQLiteRepository(
            Path(tempdir.name) / "research-state.sqlite3"
        )
        repository.initialize_from_validated_state_view(seed)
        self._tempdirs.append(tempdir)
        self._repositories.append(repository)
        return repository, StateTransitionService(
            repository,
            schema_validator=SCHEMA_VALIDATOR,
        )


class SQLiteRepositorySpecificTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "state.sqlite3"
        self.repositories = []

    def tearDown(self):
        for repository in reversed(self.repositories):
            try:
                repository.close()
            except sqlite3.Error:
                pass
        self.tempdir.cleanup()

    def repo(self, seed=None):
        repository = SQLiteResearchStateRepository(self.db_path)
        if seed is not None:
            repository.initialize_from_validated_state_view(seed)
        self.repositories.append(repository)
        return repository

    def service(self, repository):
        return StateTransitionService(
            repository,
            schema_validator=SCHEMA_VALIDATOR,
        )

    def test_fresh_migration_bootstrap_reopen_is_identical(self):
        seed = seed_state(
            objects=[project(), rq()],
            project_config={"title": "SQLite 日本語", "enabled": False},
            constraints={"minimum": 0},
            source_modes={"SRC-V": "virtual"},
            non_reusable=("RUN-V",),
        )
        repository = self.repo(seed)
        first = repository.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(repository.schema_version, 1)
        self.assertEqual(repository.integrity_issues(), ())
        repository.close()
        self.repositories.remove(repository)

        reopened = self.repo()
        second = reopened.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(first, second)
        self.assertEqual(second.project_config["title"], "SQLite 日本語")
        self.assertFalse(second.project_config["enabled"])
        self.assertEqual(second.effective_constraints["minimum"], 0)
        self.assertEqual(second.source_modes, {"SRC-V": "virtual"})
        self.assertEqual(second.non_reusable_refs, ("RUN-V",))

    def test_generic_schema_has_no_capability_specific_tables(self):
        self.repo(seed_state(objects=[project()]))
        with sqlite3.connect(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        for required in (
            "object_revisions",
            "snapshots",
            "lineages",
            "commits",
        ):
            self.assertIn(required, tables)
        for forbidden in (
            "survey_result",
            "delphi_result",
            "case_result",
            "poc_result",
        ):
            self.assertNotIn(forbidden, tables)

    def test_unknown_newer_schema_fails_closed(self):
        repository = self.repo()
        repository.close()
        self.repositories.remove(repository)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name)
                VALUES (999, 'future')
                """
            )
        with self.assertRaises(RepositoryError):
            SQLiteResearchStateRepository(self.db_path)

    def test_pending_migration_failure_rolls_back_transaction(self):
        migration_dir = Path(self.tempdir.name) / "migrations"
        migration_dir.mkdir()
        shutil.copyfile(
            sqlite_support.MIGRATION_DIR / "0001_research_state.sql",
            migration_dir / "0001_research_state.sql",
        )
        (migration_dir / "0002_broken.sql").write_text(
            "CREATE TABLE should_rollback(id INTEGER PRIMARY KEY);\n"
            "THIS IS NOT VALID SQL;\n",
            encoding="utf-8",
        )
        prior = sqlite_adapter.MIGRATION_DIR
        sqlite_adapter.MIGRATION_DIR = migration_dir
        broken = Path(self.tempdir.name) / "broken.sqlite3"
        try:
            with self.assertRaises(RepositoryError):
                SQLiteResearchStateRepository(broken)
        finally:
            sqlite_adapter.MIGRATION_DIR = prior
        with sqlite3.connect(broken) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertNotIn("project_state", tables)
        self.assertNotIn("should_rollback", tables)

    def test_unicode_roundtrip_commit_receipt_and_resolve_refs(self):
        seed = seed_state(objects=[project(), rq()])
        repository = self.repo(seed)
        claim = {
            "schema_version": "0.1.0",
            "id": "CLM-JP",
            "kind": "claim",
            "revision": 0,
            "project_id": "PRJ-1",
            "question_id": "RQ-1",
            "statement": "日本語の主張 🧪",
            "assessment": "proposed",
        }
        request = make_request(
            seed,
            [
                TransitionAction(
                    TransitionKind.CREATE_OBJECT,
                    {"object": claim},
                )
            ],
            key="IDEMP-JP",
        )
        receipt = self.service(repository).apply(request)
        self.assertIsInstance(receipt, CommitReceipt)
        self.assertEqual(
            repository.load_object_revision("claim", "CLM-JP", 0)[
                "statement"
            ],
            "日本語の主張 🧪",
        )
        self.assertEqual(
            repository.find_commit_by_idempotency_key("IDEMP-JP"),
            (request.request_digest, receipt),
        )
        self.assertEqual(
            repository.resolve_refs(
                (
                    ("claim", "CLM-JP"),
                    ("snapshot", receipt.new_snapshot_ref),
                    ("research_lineage", "LIN-1"),
                    ("claim", "MISSING"),
                )
            ),
            {
                ("claim", "CLM-JP"): True,
                ("snapshot", receipt.new_snapshot_ref): True,
                ("research_lineage", "LIN-1"): True,
                ("claim", "MISSING"): False,
            },
        )
        self.assertEqual(repository.integrity_issues(), ())

    def test_two_connections_reject_second_stale_head(self):
        seed = seed_state(objects=[project(), rq()])
        first = self.repo(seed)
        second = _RaceSQLiteRepository(self.db_path)
        self.repositories.append(second)

        request_a = make_request(
            seed,
            [
                TransitionAction(
                    TransitionKind.CREATE_OBJECT,
                    {"object": _claim("CLM-A", "A")},
                )
            ],
            suffix="31",
            key="IDEMP-A",
            new_snapshot_id="SNP-A",
        )
        request_b = make_request(
            seed,
            [
                TransitionAction(
                    TransitionKind.CREATE_OBJECT,
                    {"object": _claim("CLM-B", "B")},
                )
            ],
            suffix="32",
            key="IDEMP-B",
            new_snapshot_id="SNP-B",
        )

        def competing_commit():
            result = self.service(first).apply(request_a)
            self.assertIsInstance(result, CommitReceipt)

        second.before_commit = competing_commit
        rejected = self.service(second).apply(request_b)
        self.assertNotIsInstance(rejected, CommitReceipt)
        self.assertIn(
            "RT-HEAD-002",
            {issue.error_code for issue in rejected.issues},
        )
        self.assertIsNone(
            second.load_object_revision("claim", "CLM-B", 0)
        )

    def test_mid_transaction_fault_rolls_back_all_research_state(self):
        seed = seed_state(objects=[project(), rq()])
        repository = self.repo(seed)
        before = repository.debug_state()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER fail_audit
                BEFORE INSERT ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'fault injection');
                END
                """
            )
        request = make_request(
            seed,
            [
                TransitionAction(
                    TransitionKind.CREATE_OBJECT,
                    {"object": _claim("CLM-FAULT", "rollback")},
                )
            ],
            suffix="41",
            key="IDEMP-FAULT",
            new_snapshot_id="SNP-FAULT",
        )
        rejected = self.service(repository).apply(request)
        self.assertIn(
            "RT-PERSIST-001",
            {issue.error_code for issue in rejected.issues},
        )
        self.assertEqual(repository.debug_state(), before)
        self.assertIsNone(
            repository.load_object_revision("claim", "CLM-FAULT", 0)
        )
        self.assertIsNone(repository.load_snapshot("SNP-FAULT"))
        self.assertIsNone(
            repository.find_commit_by_idempotency_key("IDEMP-FAULT")
        )

    def test_doctor_reports_foreign_key_corruption_without_repair(self):
        seed = seed_state(objects=[project(), rq()])
        repository = self.repo(seed)
        repository.close()
        self.repositories.remove(repository)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                """
                DELETE FROM object_revisions
                WHERE kind='research_question'
                  AND object_id='RQ-1'
                  AND revision=0
                """
            )
        reopened = self.repo()
        issues = reopened.integrity_issues()
        self.assertTrue(
            any(
                issue.startswith("foreign-key:")
                or issue.startswith("snapshot-member-object-missing:")
                for issue in issues
            ),
            issues,
        )
        self.assertIsNone(
            reopened.load_object_revision(
                "research_question", "RQ-1", 0
            )
        )

    def test_external_content_digest_is_preserved_not_reinterpreted(self):
        seed = seed_state(objects=[project()])
        repository = self.repo(seed)
        artifact = {
            "schema_version": "0.1.0",
            "id": "ART-1",
            "kind": "artifact",
            "revision": 0,
            "project_id": "PRJ-1",
            "role": "input",
            "lane": "research",
            "artifact_class": "input",
            "locator": "fixture://artifact",
            "evidence_eligible": False,
            "content_digest": "sha256:external-bytes-digest",
        }
        with repository._write_transaction():
            repository._insert_immutable_object(
                artifact,
                created_commit_id=None,
            )
        self.assertEqual(
            repository.load_object_revision("artifact", "ART-1", 0)[
                "content_digest"
            ],
            "sha256:external-bytes-digest",
        )


def _claim(claim_id: str, statement: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "id": claim_id,
        "kind": "claim",
        "revision": 0,
        "project_id": "PRJ-1",
        "question_id": "RQ-1",
        "statement": statement,
        "assessment": "proposed",
    }


if __name__ == "__main__":
    unittest.main()
