from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.runtime import ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind

from .candidate_projection import build_candidate_projection
from .new_material_continuation_public_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ACTION_REGISTRATION_LOCK = RLock()
_ACTION_TYPE = "research.recommendation.propose"
_PAYLOAD_CONTRACT = "research-recommendation-proposal@0.1.0"
_MAX_FINDING_IDS = 256
_MAX_SEMANTIC_TEXT_CHARS = 8_192
_MAX_SEMANTIC_LIST_ITEMS = 64
_MAX_SEMANTIC_LIST_ITEM_CHARS = 4_096
_CANDIDATE_PROJECTION_ACTIONS = {
    "research_question.propose",
    "research_question.propose_many",
    "research.argument.propose",
    "research.recommendation.propose",
}


def research_recommendation_proposal_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"statement", "finding_ids", "conditions", "scope", "rationale"}
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ValueError("research.recommendation.propose contains unknown fields")
    normalized = deepcopy(dict(payload))
    statement = normalized.get("statement")
    if (
        not isinstance(statement, str)
        or not statement.strip()
        or len(statement) > _MAX_SEMANTIC_TEXT_CHARS
    ):
        raise ValueError("statement must be a non-empty string within the size limit")
    finding_ids = normalized.get("finding_ids")
    if (
        not isinstance(finding_ids, list)
        or not finding_ids
        or any(not isinstance(item, str) or not item for item in finding_ids)
    ):
        raise ValueError("finding_ids must be a non-empty array of non-empty IDs")
    if len(set(finding_ids)) != len(finding_ids):
        raise ValueError("finding_ids must not contain duplicate IDs")
    if len(finding_ids) > _MAX_FINDING_IDS:
        raise ValueError(f"finding_ids may contain at most {_MAX_FINDING_IDS} IDs")
    normalized["finding_ids"] = list(finding_ids)
    for field in ("conditions", "scope"):
        value = normalized.get(field, [])
        if (
            not isinstance(value, list)
            or len(value) > _MAX_SEMANTIC_LIST_ITEMS
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > _MAX_SEMANTIC_LIST_ITEM_CHARS
                for item in value
            )
        ):
            raise ValueError(f"{field} exceeds the bounded semantic-content limits")
        normalized[field] = list(value)
    if "rationale" in normalized:
        rationale = normalized["rationale"]
        if rationale is not None and (
            not isinstance(rationale, str)
            or not rationale.strip()
            or len(rationale) > _MAX_SEMANTIC_TEXT_CHARS
        ):
            raise ValueError("rationale must be a non-empty string within the size limit")
    return normalized


def _current_authoritative_finding(
    effective: Mapping[tuple[str, str], Mapping[str, Any]],
    project_ref: str,
    finding_id: str,
) -> bool:
    finding = effective.get(("finding", finding_id))
    return bool(
        finding is not None
        and finding.get("project_id") == project_ref
        and finding.get("adoption_state") in {"approved", "revised"}
    )


class ResearchRecommendationProposeHandler:
    def __init__(self, store: Any, id_provider: Any) -> None:
        self._store = store
        self._ids = id_provider

    def execute(self, payload: Mapping[str, Any], *, state: Any, actor: Any, proposal: Mapping[str, Any]) -> HarnessServiceResult:
        del actor
        effective = {
            (str(item.get("kind")), str(item.get("id"))): item
            for item in state.effective_objects()
        }
        for finding_id in payload["finding_ids"]:
            if not _current_authoritative_finding(effective, state.project_ref, str(finding_id)):
                raise ConversationRuntimeError(
                    "RECOMMENDATION-SUPPORT-001",
                    "finding_ids must resolve to current authoritative approved Findings: "
                    + str(finding_id),
                )

        recommendation_id = self._ids.new("REC-")
        recommendation: dict[str, Any] = {
            "schema_version": "0.1.0",
            "id": recommendation_id,
            "kind": "recommendation",
            "revision": 0,
            "project_id": state.project_ref,
            "statement": str(payload["statement"]),
            "finding_ids": list(payload["finding_ids"]),
            # The StateDelta is still candidate-only. Marking the proposed value
            # approved intentionally routes application through research_adoption.
            "adoption_state": "approved",
        }
        for field in ("conditions", "scope"):
            if payload.get(field):
                recommendation[field] = list(payload[field])

        transition_action = TransitionAction(
            TransitionKind.CREATE_OBJECT,
            {"object": recommendation},
            decision_refs=(),
            source_refs=(),
        )
        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            source_refs=(),
            proposed_actions=(transition_action,),
            affected_refs=(ObjectRef("recommendation", recommendation_id),),
            rationale=str(
                payload.get("rationale")
                or "Finding-backed Recommendation candidate proposed through bounded semantic ingress."
            ),
            required_human_decision_kinds=(),
            current_snapshot_ref=str(state.current_snapshot["id"]),
            current_snapshot_digest=str(state.current_snapshot["content_digest"]),
            provenance={
                "producer": "research.recommendation.propose@0.1.0",
                "source_action_proposal": {
                    "proposal_id": str(proposal["proposal_id"]),
                    "proposal_digest": str(proposal["proposal_digest"]),
                },
                "source_input_id": str(proposal["source"]["input_id"]),
                "finding_ids": list(payload["finding_ids"]),
            },
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
            "affected_refs": [{"kind": "recommendation", "id": recommendation_id}],
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
                "recommendation_candidate": deepcopy(recommendation),
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public production facade extension for bounded Recommendation proposal."""

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_recommendation_action()
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_recommendation_action()
        result = dict(super().submit_action(draft_input))
        if draft_input.get("action_type") not in _CANDIDATE_PROJECTION_ACTIONS:
            return result
        data = result.get("data")
        candidate = data.get("state_delta_proposal") if isinstance(data, Mapping) else None
        if not isinstance(candidate, Mapping):
            return result
        projected_data = deepcopy(dict(data))
        projected_data["candidate_projection"] = build_candidate_projection(
            candidate, self._current_state_view()
        )
        result["data"] = projected_data
        return result

    def resume_context(self, *, limits: Mapping[str, int] | None = None) -> Mapping[str, Any]:
        result = deepcopy(dict(super().resume_context(limits=limits)))
        questions = result.get("research_questions")
        candidates = questions.get("candidates") if isinstance(questions, Mapping) else None
        if not isinstance(candidates, list):
            return result
        state = self._current_state_view()
        for row in candidates:
            if not isinstance(row, dict):
                continue
            candidate_id = row.get("state_delta_proposal_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ConversationRuntimeError(
                    "APPLICATION-CANDIDATE-PROJECTION-001",
                    "resume candidate identity is invalid",
                )
            candidate = self._application.conversation_store.load_state_delta_proposal(candidate_id)
            if not isinstance(candidate, Mapping):
                raise ConversationRuntimeError(
                    "APPLICATION-CANDIDATE-PROJECTION-001",
                    "resume candidate does not resolve",
                )
            row["candidate_projection"] = build_candidate_projection(candidate, state)
        return result

    def _current_state_view(self):
        repository = self._application.state_repository
        return repository.load_state_view(
            self._project_id, repository.load_active_lineage_ref(self._project_id)
        )

    def _ensure_recommendation_action(self) -> None:
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
                        payload_validator=research_recommendation_proposal_payload,
                    )
                )
            elif (
                definition.payload_contract != _PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _ACTION_TYPE
            ):
                raise RuntimeError("research.recommendation.propose action registration conflict")
            try:
                service_registry.resolve(_ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _ACTION_TYPE,
                    ResearchRecommendationProposeHandler(
                        self._application.conversation_store,
                        self._application.ids,
                    ),
                )
