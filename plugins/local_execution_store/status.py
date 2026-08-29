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