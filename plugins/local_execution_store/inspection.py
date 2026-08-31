from __future__ import annotations

import json
from typing import Any, Mapping

from .store import LocalExecutionStoreIntegrityError


def diagnostics_for(
    store,
    run_id: str,
    *,
    limit: int,
) -> tuple[Mapping[str, Any], ...]:
    """Read a bounded Run-scoped set of persisted execution diagnostics."""
    if limit <= 0:
        raise ValueError("diagnostic query limit must be positive")
    with store._lock:
        rows = store._connection.execute(
            """
            SELECT kind, payload_json
            FROM diagnostics
            WHERE run_id=?
            ORDER BY diagnostic_id
            LIMIT ?
            """,
            (str(run_id), int(limit)),
        ).fetchall()

    diagnostics: list[Mapping[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as exc:
            raise LocalExecutionStoreIntegrityError(
                "persisted execution diagnostic is invalid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise LocalExecutionStoreIntegrityError(
                "persisted execution diagnostic payload must be an object"
            )
        diagnostics.append({"kind": str(row["kind"]), "payload": dict(payload)})
    return tuple(diagnostics)
