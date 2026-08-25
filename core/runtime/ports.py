from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .transition_models import (
    CommitBundle,
    CommitReceipt,
    ReductionResult,
    StateDeltaProposal,
    StateTransitionRequest,
    StateView,
    ValidationIssue,
)


class RepositoryError(RuntimeError):
    """Base error for persistence-port failures."""


class StaleHeadError(RepositoryError):
    pass


class IdempotencyConflictError(RepositoryError):
    pass


class AtomicCommitError(RepositoryError):
    pass


class ResearchStateRepository(Protocol):
    """Storage-neutral repository boundary.

    Concrete adapters are responsible for transactions, locking and physical
    storage. The reducer never depends on an adapter implementation.
    """

    def load_state_view(self, project_ref: str, lineage_ref: str) -> StateView:
        ...

    def load_snapshot(self, snapshot_ref: str) -> Mapping[str, Any] | None:
        ...

    def load_object_revision(self, kind: str, object_id: str, revision: int) -> Mapping[str, Any] | None:
        ...

    def resolve_refs(self, refs: Sequence[tuple[str, str]]) -> Mapping[tuple[str, str], bool]:
        ...

    def find_commit_by_idempotency_key(self, idempotency_key: str) -> tuple[str, CommitReceipt] | None:
        """Return (request_digest, receipt) for a prior committed request."""
        ...

    def commit(self, bundle: CommitBundle, *, expected_head_snapshot_digest: str) -> CommitReceipt:
        """Atomically persist the whole bundle or persist none of it."""
        ...


class StatePolicyValidator(Protocol):
    """Extension point for resolved Profile/Project/method adoption policy.

    Implementations inspect canonical state semantics. They must not write
    authoritative state and must return deterministic issues for deterministic
    inputs.
    """

    def validate(
        self,
        current_state: StateView,
        request: StateTransitionRequest,
        reduction: ReductionResult,
    ) -> tuple[ValidationIssue, ...]:
        ...


class CapabilityResultNormalizer(Protocol):
    """Capability-specific validation/normalization port.

    The State Reducer depends only on StateDeltaProposal and typed transitions;
    it never dispatches on capability IDs or imports concrete capability code.
    """

    def supports(self, capability_contract_id: str, function_id: str, contract_version: str) -> bool:
        ...

    def validate_extension(
        self,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> tuple[str, ...]:
        ...

    def normalize(
        self,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> StateDeltaProposal:
        ...


class StateSchemaValidator(Protocol):
    """Canonical object-schema validation used before and after reduction."""

    def validate_request(self, request: StateTransitionRequest) -> tuple[ValidationIssue, ...]:
        ...

    def validate_reduction(self, reduction: ReductionResult) -> tuple[ValidationIssue, ...]:
        ...
