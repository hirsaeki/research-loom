from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class ConversationRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ActionDraft:
    """Candidate-only resolver output. It never carries execution authority."""

    action_type: str
    payload: Mapping[str, Any]
    rationale: str | None = None


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    payload_contract: str
    effect: str
    route_kind: str
    confirmation_required: bool
    human_decision_required: bool = False
    service_id: str | None = None
    capability_id: str | None = None
    capability_version: str | None = None
    function_id: str | None = None
    execution_mode: str | None = None
    materializer_id: str | None = None
    execution_style: str = "external"
    payload_validator: Any | None = None


@dataclass(frozen=True)
class CapabilityMaterialization:
    descriptor: Mapping[str, Any]
    context_pack: Mapping[str, Any]
    context_extension: Mapping[str, Any] | None
    lineage_ref: str
    execution_mode: str


@dataclass(frozen=True)
class HarnessServiceResult:
    result_reference: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    state_transition_request: Any | None = None
    research_state_mutation_performed: bool = False


@dataclass(frozen=True)
class CoordinatorResult:
    status: str
    input_document: Mapping[str, Any]
    proposal: Mapping[str, Any] | None = None
    confirmation_request: Mapping[str, Any] | None = None
    confirmation_receipt: Mapping[str, Any] | None = None
    decision_request: Mapping[str, Any] | None = None
    action_receipt: Mapping[str, Any] | None = None
    prepared_execution: Any | None = None
    execution_result: Any | None = None
    presentations: tuple[Mapping[str, Any], ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[Mapping[str, Any], ...] = ()
