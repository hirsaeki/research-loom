from __future__ import annotations

from dataclasses import replace

from core.conversation import ConversationRuntimeError, CoordinatorResult
from core.conversation.service import WorkConversationService


class DecisionAwareResearchCoordinator(WorkConversationService):
    """PR26 operational authority extension for the PR10 Coordinator.

    DecisionRequirements remain owned by PR20/HumanDecisionService. This class
    only surfaces pending authority and prevents a new Research Capability from
    running while an exact Human Decision Request is unresolved.
    """

    def __init__(self, *args, human_decisions, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._human_decisions = human_decisions

    def _confirm(self, input_document):
        # Preserve PR10 single-use semantics even if the Research State has moved
        # after the first Confirmation was consumed. A replay is a replay, not a
        # new state-binding attempt.
        request_id = str(input_document["target"]["target_id"])
        request = self._store.load_confirmation_request(request_id)
        if request is not None:
            pending_ids = {
                str(item.get("confirmation_request_id"))
                for item in self._store.list_pending(str(request["conversation_id"]))
                if item.get("message_type") == "confirmation_request"
            }
            if request_id not in pending_ids:
                raise ConversationRuntimeError(
                    "CONV-CONFIRMATION-REPLAY-001",
                    "Confirmation Request was already consumed or cancelled",
                )
        return super()._confirm(input_document)

    def _execute(self, source_input, proposal, state, confirmation_receipt):
        route = proposal.get("route", {})
        if route.get("route_type") == "capability_invocation":
            pending = self._human_decisions.pending(str(proposal["project_id"]))
            if pending:
                receipt = self._rejection_receipt(
                    source_input,
                    proposal,
                    state,
                    "CONV-HUMAN-DECISION-PENDING-001",
                    confirmation_receipt,
                )
                return CoordinatorResult(
                    "DECISION_PENDING",
                    source_input,
                    proposal=proposal,
                    action_receipt=receipt,
                    data={
                        "pending_human_decision_request_ids": [
                            str(item["request_id"]) for item in pending
                        ]
                    },
                    issues=({
                        "code": "CONV-HUMAN-DECISION-PENDING-001",
                        "message": "a Human Decision Request is pending before the next Research Capability may execute",
                    },),
                )

        result = super()._execute(source_input, proposal, state, confirmation_receipt)
        decision_request = result.data.get("decision_request") if result.data else None
        if result.data.get("decision_required") is True and decision_request is not None:
            return replace(result, decision_request=decision_request)
        return result
