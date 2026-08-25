from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from core.runtime.ports import RepositoryError

from ._bootstrap import BootstrapMixin
from ._diagnostics import DiagnosticsMixin
from ._read import ReadMixin
from ._support import MIGRATION_DIR, load_migrations, rollback_quietly, split_sql_statements
from ._write import WriteMixin

_ALLOWED_JOURNAL_MODES = {"DELETE", "WAL"}
_ALLOWED_SYNCHRONOUS = {"FULL", "NORMAL", "EXTRA"}


class SQLiteResearchStateRepository(
    BootstrapMixin,
    ReadMixin,
    WriteMixin,
    DiagnosticsMixin,
):
    """Production SQLite implementation of PR20 ResearchStateRepository.

    Core/runtime owns all Research semantics. This adapter owns only physical
    persistence, deterministic migration, integrity, transactions, locking,
    and commit-time optimistic concurrency.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
        journal_mode: str = "DELETE",
        synchronous: str = "FULL",
    ) -> None:
        self.database = str(database)
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        journal_mode = journal_mode.upper()
        synchronous = synchronous.upper()
        if journal_mode not in _ALLOWED_JOURNAL_MODES:
            raise ValueError(f"unsupported journal_mode {journal_mode!r}")
        if synchronous not in _ALLOWED_SYNCHRONOUS:
            raise ValueError(
                f"unsupported synchronous setting {synchronous!r}"
            )

        try:
            self._connection = sqlite3.connect(
                self.database,
                isolation_level=None,
                timeout=max(busy_timeout_ms / 1000.0, 0.001),
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                f"PRAGMA busy_timeout = {int(busy_timeout_ms)}"
            )
            actual_journal = str(
                self._connection.execute(
                    f"PRAGMA journal_mode = {journal_mode}"
                ).fetchone()[0]
            ).upper()
            self._connection.execute(
                f"PRAGMA synchronous = {synchronous}"
            )
            if (
                self.database != ":memory:"
                and actual_journal != journal_mode
            ):
                raise RepositoryError(
                    "SQLite refused requested journal_mode "
                    f"{journal_mode!r}; got {actual_journal!r}"
                )
            if int(
                self._connection.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0]
            ) != 1:
                raise RepositoryError(
                    "SQLite foreign_keys pragma is not enabled"
                )
            self._migrate()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteResearchStateRepository":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        try:
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS version
                FROM schema_migrations
                """
            ).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(
                "SQLite schema metadata is unavailable"
            ) from exc
        return int(row["version"]) if row is not None else 0

    def _migrate(self) -> None:
        migrations = load_migrations(MIGRATION_DIR)
        latest = migrations[-1][0] if migrations else 0
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                int(row["version"]): str(row["name"])
                for row in self._connection.execute(
                    """
                    SELECT version, name FROM schema_migrations
                    ORDER BY version
                    """
                )
            }
            if applied and max(applied) > latest:
                raise RepositoryError(
                    f"SQLite schema version {max(applied)} is newer "
                    f"than supported version {latest}"
                )
            for version, name, _sql in migrations:
                existing_name = applied.get(version)
                if (
                    existing_name is not None
                    and existing_name != name
                ):
                    raise RepositoryError(
                        f"SQLite migration {version:04d} name mismatch: "
                        f"{existing_name!r} != {name!r}"
                    )
            for version, name, sql in migrations:
                if version in applied:
                    continue
                for statement in split_sql_statements(sql):
                    self._connection.execute(statement)
                self._connection.execute(
                    """
                    INSERT INTO schema_migrations(version, name)
                    VALUES (?, ?)
                    """,
                    (version, name),
                )
            self._connection.execute("COMMIT")
        except RepositoryError:
            rollback_quietly(self._connection)
            raise
        except (OSError, UnicodeError, sqlite3.Error) as exc:
            rollback_quietly(self._connection)
            raise RepositoryError(
                "SQLite schema migration failed atomically"
            ) from exc

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
            self._connection.execute("COMMIT")
        except Exception:
            rollback_quietly(self._connection)
            raise
