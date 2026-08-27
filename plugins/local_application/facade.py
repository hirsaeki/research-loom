from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from core.conversation import ActionDraft, ConversationRuntimeError, CoordinatorResult
from core.conversation.validation import with_document_digest
from plugins.local_application.workspace import LocalWorkspace, OpenedLocalWorkspace


_INGRESS_FIELDS = {"action_type", "payload", "rationale", "actor_id", "conversation_id"}
_AUTHORITY_PAYLOAD_FIELDS = {
    "decision_reference_ids",
    "state_transition_request",
    "commit_bundle",
    "commit_id",
    "new_snapshot_id",
    "runtime_authorization_evidence",
    "authorization_evidence",
    "capability_implementation",
    "implementation_id",
}


class LocalApplicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _conversation_input(
    app,
    *,
    project_id: str,
    classification: str,
    actor_id: str,
    text: str,
    conversation_id: str | None = None,
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "0.1.0",
        "message_type": "conversation_input",
        "input_id": app.ids.new("IN-"),
        "conversation_id": conversation_id or app.ids.new("CONV-"),
        "project_id": project_id,
        "actor": {"actor_id": actor_id, "actor_type": "human"},
        "classification": classification,
        "text": text,
        "received_at": app.clock.now(),
    }
    if target is not None:
        document["target"] = deepcopy(dict(target))
    return with_document_digest(document)


def _result_projection(result: CoordinatorResult) -> dict[str, Any]:
    status = result.status
    decision_request = result.decision_request
    if decision_request is None and result.data:
        maybe = result.data.get("decision_request")
        if isinstance(maybe, Mapping):
            decision_request = maybe
    if result.confirmation_request is not None:
        status = "CONFIRMATION_REQUIRED"
    elif decision_request is not None:
        status = "HUMAN_DECISION_REQUIRED"
    elif result.prepared_execution is not None:
        status = "CAPABILITY_EXECUTION_PREPARED"

    output: dict[str, Any] = {"status": status}
    if result.proposal is not None:
        output["proposal"] = _jsonable(result.proposal)
    if result.confirmation_request is not None:
        output["confirmation_request"] = _jsonable(result.confirmation_request)
    if result.confirmation_receipt is not None:
        output["confirmation_receipt"] = _jsonable(result.confirmation_receipt)
    if decision_request is not None:
        output["decision_request"] = _jsonable(decision_request)
    if result.action_receipt is not None:
        output["action_receipt"] = _jsonable(result.action_receipt)
    if result.prepared_execution is not None:
        prepared = _jsonable(result.prepared_execution)
        output["prepared_execution"] = prepared
        run = prepared.get("run") if isinstance(prepared, Mapping) else None
        if isinstance(run, Mapping) and run.get("run_id"):
            output["run_id"] = str(run["run_id"])
    if result.execution_result is not None:
        output["execution_result"] = _jsonable(result.execution_result)
    if result.presentations:
        output["presentations"] = _jsonable(result.presentations)
    if result.data:
        output["data"] = _jsonable(result.data)
    if result.issues:
        output["issues"] = _jsonable(result.issues)
    return output


class LocalApplicationFacade:
    """Small transport-neutral application surface over LocalResearchApplication.

    Callers submit candidate action data only. Registry-owned routing, effects,
    confirmation policy, Capability identity, runtime authorization, Human Decision
    binding, and State transitions remain inside the existing application path.
    """

    def __init__(
        self,
        application,
        project_id: str,
        *,
        workspace_root: str | Path | None = None,
        owns_application: bool = False,
    ) -> None:
        self._application = application
        self._project_id = str(project_id)
        self._workspace_root = Path(workspace_root) if workspace_root is not None else None
        self._owns_application = owns_application

    @classmethod
    def from_opened_workspace(cls, opened: OpenedLocalWorkspace) -> "LocalApplicationFacade":
        return cls(
            opened.application,
            opened.project_id,
            workspace_root=opened.root,
            owns_application=True,
        )

    @classmethod
    def open_workspace(cls, workspace: str | Path) -> "LocalApplicationFacade":
        return cls.from_opened_workspace(LocalWorkspace.open(workspace))

    @property
    def project_id(self) -> str:
        return self._project_id

    def close(self) -> None:
        if self._owns_application:
            self._application.close()
            self._owns_application = False

    def __enter__(self) -> "LocalApplicationFacade":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def list_actions(self) -> Mapping[str, Any]:
        definitions = self._application.coordinator._actions.definitions()
        actions = []
        for definition in definitions:
            actions.append({
                "action_type": definition.action_type,
                "payload_contract": definition.payload_contract,
                "effect": definition.effect,
                "confirmation_required": bool(definition.confirmation_required),
                "route_category": (
                    "research_capability"
                    if definition.route_kind == "capability_invocation"
                    else "harness_service"
                ),
            })
        return {"status": "OK", "project_id": self._project_id, "actions": actions}

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(draft_input, Mapping):
            raise LocalApplicationError("APPLICATION-INGRESS-001", "typed action input must be an object")
        unknown = set(draft_input) - _INGRESS_FIELDS
        if unknown:
            raise LocalApplicationError(
                "APPLICATION-INGRESS-001",
                "typed action input contains caller-controlled authority or unknown fields: "
                + ", ".join(sorted(str(item) for item in unknown)),
            )
        action_type = draft_input.get("action_type")
        payload = draft_input.get("payload")
        if not isinstance(action_type, str) or not action_type:
            raise LocalApplicationError("APPLICATION-INGRESS-001", "action_type is required")
        if not isinstance(payload, Mapping):
            raise LocalApplicationError("APPLICATION-INGRESS-001", "payload must be an object")
        forbidden = set(payload) & _AUTHORITY_PAYLOAD_FIELDS
        if forbidden:
            raise LocalApplicationError(
                "APPLICATION-AUTHORITY-001",
                "caller may not supply Harness authority metadata: "
                + ", ".join(sorted(forbidden)),
            )
        rationale = draft_input.get("rationale")
        if rationale is not None and not isinstance(rationale, str):
            raise LocalApplicationError("APPLICATION-INGRESS-001", "rationale must be a string")
        actor_id = draft_input.get("actor_id", "local-human")
        conversation_id = draft_input.get("conversation_id")
        if not isinstance(actor_id, str) or not actor_id:
            raise LocalApplicationError("APPLICATION-INGRESS-001", "actor_id must be a non-empty string")
        if conversation_id is not None and (not isinstance(conversation_id, str) or not conversation_id):
            raise LocalApplicationError("APPLICATION-INGRESS-001", "conversation_id must be a non-empty string")

        coordinator = self._application.coordinator
        definition = coordinator._actions.get(action_type)
        classification = "QUERY" if definition.effect == "read_only" else "COMMITTABLE_ACTION"
        document = _conversation_input(
            self._application,
            project_id=self._project_id,
            classification=classification,
            actor_id=actor_id,
            conversation_id=conversation_id,
            text=rationale or f"typed action {action_type}",
        )
        draft = ActionDraft(action_type, deepcopy(dict(payload)), rationale)

        # This is deliberately the same proposal/confirmation/execution path used
        # after natural-language resolution in WorkConversationService. No route,
        # effect, Capability identity, authorization, Decision ref, or transition
        # request is accepted from the caller.
        coordinator._validator.validate(document)
        coordinator._store.store_input(document)
        state = coordinator._state(self._project_id)
        try:
            proposal = coordinator._build_proposal(document, definition, draft.payload, state)
        except ValueError as exc:
            raise LocalApplicationError("APPLICATION-PAYLOAD-001", str(exc)) from exc
        coordinator._validator.validate(proposal)
        coordinator._store.store_proposal(proposal)
        if definition.effect == "state_changing" and definition.confirmation_required:
            request = coordinator._build_confirmation_request(proposal, state)
            coordinator._validator.validate(request)
            coordinator._store.store_confirmation_request(request)
            result = CoordinatorResult(
                "CONFIRMATION_REQUIRED",
                document,
                proposal=proposal,
                confirmation_request=request,
            )
        else:
            result = coordinator._execute(document, proposal, state, confirmation_receipt=None)
        return _result_projection(result)

    def submit_confirmation(self, confirmation: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = {"confirmation_request_id", "actor_id"}
        if not isinstance(confirmation, Mapping) or set(confirmation) - allowed:
            raise LocalApplicationError(
                "APPLICATION-CONFIRMATION-001",
                "confirmation accepts only confirmation_request_id and optional actor_id",
            )
        request_id = confirmation.get("confirmation_request_id")
        actor_id = confirmation.get("actor_id", "local-human")
        if not isinstance(request_id, str) or not request_id:
            raise LocalApplicationError("APPLICATION-CONFIRMATION-001", "confirmation_request_id is required")
        if not isinstance(actor_id, str) or not actor_id:
            raise LocalApplicationError("APPLICATION-CONFIRMATION-001", "actor_id must be a non-empty string")
        request = self._application.conversation_store.load_confirmation_request(request_id)
        if request is None:
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-BINDING-001", "unknown Confirmation Request"
            )
        document = _conversation_input(
            self._application,
            project_id=self._project_id,
            classification="CONFIRMATION",
            actor_id=actor_id,
            conversation_id=str(request["conversation_id"]),
            text="confirm exact bound action",
            target={"target_type": "confirmation_request", "target_id": request_id},
        )
        return _result_projection(self._application.coordinator.process_input(document))

    def resolve_human_decision(self, response: Mapping[str, Any]) -> Mapping[str, Any]:
        result = self._application.resolve_human_decision(response)
        return {
            "status": str(result.status),
            "request": _jsonable(result.request),
            "response": _jsonable(result.response),
            "commit_receipt": _jsonable(result.commit_receipt) if result.commit_receipt is not None else None,
            "transition_rejection": (
                _jsonable(result.transition_rejection)
                if result.transition_rejection is not None
                else None
            ),
        }

    def collect_external(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(run_id, str) or not run_id:
            raise LocalApplicationError("APPLICATION-EXTERNAL-001", "run_id is required")
        if not isinstance(submission, Mapping) or set(submission) - {"handoff", "extension"}:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-001", "external collection accepts handoff and optional extension"
            )
        handoff = submission.get("handoff")
        extension = submission.get("extension")
        if not isinstance(handoff, Mapping):
            raise LocalApplicationError("APPLICATION-EXTERNAL-001", "handoff must be an object")
        if extension is not None and not isinstance(extension, Mapping):
            raise LocalApplicationError("APPLICATION-EXTERNAL-001", "extension must be an object")
        result = self._application.coordinator.collect_external(
            run_id,
            deepcopy(dict(handoff)),
            deepcopy(dict(extension)) if extension is not None else None,
        )
        return _result_projection(result)

    def status(self) -> Mapping[str, Any]:
        repo = self._application.state_repository
        lineage_id = repo.load_active_lineage_ref(self._project_id)
        state = repo.load_state_view(self._project_id, lineage_id)
        pending_decisions = self._application.human_decisions.pending(self._project_id)

        pending_confirmations = []
        store = self._application.conversation_store
        with store._lock:
            rows = store._db.execute(
                "SELECT d.payload_json FROM confirmation_requests c "
                "JOIN documents d ON d.message_type='confirmation_request' AND d.document_id=c.request_id "
                "WHERE c.status='pending' ORDER BY c.request_id"
            ).fetchall()
        for row in rows:
            import json
            item = json.loads(str(row["payload_json"]))
            if str(item.get("project_id")) == self._project_id:
                pending_confirmations.append(item)

        pending_runs = []
        execution_store = self._application.execution_store
        with execution_store._lock:
            rows = execution_store._connection.execute(
                "SELECT run_id,capability_id,function_id,execution_mode,status,lineage_ref,snapshot_ref,snapshot_digest "
                "FROM runs WHERE project_ref=? AND status IN ('PREPARED','RUNNING') ORDER BY run_id",
                (self._project_id,),
            ).fetchall()
        for row in rows:
            pending_runs.append({key: row[key] for key in row.keys()})

        snapshot = state.current_snapshot
        return {
            "status": "OK",
            "project_id": self._project_id,
            "active_lineage": state.active_lineage_ref,
            "snapshot": {
                "snapshot_id": str(snapshot["id"]),
                "revision": int(snapshot.get("revision", 0)),
                "content_digest": str(snapshot["content_digest"]),
            },
            "bindings": {
                "project_config": {
                    "ref": state.project_config_ref,
                    "digest": state.project_config_digest,
                },
                "effective_profile_set": {
                    "ref": state.effective_profile_set_ref,
                    "digest": state.effective_profile_set_digest,
                },
            },
            "pending_confirmations": _jsonable(pending_confirmations),
            "pending_human_decisions": _jsonable(pending_decisions),
            "pending_runs": _jsonable(pending_runs),
        }

    def doctor(self) -> Mapping[str, Any]:
        if self._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-WORKSPACE-001", "doctor requires a facade opened from a local workspace"
            )
        return LocalWorkspace.doctor(self._workspace_root)
