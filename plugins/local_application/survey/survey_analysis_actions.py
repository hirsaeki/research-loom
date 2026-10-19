"""Survey analysis action definitions, payload checks and handler (#494)."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from core.conversation import (
    ConversationRuntimeError,
    HarnessServiceResult,
)

_STORE_NAME = "survey-analysis-registry.sqlite3"
_ANALYSIS_SPEC_CAPTURE_FIELDS = {"dataset_id", "dataset_digest", "analysis_items"}
_ANALYSIS_SPEC_SHOW_FIELDS = {"analysis_spec_id"}
_AGGREGATE_RUN_FIELDS = {
    "analysis_spec_id",
    "analysis_spec_digest",
    "dataset_id",
    "dataset_digest",
}
_AGGREGATE_SHOW_FIELDS = {"aggregate_result_id", "limit", "offset"}
_VIRTUAL_PRETEST_SHOW_FIELDS = {"run_id", "aggregate_result_id"}
_VIRTUAL_PRETEST_COMPARE_FIELDS = {
    "run_a_id",
    "run_b_id",
    "aggregate_a_result_id",
    "aggregate_b_result_id",
}
_REAL_INTAKE_CAPTURE_FIELDS = {
    "file",
    "instrument_id",
    "instrument_version",
    "instrument_digest",
    "analysis_items",
}
_REAL_INTAKE_SHOW_FIELDS = {"dataset_id", "aggregate_result_id", "limit", "offset"}
_MAX_REAL_INTAKE_BYTES = 8 * 1024 * 1024

_SURVEY_ANALYSIS_ACTIONS = (
    (
        "survey_analysis_spec.capture",
        "survey-analysis-spec-capture@0.1.0",
        "capture_spec",
    ),
    (
        "survey_analysis_spec.show",
        "survey-analysis-spec-show@0.1.0",
        "show_spec",
    ),
    (
        "survey_aggregate.run",
        "survey-aggregate-run@0.1.0",
        "aggregate",
    ),
    (
        "survey_aggregate.show",
        "survey-aggregate-show@0.1.0",
        "show_result",
    ),
    (
        "survey_virtual_pretest.show",
        "survey-virtual-pretest-show@0.1.0",
        "show_virtual_pretest",
    ),
    (
        "survey_virtual_pretest.compare",
        "survey-virtual-pretest-compare@0.1.0",
        "compare_virtual_pretest",
    ),
    (
        "survey_real_intake.capture",
        "survey-real-intake-capture@0.1.0",
        "capture_real_intake",
    ),
    (
        "survey_real_intake.show",
        "survey-real-intake-show@0.1.0",
        "show_real_intake",
    ),
)
_ACTION_REGISTRATION_LOCK = RLock()


def _payload_fields(payload: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            f"{label} payload contains unknown fields: " + ", ".join(sorted(map(str, unknown)))
        )


def _nonempty_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _analysis_spec_capture_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _ANALYSIS_SPEC_CAPTURE_FIELDS, "Survey analysis specification capture")
    _nonempty_string(payload, "dataset_id")
    _nonempty_string(payload, "dataset_digest")
    items = payload.get("analysis_items")
    if items is not None and not isinstance(items, list):
        raise ValueError("analysis_items must be an array when supplied")


def _analysis_spec_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _ANALYSIS_SPEC_SHOW_FIELDS, "Survey analysis specification show")
    _nonempty_string(payload, "analysis_spec_id")


def _aggregate_run_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _AGGREGATE_RUN_FIELDS, "Survey aggregate run")
    for field in _AGGREGATE_RUN_FIELDS:
        _nonempty_string(payload, field)


def _virtual_pretest_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _VIRTUAL_PRETEST_SHOW_FIELDS, "Survey Virtual pretest show")
    _nonempty_string(payload, "run_id")
    if "aggregate_result_id" in payload:
        _nonempty_string(payload, "aggregate_result_id")


def _virtual_pretest_compare_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _VIRTUAL_PRETEST_COMPARE_FIELDS, "Survey Virtual pretest compare")
    _nonempty_string(payload, "run_a_id")
    _nonempty_string(payload, "run_b_id")
    if payload["run_a_id"] == payload["run_b_id"]:
        raise ValueError("run_a_id and run_b_id must identify different Runs")
    for field in ("aggregate_a_result_id", "aggregate_b_result_id"):
        if field in payload:
            _nonempty_string(payload, field)


def _aggregate_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _AGGREGATE_SHOW_FIELDS, "Survey aggregate show")
    _nonempty_string(payload, "aggregate_result_id")
    if "limit" in payload and not isinstance(payload["limit"], int):
        raise ValueError("limit must be an integer")
    if "offset" in payload and not isinstance(payload["offset"], int):
        raise ValueError("offset must be an integer")


def _real_intake_capture_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _REAL_INTAKE_CAPTURE_FIELDS, "Survey REAL intake capture")
    for field in ("file", "instrument_id", "instrument_version", "instrument_digest"):
        _nonempty_string(payload, field)
    items = payload.get("analysis_items")
    if items is not None and not isinstance(items, list):
        raise ValueError("analysis_items must be an array when supplied")


def _real_intake_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _REAL_INTAKE_SHOW_FIELDS, "Survey REAL intake show")
    _nonempty_string(payload, "dataset_id")
    if "aggregate_result_id" in payload:
        _nonempty_string(payload, "aggregate_result_id")
    if "limit" in payload and not isinstance(payload["limit"], int):
        raise ValueError("limit must be an integer")
    if "offset" in payload and not isinstance(payload["offset"], int):
        raise ValueError("offset must be an integer")


_ACTION_VALIDATORS = {
    "survey_analysis_spec.capture": _analysis_spec_capture_payload,
    "survey_analysis_spec.show": _analysis_spec_show_payload,
    "survey_aggregate.run": _aggregate_run_payload,
    "survey_aggregate.show": _aggregate_show_payload,
    "survey_virtual_pretest.show": _virtual_pretest_show_payload,
    "survey_virtual_pretest.compare": _virtual_pretest_compare_payload,
    "survey_real_intake.capture": _real_intake_capture_payload,
    "survey_real_intake.show": _real_intake_show_payload,
}


class _SurveyAnalysisActionHandler:
    """Bridge audited Conversation actions to the shared Survey analysis facade."""

    def __init__(
        self,
        application,
        operation: str,
        *,
        facade_class,
        workspace_root: Path | None = None,
    ) -> None:
        self._application = application
        self._operation = operation
        self._facade_class = facade_class
        self._workspace_root = workspace_root

    def execute(self, payload, *, state, actor, proposal):
        facade = self._facade_class(
            self._application,
            state.project_ref,
            workspace_root=self._workspace_root,
        )
        if self._operation == "capture_spec":
            result = facade.capture_survey_analysis_spec(payload)
        elif self._operation == "show_spec":
            result = facade.show_survey_analysis_spec(_nonempty_string(payload, "analysis_spec_id"))
        elif self._operation == "aggregate":
            result = facade.run_survey_aggregation(payload)
        elif self._operation == "show_result":
            result = facade.show_survey_aggregate_result(
                _nonempty_string(payload, "aggregate_result_id"),
                limit=payload.get("limit", 25),
                offset=payload.get("offset", 0),
            )
        elif self._operation == "show_virtual_pretest":
            result = facade.show_survey_virtual_pretest(
                _nonempty_string(payload, "run_id"),
                aggregate_result_id=payload.get("aggregate_result_id"),
            )
        elif self._operation == "compare_virtual_pretest":
            result = facade.compare_survey_virtual_pretests(
                _nonempty_string(payload, "run_a_id"),
                _nonempty_string(payload, "run_b_id"),
                aggregate_a_result_id=payload.get("aggregate_a_result_id"),
                aggregate_b_result_id=payload.get("aggregate_b_result_id"),
            )
        elif self._operation == "capture_real_intake":
            result = facade.capture_real_survey_intake(payload)
        elif self._operation == "show_real_intake":
            result = facade.show_real_survey_intake(
                _nonempty_string(payload, "dataset_id"),
                aggregate_result_id=payload.get("aggregate_result_id"),
                limit=payload.get("limit", 25),
                offset=payload.get("offset", 0),
            )
        else:  # pragma: no cover - registration is closed above.
            raise ConversationRuntimeError(
                "CONV-ROUTE-001",
                f"unknown Survey analysis operation: {self._operation}",
            )

        result_reference = None
        for field in ("aggregate_result_id", "analysis_spec_id", "content_digest"):
            value = result.get(field)
            if isinstance(value, str) and value:
                result_reference = value
                break
        return HarnessServiceResult(
            result_reference=result_reference,
            data=deepcopy(dict(result)),
            research_state_mutation_performed=False,
        )
