from __future__ import annotations

from core.execution.models import CapabilityRunRecord, RunStatus


def pending_runs_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
) -> tuple[CapabilityRunRecord, ...]:
    """Read a bounded project-scoped set of non-terminal external/active Runs."""
    if limit <= 0:
        raise ValueError("pending Run query limit must be positive")
    with store._lock:
        rows = store._connection.execute(
            """
            SELECT * FROM runs
            WHERE project_ref=? AND status IN (?, ?)
            ORDER BY prepared_at, run_id
            LIMIT ?
            """,
            (
                str(project_ref),
                RunStatus.PREPARED.value,
                RunStatus.RUNNING.value,
                int(limit),
            ),
        ).fetchall()
    return tuple(store._decode_run(row) for row in rows)


def recent_runs_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
) -> tuple[CapabilityRunRecord, ...]:
    """Read a bounded newest-first project-scoped set of terminal Runs."""
    if limit <= 0:
        raise ValueError("recent Run query limit must be positive")
    terminal = (
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.ABORTED.value,
        RunStatus.SUPERSEDED.value,
    )
    with store._lock:
        rows = store._connection.execute(
            """
            SELECT * FROM runs
            WHERE project_ref=? AND status IN (?, ?, ?, ?)
            ORDER BY COALESCE(completed_at, prepared_at) DESC, run_id DESC
            LIMIT ?
            """,
            (str(project_ref), *terminal, int(limit)),
        ).fetchall()
    return tuple(store._decode_run(row) for row in rows)


def child_runs_for_parent(
    store,
    parent_run_id: str,
    *,
    limit: int,
    newest_first: bool = False,
    before: tuple[int, str, str] | None = None,
) -> tuple[CapabilityRunRecord, ...]:
    """Return a page of Runs with an explicit persisted parent binding."""
    if not isinstance(parent_run_id, str) or not parent_run_id or limit <= 0:
        raise ValueError("parent Run ID and positive limit are required")
    if before is not None and not newest_first:
        raise ValueError("a child Run cursor requires newest-first ordering")
    cursor_predicate = ""
    parameters: tuple[object, ...] = (parent_run_id,)
    if before is not None:
        attempt, prepared_at, run_id = before
        if attempt <= 0 or not prepared_at or not run_id:
            raise ValueError("child Run cursor is invalid")
        cursor_predicate = """
            AND (
                attempt < ?
                OR (attempt = ? AND prepared_at < ?)
                OR (attempt = ? AND prepared_at = ? AND run_id < ?)
            )
        """
        parameters += (attempt, attempt, prepared_at, attempt, prepared_at, run_id)
    direction = "DESC" if newest_first else "ASC"
    with store._lock:
        rows = store._connection.execute(
            f"""
            SELECT * FROM runs
            WHERE parent_run_id=?
            {cursor_predicate}
            ORDER BY attempt {direction}, prepared_at {direction}, run_id {direction}
            LIMIT ?
            """,
            (*parameters, int(limit)),
        ).fetchall()
    return tuple(store._decode_run(row) for row in rows)


def latest_child_attempt_for_parent(store, parent_run_id: str) -> int:
    """Return the greatest persisted child Run attempt without loading Run history."""
    if not isinstance(parent_run_id, str) or not parent_run_id:
        raise ValueError("parent Run ID is required")
    with store._lock:
        row = store._connection.execute(
            "SELECT COALESCE(MAX(attempt), 0) AS latest_attempt FROM runs WHERE parent_run_id=?",
            (parent_run_id,),
        ).fetchone()
    return int(row["latest_attempt"])
