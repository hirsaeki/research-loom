from __future__ import annotations

import json
from typing import Mapping

from core.execution.models import ExecutionArtifactMetadata

from .store import LocalExecutionStoreIntegrityError


_ORIGINAL_ROLE = "desktop_research.original_capture"
_TEXT_ROLE = "desktop_research.text_rendition"


def _artifact_from_row(row) -> ExecutionArtifactMetadata:
    try:
        provenance = json.loads(str(row["provenance_json"]))
    except json.JSONDecodeError as exc:
        raise LocalExecutionStoreIntegrityError(
            "persisted external capture provenance is invalid JSON"
        ) from exc
    if not isinstance(provenance, Mapping):
        raise LocalExecutionStoreIntegrityError(
            "persisted external capture provenance must be an object"
        )
    return ExecutionArtifactMetadata(
        str(row["artifact_id"]),
        str(row["run_id"]),
        str(row["role"]),
        str(row["media_type"]),
        int(row["size"]),
        str(row["digest"]),
        str(row["storage_locator"]),
        str(row["execution_mode"]),
        dict(provenance),
    )


def external_capture_artifact_metadata_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
    after: tuple[str, str] | None = None,
) -> tuple[tuple[ExecutionArtifactMetadata, ...], tuple[str, str] | None]:
    """Read one bounded material page of persisted Desktop Research captures.

    ``after`` is the exclusive ``(first_captured_at, material_id)`` page key.
    Callers receive artifact metadata only, never SQLite rows, paths, or blob bytes.
    """
    if limit <= 0:
        raise ValueError("external material query limit must be positive")
    if after is not None and (
        len(after) != 2
        or not all(isinstance(item, str) and item for item in after)
    ):
        raise ValueError("external material cursor key is invalid")

    cursor_clause = ""
    key_params: list[object] = [str(project_ref), _ORIGINAL_ROLE]
    if after is not None:
        cursor_clause = """
        WHERE first_captured_at > ?
           OR (first_captured_at = ? AND material_id > ?)
        """
        key_params.extend((after[0], after[0], after[1]))
    key_params.append(int(limit) + 1)

    with store._lock:
        material_rows = store._connection.execute(
            f"""
            WITH material_keys AS (
                SELECT a.digest AS material_id,
                       MIN(json_extract(a.provenance_json, '$.stored_at')) AS first_captured_at
                FROM execution_artifacts AS a
                JOIN runs AS r ON r.run_id = a.run_id
                WHERE r.project_ref = ?
                  AND r.capability_id = 'desktop-research'
                  AND r.function_id = 'investigate'
                  AND r.execution_mode = 'real'
                  AND a.role = ?
                GROUP BY a.digest
            )
            SELECT material_id, first_captured_at
            FROM material_keys
            {cursor_clause}
            ORDER BY first_captured_at, material_id
            LIMIT ?
            """,
            tuple(key_params),
        ).fetchall()

        page_rows = material_rows[:limit]
        material_keys: list[tuple[str, str]] = []
        for row in page_rows:
            captured_at = row["first_captured_at"]
            material_id = row["material_id"]
            if not isinstance(captured_at, str) or not captured_at:
                raise LocalExecutionStoreIntegrityError(
                    "persisted external capture provenance is missing stored_at"
                )
            if not isinstance(material_id, str) or not material_id:
                raise LocalExecutionStoreIntegrityError(
                    "persisted external capture artifact is missing digest"
                )
            material_keys.append((captured_at, material_id))

        if not material_keys:
            return (), None

        digests = [material_id for _, material_id in material_keys]
        placeholders = ",".join("?" for _ in digests)
        original_rows = store._connection.execute(
            f"""
            SELECT a.artifact_id, a.run_id, a.role, a.media_type, a.size, a.digest,
                   a.storage_locator, a.execution_mode, a.provenance_json
            FROM execution_artifacts AS a
            JOIN runs AS r ON r.run_id = a.run_id
            WHERE r.project_ref = ?
              AND r.capability_id = 'desktop-research'
              AND r.function_id = 'investigate'
              AND r.execution_mode = 'real'
              AND a.role = ?
              AND a.digest IN ({placeholders})
            ORDER BY r.prepared_at, a.run_id, a.artifact_id
            """,
            (str(project_ref), _ORIGINAL_ROLE, *digests),
        ).fetchall()

        rendition_rows = store._connection.execute(
            f"""
            SELECT t.artifact_id, t.run_id, t.role, t.media_type, t.size, t.digest,
                   t.storage_locator, t.execution_mode, t.provenance_json
            FROM execution_artifacts AS t
            JOIN runs AS r ON r.run_id = t.run_id
            WHERE r.project_ref = ?
              AND r.capability_id = 'desktop-research'
              AND r.function_id = 'investigate'
              AND r.execution_mode = 'real'
              AND t.role = ?
              AND EXISTS (
                  SELECT 1
                  FROM execution_artifacts AS o
                  WHERE o.run_id = t.run_id
                    AND o.role = ?
                    AND o.digest IN ({placeholders})
                    AND json_extract(o.provenance_json, '$.capture_id')
                        = json_extract(t.provenance_json, '$.capture_id')
              )
            ORDER BY r.prepared_at, t.run_id, t.artifact_id
            """,
            (str(project_ref), _TEXT_ROLE, _ORIGINAL_ROLE, *digests),
        ).fetchall()

    artifacts = tuple(
        _artifact_from_row(row)
        for row in (*original_rows, *rendition_rows)
    )
    next_after = material_keys[-1] if len(material_rows) > limit else None
    return artifacts, next_after
