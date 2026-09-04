from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError
from .research_question_review import (
    ResearchQuestionReviewHandler,
    research_question_review_payload,
)
from .survey_analysis_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ACTION_REGISTRATION_LOCK = RLock()
_ACTION_TYPE = "research_question.review"
_PAYLOAD_CONTRACT = "research-question-review@0.1.0"


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extension for iterative Research Question review."""

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_question_review_action()
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_question_review_action()
        return super().submit_action(draft_input)

    def resume_context(self, *, limits: Mapping[str, int] | None = None) -> Mapping[str, Any]:
        result = deepcopy(dict(super().resume_context(limits=limits)))
        repository = self._application.state_repository
        state = repository.load_state_view(
            self._project_id,
            repository.load_active_lineage_ref(self._project_id),
        )
        current = {
            str(item["id"]): item
            for item in state.effective_objects()
            if item.get("kind") == "research_question" and item.get("id")
        }
        questions = result.get("research_questions")
        if isinstance(questions, Mapping):
            for collection_name in ("authoritative", "candidates"):
                collection = questions.get(collection_name)
                if not isinstance(collection, list):
                    continue
                for item in collection:
                    if not isinstance(item, dict):
                        continue
                    source = current.get(str(item.get("id", "")))
                    if source is None:
                        continue
                    item["revision"] = int(source.get("revision", item.get("revision", 0)))
                    item["question_lineage_id"] = str(
                        source.get("question_lineage_id") or source.get("id")
                    )
                    for key in (
                        "derived_from_question_revisions",
                        "question_delta",
                        "review_inputs",
                        "downstream_review_required_refs",
                    ):
                        if key in source:
                            item[key] = deepcopy(source[key])
        return result

    def _ensure_question_review_action(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
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
                        payload_validator=research_question_review_payload,
                    )
                )
            elif (
                definition.payload_contract != _PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _ACTION_TYPE
            ):
                raise RuntimeError("research_question.review action registration conflict")

            try:
                service_registry.resolve(_ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _ACTION_TYPE,
                    ResearchQuestionReviewHandler(
                        self._application.conversation_store,
                        self._application.ids,
                    ),
                )
