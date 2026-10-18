"""Execution store errors, configuration, records and encoding helpers (#494)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import rfc8785

from core.execution.models import (
    ExecutionIssue,
    RunStatus,
)
from core.runtime.digests import jcs_digest

_MIGRATION_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_ALLOWED_TRANSITIONS = {
    RunStatus.PREPARED: {
        RunStatus.RUNNING,
        RunStatus.ABORTED,
        RunStatus.SUPERSEDED,
    },
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.ABORTED,
        RunStatus.SUPERSEDED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.ABORTED: set(),
    RunStatus.SUPERSEDED: set(),
}
_DOCUMENT_DIGEST_FIELDS = {
    "descriptor": "descriptor_digest",
    "invocation": "invocation_digest",
    "context_pack": "context_pack_digest",
    "handoff": "handoff_digest",
}
_RUN_IMMUTABLE_FIELDS = (
    "run_id",
    "invocation_id",
    "invocation_digest",
    "capability_id",
    "capability_version",
    "descriptor_digest",
    "implementation_id",
    "implementation_version",
    "function_id",
    "execution_mode",
    "context_pack_id",
    "context_pack_digest",
    "project_ref",
    "lineage_ref",
    "snapshot_ref",
    "snapshot_digest",
    "attempt",
    "parent_run_id",
    "prepared_at",
    "provenance",
)


class LocalExecutionStoreError(RuntimeError):
    """Base error for local execution persistence failures."""


class LocalExecutionStoreIntegrityError(LocalExecutionStoreError):
    """Raised when persisted execution bytes or metadata fail verification."""


@dataclass(frozen=True)
class LocalExecutionStoreConfig:
    max_artifact_bytes: int = 64 * 1024 * 1024
    max_run_output_bytes: int = 256 * 1024 * 1024
    max_resource_bytes: int = 256 * 1024 * 1024
    busy_timeout_ms: int = 5_000
    journal_mode: str = "DELETE"
    synchronous: str = "FULL"


@dataclass(frozen=True)
class RegisteredResource:
    reference_id: str
    media_type: str | None
    size: int
    digest: str
    storage_locator: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class StoreIntegrityDiagnostic:
    code: str
    message: str
    run_id: str | None = None
    artifact_id: str | None = None
    reference_id: str | None = None


def _canonical_json(value: Any) -> str:
    return rfc8785.dumps(value).decode("utf-8")


def _payload_sha256(value: Mapping[str, Any]) -> str:
    return jcs_digest(dict(value))


def _failure_json(issue: ExecutionIssue | None) -> str | None:
    if issue is None:
        return None
    return _canonical_json(asdict(issue))
