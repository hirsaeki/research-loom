"""Canonical storage-neutral Research State runtime boundary (PR20)."""

from .normalization import CapabilityNormalizationBoundary, NormalizationRejected
from .schema_validation import CanonicalResearchObjectSchemaValidator
from .state_reducer import ReductionError, reduce_state
from .state_transition import StateTransitionService
from .transition_models import (
    Actor,
    CommitBundle,
    CommitReceipt,
    LineageView,
    ObjectRef,
    StateDeltaProposal,
    StateTransitionRejected,
    StateTransitionRequest,
    StateView,
    TransitionAction,
    TransitionKind,
    ValidationIssue,
    ValidationStage,
    canonical_digest,
)

__all__ = [
    "Actor",
    "CanonicalResearchObjectSchemaValidator",
    "CapabilityNormalizationBoundary",
    "CommitBundle",
    "CommitReceipt",
    "LineageView",
    "NormalizationRejected",
    "ObjectRef",
    "ReductionError",
    "StateDeltaProposal",
    "StateTransitionRejected",
    "StateTransitionRequest",
    "StateTransitionService",
    "StateView",
    "TransitionAction",
    "TransitionKind",
    "ValidationIssue",
    "ValidationStage",
    "canonical_digest",
    "reduce_state",
]
