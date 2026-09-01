from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import (
    ActionDefinition,
    ConversationRuntimeError,
    HarnessServiceResult,
)

from .facade import LocalApplicationError
from .survey_facade import LocalApplicationFacade as SurveyApplicationFacade
from .survey_response_capture import SurveyResponseCaptureMixin
from .survey_response_core import (
    SurveyResponseCoreMixin,
    _DATASET_FIELDS,
    _RESPONSE_FIELDS,
)
from .survey_response_inspection import SurveyResponseInspectionMixin
from .survey_validation import required_string


_SURVEY_RESPONSE_ACTIONS = (
    (
        "survey_response.normalize",
        "survey-response-normalize@0.1.0",
        "normalize",
    ),
    (
        "survey_response.capture",
        "survey-response-capture@0.1.0",
        "capture",
    ),
    (
        "survey_response.show",
        "survey-response-show@0.1.0",
        "show_response",
    ),
    (
        "survey_response_dataset.capture",
        "survey-response-dataset-capture@0.1.0",
        "capture_dataset",
    ),
    (
        "survey_response_dataset.show",
        "survey-response-dataset-show@0.1.0",
        "show_dataset",
    ),
)


def _payload_fields(payload: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            f"{label} payload contains unknown fields: "
            + ", ".join(sorted(map(str, unknown)))
        )


def _response_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _RESPONSE_FIELDS, "Survey response")


def _dataset_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _DATASET_FIELDS, "Survey response Dataset")


def _response_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, {"response_id", "identity_namespace"}, "Survey response show")
    required_string(payload, "response_id")
    namespace = payload.get("identity_namespace")
    if namespace is not None and (not isinstance(namespace, str) or not namespace):
        raise ValueError("identity_namespace must be a non-empty string when supplied")


def _dataset_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, {"dataset_id", "limit", "offset"}, "Survey response Dataset show")
    required_string(payload, "dataset_id")
    if "limit" in payload and not isinstance(payload["limit"], int):
        raise ValueError("limit must be an integer")
    if "offset" in payload and not isinstance(payload["offset"], int):
        raise ValueError("offset must be an integer")


_ACTION_VALIDATORS = {
    "survey_response.normalize": _response_payload,
    "survey_response.capture": _response_payload,
    "survey_response.show": _response_show_payload,
    "survey_response_dataset.capture": _dataset_payload,
    "survey_response_dataset.show": _dataset_show_payload,
}


class _SurveyResponseActionHandler:
    """Bridge audited Conversation actions to the transport-neutral Survey facade."""

    def __init__(self, application, operation: str) -> None:
        self._application = application
        self._operation = operation

    def execute(self, payload, *, state, actor, proposal):
        facade = LocalApplicationFacade(self._application, state.project_ref)
        if self._operation == "normalize":
            result = facade.normalize_survey_response(payload)
        elif self._operation == "capture":
            result = facade.capture_survey_response(payload)
        elif self._operation == "show_response":
            result = facade.show_survey_response(
                required_string(payload, "response_id"),
                identity_namespace=payload.get("identity_namespace"),
            )
        elif self._operation == "capture_dataset":
            result = facade.capture_survey_response_dataset(payload)
        elif self._operation == "show_dataset":
            result = facade.show_survey_response_dataset(
                required_string(payload, "dataset_id"),
                limit=payload.get("limit", 25),
                offset=payload.get("offset", 0),
            )
        else:  # pragma: no cover - registration is closed above.
            raise ConversationRuntimeError(
                "CONV-ROUTE-001",
                f"unknown Survey response operation: {self._operation}",
            )

        result_reference = None
        for field in ("dataset_id", "response_id", "content_digest"):
            value = result.get(field)
            if isinstance(value, str) and value:
                result_reference = value
                break
        return HarnessServiceResult(
            result_reference=result_reference,
            data=deepcopy(dict(result)),
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(
    SurveyResponseInspectionMixin,
    SurveyResponseCaptureMixin,
    SurveyResponseCoreMixin,
    SurveyApplicationFacade,
):
    """Canonical Survey response normalization, persistence, and inspection."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._ensure_survey_response_actions()

    def _ensure_survey_response_actions(self) -> None:
        """Compose PR42 actions into the existing audited Coordinator registry."""
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        existing = {
            definition.action_type: definition
            for definition in coordinator.action_definitions()
        }

        for action_type, payload_contract, operation in _SURVEY_RESPONSE_ACTIONS:
            definition = existing.get(action_type)
            if definition is None:
                action_registry.register(
                    ActionDefinition(
                        action_type,
                        payload_contract,
                        "read_only",
                        "harness_service",
                        False,
                        human_decision_required=False,
                        service_id=action_type,
                        payload_validator=_ACTION_VALIDATORS[action_type],
                    )
                )
            elif (
                definition.payload_contract != payload_contract
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != action_type
            ):
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-RESPONSE-ROUTE-001",
                    f"registered action conflicts with Survey response route: {action_type}",
                )

            try:
                service_registry.resolve(action_type)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    action_type,
                    _SurveyResponseActionHandler(self._application, operation),
                )
