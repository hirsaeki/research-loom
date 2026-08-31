from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from core.execution.models import CapabilityRunRecord, ExecutionArtifactMetadata, RunStatus
from core.execution.operational_trace import OperationalTraceEvent

from .operational_trace import LocalOperationalTraceStore as _BaseOperationalTraceStore
from .store import (
    LocalExecutionStore as _BaseExecutionStore,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
)


class LocalExecutionStore(_BaseExecutionStore):
    """Local store with small atomic seams needed by production external intake."""

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        # Batch artifact writes call the existing put_bytes implementation while an
        # outer transaction is active. Keep the single-item implementation as the
        # source of truth and make only same-connection nesting transaction-aware.
        with self._lock:
            if self._connection.in_transaction:
                yield
                return
            with super()._write_transaction():
                yield

    @contextmanager
    def require_run_status(
        self,
        run_id: str,
        expected_status: RunStatus,
    ) -> Iterator[CapabilityRunRecord]:
        """Hold the execution DB write lock while a Run status condition is true."""
        with self._write_transaction():
            persisted = self.load_run(run_id)
            if persisted is None:
                raise ValueError(f"unknown Run {run_id}")
            if persisted.status is not expected_status:
                raise ValueError(
                    f"Run {run_id} must remain {expected_status.value} for this operation"
                )
            yield persisted

    def put_bytes_batch(
        self,
        run: CapabilityRunRecord,
        items: tuple[Mapping[str, Any], ...],
        *,
        expected_status: RunStatus | None = None,
        role_byte_limits: Mapping[str, int] | None = None,
        role_count_limits: Mapping[str, int] | None = None,
    ) -> tuple[ExecutionArtifactMetadata, ...]:
        """Atomically register a bounded set of artifacts using existing put_bytes semantics."""
        if not items:
            return ()

        normalized: list[dict[str, Any]] = []
        identities: list[str] = []
        for item in items:
            if not isinstance(item, Mapping):
                raise TypeError("artifact batch items must be mappings")
            content = item.get("content")
            if not isinstance(content, bytes):
                raise TypeError("artifact content must be bytes")
            if len(content) > self.config.max_artifact_bytes:
                raise LocalExecutionStoreError(
                    "artifact exceeds configured max_artifact_bytes"
                )
            role = str(item.get("role") or "")
            media_type = str(item.get("media_type") or "")
            if not role or not media_type:
                raise ValueError("artifact role and media_type are required")
            artifact_id = item.get("artifact_id")
            if artifact_id is not None:
                artifact_id = str(artifact_id)
                if not artifact_id:
                    raise ValueError("artifact_id must be non-empty when supplied")
                identities.append(artifact_id)
            provenance = item.get("provenance")
            if provenance is not None and not isinstance(provenance, Mapping):
                raise TypeError("artifact provenance must be a mapping")
            parent_refs = tuple(str(ref) for ref in item.get("parent_artifact_refs", ()))
            normalized.append(
                {
                    "role": role,
                    "media_type": media_type,
                    "content": content,
                    "artifact_id": artifact_id,
                    "provenance": dict(provenance or {}),
                    "parent_artifact_refs": parent_refs,
                }
            )
        if len(identities) != len(set(identities)):
            raise ValueError("artifact batch identities must be unique")

        byte_limits = {str(role): int(limit) for role, limit in (role_byte_limits or {}).items()}
        count_limits = {str(role): int(limit) for role, limit in (role_count_limits or {}).items()}
        if any(limit < 0 for limit in (*byte_limits.values(), *count_limits.values())):
            raise ValueError("artifact role limits must be non-negative")

        planned_counts = Counter(item["role"] for item in normalized)
        planned_bytes = Counter()
        for item in normalized:
            planned_bytes[item["role"]] += len(item["content"])

        with self._write_transaction():
            persisted = self.load_run(run.run_id)
            if persisted is None:
                raise LocalExecutionStoreError(
                    "artifact Run must already exist in the execution trace"
                )
            if (
                persisted.execution_mode != run.execution_mode
                or persisted.capability_id != run.capability_id
            ):
                raise LocalExecutionStoreIntegrityError(
                    "artifact Run binding does not match persisted Run"
                )
            if expected_status is not None and persisted.status is not expected_status:
                raise LocalExecutionStoreError(
                    f"artifact Run must remain {expected_status.value}"
                )

            existing = self.artifacts_for(run.run_id)
            existing_counts = Counter(item.role for item in existing)
            existing_bytes = Counter()
            for artifact in existing:
                existing_bytes[artifact.role] += artifact.size

            for role, limit in count_limits.items():
                if existing_counts[role] + planned_counts[role] > limit:
                    raise LocalExecutionStoreError(
                        f"artifact role count limit exceeded: {role}"
                    )
            for role, limit in byte_limits.items():
                if existing_bytes[role] + planned_bytes[role] > limit:
                    raise LocalExecutionStoreError(
                        f"artifact role byte limit exceeded: {role}"
                    )

            written = []
            for item in normalized:
                written.append(
                    self.put_bytes(
                        run,
                        role=item["role"],
                        media_type=item["media_type"],
                        content=item["content"],
                        artifact_id=item["artifact_id"],
                        provenance=item["provenance"],
                        parent_artifact_refs=item["parent_artifact_refs"],
                    )
                )
            return tuple(written)


class LocalOperationalTraceStore(_BaseOperationalTraceStore):
    """Operational trace store with an atomic Run-status-conditioned append."""

    def append_if_run_status(
        self,
        run_id: str,
        expected_status: RunStatus,
        event_type: str,
        occurred_at: str,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
    ) -> OperationalTraceEvent:
        guard = getattr(self._run_store, "require_run_status", None)
        if callable(guard):
            with guard(run_id, expected_status):
                return self.append(
                    run_id,
                    event_type,
                    occurred_at,
                    payload,
                    event_id=event_id,
                )

        persisted = self._run_store.load_run(run_id)
        if persisted is None or persisted.status is not expected_status:
            raise ValueError(
                f"Run {run_id} must remain {expected_status.value} for this operation"
            )
        return self.append(
            run_id,
            event_type,
            occurred_at,
            payload,
            event_id=event_id,
        )
