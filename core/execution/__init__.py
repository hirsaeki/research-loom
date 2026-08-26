"""Canonical Research Capability execution boundary (PR22/23/24)."""

from .artifact_access import BoundedArtifactSink
from .context_extensions import (
    CapabilityContextExtensionRegistry,
    CapabilityContextExtensionStore,
    CapabilityContextExtensionValidator,
)
from .models import (
    AuthorizationDecision, CapabilityExecutionError, CapabilityExecutionOutput,
    CapabilityExecutionRequest, CapabilityRunRecord, ExecutionArtifactMetadata,
    ExecutionFailureCode, ExecutionIssue, ExecutionResult, ExecutionStyle,
    PreparedExecution, ResourcePayload, RunLifecycleEvent, RunStatus,
)
from .operational_trace import OperationalTraceEvent, OperationalTraceStore
from .registry import CapabilityRegistry
from .resource_access import BoundedResourceAccess
from .context_service import CapabilityExecutionService
from .validation import CanonicalCapabilityExecutionValidator

__all__ = [
    "AuthorizationDecision", "BoundedArtifactSink", "BoundedResourceAccess",
    "CanonicalCapabilityExecutionValidator", "CapabilityContextExtensionRegistry",
    "CapabilityContextExtensionStore", "CapabilityContextExtensionValidator",
    "CapabilityExecutionError", "CapabilityExecutionOutput",
    "CapabilityExecutionRequest", "CapabilityExecutionService", "CapabilityRegistry",
    "CapabilityRunRecord", "ExecutionArtifactMetadata", "ExecutionFailureCode",
    "ExecutionIssue", "ExecutionResult", "ExecutionStyle", "OperationalTraceEvent",
    "OperationalTraceStore", "PreparedExecution", "ResourcePayload",
    "RunLifecycleEvent", "RunStatus",
]
