from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.runtime import ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind

from .project_input_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ACTION_REGISTRATION_LOCK = RLock()
_ACTION_TYPE = "research.argument.propose"
_PAYLOAD_CONTRACT = "research-argument-proposal@0.1.0"
_MAX_SUPPORT_IDS = 256
_LIST_ID_FIELDS = (
    "question_ids",
    "premise_claim_ids",
    "finding_ids",
    "evidence_ids",
    "counter_review_ids",
)
_ALLOWED_SUPPORT = {
    "question_ids": "research_question",
    "premise_claim_ids": "claim",
    "finding_ids": "finding",
    "evidence_ids": "evidence",
    "counter_review_ids": "counter_review",
}


def research_argument_proposal_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "conclusion",
        "warrant",
        "question_ids",
        "conclusion_claim_id",
        "premise_claim_ids",
        "finding_ids",
        "evidence_ids",
        "qualifier",
        "counter_review_ids",
        "implications",
        "rationale",
    }
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ValueError("research.argument.propose contains unknown fields")
    normalized = deepcopy(dict(payload))
    for field in ("conclusion", "warrant"):
        value = normalized.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
    for field in _LIST_ID_FIELDS:
        value = normalized.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError(f"{field} must be an array of non-empty IDs")
        if len(set(value)) != len(value):
            raise ValueError(f"{field} must not contain duplicate IDs")
        normalized[field] = list(value)
    if sum(len(normalized[field]) for field in _LIST_ID_FIELDS) > _MAX_SUPPORT_IDS:
        raise ValueError(f"Argument support references may contain at most {_MAX_SUPPORT_IDS} IDs in total")
    for field in ("conclusion_claim_id", "qualifier", "rationale"):
        if field not in normalized:
            continue
        value = normalized[field]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{field} must be a non-empty string when provided")
    implications = normalized.get("implications", [])
    if not isinstance(implications, list) or any(not isinstance(item, str) or not item.strip() for item in implications):
        raise ValueError("implications must be an array of non-empty strings")
    normalized["implications"] = list(implications)
    if not normalized["finding_ids"] and not normalized["evidence_ids"]:
        raise ValueError("Argument requires at least one authoritative Finding or Evidence reference")
    return normalized


def _current_authoritative_argument_support(
    effective: Mapping[tuple[str, str], Mapping[str, Any]],
    project_ref: str,
    kind: str,
    object_id: str,
) -> bool:
    item = effective.get((kind, object_id))
    if item is None or item.get("project_id") != project_ref:
        return False
    if kind in {"research_question", "finding"}:
        return item.get("adoption_state") in {"approved", "revised"}
    if kind == "claim":
        return item.get("assessment") not in {"proposed", "candidate"}
    return True


class ResearchArgumentProposeHandler:
    def __init__(self, store: Any, id_provider: Any) -> None:
        self._store = store
        self._ids = id_provider

    def execute(self, payload: Mapping[str, Any], *, state: Any, actor: Any, proposal: Mapping[str, Any]) -> HarnessServiceResult:
        del actor
        effective = {
            (str(item.get("kind")), str(item.get("id"))): item
            for item in state.effective_objects()
        }
        for field, kind in _ALLOWED_SUPPORT.items():
            for object_id in payload.get(field, ()):  # type: ignore[arg-type]
                if not _current_authoritative_argument_support(
                    effective, state.project_ref, kind, str(object_id)
                ):
                    raise ConversationRuntimeError(
                        "ARGUMENT-SUPPORT-001",
                        f"{field} must resolve to current authoritative {kind} objects: {object_id}",
                    )
        conclusion_claim_id = payload.get("conclusion_claim_id")
        if conclusion_claim_id is not None and not _current_authoritative_argument_support(
            effective, state.project_ref, "claim", str(conclusion_claim_id)
        ):
            raise ConversationRuntimeError(
                "ARGUMENT-SUPPORT-001",
                f"conclusion_claim_id must resolve to a current authoritative claim: {conclusion_claim_id}",
            )

        argument_id = self._ids.new("ARG-")
        argument: dict[str, Any] = {
            "schema_version": "0.1.0",
            "id": argument_id,
            "kind": "argument",
            "revision": 0,
            "project_id": state.project_ref,
            "conclusion": str(payload["conclusion"]),
            "warrant": str(payload["warrant"]),
            "question_ids": list(payload.get("question_ids", ())),
            "premise_claim_ids": list(payload.get("premise_claim_ids", ())),
            "finding_ids": list(payload.get("finding_ids", ())),
            "evidence_ids": list(payload.get("evidence_ids", ())),
            "counter_review_ids": list(payload.get("counter_review_ids", ())),
            "implications": list(payload.get("implications", ())),
        }
        for field in ("conclusion_claim_id", "qualifier"):
            if payload.get(field) is not None:
                argument[field] = str(payload[field])

        transition_action = TransitionAction(
            TransitionKind.CREATE_OBJECT,
            {"object": argument},
            decision_refs=(),
            source_refs=(),
        )
        provenance = {
            "producer": "research.argument.propose@0.1.0",
            "source_action_proposal": {
                "proposal_id": str(proposal["proposal_id"]),
                "proposal_digest": str(proposal["proposal_digest"]),
            },
            "source_input_id": str(proposal["source"]["input_id"]),
            "support_refs": {
                field: list(payload.get(field, ())) for field in _LIST_ID_FIELDS
            }
            | ({"conclusion_claim_id": str(conclusion_claim_id)} if conclusion_claim_id is not None else {}),
        }
        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            source_refs=(),
            proposed_actions=(transition_action,),
            affected_refs=(ObjectRef("argument", argument_id),),
            rationale=str(payload.get("rationale") or "Evidence-linked Argument candidate proposed through bounded Research synthesis ingress."),
            required_human_decision_kinds=(),
            current_snapshot_ref=str(state.current_snapshot["id"]),
            current_snapshot_digest=str(state.current_snapshot["content_digest"]),
            provenance=provenance,
            candidate_only=True,
        ).with_calculated_digest()
        candidate_wire = {
            "proposal_id": candidate.proposal_id,
            "project_ref": candidate.project_ref,
            "lineage_ref": candidate.lineage_ref,
            "source_refs": list(candidate.source_refs),
            "proposed_actions": [{
                "kind": transition_action.kind.value,
                "payload": deepcopy(dict(transition_action.payload)),
                "decision_refs": list(transition_action.decision_refs),
                "source_refs": list(transition_action.source_refs),
            }],
            "affected_refs": [{"kind": "argument", "id": argument_id}],
            "rationale": candidate.rationale,
            "required_human_decision_kinds": list(candidate.required_human_decision_kinds),
            "current_snapshot_ref": candidate.current_snapshot_ref,
            "current_snapshot_digest": candidate.current_snapshot_digest,
            "provenance": deepcopy(dict(candidate.provenance)),
            "candidate_only": True,
            "proposal_digest": candidate.proposal_digest,
        }
        self._store.store_state_delta_proposal(candidate.proposal_id, candidate_wire)
        return HarnessServiceResult(
            result_reference=candidate.proposal_id,
            data={
                "state_delta_proposal_id": candidate.proposal_id,
                "argument_candidate": deepcopy(argument),
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public production facade extension for bounded Research Argument synthesis."""

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_argument_action()
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_argument_action()
        return super().submit_action(draft_input)

    def _ensure_argument_action(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _ACTION_REGISTRATION_LOCK:
            existing = {definition.action_type: definition for definition in coordinator.action_definitions()}
            definition = existing.get(_ACTION_TYPE)
            if definition is None:
                action_registry.register(
                    ActionDefinition(
                        _ACTION_TYPE,
                        _PAYLOAD_CONTRACT,
                        "read_only",
                        "harness_service",
                        False,
                        human_decision_required=False,
                        service_id=_ACTION_TYPE,
                        payload_validator=research_argument_proposal_payload,
                    )
                )
            elif (
                definition.payload_contract != _PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _ACTION_TYPE
            ):
                raise RuntimeError("research.argument.propose action registration conflict")
            try:
                service_registry.resolve(_ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _ACTION_TYPE,
                    ResearchArgumentProposeHandler(
                        self._application.conversation_store,
                        self._application.ids,
                    ),
                )
