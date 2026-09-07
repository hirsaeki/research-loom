from __future__ import annotations

import json

from core.execution.models import ExecutionArtifactMetadata


def artifacts_for_capture_ids(store, run_id: str, capture_ids: list[str] | tuple[str, ...]):
    """Return metadata only for the selected capture identities in one bounded query."""
    selected = tuple(dict.fromkeys(capture_ids))
    if not selected:
        return ()
    placeholders = ",".join("?" for _ in selected)
    with store._lock:
        rows = store._connection.execute(
            f"""
            SELECT artifact_id, run_id, role, media_type, size, digest,
                   storage_locator, execution_mode, provenance_json
            FROM execution_artifacts
            WHERE run_id = ?
              AND json_extract(provenance_json, '$.capture_id') IN ({placeholders})
            ORDER BY artifact_id
            """,
            (run_id, *selected),
        ).fetchall()
    return tuple(
        ExecutionArtifactMetadata(
            str(row["artifact_id"]),
            str(row["run_id"]),
            str(row["role"]),
            str(row["media_type"]),
            int(row["size"]),
            str(row["digest"]),
            str(row["storage_locator"]),
            str(row["execution_mode"]),
            json.loads(str(row["provenance_json"])),
        )
        for row in rows
    )
