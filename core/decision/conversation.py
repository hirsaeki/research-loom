from __future__ import annotations

from dataclasses import replace

from core.conversation import ConversationRuntimeError, CoordinatorResult
from core.conversation.service import WorkConversationService


class DecisionAwareResearchCoordinator(WorkConversationService):
    """PR26 operational authority extension for the PR10 Coordinator.

    DecisionRequirements remain owned by PR20/HumanDecisionService. This class
    surfaces pending authority and prevents duplicate application of the exact
    candidate already governed by an unresolved Human Decision Request. Pending
    authority does not block unrelated candidate-only research or operational
    lifecycle work.
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
            proposal = self._store.load_proposal(
                str(request["proposal_binding"]["proposal_id"])
            )
            if proposal is None:
                raise ConversationRuntimeError(
                    "CONV-CONFIRMATION-BINDING-001",
                    "bound Action Proposal is missing",
                )
            if (
                str(input_document.get("project_id")) != str(request.get("project_id"))
                or str(input_document.get("conversation_id"))
                != str(request.get("conversation_id"))
                or str(proposal.get("project_id")) != str(request.get("project_id"))
                or str(proposal.get("conversation_id"))
                != str(request.get("conversation_id"))
                or str(proposal.get("proposal_digest"))
                != str(request["proposal_binding"].get("proposal_digest"))
            ):
                raise ConversationRuntimeError(
                    "CONV-CONFIRMATION-BINDING-001",
                    "Confirmation Request project/conversation/proposal binding mismatch",
                )
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
        action = proposal.get("action", {})
        pending = self._human_decisions.pending(str(proposal["project_id"]))
        candidate_id = None
        candidate_digest = None
        if action.get("action_type") == "state.apply_candidate":
            candidate_id = action.get("payload", {}).get("state_delta_proposal_id")
            candidate = self._store.load_state_delta_proposal(str(candidate_id)) if candidate_id else None
            if candidate is not None:
                candidate_digest = candidate.get("proposal_digest")
        matching_pending = tuple(
            item
            for item in pending
            if candidate_id is not None
            and candidate_digest is not None
            and str(item.get("source_state_delta_proposal", {}).get("proposal_id"))
            == str(candidate_id)
            and str(item.get("source_state_delta_proposal", {}).get("proposal_digest"))
            == str(candidate_digest)
        )
        if matching_pending:
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
                        str(item["request_id"]) for item in matching_pending
                    ]
                },
                issues=({
                    "code": "CONV-HUMAN-DECISION-PENDING-001",
                    "message": "the exact candidate is already governed by a pending Human Decision Request",
                },),
            )

        result = super()._execute(source_input, proposal, state, confirmation_receipt)
        decision_request = result.data.get("decision_request") if result.data else None
        if result.data.get("decision_required") is True and decision_request is not None:
            return replace(result, decision_request=decision_request)
        return result
