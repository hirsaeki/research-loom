from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .facade import LocalApplicationError, _AUTHORITY_PAYLOAD_FIELDS, _INGRESS_FIELDS
from .survey_facade import LocalApplicationFacade as SurveyApplicationFacade
from .survey_response_capture import SurveyResponseCaptureMixin
from .survey_response_core import SurveyResponseCoreMixin
from .survey_response_inspection import SurveyResponseInspectionMixin
from .survey_validation import required_string


class LocalApplicationFacade(
    SurveyResponseInspectionMixin,
    SurveyResponseCaptureMixin,
    SurveyResponseCoreMixin,
    SurveyApplicationFacade,
):
    """Canonical Survey response normalization, persistence, and inspection."""

    def list_actions(self) -> Mapping[str, Any]:
        result = deepcopy(dict(super().list_actions()))
        result["actions"].extend(
            [
                {
                    "action_type": "survey_response.normalize",
                    "payload_contract": "survey-response-normalize@0.1.0",
                    "effect": "read_only",
                    "confirmation_required": False,
                    "route_category": "survey_response",
                },
                {
                    "action_type": "survey_response.capture",
                    "payload_contract": "survey-response-capture@0.1.0",
                    "effect": "append_only_registry",
                    "confirmation_required": False,
                    "route_category": "survey_response",
                },
                {
                    "action_type": "survey_response.show",
                    "payload_contract": "survey-response-show@0.1.0",
                    "effect": "read_only",
                    "confirmation_required": False,
                    "route_category": "survey_response",
                },
                {
                    "action_type": "survey_response_dataset.capture",
                    "payload_contract": "survey-response-dataset-capture@0.1.0",
                    "effect": "append_only_registry",
                    "confirmation_required": False,
                    "route_category": "survey_response",
                },
                {
                    "action_type": "survey_response_dataset.show",
                    "payload_contract": "survey-response-dataset-show@0.1.0",
                    "effect": "read_only",
                    "confirmation_required": False,
                    "route_category": "survey_response",
                },
            ]
        )
        return result

    @staticmethod
    def _action_payload(draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        unknown = set(draft_input) - _INGRESS_FIELDS
        if unknown:
            raise LocalApplicationError(
                "APPLICATION-INGRESS-001",
                "typed action input contains caller-controlled authority or unknown fields: "
                + ", ".join(sorted(map(str, unknown))),
            )
        payload = draft_input.get("payload")
        if not isinstance(payload, Mapping):
            raise LocalApplicationError("APPLICATION-INGRESS-001", "payload must be an object")
        forbidden = set(payload) & _AUTHORITY_PAYLOAD_FIELDS
        if forbidden:
            raise LocalApplicationError(
                "APPLICATION-AUTHORITY-001",
                "caller may not supply Harness authority metadata: "
                + ", ".join(sorted(forbidden)),
            )
        return payload

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        action_type = draft_input.get("action_type") if isinstance(draft_input, Mapping) else None
        if action_type not in {
            "survey_response.normalize",
            "survey_response.capture",
            "survey_response.show",
            "survey_response_dataset.capture",
            "survey_response_dataset.show",
        }:
            return super().submit_action(draft_input)
        payload = self._action_payload(draft_input)
        if action_type == "survey_response.normalize":
            return self.normalize_survey_response(payload)
        if action_type == "survey_response.capture":
            return self.capture_survey_response(payload)
        if action_type == "survey_response.show":
            allowed = {"response_id", "identity_namespace"}
            unknown = set(payload) - allowed
            if unknown:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-INPUT-001",
                    "Survey response show payload has unknown fields: "
                    + ", ".join(sorted(map(str, unknown))),
                )
            response_id = required_string(payload, "response_id")
            namespace = payload.get("identity_namespace")
            if namespace is not None and (not isinstance(namespace, str) or not namespace):
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-INPUT-001",
                    "identity_namespace must be a non-empty string when supplied",
                )
            return self.show_survey_response(response_id, identity_namespace=namespace)
        if action_type == "survey_response_dataset.capture":
            return self.capture_survey_response_dataset(payload)
        allowed = {"dataset_id", "limit", "offset"}
        unknown = set(payload) - allowed
        if unknown:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "Survey response Dataset show payload has unknown fields: "
                + ", ".join(sorted(map(str, unknown))),
            )
        dataset_id = required_string(payload, "dataset_id")
        return self.show_survey_response_dataset(
            dataset_id,
            limit=payload.get("limit", 25),
            offset=payload.get("offset", 0),
        )
