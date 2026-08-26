from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping


class RunStatus(str, Enum):
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    SUPERSEDED = "SUPERSEDED"


class ExecutionStyle(str, Enum):
    MANAGED = "managed"
    EXTERNAL = "external"


class ExecutionFailureCode(str, Enum):
    DESCRIPTOR_INVALID = "DESCRIPTOR_INVALID"
    INVOCATION_INVALID = "INVOCATION_INVALID"
    CONTEXT_INVALID = "CONTEXT_INVALID"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    IMPLEMENTATION_NOT_FOUND = "IMPLEMENTATION_NOT_FOUND"
    IMPLEMENTATION_AMBIGUOUS = "IMPLEMENTATION_AMBIGUOUS"
    RESOURCE_DENIED = "RESOURCE_DENIED"
    RESOURCE_INTEGRITY = "RESOURCE_INTEGRITY"
    ARTIFACT_STORE_ERROR = "ARTIFACT_STORE_ERROR"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    HANDOFF_INVALID = "HANDOFF_INVALID"
    HANDOFF_REJECTED = "HANDOFF_REJECTED"
    NORMALIZATION_REJECTED = "NORMALIZATION_REJECTED"
    RUN_ABORTED = "RUN_ABORTED"
    STALE_STATE = "STALE_STATE"


@dataclass(frozen=True)
class ExecutionIssue:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class CapabilityRunRecord:
    run_id: str
    invocation_id: str
    invocation_digest: str
    capability_id: str
    capability_version: str
    descriptor_digest: str
    implementation_id: str
    implementation_version: str
    function_id: str
    execution_mode: str
    context_pack_id: str
    context_pack_digest: str
    project_ref: str
    lineage_ref: str
    snapshot_ref: str
    snapshot_digest: str
    attempt: int
    parent_run_id: str | None
    status: RunStatus
    prepared_at: str
    started_at: str | None = None
    completed_at: str | None = None
    handoff_ref: str | None = None
    handoff_digest: str | None = None
    failure: ExecutionIssue | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def with_status(self, status: RunStatus, **changes: Any) -> "CapabilityRunRecord":
        return replace(self, status=status, **changes)


@dataclass(frozen=True)
class RunLifecycleEvent:
    run_id: str
    sequence: int
    from_status: RunStatus | None
    to_status: RunStatus
    occurred_at: str
    reason: str


@dataclass(frozen=True)
class ExecutionArtifactMetadata:
    artifact_id: str
    run_id: str
    role: str
    media_type: str
    size: int
    digest: str
    storage_locator: str
    execution_mode: str
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourcePayload:
    reference_id: str
    content: bytes
    digest: str | None = None
    media_type: str | None = None


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    resource_reference_ids: tuple[str, ...] = ()
    issues: tuple[ExecutionIssue, ...] = ()


@dataclass(frozen=True)
class CapabilityExecutionRequest:
    run: CapabilityRunRecord
    descriptor: Mapping[str, Any]
    invocation: Mapping[str, Any]
    context_pack: Mapping[str, Any]
    resources: Any
    artifacts: Any = None

    def __post_init__(self) -> None:
        if self.artifacts is None:
            from .artifact_access import BoundedArtifactSink

            object.__setattr__(
                self,
                "artifacts",
                BoundedArtifactSink(
                    self.run,
                    getattr(self.resources, "artifact_store", None),
                ),
            )


@dataclass(frozen=True)
class CapabilityExecutionOutput:
    handoff: Mapping[str, Any]
    extension: Mapping[str, Any] | None = None
    artifacts: tuple[ExecutionArtifactMetadata, ...] = ()


@dataclass(frozen=True)
class PreparedExecution:
    run: CapabilityRunRecord
    invocation_digest: str
    context_pack_digest: str


@dataclass(frozen=True)
class ExecutionResult:
    run: CapabilityRunRecord
    handoff_ref: str | None
    handoff_status: str | None
    extension_ref: str | None
    state_delta_proposal: Any | None
    issues: tuple[ExecutionIssue, ...] = ()


class CapabilityExecutionError(RuntimeError):
    def __init__(self, code: str | ExecutionFailureCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.issue = ExecutionIssue(str(code.value if isinstance(code, ExecutionFailureCode) else code), message, retryable)
