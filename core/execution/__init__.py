"""Canonical Research Capability execution boundary (PR22/23)."""

from .artifact_access import BoundedArtifactSink
from .models import (
    AuthorizationDecision, CapabilityExecutionError, CapabilityExecutionOutput,
    CapabilityExecutionRequest, CapabilityRunRecord, ExecutionArtifactMetadata,
    ExecutionFailureCode, ExecutionIssue, ExecutionResult, ExecutionStyle,
    PreparedExecution, ResourcePayload, RunLifecycleEvent, RunStatus,
)
from .registry import CapabilityRegistry
from .resource_access import BoundedResourceAccess
from .service import CapabilityExecutionService
from .validation import CanonicalCapabilityExecutionValidator

__all__ = [
    "AuthorizationDecision", "BoundedArtifactSink", "BoundedResourceAccess",
    "CanonicalCapabilityExecutionValidator", "CapabilityExecutionError",
    "CapabilityExecutionOutput", "CapabilityExecutionRequest",
    "CapabilityExecutionService", "CapabilityRegistry", "CapabilityRunRecord",
    "ExecutionArtifactMetadata", "ExecutionFailureCode", "ExecutionIssue",
    "ExecutionResult", "ExecutionStyle", "PreparedExecution", "ResourcePayload",
    "RunLifecycleEvent", "RunStatus",
]
