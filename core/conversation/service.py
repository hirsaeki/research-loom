from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Mapping

from core.execution import CapabilityExecutionError
from core.runtime import CommitReceipt, StateTransitionRejected

from .models import (
    ActionDefinition,
    ActionDraft,
    CapabilityMaterialization,
    ConversationRuntimeError,
    CoordinatorResult,
)
from .registry import (
    ActionRegistry,
    CapabilityActionMaterializerRegistry,
    CapabilityDescriptorRegistry,
    HarnessServiceRegistry,
)
from .validation import (
    WorkConversationValidator,
    canonical_digest,
    research_context_binding,
    state_binding,
    with_document_digest,
)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    result = _jsonable(value)
    if isinstance(result, Mapping):
        return result
    raise TypeError(f"not serializable as mapping: {type(value)!r}")


class WorkConversationService:
    """Production PR10 Work Conversation runtime.

    Natural-language text is passed only to the candidate-only resolver. Everything
    after resolution is an exact typed proposal bound to the current Research State.
    This service never implements research semantics itself: Harness operations go to
    registered handlers, capability work goes through PR9 CapabilityExecutionService,
    and authoritative writes go only through StateTransitionService.
    """

    def __init__(
        self,
        *,
        resolver,
        store,
        state_provider,
        state_transition_service,
        capability_execution_service,
        action_registry: ActionRegistry,
        harness_services: HarnessServiceRegistry,
        capability_materializers: CapabilityActionMaterializerRegistry,
        descriptors: CapabilityDescriptorRegistry,
        authorization_evidence_provider,
        clock,
        id_provider,
        lineage_resolver: Callable[[str], str],
        confirmation_ttl_seconds: int = 900,
        validator: WorkConversationValidator | None = None,
    ) -> None:
        self._resolver = resolver
        self._store = store
        self._states = state_provider
        self._transitions = state_transition_service
        self._execution = capability_execution_service
        self._actions = action_registry
        self._services = harness_services
        self._materializers = capability_materializers
        self._descriptors = descriptors
        self._authorization = authorization_evidence_provider
        self._clock = clock
        self._ids = id_provider
        self._lineage = lineage_resolver
        self._confirmation_ttl = confirmation_ttl_seconds
        self._validator = validator or WorkConversationValidator()

    def action_definitions(self) -> tuple[ActionDefinition, ...]:
        """Return the static registry definitions without exposing the registry itself."""
        return self._actions.definitions()

    def process_action_draft(
        self,
        draft: ActionDraft,
        *,
        project_id: str,
        actor: Mapping[str, Any],
        conversation_id: str | None = None,
        text: str | None = None,
    ) -> CoordinatorResult:
        """Process an already-typed untrusted ActionDraft through the PR10 path."""
        definition = self._actions.get(str(draft.action_type))
        classification = "QUERY" if definition.effect == "read_only" else "COMMITTABLE_ACTION"
        document = with_document_digest({
            "schema_version": "0.1.0",
            "message_type": "conversation_input",
            "input_id": self._ids.new("IN-"),
            "conversation_id": conversation_id or self._ids.new("CONV-"),
            "project_id": str(project_id),
            "actor": deepcopy(dict(actor)),
            "classification": classification,
            "text": text or draft.rationale or f"typed action {draft.action_type}",
            "received_at": self._clock.now(),
        })
        self._validator.validate(document)
        self._store.store_input(document)
        state = self._state(str(project_id))
        return self._process_resolved_action(document, draft, state, definition)

    def process_input(self, conversation_input: Mapping[str, Any]) -> CoordinatorResult:
        document = deepcopy(dict(conversation_input))
        self._validator.validate(document)
        self._store.store_input(document)
        classification = str(document["classification"])
        if classification == "CONFIRMATION":
            return self._confirm(document)
        if classification == "CANCEL":
            return self._cancel(document)

        state = self._state(document["project_id"])
        summary = self._bounded_state_summary(state)
        draft = self._resolver.resolve(document, summary, self.action_definitions())
        if draft is None:
            return CoordinatorResult("UNRESOLVED", document)

        try:
            definition = self._actions.get(draft.action_type)
        except ConversationRuntimeError as exc:
            return CoordinatorResult(
                "UNRESOLVED",
                document,
                issues=({"code": exc.code, "message": exc.message},),
            )
        return self._process_resolved_action(document, draft, state, definition)

    def _process_resolved_action(
        self,
        document: Mapping[str, Any],
        draft: ActionDraft,
        state,
        definition: ActionDefinition,
    ) -> CoordinatorResult:
        """Shared proposal-through-execution path for natural and typed ingress."""
        classification = str(document["classification"])
        proposal = self._build_proposal(document, definition, draft.payload, state)
        self._validator.validate(proposal)
        self._store.store_proposal(proposal)

        if classification == "PROPOSAL":
            return CoordinatorResult("PROPOSED", document, proposal=proposal)
        if classification == "QUERY":
            if definition.effect != "read_only":
                raise ConversationRuntimeError(
                    "CONV-CLASSIFICATION-001", "QUERY resolved to a state-changing action"
                )
            return self._execute(document, proposal, state, confirmation_receipt=None)
        if classification != "COMMITTABLE_ACTION":
            raise ConversationRuntimeError(
                "CONV-CLASSIFICATION-001", f"unsupported classification: {classification}"
            )

        if definition.effect == "state_changing" and definition.confirmation_required:
            request = self._build_confirmation_request(proposal, state)
            self._validator.validate(request)
            self._store.store_confirmation_request(request)
            return CoordinatorResult(
                "CONFIRMATION_REQUIRED",
                document,
                proposal=proposal,
                confirmation_request=request,
            )
        return self._execute(document, proposal, state, confirmation_receipt=None)

    def collect_external(
        self,
        run_id: str,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None = None,
        artifacts=(),
    ) -> CoordinatorResult:
        correlation = self._store.load_run_correlation(run_id)
        if correlation is None:
            raise ConversationRuntimeError(
                "CONV-AUDIT-001", f"Run is not correlated to a conversation action: {run_id}"
            )
        proposal = self._store.load_proposal(str(correlation["proposal_id"]))
        if proposal is None:
            raise ConversationRuntimeError("CONV-AUDIT-001", "correlated proposal is missing")
        input_document = {"input_id": correlation["input_id"], "message_type": "conversation_input"}
        result = self._execution.collect_external(run_id, handoff, extension, artifacts)

        if result.state_delta_proposal is not None:
            candidate = _mapping(result.state_delta_proposal)
            self._store.store_state_delta_proposal(str(candidate["proposal_id"]), candidate)

        presentations = ()
        if not result.issues and result.handoff_ref is not None:
            presentations = self._candidate_presentations(proposal, handoff)
        return CoordinatorResult(
            "CAPABILITY_RESULT_COLLECTED",
            input_document,
            proposal=proposal,
            execution_result=result,
            presentations=presentations,
            data={
                "handoff": deepcopy(dict(handoff)),
                "state_delta_proposal": _mapping(result.state_delta_proposal)
                if result.state_delta_proposal is not None else None,
                "issues": [asdict(item) if is_dataclass(item) else item for item in result.issues],
            },
        )

    def _state(self, project_id: str):
        lineage = self._lineage(str(project_id))
        try:
            return self._states.load_state_view(str(project_id), lineage)
        except KeyError as exc:
            raise ConversationRuntimeError(
                "CONV-PIN-001", "project/lineage does not resolve to current Research State"
            ) from exc

    def _bounded_state_summary(self, state) -> Mapping[str, Any]:
        objects = []
        for obj in state.effective_objects():
            if obj.get("kind") in {"project", "research_question", "evidence_gap"}:
                objects.append({
                    key: obj[key]
                    for key in ("kind", "id", "revision", "state", "adoption_state", "question", "statement")
                    if key in obj
                })
        return {
            "project_id": state.project_ref,
            "active_lineage_ref": state.active_lineage_ref,
            "current_state": state_binding(state),
            "research_context": research_context_binding(state),
            "objects": objects,
        }

    def _build_proposal(self, input_document, definition: ActionDefinition, payload, state):
        classification = str(input_document["classification"])
        commitment = "proposal_only" if classification == "PROPOSAL" else "commit_requested"
        payload_copy = deepcopy(dict(payload))
        if definition.payload_validator is not None:
            definition.payload_validator(payload_copy)
        route: dict[str, Any]
        proposal_id = self._ids.new("PROP-")

        if definition.route_kind == "harness_service":
            if not definition.service_id:
                raise ConversationRuntimeError("CONV-ROUTE-001", "missing Harness service id")
            route = {"route_type": "harness_service", "service_id": definition.service_id}
        else:
            if not all((definition.capability_id, definition.capability_version,
                        definition.function_id, definition.materializer_id, definition.execution_mode)):
                raise ConversationRuntimeError("CONV-ROUTE-001", "incomplete capability action definition")
            descriptor = self._descriptors.resolve(
                definition.capability_id, definition.capability_version
            )
            materializer = self._materializers.resolve(definition.materializer_id)
            materialized = materializer.materialize(
                payload_copy,
                state,
                descriptor,
                context_pack_id=self._ids.new("CTX-"),
            )
            if materialized.execution_mode != definition.execution_mode:
                raise ConversationRuntimeError(
                    "CONV-ROUTE-001", "capability materializer changed the registered execution mode"
                )
            materialized_payload = {
                "descriptor": deepcopy(dict(materialized.descriptor)),
                "context_pack": deepcopy(dict(materialized.context_pack)),
                "context_extension": deepcopy(dict(materialized.context_extension))
                if materialized.context_extension is not None else None,
                "lineage_ref": materialized.lineage_ref,
                "execution_mode": materialized.execution_mode,
                "execution_style": definition.execution_style,
            }
            self._store.store_materialization(proposal_id, materialized_payload)
            route = {
                "route_type": "capability_invocation",
                "invocation_contract": "capability-invocation@0.1.0",
                "capability": {
                    "capability_id": definition.capability_id,
                    "capability_version": definition.capability_version,
                    "descriptor_digest": str(descriptor["descriptor_digest"]),
                    "function_id": definition.function_id,
                },
                "execution_mode": materialized.execution_mode,
                "context_pack": {
                    "context_pack_id": materialized.context_pack["context_pack_id"],
                    "context_pack_digest": materialized.context_pack["context_pack_digest"],
                },
            }

        decision_refs = list(payload_copy.get("decision_reference_ids", ()))
        human_boundary = {
            "required": definition.human_decision_required,
            "confirmation_is_human_decision": False,
        }
        if decision_refs:
            human_boundary["decision_reference_ids"] = decision_refs
        proposal = {
            "schema_version": "0.1.0",
            "message_type": "action_proposal",
            "proposal_id": proposal_id,
            "conversation_id": input_document["conversation_id"],
            "project_id": input_document["project_id"],
            "source": {"source_type": "human_input", "input_id": input_document["input_id"]},
            "initiating_actor": deepcopy(input_document["actor"]),
            "action": {
                "action_type": definition.action_type,
                "effect": definition.effect,
                "payload_contract": definition.payload_contract,
                "payload": payload_copy,
                "payload_digest": canonical_digest(payload_copy),
            },
            "commitment_mode": commitment,
            "confirmation_policy": {
                "required_on_commit": definition.confirmation_required,
                "human_confirmation_only": True,
            },
            "human_decision_boundary": human_boundary,
            "bindings": {
                "current_state": state_binding(state),
                "research_context": research_context_binding(state),
            },
            "route": route,
            "created_at": self._clock.now(),
        }
        return with_document_digest(proposal)

    def _build_confirmation_request(self, proposal, state):
        now = _parse_time(self._clock.now())
        expires = now + timedelta(seconds=self._confirmation_ttl)
        request = {
            "schema_version": "0.1.0",
            "message_type": "confirmation_request",
            "confirmation_request_id": self._ids.new("CONFREQ-"),
            "conversation_id": proposal["conversation_id"],
            "project_id": proposal["project_id"],
            "proposal_binding": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
            },
            "actor_binding": deepcopy(proposal["initiating_actor"]),
            "action_binding": {
                "action_type": proposal["action"]["action_type"],
                "payload_digest": proposal["action"]["payload_digest"],
            },
            "state_binding": state_binding(state),
            "research_context_binding": research_context_binding(state),
            "issued_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
            "single_use": True,
        }
        return with_document_digest(request)

    def _confirm(self, input_document):
        request_id = str(input_document["target"]["target_id"])
        request = self._store.load_confirmation_request(request_id)
        if request is None:
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-BINDING-001", "unknown Confirmation Request"
            )
        proposal = self._store.load_proposal(str(request["proposal_binding"]["proposal_id"]))
        if proposal is None:
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-BINDING-001", "bound Action Proposal is missing"
            )
        state = self._state(str(request["project_id"]))
        if input_document["actor"] != request["actor_binding"] or input_document["actor"]["actor_type"] != "human":
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-BINDING-001", "confirmation actor does not match request"
            )
        if state_binding(state) != request["state_binding"] or research_context_binding(state) != request.get("research_context_binding"):
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-BINDING-001", "Research State or pins changed after confirmation request"
            )
        if _parse_time(self._clock.now()) >= _parse_time(str(request["expires_at"])):
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-EXPIRED-001", "Confirmation Request expired"
            )

        receipt = with_document_digest({
            "schema_version": "0.1.0",
            "message_type": "confirmation_receipt",
            "confirmation_receipt_id": self._ids.new("CONFREC-"),
            "conversation_id": request["conversation_id"],
            "project_id": request["project_id"],
            "request_binding": {
                "confirmation_request_id": request_id,
                "request_digest": request["request_digest"],
            },
            "proposal_binding": deepcopy(request["proposal_binding"]),
            "actor": deepcopy(input_document["actor"]),
            "action_binding": deepcopy(request["action_binding"]),
            "observed_state": state_binding(state),
            "research_context_binding": research_context_binding(state),
            "confirmed_at": self._clock.now(),
            "outcome": "confirmed",
        })
        self._validator.validate(receipt)
        if not self._store.consume_confirmation_request(request_id, request["request_digest"], receipt):
            raise ConversationRuntimeError(
                "CONV-CONFIRMATION-REPLAY-001", "Confirmation Request was already consumed or cancelled"
            )
        result = self._execute(input_document, proposal, state, confirmation_receipt=receipt)
        return CoordinatorResult(
            result.status,
            input_document,
            proposal=proposal,
            confirmation_receipt=receipt,
            action_receipt=result.action_receipt,
            prepared_execution=result.prepared_execution,
            execution_result=result.execution_result,
            presentations=result.presentations,
            data=result.data,
            issues=result.issues,
        )

    def _cancel(self, input_document):
        target = input_document["target"]
        target_type = str(target["target_type"])
        target_id = str(target["target_id"])
        proposal = None
        if target_type == "proposal":
            proposal = self._store.load_proposal(target_id)
            if proposal is None or proposal["commitment_mode"] != "proposal_only":
                raise ConversationRuntimeError("CONV-CANCEL-001", "proposal is not cancellable")
        elif target_type == "confirmation_request":
            request = self._store.load_confirmation_request(target_id)
            if request is None:
                raise ConversationRuntimeError("CONV-CANCEL-001", "Confirmation Request is unknown")
            proposal = self._store.load_proposal(str(request["proposal_binding"]["proposal_id"]))
        if proposal is None or not self._store.cancel_pending(target_type, target_id):
            raise ConversationRuntimeError("CONV-CANCEL-001", "target is finalized, consumed, cancelled, or unknown")

        bound = proposal["bindings"]["current_state"]
        receipt = self._action_receipt(
            input_document,
            proposal,
            status="cancelled",
            state_before=bound,
            state_after=bound,
            mutation=False,
            execution={"execution_type": "none", "reason": f"cancelled pending {target_type}"},
        )
        self._store.store_action_receipt(receipt)
        return CoordinatorResult("CANCELLED", input_document, proposal=proposal, action_receipt=receipt)

    def _execute(self, source_input, proposal, state, confirmation_receipt):
        self._assert_fresh(proposal, state)
        definition = self._actions.get(str(proposal["action"]["action_type"]))
        if proposal["commitment_mode"] != "commit_requested":
            raise ConversationRuntimeError("CONV-PROPOSAL-ONLY-001", "proposal-only action cannot execute")
        if definition.human_decision_required:
            decision_ids = tuple(proposal["human_decision_boundary"].get("decision_reference_ids", ()))
            payload_ids = tuple(proposal["action"]["payload"].get("decision_reference_ids", ()))
            refs = decision_ids or payload_ids
            if not refs or any(state.decision(str(item)) is None for item in refs):
                receipt = self._rejection_receipt(
                    source_input, proposal, state, "CONV-HUMAN-DECISION-001", confirmation_receipt
                )
                return CoordinatorResult(
                    "DECISION_REQUIRED", source_input, proposal=proposal,
                    action_receipt=receipt,
                    issues=({"code": "CONV-HUMAN-DECISION-001", "message": "explicit structured Human Decision is required"},),
                )

        route = proposal["route"]
        before = state_binding(state)
        if route["route_type"] == "harness_service":
            handler = self._services.resolve(str(route["service_id"]))
            try:
                output = handler.execute(
                    proposal["action"]["payload"],
                    state=state,
                    actor=proposal["initiating_actor"],
                    proposal=proposal,
                )
            except ConversationRuntimeError:
                raise
            except Exception as exc:
                receipt = self._rejection_receipt(
                    source_input, proposal, state, "CONV-AUDIT-001", confirmation_receipt, failed=True
                )
                return CoordinatorResult(
                    "FAILED", source_input, proposal=proposal, action_receipt=receipt,
                    issues=({"code": "CONV-AUDIT-001", "message": str(exc)},),
                )
            after_state = state
            mutation = bool(output.research_state_mutation_performed)
            result_reference = output.result_reference
            if output.state_transition_request is not None:
                transition = self._transitions.apply(output.state_transition_request)
                if isinstance(transition, StateTransitionRejected):
                    code = transition.issues[0].error_code if transition.issues else "CONV-AUDIT-001"
                    receipt = self._rejection_receipt(source_input, proposal, state, code, confirmation_receipt)
                    return CoordinatorResult(
                        "REJECTED", source_input, proposal=proposal, action_receipt=receipt,
                        data={"transition_rejection": _mapping(transition)},
                        issues=tuple(_mapping(item) for item in transition.issues),
                    )
                if not isinstance(transition, CommitReceipt):
                    raise ConversationRuntimeError("CONV-AUDIT-001", "unexpected StateTransition result")
                after_state = self._state(proposal["project_id"])
                mutation = True
                result_reference = transition.commit_id
            after = state_binding(after_state)
            if definition.effect == "read_only" and (mutation or before != after):
                raise ConversationRuntimeError("CONV-READONLY-001", "read-only handler changed Research State")
            receipt = self._action_receipt(
                source_input, proposal, status="succeeded", state_before=before, state_after=after,
                mutation=mutation,
                execution={
                    "execution_type": "harness_service",
                    "service_id": route["service_id"],
                    **({"result_reference": result_reference} if result_reference else {}),
                },
                confirmation_receipt=confirmation_receipt,
            )
            self._store.store_action_receipt(receipt)
            return CoordinatorResult(
                "SUCCEEDED", source_input, proposal=proposal, action_receipt=receipt, data=output.data
            )

        if route["route_type"] != "capability_invocation":
            raise ConversationRuntimeError("CONV-ROUTE-001", "committed proposal route is unresolved")
        materialized_raw = self._store.load_materialization(str(proposal["proposal_id"]))
        if materialized_raw is None:
            raise ConversationRuntimeError("CONV-PIN-001", "proposal capability materialization is missing")
        materialized = CapabilityMaterialization(
            descriptor=materialized_raw["descriptor"],
            context_pack=materialized_raw["context_pack"],
            context_extension=materialized_raw.get("context_extension"),
            lineage_ref=str(materialized_raw["lineage_ref"]),
            execution_mode=str(materialized_raw["execution_mode"]),
        )
        invocation = self._build_invocation(proposal, materialized)
        try:
            if str(materialized_raw.get("execution_style", "external")) == "managed":
                execution_result = self._execution.execute_managed(
                    materialized.descriptor, invocation, materialized.context_pack,
                    lineage_ref=materialized.lineage_ref,
                    context_extension=materialized.context_extension,
                )
                prepared = None
            else:
                prepared = self._execution.prepare_external(
                    materialized.descriptor, invocation, materialized.context_pack,
                    lineage_ref=materialized.lineage_ref,
                    context_extension=materialized.context_extension,
                )
                execution_result = None
        except CapabilityExecutionError as exc:
            receipt = self._rejection_receipt(
                source_input, proposal, state, exc.issue.code, confirmation_receipt, failed=True
            )
            return CoordinatorResult(
                "FAILED", source_input, proposal=proposal, action_receipt=receipt,
                issues=({"code": exc.issue.code, "message": exc.issue.message},),
            )

        self._store.store_run_correlation(invocation["run_id"], proposal["proposal_id"], source_input["input_id"])
        if execution_result is not None and execution_result.state_delta_proposal is not None:
            candidate = _mapping(execution_result.state_delta_proposal)
            self._store.store_state_delta_proposal(str(candidate["proposal_id"]), candidate)
        execution_wire = {
            "execution_type": "capability_invocation",
            "invocation_contract": "capability-invocation@0.1.0",
            "invocation_id": invocation["invocation_id"],
            "invocation_digest": invocation["invocation_digest"],
        }
        if execution_result is not None and execution_result.handoff_ref and execution_result.run.handoff_digest:
            execution_wire["handoff"] = {
                "handoff_id": execution_result.handoff_ref,
                "handoff_digest": execution_result.run.handoff_digest,
            }
        receipt = self._action_receipt(
            source_input, proposal, status="succeeded", state_before=before, state_after=before,
            mutation=False, execution=execution_wire, confirmation_receipt=confirmation_receipt,
        )
        self._store.store_action_receipt(receipt)
        return CoordinatorResult(
            "EXECUTION_PREPARED" if prepared is not None else "SUCCEEDED",
            source_input, proposal=proposal, action_receipt=receipt,
            prepared_execution=prepared, execution_result=execution_result,
        )

    def _build_invocation(self, proposal, materialized):
        invocation_id = self._ids.new("INV-")
        run_id = self._ids.new("RUN-")
        authorization = self._authorization.evidence_for(
            proposal, materialized, invocation_id=invocation_id, run_id=run_id
        )
        route = proposal["route"]
        invocation = {
            "schema_version": "0.1.0",
            "invocation_id": invocation_id,
            "run_id": run_id,
            "project_id": proposal["project_id"],
            "capability": deepcopy(route["capability"]),
            "execution_mode": materialized.execution_mode,
            "context_pack": deepcopy(route["context_pack"]),
            "pins": deepcopy(materialized.context_pack["pins"]),
            "runtime_authorization_evidence": deepcopy(dict(authorization)),
            "trace": {"trace_id": self._ids.new("TRACE-")},
        }
        parent_run_id = proposal["action"]["payload"].get("parent_run_id")
        if parent_run_id:
            invocation["trace"]["parent_run_id"] = str(parent_run_id)
        invocation["invocation_digest"] = canonical_digest(invocation)
        return invocation

    def _assert_fresh(self, proposal, state):
        if (
            proposal["bindings"]["current_state"] != state_binding(state)
            or proposal["bindings"].get("research_context") != research_context_binding(state)
        ):
            raise ConversationRuntimeError(
                "CONV-PIN-001", "Action Proposal is stale; automatic rebase is forbidden"
            )

    def _rejection_receipt(self, source_input, proposal, state, code, confirmation_receipt, failed=False):
        bound = state_binding(state)
        receipt = self._action_receipt(
            source_input, proposal,
            status="failed" if failed else "rejected",
            state_before=bound, state_after=bound, mutation=False,
            execution={"execution_type": "none", "reason": code},
            confirmation_receipt=confirmation_receipt,
            rejection_code=code.replace("-", "_")[:64] if code else None,
        )
        self._store.store_action_receipt(receipt)
        return receipt

    def _action_receipt(
        self, source_input, proposal, *, status, state_before, state_after, mutation,
        execution, confirmation_receipt=None, rejection_code=None,
    ):
        doc = {
            "schema_version": "0.1.0",
            "message_type": "action_receipt",
            "action_receipt_id": self._ids.new("ACTREC-"),
            "conversation_id": proposal["conversation_id"],
            "project_id": proposal["project_id"],
            "source_input_id": source_input["input_id"],
            "proposal_binding": {
                "proposal_id": proposal["proposal_id"],
                "proposal_digest": proposal["proposal_digest"],
            },
            "actor": deepcopy(source_input["actor"]),
            "action_binding": {
                "action_type": proposal["action"]["action_type"],
                "payload_digest": proposal["action"]["payload_digest"],
            },
            "effect": proposal["action"]["effect"],
            "status": status,
            "state_before": deepcopy(state_before),
            "state_after": deepcopy(state_after),
            "research_context_binding": deepcopy(proposal["bindings"].get("research_context")),
            "research_state_mutation_performed": mutation,
            "execution": deepcopy(execution),
            "trace_id": self._ids.new("CONVTRACE-"),
            "completed_at": self._clock.now(),
            "immutable": True,
        }
        if rejection_code:
            doc["rejection_code"] = rejection_code
        if confirmation_receipt is not None:
            doc["confirmation_receipt_binding"] = {
                "confirmation_receipt_id": confirmation_receipt["confirmation_receipt_id"],
                "receipt_digest": confirmation_receipt["receipt_digest"],
            }
        result = with_document_digest(doc)
        self._validator.validate(result)
        return result

    def _candidate_presentations(self, source_proposal, handoff):
        results = []
        outputs = handoff.get("outputs", {})
        for kind, key in (("next_action", "candidate_next_actions"), ("next_method", "candidate_next_methods")):
            for candidate in outputs.get(key, ()):
                candidate_id = str(candidate["proposal_id"])
                action_type = (
                    str(candidate.get("action_type", "research.next_action.consider"))
                    if kind == "next_action" else "research.next_method.consider"
                )
                payload = deepcopy(dict(candidate))
                proposal = with_document_digest({
                    "schema_version": "0.1.0",
                    "message_type": "action_proposal",
                    "proposal_id": self._ids.new("PROP-"),
                    "conversation_id": source_proposal["conversation_id"],
                    "project_id": source_proposal["project_id"],
                    "source": {
                        "source_type": "capability_handoff_candidate",
                        "handoff_id": handoff["handoff_id"],
                        "handoff_digest": handoff["handoff_digest"],
                        "candidate_kind": kind,
                        "candidate_proposal_id": candidate_id,
                    },
                    "initiating_actor": deepcopy(source_proposal["initiating_actor"]),
                    "action": {
                        "action_type": action_type,
                        "effect": "state_changing" if kind == "next_method" else "read_only",
                        "payload_contract": "capability-handoff-candidate@0.1.0",
                        "payload": payload,
                        "payload_digest": canonical_digest(payload),
                    },
                    "commitment_mode": "proposal_only",
                    "confirmation_policy": {
                        "required_on_commit": kind == "next_method",
                        "human_confirmation_only": True,
                    },
                    "human_decision_boundary": {
                        "required": kind == "next_method",
                        "confirmation_is_human_decision": False,
                    },
                    "bindings": deepcopy(source_proposal["bindings"]),
                    "route": {"route_type": "unresolved", "reason": "Capability Handoff candidates remain proposal-only"},
                    "created_at": self._clock.now(),
                })
                self._validator.validate(proposal)
                self._store.store_proposal(proposal)
                presentation = with_document_digest({
                    "schema_version": "0.1.0",
                    "message_type": "candidate_presentation",
                    "presentation_id": self._ids.new("PRES-"),
                    "conversation_id": source_proposal["conversation_id"],
                    "project_id": source_proposal["project_id"],
                    "handoff_binding": {
                        "handoff_id": handoff["handoff_id"],
                        "handoff_digest": handoff["handoff_digest"],
                        "invocation_id": handoff["invocation_id"],
                    },
                    "candidate": {"candidate_kind": kind, "candidate_proposal_id": candidate_id},
                    "proposal_binding": {
                        "proposal_id": proposal["proposal_id"],
                        "proposal_digest": proposal["proposal_digest"],
                    },
                    "display_text": str(candidate.get("instruction") or candidate.get("rationale") or candidate_id),
                    "structured_source_only": True,
                    "auto_adopted": False,
                    "presented_at": self._clock.now(),
                })
                self._validator.validate(presentation)
                self._store.store_candidate_presentation(presentation)
                results.append(presentation)
        return tuple(results)


ResearchCoordinator = WorkConversationService
