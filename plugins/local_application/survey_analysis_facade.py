from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from core.conversation import (
    ActionDefinition,
    ConversationRuntimeError,
    HarnessServiceResult,
)
from plugins.local_survey_analysis_store import (
    LocalSurveyAnalysisStore,
    LocalSurveyAnalysisStoreError,
)
from plugins.local_survey_response_store import LocalSurveyResponseStoreError
from plugins.survey_analysis import (
    aggregate_dataset,
    analysis_spec_content_digest,
    normalize_analysis_items,
    registry_digest,
    stable_identity,
    validate_analysis_spec,
)
from .facade import LocalApplicationError
from .survey_facade import _snapshot
from .survey_validation import input_object, required_string
from .virtual_runner_facade import LocalApplicationFacade as VirtualRunnerApplicationFacade

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
)
_ACTION_REGISTRATION_LOCK = RLock()


def _payload_fields(payload: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            f"{label} payload contains unknown fields: "
            + ", ".join(sorted(map(str, unknown)))
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


def _aggregate_show_payload(payload: Mapping[str, Any]) -> None:
    _payload_fields(payload, _AGGREGATE_SHOW_FIELDS, "Survey aggregate show")
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
}


class _SurveyAnalysisActionHandler:
    """Bridge audited Conversation actions to the shared Survey analysis facade."""

    def __init__(self, application, operation: str) -> None:
        self._application = application
        self._operation = operation

    def execute(self, payload, *, state, actor, proposal):
        facade = LocalApplicationFacade(self._application, state.project_ref)
        if self._operation == "capture_spec":
            result = facade.capture_survey_analysis_spec(payload)
        elif self._operation == "show_spec":
            result = facade.show_survey_analysis_spec(
                _nonempty_string(payload, "analysis_spec_id")
            )
        elif self._operation == "aggregate":
            result = facade.run_survey_aggregation(payload)
        elif self._operation == "show_result":
            result = facade.show_survey_aggregate_result(
                _nonempty_string(payload, "aggregate_result_id"),
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


class LocalApplicationFacade(VirtualRunnerApplicationFacade):
    """Final production facade including shared Survey aggregation and inspection."""

    def _survey_analysis_store(self) -> LocalSurveyAnalysisStore:
        if self._workspace_root is None:
            root = getattr(self._application, "root", None)
            if root is None:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-ANALYSIS-STORE-001",
                    "Survey analysis registry requires a local application root",
                )
            return LocalSurveyAnalysisStore(Path(root) / _STORE_NAME)
        return LocalSurveyAnalysisStore(
            self._workspace_root / ".research-loom" / _STORE_NAME
        )

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_survey_analysis_actions()
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_survey_analysis_actions()
        return super().submit_action(draft_input)

    def _ensure_survey_analysis_actions(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
            for action_type, payload_contract, operation in _SURVEY_ANALYSIS_ACTIONS:
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
                    existing[action_type] = action_registry.get(action_type)
                elif (
                    definition.payload_contract != payload_contract
                    or definition.effect != "read_only"
                    or definition.route_kind != "harness_service"
                    or definition.confirmation_required
                    or definition.service_id != action_type
                ):
                    raise LocalApplicationError(
                        "APPLICATION-SURVEY-ANALYSIS-ROUTE-001",
                        f"registered action conflicts with Survey analysis route: {action_type}",
                    )
                try:
                    service_registry.resolve(action_type)
                except ConversationRuntimeError as exc:
                    if exc.code != "CONV-ROUTE-001":
                        raise
                    service_registry.register(
                        action_type,
                        _SurveyAnalysisActionHandler(self._application, operation),
                    )

    def _load_dataset_exact(self, dataset_id: str, dataset_digest: str) -> dict[str, Any]:
        if not dataset_digest.startswith("sha256:"):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-DATASET-001",
                "dataset_digest must be a sha256 digest",
            )
        try:
            dataset = self._survey_response_store().load_dataset(self._project_id, dataset_id)
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if dataset is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-DATASET-001",
                "canonical SurveyResponseDataset was not found",
            )
        if str(dataset["content_digest"]) != dataset_digest:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-DATASET-001",
                "SurveyResponseDataset digest does not match the exact stored Dataset",
            )
        return dataset

    def _load_spec_exact(self, analysis_spec_id: str, analysis_spec_digest: str) -> dict[str, Any]:
        if not analysis_spec_digest.startswith("sha256:"):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001",
                "analysis_spec_digest must be a sha256 digest",
            )
        try:
            spec = self._survey_analysis_store().load_spec(
                self._project_id, analysis_spec_id
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if spec is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001",
                "SurveyAnalysisSpec was not found",
            )
        if str(spec["content_digest"]) != analysis_spec_digest:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001",
                "SurveyAnalysisSpec digest does not match the exact stored specification",
            )
        return spec

    def _questionnaire_for_dataset(self, dataset: Mapping[str, Any]) -> dict[str, Any]:
        instrument = dataset["instrument_ref"]
        questionnaire, resolved = self._resolve_instrument({
            "instrument_id": str(instrument["id"]),
            "instrument_version": str(instrument["version"]),
            "instrument_digest": str(instrument["content_digest"]),
        })
        if resolved != instrument:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-INSTRUMENT-001",
                "SurveyResponseDataset Instrument binding is inconsistent",
            )
        return questionnaire

    def _dataset_population(
        self,
        dataset: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        expected_instrument = dataset["instrument_ref"]
        for field, expected_status, target in (
            ("accepted_response_refs", "accepted", accepted),
            ("rejected_response_refs", "rejected", rejected),
        ):
            for ref in dataset[field]:
                try:
                    record = self._survey_response_store().load_response(
                        self._project_id,
                        str(ref["response_id"]),
                        identity_namespace=str(ref["identity_namespace"]),
                    )
                except LocalSurveyResponseStoreError as exc:
                    raise LocalApplicationError(exc.code, exc.message) from exc
                if record is None:
                    raise LocalApplicationError(
                        "APPLICATION-SURVEY-ANALYSIS-DATASET-001",
                        "SurveyResponseDataset response reference cannot be resolved",
                    )
                response = deepcopy(dict(record["response"]))
                if (
                    str(response["content_digest"]) != str(ref["content_digest"])
                    or str(response["validation"]["status"]) != expected_status
                    or response["instrument_ref"] != expected_instrument
                    or response["response_origin"] != dataset["response_origin"]
                    or response["epistemic_status"] != dataset["epistemic_status"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-SURVEY-ANALYSIS-DATASET-001",
                        "SurveyResponseDataset contains stale or mixed canonical response content",
                    )
                target.append(response)
        if len(accepted) != int(dataset["accepted_count"]):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-DATASET-001",
                "SurveyResponseDataset accepted population does not resolve exactly",
            )
        return accepted, rejected

    def capture_survey_analysis_spec(
        self,
        input_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        value = input_object(
            input_value,
            _ANALYSIS_SPEC_CAPTURE_FIELDS,
            "Survey analysis specification capture",
        )
        dataset_id = required_string(value, "dataset_id")
        dataset_digest = required_string(value, "dataset_digest")
        dataset = self._load_dataset_exact(dataset_id, dataset_digest)
        questionnaire = self._questionnaire_for_dataset(dataset)
        try:
            analysis_items = normalize_analysis_items(
                questionnaire, value.get("analysis_items")
            )
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001", str(exc)
            ) from exc

        document: dict[str, Any] = {
            "schema_version": "0.1.0",
            "object_type": "survey_analysis_spec",
            "project_id": self._project_id,
            "dataset_ref": {
                "id": dataset_id,
                "content_digest": dataset_digest,
            },
            "instrument_ref": deepcopy(dict(dataset["instrument_ref"])),
            "analysis_items": analysis_items,
            "created_at": self._application.clock.now(),
        }
        document["content_digest"] = analysis_spec_content_digest(document)
        document["analysis_spec_id"] = stable_identity(
            "SAS-", document["content_digest"]
        )
        document["registry_digest"] = registry_digest(document)
        try:
            validate_analysis_spec(document)
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001", str(exc)
            ) from exc

        state = self._state()
        before = _snapshot(state)
        try:
            created = self._capture(
                state,
                lambda: self._survey_analysis_store().capture_spec(document),
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        after = _snapshot(self._state())
        if before != after:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-STATE-MUTATION-001",
                "Survey analysis specification capture mutated authoritative Research State",
            )
        return {
            "status": "CAPTURED" if created else "ALREADY_CAPTURED",
            "project_id": self._project_id,
            "analysis_spec_id": document["analysis_spec_id"],
            "content_digest": document["content_digest"],
            "dataset_ref": deepcopy(document["dataset_ref"]),
            "instrument_ref": deepcopy(document["instrument_ref"]),
            "analysis_item_count": len(analysis_items),
            "research_state_mutation_performed": False,
        }

    def show_survey_analysis_spec(self, analysis_spec_id: str) -> Mapping[str, Any]:
        try:
            document = self._survey_analysis_store().load_spec(
                self._project_id, analysis_spec_id
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if document is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001",
                "SurveyAnalysisSpec was not found",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "analysis_spec": document,
            "research_state_mutation_performed": False,
        }

    def run_survey_aggregation(
        self,
        input_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        value = input_object(
            input_value, _AGGREGATE_RUN_FIELDS, "Survey aggregate run"
        )
        analysis_spec_id = required_string(value, "analysis_spec_id")
        analysis_spec_digest = required_string(value, "analysis_spec_digest")
        dataset_id = required_string(value, "dataset_id")
        dataset_digest = required_string(value, "dataset_digest")
        spec = self._load_spec_exact(analysis_spec_id, analysis_spec_digest)
        dataset = self._load_dataset_exact(dataset_id, dataset_digest)
        if spec["dataset_ref"] != {
            "id": dataset_id,
            "content_digest": dataset_digest,
        }:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001",
                "SurveyAnalysisSpec is stale or bound to a different Dataset",
            )
        if spec["instrument_ref"] != dataset["instrument_ref"]:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-INSTRUMENT-001",
                "SurveyAnalysisSpec and Dataset are bound to different Instrument revisions",
            )
        questionnaire = self._questionnaire_for_dataset(dataset)
        try:
            normalized_items = normalize_analysis_items(
                questionnaire, spec["analysis_items"]
            )
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001", str(exc)
            ) from exc
        if normalized_items != spec["analysis_items"]:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-SPEC-001",
                "stored SurveyAnalysisSpec no longer matches Instrument semantics",
            )
        accepted, rejected = self._dataset_population(dataset)
        try:
            result = aggregate_dataset(
                questionnaire,
                dataset,
                accepted,
                rejected,
                spec,
                generated_at=self._application.clock.now(),
            )
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-AGGREGATE-001", str(exc)
            ) from exc

        state = self._state()
        before = _snapshot(state)
        try:
            created = self._capture(
                state,
                lambda: self._survey_analysis_store().capture_result(result),
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        after = _snapshot(self._state())
        if before != after:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-STATE-MUTATION-001",
                "Survey aggregation mutated authoritative Research State",
            )
        return {
            "status": "CAPTURED" if created else "ALREADY_CAPTURED",
            "project_id": self._project_id,
            "aggregate_result_id": result["aggregate_result_id"],
            "content_digest": result["content_digest"],
            "analysis_spec_ref": deepcopy(result["analysis_spec_ref"]),
            "dataset_ref": deepcopy(result["dataset_ref"]),
            "instrument_ref": deepcopy(result["instrument_ref"]),
            "response_origin": result["response_origin"],
            "epistemic_status": result["epistemic_status"],
            "population": deepcopy(result["population"]),
            "exclusions": deepcopy(result["exclusions"]),
            "warnings": deepcopy(result["warnings"]),
            "research_state_mutation_performed": False,
        }

    def show_survey_aggregate_result(
        self,
        aggregate_result_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> Mapping[str, Any]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-INPUT-001",
                "limit must be an integer from 1 through 100",
            )
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-ANALYSIS-INPUT-001",
                "offset must be a non-negative integer",
            )
        try:
            document = self._survey_analysis_store().load_result(
                self._project_id, aggregate_result_id
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if document is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-AGGREGATE-001",
                "SurveyAggregateResult was not found",
            )
        items = list(document["result_items"])
        summary = deepcopy(document)
        summary.pop("result_items", None)
        page = deepcopy(items[offset : offset + limit])
        return {
            "status": "OK",
            "project_id": self._project_id,
            "aggregate_result": summary,
            "result_items": page,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(page),
                "total": len(items),
            },
            "research_state_mutation_performed": False,
        }
