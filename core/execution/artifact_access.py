from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .models import (
    CapabilityExecutionError,
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ExecutionFailureCode,
)
from .ports import ExecutionArtifactStore


class BoundedArtifactSink:
    """Capability-facing write-only sink bound to one immutable Run identity."""

    def __init__(
        self,
        run: CapabilityRunRecord,
        store: ExecutionArtifactStore | None,
    ) -> None:
        self._run = run
        self._store = store

    def put_bytes(
        self,
        *,
        role: str,
        media_type: str,
        content: bytes,
        artifact_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        parent_artifact_refs: tuple[str, ...] = (),
    ) -> ExecutionArtifactMetadata:
        if self._store is None:
            raise CapabilityExecutionError(
                ExecutionFailureCode.ARTIFACT_STORE_ERROR,
                "artifact output is unavailable because no trusted Artifact Store is configured",
            )
        if not isinstance(content, bytes):
            raise CapabilityExecutionError(
                ExecutionFailureCode.ARTIFACT_STORE_ERROR,
                "artifact content must be bytes",
            )
        try:
            return self._store.put_bytes(
                self._run,
                role=str(role),
                media_type=str(media_type),
                content=content,
                artifact_id=artifact_id,
                provenance=deepcopy(dict(provenance or {})),
                parent_artifact_refs=tuple(parent_artifact_refs),
            )
        except CapabilityExecutionError:
            raise
        except Exception as exc:
            raise CapabilityExecutionError(
                ExecutionFailureCode.ARTIFACT_STORE_ERROR,
                f"trusted Artifact Store rejected output: {exc}",
            ) from exc
