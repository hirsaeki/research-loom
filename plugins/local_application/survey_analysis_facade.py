from __future__ import annotations

from copy import deepcopy
import hashlib
import json
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
from plugins.local_execution_store import (
    LocalExecutionStoreError,
    bind_controlled_import_root,
    read_controlled_file,
)
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
from .survey_response_capture import _real_response_provenance
from .survey_validation import input_object, required_string
from .virtual_runner_facade import LocalApplicationFacade as VirtualRunnerApplicationFacade
from .survey_virtual_pretest_inspection import SurveyVirtualPretestInspectionMixin

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
_VIRTUAL_PRETEST_COMPARE_FIELDS = {"run_a_id", "run_b_id", "aggregate_a_result_id", "aggregate_b_result_id"}
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

    def __init__(self, application, operation: str, *, workspace_root: Path | None = None) -> None:
        self._application = application
        self._operation = operation
        self._workspace_root = workspace_root

    def execute(self, payload, *, state, actor, proposal):
        facade = LocalApplicationFacade(
            self._application,
            state.project_ref,
            workspace_root=self._workspace_root,
        )
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


class LocalApplicationFacade(SurveyVirtualPretestInspectionMixin, VirtualRunnerApplicationFacade):
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
                        _SurveyAnalysisActionHandler(
                            self._application,
                            operation,
                            workspace_root=self._workspace_root,
                        ),
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
        response_keys = [
            (str(ref["identity_namespace"]), str(ref["response_id"]))
            for field in ("accepted_response_refs", "rejected_response_refs")
            for ref in dataset[field]
        ]
        try:
            records = self._survey_response_store().load_responses(
                self._project_id,
                response_keys,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        for field, expected_status, target in (
            ("accepted_response_refs", "accepted", accepted),
            ("rejected_response_refs", "rejected", rejected),
        ):
            for ref in dataset[field]:
                key = (str(ref["identity_namespace"]), str(ref["response_id"]))
                record = records.get(key)
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

    def _real_intake_file(self, locator: str) -> tuple[bytes, str]:
        workspace_root = self._workspace_root
        if workspace_root is None:
            root = getattr(self._application, "root", None)
            if root is None:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-REAL-INTAKE-FILE-001",
                    "REAL Survey intake requires a local workspace root",
                )
            workspace_root = Path(root)
        relative = Path(locator)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-FILE-001",
                "REAL Survey intake file must be a workspace-relative path without traversal",
            )
        source_path = workspace_root.joinpath(relative)
        bind_controlled_import_root(self._application.execution_store, workspace_root)
        try:
            content = read_controlled_file(
                self._application.execution_store,
                source_path,
                max_bytes=_MAX_REAL_INTAKE_BYTES,
            )
        except (OSError, PermissionError, ValueError, LocalExecutionStoreError) as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-FILE-001",
                "REAL Survey intake file must be an allowed regular workspace file",
            ) from exc
        return content, "sha256:" + hashlib.sha256(content).hexdigest()

    @staticmethod
    def _canonical_raw(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _verified_real_dataset_reuse(
        self,
        dataset: Mapping[str, Any],
        *,
        instrument_ref: Mapping[str, str],
        provenance: Mapping[str, Any],
        raw_inputs: list[Any],
    ) -> Mapping[str, Any]:
        if (
            str(dataset.get("project_id")) != self._project_id
            or dataset.get("instrument_ref") != dict(instrument_ref)
            or dataset.get("response_origin") != "real"
            or dataset.get("epistemic_status") != "EMPIRICAL"
            or dataset.get("capture_origin") != "survey_real_intake"
            or dataset.get("source_provenance") != dict(provenance)
            or int(dataset.get("response_count", -1)) != len(raw_inputs)
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-REUSE-001",
                "existing REAL Survey Dataset does not match the exact intake identity",
            )

        refs = list(dataset["accepted_response_refs"]) + list(dataset["rejected_response_refs"])
        response_keys = [
            (str(ref["identity_namespace"]), str(ref["response_id"]))
            for ref in refs
        ]
        try:
            loaded = self._survey_response_store().load_responses(
                self._project_id,
                response_keys,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if len(loaded) != len(response_keys):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-REUSE-001",
                "existing REAL Survey Dataset response set is incomplete",
            )

        stored_raw_inputs = [deepcopy(item["raw_input"]) for item in loaded.values()]
        stored_raw_inputs.extend(
            deepcopy(item["raw_input"])
            for item in dataset["rejected_inputs"]
            if not item.get("canonical_response_ref")
        )
        if sorted(self._canonical_raw(item) for item in stored_raw_inputs) != sorted(
            self._canonical_raw(item) for item in raw_inputs
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-REUSE-001",
                "existing REAL Survey Dataset raw responses do not match the intake file",
            )
        for ref in refs:
            key = (str(ref["identity_namespace"]), str(ref["response_id"]))
            stored = loaded[key]["response"]
            expected_provenance = {"intake_format": provenance["intake_format"]}
            producer = loaded[key]["raw_input"].get("provenance")
            if isinstance(producer, Mapping):
                expected_provenance["producer"] = deepcopy(dict(producer))
            if (
                str(stored["content_digest"]) != str(ref["content_digest"])
                or stored["instrument_ref"] != dict(instrument_ref)
                or stored["response_origin"] != "real"
                or stored["epistemic_status"] != "EMPIRICAL"
                or _real_response_provenance(stored["source_provenance"]) != expected_provenance
            ):
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-REAL-INTAKE-REUSE-001",
                    "existing REAL Survey Dataset canonical response binding does not match the intake file",
                )
        return self._dataset_capture_result(dataset, status="ALREADY_CAPTURED")

    def capture_real_survey_intake(
        self,
        input_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        value = input_object(
            input_value,
            _REAL_INTAKE_CAPTURE_FIELDS,
            "Survey REAL intake capture",
        )
        locator = required_string(value, "file")
        content, file_digest = self._real_intake_file(locator)
        try:
            document = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-FORMAT-001",
                "REAL Survey interchange must be UTF-8 JSON",
            ) from exc
        if (
            not isinstance(document, Mapping)
            or set(document) != {"responses"}
            or not isinstance(document["responses"], list)
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-FORMAT-001",
                "REAL Survey interchange must be an object containing only a responses array",
            )

        instrument_id = required_string(value, "instrument_id")
        instrument_version = required_string(value, "instrument_version")
        instrument_digest = required_string(value, "instrument_digest")
        _, resolved_instrument = self._resolve_instrument(
            {
                "instrument_id": instrument_id,
                "instrument_version": instrument_version,
                "instrument_digest": instrument_digest,
            }
        )
        intake_format = "provider-neutral-json@0.1.0"
        identity_material = json.dumps(
            {
                "intake_format": intake_format,
                "intake_file": locator,
                "file_digest": file_digest,
                "instrument_id": instrument_id,
                "instrument_version": instrument_version,
                "instrument_digest": instrument_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        dataset_id = "SRD-REAL-" + hashlib.sha256(identity_material).hexdigest()[:32]
        provenance = {
            "intake_format": intake_format,
            "intake_file": locator,
            "intake_file_digest": file_digest,
        }
        raw_inputs = deepcopy(document["responses"])
        try:
            existing = self._survey_response_store().load_dataset(
                self._project_id,
                dataset_id,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if existing is not None:
            dataset_capture = self._verified_real_dataset_reuse(
                existing,
                instrument_ref=resolved_instrument,
                provenance=provenance,
                raw_inputs=raw_inputs,
            )
        else:
            try:
                dataset_capture = self._capture_dataset(
                    {
                        "instrument_id": instrument_id,
                        "instrument_version": instrument_version,
                        "instrument_digest": instrument_digest,
                        "response_origin": "real",
                        "epistemic_status": "EMPIRICAL",
                        "responses": raw_inputs,
                        "capture_origin": "survey_real_intake",
                        "source_provenance": provenance,
                    },
                    dataset_id=dataset_id,
                    reuse_real_responses=True,
                )
            except LocalApplicationError as exc:
                if exc.code != "SURVEY-RESPONSE-DATASET-IMMUTABLE-001":
                    raise
                try:
                    raced = self._survey_response_store().load_dataset(
                        self._project_id,
                        dataset_id,
                    )
                except LocalSurveyResponseStoreError as store_exc:
                    raise LocalApplicationError(store_exc.code, store_exc.message) from store_exc
                if raced is None:
                    raise
                dataset_capture = self._verified_real_dataset_reuse(
                    raced,
                    instrument_ref=resolved_instrument,
                    provenance=provenance,
                    raw_inputs=raw_inputs,
                )

        spec = self.capture_survey_analysis_spec(
            {
                "dataset_id": dataset_capture["dataset_id"],
                "dataset_digest": dataset_capture["content_digest"],
                "analysis_items": value.get("analysis_items"),
            }
        )
        aggregate = self.run_survey_aggregation(
            {
                "analysis_spec_id": spec["analysis_spec_id"],
                "analysis_spec_digest": spec["content_digest"],
                "dataset_id": dataset_capture["dataset_id"],
                "dataset_digest": dataset_capture["content_digest"],
            }
        )
        return {
            "status": (
                "CAPTURED"
                if dataset_capture["status"] == "CAPTURED"
                else "ALREADY_CAPTURED"
            ),
            "project_id": self._project_id,
            "intake_source": deepcopy(provenance),
            "instrument_ref": deepcopy(dataset_capture["instrument_ref"]),
            "dataset_id": dataset_capture["dataset_id"],
            "content_digest": dataset_capture["content_digest"],
            "dataset_ref": {
                "id": dataset_capture["dataset_id"],
                "content_digest": dataset_capture["content_digest"],
            },
            "aggregate_result_id": aggregate["aggregate_result_id"],
            "aggregate_ref": {
                "id": aggregate["aggregate_result_id"],
                "content_digest": aggregate["content_digest"],
            },
            "accepted_count": dataset_capture["accepted_count"],
            "rejected_count": dataset_capture["rejected_count"],
            "validation_summary": deepcopy(dataset_capture["validation_summary"]),
            "response_origin": "real",
            "epistemic_status": "EMPIRICAL",
            "candidate_interpretation": {
                "status": "candidate_research_material",
                "aggregate_result_id": aggregate["aggregate_result_id"],
                "authoritative_finding_created": False,
            },
            "research_state_mutation_performed": False,
        }

    def show_real_survey_intake(
        self,
        dataset_id: str,
        *,
        aggregate_result_id: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Mapping[str, Any]:
        shown = self.show_survey_response_dataset(
            dataset_id,
            limit=limit,
            offset=offset,
        )
        dataset = shown["dataset"]
        if (
            dataset.get("response_origin") != "real"
            or dataset.get("epistemic_status") != "EMPIRICAL"
        ):
            raise LocalApplicationError(
                "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                "REAL Survey intake inspection requires an EMPIRICAL real Dataset",
            )
        if dataset.get("capture_origin") != "survey_real_intake":
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-001",
                "Dataset was not produced by the REAL Survey intake path",
            )
        try:
            candidates = self._survey_analysis_store().find_results_by_dataset(
                self._project_id,
                dataset_id,
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if aggregate_result_id is None:
            if len(candidates) != 1:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-REAL-INTAKE-AGGREGATE-001",
                    "aggregate_result_id is required unless exactly one aggregate result exists",
                )
            aggregate_result_id = str(candidates[0]["aggregate_result_id"])
        aggregate = self.show_survey_aggregate_result(
            aggregate_result_id,
            limit=limit,
            offset=offset,
        )
        if aggregate["aggregate_result"]["dataset_ref"] != {
            "id": dataset_id,
            "content_digest": dataset["content_digest"],
        }:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-REAL-INTAKE-AGGREGATE-001",
                "SurveyAggregateResult is not bound to the exact REAL intake Dataset",
            )

        response_keys = [
            (str(ref["identity_namespace"]), str(ref["response_id"]))
            for entry in shown["entries"]
            if (ref := entry.get("response_ref")) is not None
        ]
        try:
            records = self._survey_response_store().load_responses(
                self._project_id,
                response_keys,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc

        joined = []
        for entry in shown["entries"]:
            item = deepcopy(entry)
            ref = item.get("response_ref")
            if ref is not None:
                key = (str(ref["identity_namespace"]), str(ref["response_id"]))
                record = records.get(key)
                if record is None:
                    raise LocalApplicationError(
                        "APPLICATION-SURVEY-REAL-INTAKE-001",
                        "Dataset response reference cannot be resolved",
                    )
                item["raw_input"] = deepcopy(record["raw_input"])
                item["canonical_response"] = deepcopy(record["response"])
            joined.append(item)
        return {
            "status": "OK",
            "project_id": self._project_id,
            "intake_source": deepcopy(dataset["source_provenance"]),
            "instrument_ref": deepcopy(dataset["instrument_ref"]),
            "response_origin": dataset["response_origin"],
            "epistemic_status": dataset["epistemic_status"],
            "accepted_count": dataset["accepted_count"],
            "rejected_count": dataset["rejected_count"],
            "validation_summary": deepcopy(dataset["validation_summary"]),
            "dataset": dataset,
            "responses": joined,
            "response_pagination": shown["pagination"],
            "aggregate_result": aggregate["aggregate_result"],
            "aggregate_items": aggregate["result_items"],
            "aggregate_pagination": aggregate["pagination"],
            "candidate_interpretation": {
                "status": "candidate_research_material",
                "aggregate_result_id": aggregate_result_id,
                "authoritative_finding_created": False,
            },
            "research_state_mutation_performed": False,
        }

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
