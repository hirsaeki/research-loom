"""Real survey intake capture and inspection (#494)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from plugins.application_errors import LocalApplicationError
from plugins.local_execution_store import (
    LocalExecutionStoreError,
    bind_controlled_import_root,
    read_controlled_file,
)
from plugins.local_survey_analysis_store import (
    LocalSurveyAnalysisStoreError,
)
from plugins.local_survey_response_store import LocalSurveyResponseStoreError
from plugins.survey_validation import input_object, required_string

from .survey_analysis_actions import (
    _MAX_REAL_INTAKE_BYTES,
    _REAL_INTAKE_CAPTURE_FIELDS,
)
from .survey_response_capture import _real_response_provenance


class SurveyRealIntakeMixin:
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
        response_keys = [(str(ref["identity_namespace"]), str(ref["response_id"])) for ref in refs]
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
                "CAPTURED" if dataset_capture["status"] == "CAPTURED" else "ALREADY_CAPTURED"
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
