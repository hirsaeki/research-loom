from __future__ import annotations

import json
from typing import Any, Mapping

from core.execution.models import ExecutionArtifactMetadata

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


def artifact_metadata_for(
    store,
    run_id: str,
    *,
    limit: int,
) -> tuple[ExecutionArtifactMetadata, ...]:
    """Read a bounded Run-scoped set of persisted artifact metadata."""
    if limit <= 0:
        raise ValueError("artifact metadata query limit must be positive")
    with store._lock:
        rows = store._connection.execute(
            """
            SELECT artifact_id, run_id, role, media_type, size, digest,
                   storage_locator, execution_mode, provenance_json
            FROM execution_artifacts
            WHERE run_id=?
            ORDER BY artifact_id
            LIMIT ?
            """,
            (str(run_id), int(limit)),
        ).fetchall()

    artifacts: list[ExecutionArtifactMetadata] = []
    for row in rows:
        try:
            provenance = json.loads(str(row["provenance_json"]))
        except json.JSONDecodeError as exc:
            raise LocalExecutionStoreIntegrityError(
                "persisted artifact provenance is invalid JSON"
            ) from exc
        if not isinstance(provenance, Mapping):
            raise LocalExecutionStoreIntegrityError(
                "persisted artifact provenance must be an object"
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
