"""Per-connection SQLite settings shared by the local stores.

Stores open their own connections (URI form, isolation level and thread
checks differ by store) and then apply their PRAGMAs here, so the allowed
values and the order they are applied in are defined once.
"""

from __future__ import annotations

import sqlite3

ALLOWED_JOURNAL_MODES = frozenset({"DELETE", "WAL"})
ALLOWED_SYNCHRONOUS = frozenset({"FULL", "NORMAL", "EXTRA"})


def apply_pragmas(
    connection: sqlite3.Connection,
    *,
    foreign_keys: bool = False,
    query_only: bool = False,
    busy_timeout_ms: int | None = None,
    journal_mode: str | None = None,
    synchronous: str | None = None,
) -> str | None:
    """Apply the requested PRAGMAs; return the journal mode SQLite reports, if one was requested.

    Settings that are left at their defaults are not issued. The journal mode is
    switched after the busy timeout is set, so a contended switch waits instead
    of failing immediately.
    """
    if journal_mode is not None and journal_mode.upper() not in ALLOWED_JOURNAL_MODES:
        raise ValueError(f"unsupported journal_mode {journal_mode!r}")
    if synchronous is not None and synchronous.upper() not in ALLOWED_SYNCHRONOUS:
        raise ValueError(f"unsupported synchronous setting {synchronous!r}")
    if busy_timeout_ms is not None and busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be non-negative")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
    if query_only:
        connection.execute("PRAGMA query_only = ON")
    if busy_timeout_ms is not None:
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    actual_journal = None
    if journal_mode is not None:
        row = connection.execute(f"PRAGMA journal_mode = {journal_mode.upper()}").fetchone()
        actual_journal = str(row[0]).upper()
    if synchronous is not None:
        connection.execute(f"PRAGMA synchronous = {synchronous.upper()}")
    return actual_journal


def foreign_keys_enabled(connection: sqlite3.Connection) -> bool:
    return int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
