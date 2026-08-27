from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from core.runtime.transition_models import StateView

from .models import ActionDefinition, ActionDraft, CapabilityMaterialization, HarnessServiceResult


class ConversationActionResolver(Protocol):
    def resolve(
        self,
        conversation_input: Mapping[str, Any],
        bounded_state_summary: Mapping[str, Any],
        registered_actions: Sequence[ActionDefinition],
    ) -> ActionDraft | None:
        ...


class ConversationStore(Protocol):
    def store_input(self, document: Mapping[str, Any]) -> None: ...
    def store_proposal(self, document: Mapping[str, Any]) -> None: ...
    def load_proposal(self, proposal_id: str) -> Mapping[str, Any] | None: ...
    def store_confirmation_request(self, document: Mapping[str, Any]) -> None: ...
    def load_confirmation_request(self, request_id: str) -> Mapping[str, Any] | None: ...
    def consume_confirmation_request(
        self,
        request_id: str,
        request_digest: str,
        receipt: Mapping[str, Any],
    ) -> bool: ...
    def cancel_pending(self, target_type: str, target_id: str) -> bool: ...
    def store_action_receipt(self, document: Mapping[str, Any]) -> None: ...
    def store_candidate_presentation(self, document: Mapping[str, Any]) -> None: ...
    def store_materialization(self, proposal_id: str, payload: Mapping[str, Any]) -> None: ...
    def load_materialization(self, proposal_id: str) -> Mapping[str, Any] | None: ...
    def store_state_delta_proposal(self, proposal_id: str, payload: Mapping[str, Any]) -> None: ...
    def store_run_correlation(self, run_id: str, proposal_id: str, input_id: str) -> None: ...
    def load_run_correlation(self, run_id: str) -> Mapping[str, Any] | None: ...
    def load_state_delta_proposal(self, proposal_id: str) -> Mapping[str, Any] | None: ...
    def list_pending(self, conversation_id: str) -> tuple[Mapping[str, Any], ...]: ...


class IdProvider(Protocol):
    def new(self, prefix: str) -> str: ...


class CapabilityActionMaterializer(Protocol):
    materializer_id: str

    def materialize(
        self,
        proposal_payload: Mapping[str, Any],
        state: StateView,
        descriptor: Mapping[str, Any],
        *,
        context_pack_id: str,
    ) -> CapabilityMaterialization:
        ...


class RuntimeAuthorizationEvidenceProvider(Protocol):
    def evidence_for(
        self,
        proposal: Mapping[str, Any],
        materialization: CapabilityMaterialization,
        *,
        invocation_id: str,
        run_id: str,
    ) -> Mapping[str, Any]:
        ...


class HarnessServiceHandler(Protocol):
    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        state: StateView,
        actor: Mapping[str, Any],
        proposal: Mapping[str, Any],
    ) -> HarnessServiceResult:
        ...
