"""A schema_migrations record for core-tier stores without migration files.

ADR 0001 has every core-tier store record its schema version in a
``schema_migrations`` table, the shape State and Execution already use. Stores
whose schema has never changed record a single baseline migration. A database
created before the record existed has no table yet; readers accept it and the
next writable open records the baseline.
"""

from __future__ import annotations

import sqlite3

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations(
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

Migration = tuple[int, str]


def recorded_migrations(connection: sqlite3.Connection) -> list[Migration] | None:
    """The recorded history, or None when the store predates the record."""
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if table is None:
        return None
    rows = connection.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    return [(int(row[0]), str(row[1])) for row in rows.fetchall()]


def migration_issue(connection: sqlite3.Connection, baseline: Migration) -> str | None:
    """Describe a history this code does not know; None when it is the baseline or absent."""
    recorded = recorded_migrations(connection)
    if recorded is None or recorded == [baseline]:
        return None
    return f"unknown schema migration history: {recorded}"


def record_baseline(connection: sqlite3.Connection, baseline: Migration) -> str | None:
    """Record the baseline inside the caller's write transaction.

    Returns an issue instead of recording when another history is present.
    """
    issue = migration_issue(connection, baseline)
    if issue is not None:
        return issue
    connection.execute(SCHEMA_MIGRATIONS_SQL)
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name) VALUES (?, ?)", baseline
    )
    return migration_issue(connection, baseline)
