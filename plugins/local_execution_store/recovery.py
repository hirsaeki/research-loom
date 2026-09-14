from __future__ import annotations

from typing import Any, Mapping


def result_extensions_for_run(
    store,
    run_id: str,
    *,
    limit: int = 3,
) -> tuple[Mapping[str, Any], ...]:
    """Return a bounded verified result-extension set for one exact Run."""
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    with store._lock:
        rows = store._connection.execute(
            """
            SELECT identity
            FROM execution_documents
            WHERE document_type = 'extension' AND run_id = ?
            ORDER BY rowid
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
    return tuple(
        document
        for row in rows
        if (document := store._load_document("extension", str(row["identity"])))
        is not None
    )
