from __future__ import annotations

from typing import Any, Mapping, Protocol

from core.runtime.transition_models import StateView

from .models import (
    AuthorizationDecision,
    CapabilityExecutionOutput,
    CapabilityExecutionRequest,
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ExecutionStyle,
    ResourcePayload,
    RunLifecycleEvent,
    RunStatus,
)


class CapabilityAdapter(Protocol):
    implementation_id: str
    implementation_version: str
    capability_id: str
    capability_version: str
    supported_functions: tuple[str, ...]
    supported_execution_modes: tuple[str, ...]
    execution_style: ExecutionStyle

    def execute(
        self,
        request: CapabilityExecutionRequest,
    ) -> CapabilityExecutionOutput:
        ...

    def cancel(self, run_id: str) -> None:
        ...


class RuntimeAuthorizationProvider(Protocol):
    def validate(
        self,
        evidence: Mapping[str, Any],
        *,
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        now: str,
    ) -> AuthorizationDecision:
        ...


class StateViewProvider(Protocol):
    def load_state_view(self, project_ref: str, lineage_ref: str) -> StateView:
        ...


class ResourceProvider(Protocol):
    def load(self, resource: Mapping[str, Any]) -> ResourcePayload:
        ...


class ExecutionArtifactStore(Protocol):
    """Trusted byte store used behind a run-bound capability-facing sink."""

    def put_bytes(
        self,
        run: CapabilityRunRecord,
        *,
        role: str,
        media_type: str,
        content: bytes,
        artifact_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        parent_artifact_refs: tuple[str, ...] = (),
    ) -> ExecutionArtifactMetadata:
        ...


class RuntimeClock(Protocol):
    def now(self) -> str:
        ...


class ExecutionTraceStore(Protocol):
    """Non-authoritative immutable execution history and atomic Run lifecycle port."""

    def create_run(self, run: CapabilityRunRecord) -> None:
        ...

    def load_run(self, run_id: str) -> CapabilityRunRecord | None:
        ...

    def append_run_event(self, event: RunLifecycleEvent) -> None:
        ...

    def transition_run(
        self,
        expected_status: RunStatus,
        updated_run: CapabilityRunRecord,
        event: RunLifecycleEvent,
    ) -> bool:
        """Atomically update Run and append event iff persisted status matches."""
        ...

    def store_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        ...

    def store_invocation(self, invocation: Mapping[str, Any]) -> None:
        ...

    def store_context_pack(self, context_pack: Mapping[str, Any]) -> None:
        ...

    def store_handoff(self, handoff: Mapping[str, Any]) -> None:
        ...

    def store_result_extension(
        self,
        run_id: str,
        extension: Mapping[str, Any],
    ) -> str:
        ...

    def register_output_artifact(
        self,
        artifact: ExecutionArtifactMetadata,
    ) -> None:
        ...

    def load_invocation(
        self,
        invocation_id: str,
    ) -> Mapping[str, Any] | None:
        ...

    def load_context_pack(
        self,
        context_pack_id: str,
    ) -> Mapping[str, Any] | None:
        ...

    def load_descriptor(
        self,
        descriptor_digest: str,
    ) -> Mapping[str, Any] | None:
        ...

    def store_diagnostic(
        self,
        run_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        ...
