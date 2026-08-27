"""Production Work Conversation / Research Coordinator application boundary (PR25)."""

from .models import (
    ActionDefinition,
    ActionDraft,
    CapabilityMaterialization,
    ConversationRuntimeError,
    CoordinatorResult,
    HarnessServiceResult,
)
from .registry import (
    ActionRegistry,
    CapabilityActionMaterializerRegistry,
    CapabilityDescriptorRegistry,
    HarnessServiceRegistry,
)
from .service import ResearchCoordinator, WorkConversationService
from .validation import WorkConversationValidator, canonical_digest, with_document_digest

__all__ = [
    "ActionDefinition", "ActionDraft", "ActionRegistry",
    "CapabilityActionMaterializerRegistry", "CapabilityDescriptorRegistry",
    "CapabilityMaterialization", "ConversationRuntimeError", "CoordinatorResult",
    "HarnessServiceRegistry", "HarnessServiceResult", "ResearchCoordinator",
    "WorkConversationService", "WorkConversationValidator", "canonical_digest",
    "with_document_digest",
]
