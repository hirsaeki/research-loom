from __future__ import annotations

import json
from typing import Mapping

from core.execution.models import ExecutionArtifactMetadata

from .store import LocalExecutionStoreIntegrityError


_CAPTURE_ROLES = (
    "desktop_research.original_capture",
    "desktop_research.text_rendition",
)


def external_capture_artifact_metadata_for_project(
    store,
    project_ref: str,
) -> tuple[ExecutionArtifactMetadata, ...]:
    """Read persisted Desktop Research capture metadata for one project.

    This is an internal storage adapter seam. Callers receive artifact metadata,
    not SQLite rows, paths, or blob bytes.
    """
    with store._lock:
        rows = store._connection.execute(
            """
            SELECT a.artifact_id, a.run_id, a.role, a.media_type, a.size, a.digest,
                   a.storage_locator, a.execution_mode, a.provenance_json
            FROM execution_artifacts AS a
            JOIN runs AS r ON r.run_id = a.run_id
            WHERE r.project_ref = ?
              AND r.capability_id = 'desktop-research'
              AND r.function_id = 'investigate'
              AND r.execution_mode = 'real'
              AND a.role IN (?, ?)
            ORDER BY r.prepared_at, a.run_id, a.artifact_id
            """,
            (str(project_ref), *_CAPTURE_ROLES),
        ).fetchall()

    artifacts: list[ExecutionArtifactMetadata] = []
    for row in rows:
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
        artifacts.append(
            ExecutionArtifactMetadata(
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
        )
    return tuple(artifacts)
