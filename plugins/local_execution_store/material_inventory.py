from __future__ import annotations

import json
from typing import Mapping

from core.execution.models import ExecutionArtifactMetadata

from .store import LocalExecutionStoreIntegrityError


_ORIGINAL_ROLE = "desktop_research.original_capture"
_TEXT_ROLE = "desktop_research.text_rendition"
_CAPTURE_KEY_BATCH_SIZE = 300


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


def _capture_id(artifact: ExecutionArtifactMetadata) -> str:
    capture_id = artifact.provenance.get("capture_id")
    if not isinstance(capture_id, str) or not capture_id:
        raise LocalExecutionStoreIntegrityError(
            "persisted external capture provenance is missing capture_id"
        )
    return capture_id


def external_capture_artifact_metadata_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
    after: tuple[str, str] | None = None,
) -> tuple[tuple[ExecutionArtifactMetadata, ...], tuple[str, str] | None]:
    """Read one bounded material page of persisted Desktop Research captures.

    ``after`` is the exclusive ``(first_captured_at, material_id)`` page key.
    The page bound limits projected materials and artifact metadata. Discovering
    material keys still aggregates the project-wide original-capture history so
    cross-Run digest identity and first-capture ordering remain exact without a
    second persisted material index.

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

        originals = tuple(_artifact_from_row(row) for row in original_rows)
        if not originals:
            raise LocalExecutionStoreIntegrityError(
                "persisted external material page has no original captures"
            )
        capture_keys = sorted(
            {
                (artifact.run_id, _capture_id(artifact))
                for artifact in originals
            }
        )

        rendition_rows = []
        for offset in range(0, len(capture_keys), _CAPTURE_KEY_BATCH_SIZE):
            capture_batch = capture_keys[offset : offset + _CAPTURE_KEY_BATCH_SIZE]
            selected_values = ",".join("(?, ?)" for _ in capture_batch)
            selected_params = [
                value
                for run_id, capture_id in capture_batch
                for value in (run_id, capture_id)
            ]
            rendition_rows.extend(
                store._connection.execute(
                    f"""
                    WITH selected(run_id, capture_id) AS (
                        VALUES {selected_values}
                    )
                    SELECT t.artifact_id, t.run_id, t.role, t.media_type, t.size,
                           t.digest, t.storage_locator, t.execution_mode,
                           t.provenance_json
                    FROM selected AS s
                    JOIN execution_artifacts AS t ON t.run_id = s.run_id
                    WHERE t.role = ?
                      AND json_extract(t.provenance_json, '$.capture_id') = s.capture_id
                    ORDER BY t.run_id, t.artifact_id
                    """,
                    (*selected_params, _TEXT_ROLE),
                ).fetchall()
            )

    renditions = tuple(_artifact_from_row(row) for row in rendition_rows)
    artifacts = (*originals, *renditions)
    next_after = material_keys[-1] if len(material_rows) > limit else None
    return artifacts, next_after
