from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from misco_harness.models import (
    ActionReceipt,
    ChatInputClassification,
    ChatStatusView,
    ChatTurnInput,
    ConfirmationRequest,
    ConfirmedAction,
    ConversationActionType,
    ConversationTurnResult,
    HumanAttentionRequired,
    ProposedAction,
    RecoveryRequest,
    utc_now,
)
from misco_harness.orchestrator import DiscoveryOrchestrator
from misco_harness.recovery import RecoveryService
from misco_harness.trace_store import TraceStore, sha256_file


class ConversationError(RuntimeError):
    pass


_CONFIRMATION_ACTIONS = {
    ConversationActionType.RECORD_DECISION,
    ConversationActionType.SUBMIT_WORK_RESULT,
    ConversationActionType.STOP_AT_BOUNDARY,
    ConversationActionType.ABORT_PENDING_RUN,
    ConversationActionType.REQUEST_RECOVERY,
    ConversationActionType.CONFIRM_RECOVERY,
    ConversationActionType.CANCEL_PENDING_ACTION,
    ConversationActionType.REGISTER_ATTENTION_DROP,
    ConversationActionType.ARCHIVE_RESEARCH,
}
_READ_ONLY_ACTIONS = {
    ConversationActionType.SHOW_STATUS,
    ConversationActionType.SHOW_DECISION,
    ConversationActionType.PROPOSE_DECISION,
}


class WorkConversationCoordinator:
    """Backend-neutral Work-chat boundary over the Harness services.

    No chat prose is persisted as Evidence and no natural-language branch
    receives mutable-state authority. Callers must submit a typed action and
    confirm it against the current state binding before mutation.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.runtime = self.workspace / ".rh"
        self.store = TraceStore(self.runtime)
        self.orchestrator = DiscoveryOrchestrator(self.workspace)
        self.recovery = RecoveryService(self.workspace)

    def status(self) -> ChatStatusView:
        state_path = self.runtime / "state" / "orchestrator" / "head.json"
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state_id = str(state.get("state_id", "uninitialized"))
            state_hash = sha256_file(state_path)
        else:
            state = {"phase": "UNINITIALIZED", "execution_state": "READY", "worker_backend": None}
            state_id, state_hash = "uninitialized", None
        research = self._json_if_exists("state/research/head.json") or {}
        pending_work = state.get("pending_work") or {}
        actions: list[ProposedAction] = []
        for action, effect, fixes, automatic, needs_confirmation in self._allowed_actions(state):
            actions.append(ProposedAction(
                action_id=f"status-{action.value.lower()}", turn_id="status", actor="HARNESS",
                action=action, effect=effect, becomes_fixed=fixes,
                does_not_happen_automatically=automatic, requires_confirmation=needs_confirmation,
                expected_state_id=state_id, expected_state_sha256=state_hash,
            ))
        attention: list[HumanAttentionRequired] = []
        if state.get("pending_decision_ids"):
            attention.append(HumanAttentionRequired(
                reason="A Human research decision is pending; Work cannot choose it.",
                references=list(state["pending_decision_ids"]),
                allowed_actions=[ConversationActionType.SHOW_DECISION, ConversationActionType.RECORD_DECISION],
            ))
        if pending_work:
            attention.append(HumanAttentionRequired(
                reason="A bounded Work result is pending; late or duplicate submissions are rejected.",
                references=[str(pending_work.get("run_id"))],
                allowed_actions=[ConversationActionType.SUBMIT_WORK_RESULT, ConversationActionType.ABORT_PENDING_RUN],
            ))
        return ChatStatusView(
            lane="RESEARCH", phase=str(state.get("phase", "UNINITIALIZED")),
            execution_state=str(state.get("execution_state", "READY")), state_id=state_id,
            lifecycle_status=str(state.get("lifecycle_status", "ACTIVE")),
            state_sha256=state_hash, pending_work_run_id=pending_work.get("run_id"),
            pending_decision_ids=list(state.get("pending_decision_ids", [])),
            active_attention_map_id=state.get("active_attention_map_id"),
            pending_attention_drop_ids=list(state.get("pending_attention_drop_ids", [])),
            evidence_summary={
                "evidence": len(research.get("evidence", [])),
                "counterevidence": len(research.get("counterevidence", [])),
                "unknowns": len(research.get("unknowns", [])),
                "evidence_gaps": len(research.get("evidence_gaps", [])),
            }, allowed_actions=actions, human_attention=attention,
            trace_references=["state/orchestrator/head.json", "state/research/head.json"],
        )

    def classify(self, turn: ChatTurnInput) -> ChatInputClassification:
        if turn.classification is not None:
            return turn.classification
        if turn.action is not None:
            return ChatInputClassification.COMMITTABLE_ACTION
        lowered = turn.text.strip().lower()
        if lowered.startswith(("confirm ", "確認 ", "cancel ", "取消 ")):
            return ChatInputClassification.CONFIRMATION if lowered.startswith(("confirm ", "確認 ")) else ChatInputClassification.CANCEL
        if lowered.endswith(("?", "？")):
            return ChatInputClassification.QUERY
        return ChatInputClassification.PROPOSAL

    def propose(self, turn: ChatTurnInput) -> ConversationTurnResult:
        classification = self.classify(turn)
        view = self.status()
        if classification in {ChatInputClassification.QUERY, ChatInputClassification.PROPOSAL}:
            return ConversationTurnResult(classification=classification, status_view=view, attention=view.human_attention)
        if classification == ChatInputClassification.CONFIRMATION:
            confirmation_id = str(turn.parameters.get("confirmation_id", ""))
            return self.confirm(confirmation_id, actor=turn.actor)
        if classification == ChatInputClassification.CANCEL:
            action = ConversationActionType.CANCEL_PENDING_ACTION
            turn = turn.model_copy(update={"action": action, "parameters": {**turn.parameters, "target": turn.parameters.get("target") or turn.text}})
        if turn.action is None:
            return self._rejected(view, "UNKNOWN", turn.actor, "A typed action is required; chat text cannot mutate Harness state.")
        return self.propose_action(turn.action, actor=turn.actor, turn_id=turn.turn_id, parameters=turn.parameters)

    def propose_action(
        self,
        action: ConversationActionType | str,
        *,
        actor: str,
        turn_id: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> ConversationTurnResult:
        view = self.status()
        try:
            typed = action if isinstance(action, ConversationActionType) else ConversationActionType(action)
        except ValueError:
            return self._rejected(view, str(action), actor, "Unknown action; allow-list resolution failed closed.")
        if typed not in {*_CONFIRMATION_ACTIONS, *_READ_ONLY_ACTIONS}:
            return self._rejected(view, typed.value, actor, "Action is not allowed by the Conversation Contract.")
        params = parameters or {}
        proposal = ProposedAction(
            action_id=self._id("action"), turn_id=turn_id or self._id("turn"), actor=actor,
            action=typed, parameters=params,
            effect=self._effect(typed), becomes_fixed=self._fixes(typed),
            does_not_happen_automatically=self._automatic_limits(typed),
            requires_confirmation=typed in _CONFIRMATION_ACTIONS,
            expected_state_id=view.state_id, expected_state_sha256=view.state_sha256,
        )
        self.store.write_immutable(Path("conversation") / "proposals" / f"{proposal.action_id}.json", proposal)
        if typed in _READ_ONLY_ACTIONS:
            return ConversationTurnResult(
                classification=ChatInputClassification.QUERY if typed == ConversationActionType.SHOW_STATUS else ChatInputClassification.PROPOSAL,
                status_view=self.status(), proposal=proposal,
            )
        confirmation = ConfirmationRequest(
            confirmation_id=self._id("confirmation"), action_id=proposal.action_id, actor=actor,
            action=typed, exact_effect=proposal.effect, becomes_fixed=proposal.becomes_fixed,
            does_not_happen_automatically=proposal.does_not_happen_automatically,
            expected_state_id=proposal.expected_state_id, expected_state_sha256=proposal.expected_state_sha256,
            token_sha256=hashlib.sha256(proposal.action_id.encode("utf-8")).hexdigest(),
            expires_at=utc_now() + timedelta(minutes=15),
        )
        self.store.write_immutable(Path("conversation") / "confirmations" / f"{confirmation.confirmation_id}.json", confirmation)
        return ConversationTurnResult(
            classification=ChatInputClassification.COMMITTABLE_ACTION, status_view=self.status(),
            proposal=proposal, confirmation_request=confirmation,
        )

    def confirm(self, confirmation_id: str, *, actor: str) -> ConversationTurnResult:
        view = self.status()
        path = self.runtime / "conversation" / "confirmations" / f"{confirmation_id}.json"
        if not path.is_file():
            return self._rejected(view, "CONFIRMATION", actor, "Confirmation is missing or unknown.")
        request = ConfirmationRequest.model_validate_json(path.read_text(encoding="utf-8"))
        if actor != request.actor:
            return self._rejected(view, request.action.value, actor, "Confirmation actor does not match the bound actor", confirmation_id=confirmation_id)
        if utc_now() >= request.expires_at:
            return self._rejected(view, request.action.value, actor, "Confirmation has expired", confirmation_id=confirmation_id)
        if (self.runtime / "conversation" / "confirmations" / f"{confirmation_id}.used.json").exists():
            return self._rejected(view, request.action.value, actor, "Confirmation is single-use and was already consumed", confirmation_id=confirmation_id)
        if view.state_id != request.expected_state_id or view.state_sha256 != request.expected_state_sha256:
            return self._rejected(view, request.action.value, actor, "Confirmation is stale or state-mismatched; no mutation was performed", confirmation_id=confirmation_id)
        confirmed = ConfirmedAction(confirmation_id=confirmation_id, action_id=request.action_id, actor=actor, action=request.action)
        self.store.write_immutable(Path("conversation") / "confirmations" / f"{confirmation_id}.used.json", confirmed)
        try:
            self._dispatch(request.action, request= self._proposal_parameters(request.action_id), actor=actor, confirmation_id=confirmation_id)
        except Exception as error:  # noqa: BLE001 - every state-changing attempt receives a receipt.
            receipt = self._receipt(request.action.value, actor, "REJECTED", f"{type(error).__name__}: {error}", confirmation_id, view)
            return ConversationTurnResult(classification=ChatInputClassification.CONFIRMATION, status_view=self.status(), confirmed_action=confirmed, receipt=receipt)
        after = self.status()
        receipt = self._receipt(request.action.value, actor, "ACCEPTED", "Typed action accepted and audited.", confirmation_id, view, after)
        return ConversationTurnResult(classification=ChatInputClassification.CONFIRMATION, status_view=after, confirmed_action=confirmed, receipt=receipt)

    def _dispatch(self, action: ConversationActionType, *, request: dict[str, Any], actor: str, confirmation_id: str) -> None:
        if action == ConversationActionType.RECORD_DECISION:
            self.orchestrator.record_decision(str(request["decision_id"]), choice=str(request["choice"]), decided_by=actor, conditions=list(request.get("conditions", [])), rationale=request.get("rationale"))
        elif action == ConversationActionType.SUBMIT_WORK_RESULT:
            self.orchestrator.collect_work_result(str(request["run_id"]), Path(str(request["result_path"])), run_limit=1)
        elif action == ConversationActionType.ABORT_PENDING_RUN:
            self.recovery.abort_pending_run(str(request["run_id"]), reason=str(request.get("reason", "Human requested operational abort")), actor=actor, confirmation_id=confirmation_id, replacement=bool(request.get("replacement", True)))
        elif action == ConversationActionType.REQUEST_RECOVERY:
            payload = dict(request.get("recovery_request", request))
            self.recovery.request(RecoveryRequest.model_validate(payload))
        elif action == ConversationActionType.CONFIRM_RECOVERY:
            recovery_id = str(request["recovery_id"])
            self.recovery.approve(recovery_id, decided_by=actor, decision_treatments=dict(request.get("decision_treatments", {})), rationale=request.get("rationale"))
        elif action == ConversationActionType.CANCEL_PENDING_ACTION:
            self.store.write_immutable(Path("conversation") / "cancellations" / f"{self._id('cancel')}.json", {"actor": actor, "target": request.get("target"), "confirmation_id": confirmation_id, "created_at": utc_now().isoformat()})
        elif action == ConversationActionType.STOP_AT_BOUNDARY:
            self.store.write_immutable(Path("conversation") / "boundaries" / f"{self._id('boundary')}.json", {"actor": actor, "reason": request.get("reason", "Human requested boundary stop"), "confirmation_id": confirmation_id, "created_at": utc_now().isoformat()})
        elif action == ConversationActionType.REGISTER_ATTENTION_DROP:
            self.orchestrator.register_attention_drop(Path(str(request["path"])), registered_by=actor)
        elif action == ConversationActionType.ARCHIVE_RESEARCH:
            self.orchestrator.archive(
                Path(str(request["destination"])),
                created_by=actor,
                reason=str(request["reason"]),
                allow_incomplete=bool(request.get("allow_incomplete", False)),
            )

    def _proposal_parameters(self, action_id: str) -> dict[str, Any]:
        path = self.runtime / "conversation" / "proposals" / f"{action_id}.json"
        if not path.is_file():
            raise ConversationError("proposal for confirmation is missing")
        return ProposedAction.model_validate_json(path.read_text(encoding="utf-8")).parameters

    def _receipt(self, action: str, actor: str, status: str, reason: str, confirmation_id: str | None, before: ChatStatusView, after: ChatStatusView | None = None) -> ActionReceipt:
        receipt = ActionReceipt(
            receipt_id=self._id("receipt"), action=action, actor=actor, status=status, reason=reason,
            confirmation_id=confirmation_id, state_before_id=before.state_id, state_before_sha256=before.state_sha256,
            state_after_id=after.state_id if after else None, state_after_sha256=after.state_sha256 if after else None,
            trace_references=["conversation/confirmations", "conversation/receipts"],
        )
        self.store.write_immutable(Path("conversation") / "receipts" / f"{receipt.receipt_id}.json", receipt)
        return receipt

    def _rejected(self, view: ChatStatusView, action: str, actor: str, reason: str, confirmation_id: str | None = None) -> ConversationTurnResult:
        receipt = self._receipt(action, actor, "REJECTED", reason, confirmation_id, view)
        return ConversationTurnResult(classification=ChatInputClassification.COMMITTABLE_ACTION, status_view=view, receipt=receipt)

    def _allowed_actions(self, state: dict[str, Any]):
        yield ConversationActionType.SHOW_STATUS, "Show current typed Harness status.", [], ["No research meaning is changed."], False
        if state.get("lifecycle_status", "ACTIVE") == "ARCHIVED":
            if state.get("pending_decision_ids"):
                yield ConversationActionType.SHOW_DECISION, "Show the preserved pending Decision Packet.", [], ["The archived workspace cannot record or resume it."], False
            return
        yield ConversationActionType.PROPOSE_DECISION, "Prepare a Human Decision proposal.", [], ["No decision is recorded automatically.", "Chat prose is not Evidence."], False
        if state.get("pending_decision_ids"):
            yield ConversationActionType.SHOW_DECISION, "Show the pending Decision Packet.", [], ["The Harness will not choose the Human decision."], False
            yield ConversationActionType.RECORD_DECISION, "Record the explicitly confirmed Human Decision choice.", ["The declared decision choice becomes part of typed state."], ["No other semantic decision is inferred."], True
        if state.get("pending_work"):
            yield ConversationActionType.SUBMIT_WORK_RESULT, "Submit the bounded structured Work result for the pending Run.", ["The validated result may enter the declared reduction path."], ["Chat prose, unstructured text, and late results do not become Evidence."], True
            yield ConversationActionType.ABORT_PENDING_RUN, "Abort the pending operational Run and optionally prepare a replacement.", ["The Run is marked aborted and its trace remains immutable."], ["Research meaning, scope, or protocol is not changed automatically."], True
        yield ConversationActionType.REQUEST_RECOVERY, "Freeze a precise Recovery Request and impact assessment.", ["The request and current head binding become immutable audit inputs."], ["Recovery is not approved and no replay starts automatically."], True
        yield ConversationActionType.CONFIRM_RECOVERY, "Approve a previously assessed Recovery Request with Human impact treatments.", ["The declared invalidation and replay plan become fixed."], ["Unlisted replay, semantic reinterpretation, and Publication refresh do not happen automatically."], True
        yield ConversationActionType.STOP_AT_BOUNDARY, "Record an explicit stop at the current Harness boundary.", ["The boundary stop is auditable."], ["No downstream Run is started."], True
        yield ConversationActionType.CANCEL_PENDING_ACTION, "Cancel a pending Conversation action.", ["The pending action is marked cancelled in the conversation audit."], ["Prior Harness state is not erased or rewound."], True
        if state.get("lifecycle_status", "ACTIVE") == "ACTIVE":
            yield ConversationActionType.REGISTER_ATTENTION_DROP, "Register one explicitly selected raw Attention drop batch.", ["The selected files are hashed and frozen for bounded Attention Distillation."], ["No drop content is treated as Evidence or automatically adopted."], True
            yield ConversationActionType.ARCHIVE_RESEARCH, "Archive the current Research workspace into a verified self-contained bundle.", ["The source workspace becomes ARCHIVED after the bundle is verified."], ["The archive does not delete data or choose a new research meaning."], True

    @staticmethod
    def _effect(action: ConversationActionType) -> str:
        return {
            ConversationActionType.RECORD_DECISION: "Record exactly the supplied Human Decision choice.",
            ConversationActionType.SUBMIT_WORK_RESULT: "Validate and submit exactly one bounded Work result.",
            ConversationActionType.ABORT_PENDING_RUN: "Abort one pending Run without deleting its directory or submissions.",
            ConversationActionType.REQUEST_RECOVERY: "Freeze one exact Recovery Request and bounded impact assessment.",
            ConversationActionType.CONFIRM_RECOVERY: "Approve one immutable Recovery Decision and its Replay Plan.",
            ConversationActionType.STOP_AT_BOUNDARY: "Record a Human-requested stop boundary.",
            ConversationActionType.CANCEL_PENDING_ACTION: "Cancel one pending Conversation action.",
            ConversationActionType.REGISTER_ATTENTION_DROP: "Freeze one explicitly selected raw Attention drop for Work distillation.",
            ConversationActionType.ARCHIVE_RESEARCH: "Create and verify one append-only workspace archive, then freeze the source lifecycle.",
        }.get(action, "Read-only or proposal-only operation.")

    @staticmethod
    def _fixes(action: ConversationActionType) -> list[str]:
        return ["Only the declared typed effect is allowed."] if action in _CONFIRMATION_ACTIONS else []

    @staticmethod
    def _automatic_limits(action: ConversationActionType) -> list[str]:
        return ["Human semantic decisions remain Human-owned.", "Chat text never becomes Research Evidence."]

    def _json_if_exists(self, relative: str) -> dict[str, Any] | None:
        path = self.runtime / relative
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
