from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Any, Mapping

from plugins.local_survey_response_store import LocalSurveyResponseStoreError
from plugins.survey_response import (
    append_rejection_issue, dataset_content_digest, normalize_response,
    registry_digest, validate_dataset, virtual_record_to_raw,
)
from .facade import LocalApplicationError
from .survey_facade import _snapshot
from .survey_response_core import _DATASET_FIELDS, _RESPONSE_FIELDS, _status_value
from .survey_validation import capture_origin, input_object


def _issue(code: str, message: str, *, response_id: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if response_id:
        value["response_id"] = response_id
    return value


class SurveyResponseCaptureMixin:
    def _capture_dataset(
        self,
        input_value: Mapping[str, Any],
        *,
        enforce_unique_participant: bool = False,
    ) -> Mapping[str, Any]:
        value = input_object(input_value, _DATASET_FIELDS, "Survey response dataset capture")
        questionnaire, instrument_ref = self._resolve_instrument(value)
        origin, epistemic = self._origin(value)
        source_run_id = self._source_run(value, origin=origin)
        provenance = self._source_provenance(value)
        raw_inputs = value.get("responses")
        if not isinstance(raw_inputs, list):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "responses must be an array",
            )

        state = self._state()
        ingested_at = self._application.clock.now()
        outcomes: list[dict[str, Any]] = []
        for raw in raw_inputs:
            outcomes.append(
                normalize_response(
                    questionnaire,
                    raw,
                    project_id=self._project_id,
                    instrument_ref=instrument_ref,
                    response_origin=origin,
                    epistemic_status=epistemic,
                    ingested_at=ingested_at,
                    source_run_id=source_run_id,
                    source_provenance=provenance,
                )
            )

        seen_response_keys: set[tuple[str, str]] = set()
        seen_participants: set[tuple[str, str]] = set()
        persistable: list[tuple[Mapping[str, Any], Any]] = []
        accepted_refs: list[dict[str, str]] = []
        rejected_refs: list[dict[str, str]] = []
        rejected_inputs: list[dict[str, Any]] = []
        issue_counts: Counter[str] = Counter()

        for outcome in outcomes:
            response = outcome["canonical_response"]
            issues = list(outcome["issues"])
            raw = outcome["raw_input"]
            raw_response_key = (
                (str(raw["identity_namespace"]), str(raw["response_id"]))
                if isinstance(raw, Mapping)
                and isinstance(raw.get("identity_namespace"), str)
                and raw["identity_namespace"]
                and isinstance(raw.get("response_id"), str)
                and raw["response_id"]
                else None
            )
            duplicate_response_id = (
                raw_response_key is not None
                and raw_response_key in seen_response_keys
            )
            if raw_response_key is not None and not duplicate_response_id:
                seen_response_keys.add(raw_response_key)

            if response is None:
                if duplicate_response_id:
                    issues.append(
                        _issue(
                            "SURVEY_RESPONSE_DUPLICATE_RECORD",
                            "response_id is duplicated within the Dataset intake",
                            response_id=raw_response_key[1] if raw_response_key else None,
                        )
                    )
                for issue in issues:
                    issue_counts[str(issue["code"])] += 1
                rejected_inputs.append(
                    {
                        "raw_input_digest": outcome["raw_input_digest"],
                        "raw_input": deepcopy(raw),
                        "issues": deepcopy(issues),
                    }
                )
                continue

            response_id = str(response["response_id"])
            if duplicate_response_id:
                duplicate = _issue(
                    "SURVEY_RESPONSE_DUPLICATE_RECORD",
                    "response_id is duplicated within the Dataset intake",
                    response_id=response_id,
                )
                issues = issues + [duplicate]
                for issue in issues:
                    issue_counts[str(issue["code"])] += 1
                rejected_inputs.append(
                    {
                        "raw_input_digest": outcome["raw_input_digest"],
                        "raw_input": deepcopy(raw),
                        "issues": deepcopy(issues),
                    }
                )
                continue

            if enforce_unique_participant:
                participant = (
                    str(response["identity_namespace"]),
                    str(response["participant_id"]),
                )
                if participant in seen_participants:
                    response = append_rejection_issue(
                        response,
                        _issue(
                            "SURVEY_RESPONSE_DUPLICATE_IDENTITY",
                            "participant identity is duplicated where one response per respondent is required",
                            response_id=response_id,
                        ),
                    )
                seen_participants.add(participant)

            response_issues = list(response["validation"]["issues"])
            for issue in response_issues:
                issue_counts[str(issue["code"])] += 1
            ref = {
                "response_id": response_id,
                "identity_namespace": str(response["identity_namespace"]),
                "content_digest": str(response["content_digest"]),
            }
            persistable.append((response, raw))
            if response["validation"]["status"] == "accepted":
                accepted_refs.append(ref)
            else:
                rejected_refs.append(ref)
                rejected_inputs.append(
                    {
                        "raw_input_digest": outcome["raw_input_digest"],
                        "raw_input": deepcopy(raw),
                        "canonical_response_ref": deepcopy(ref),
                        "issues": deepcopy(response_issues),
                    }
                )

        accepted_refs.sort(key=lambda item: (item["identity_namespace"], item["response_id"], item["content_digest"]))
        rejected_refs.sort(key=lambda item: (item["identity_namespace"], item["response_id"], item["content_digest"]))
        rejected_inputs.sort(key=lambda item: item["raw_input_digest"])
        source_run_ids = sorted({source_run_id} if source_run_id else set())
        created_at = self._application.clock.now()
        dataset: dict[str, Any] = {
            "schema_version": "0.1.0",
            "object_type": "survey_response_dataset",
            "project_id": self._project_id,
            "dataset_id": (f"SRD-{source_run_id}" if source_run_id and origin == "synthetic" else self._application.ids.new("SRD-")),
            "instrument_ref": instrument_ref,
            "response_origin": origin,
            "epistemic_status": epistemic,
            "accepted_response_refs": accepted_refs,
            "rejected_response_refs": rejected_refs,
            "rejected_inputs": rejected_inputs,
            "response_count": len(raw_inputs),
            "accepted_count": len(accepted_refs),
            "rejected_count": len(rejected_inputs),
            "created_at": created_at,
            "captured_against": _snapshot(state),
            "project_config_digest": str(state.project_config_digest),
            "effective_profile_set_digest": str(state.effective_profile_set_digest),
            "capture_origin": capture_origin(value),
            "source_run_ids": source_run_ids,
            "source_provenance": provenance,
            "validation_summary": {
                "issue_count": sum(issue_counts.values()),
                "issue_code_counts": dict(sorted(issue_counts.items())),
            },
            "research_state_mutation_performed": False,
        }
        dataset["content_digest"] = dataset_content_digest(dataset)
        dataset["registry_digest"] = registry_digest(dataset)
        try:
            validate_dataset(dataset)
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-DATASET-001",
                str(exc),
            ) from exc

        before = _snapshot(state)
        try:
            created = self._capture(
                state,
                lambda: self._survey_response_store().capture_dataset(
                    dataset,
                    persistable,
                ),
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        after = _snapshot(self._state())
        if before != after:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-STATE-MUTATION-001",
                "Survey response capture mutated authoritative Research State",
            )
        return {
            "status": "CAPTURED" if created else "ALREADY_CAPTURED",
            "project_id": self._project_id,
            "dataset_id": dataset["dataset_id"],
            "content_digest": dataset["content_digest"],
            "instrument_ref": instrument_ref,
            "response_origin": origin,
            "epistemic_status": epistemic,
            "response_count": dataset["response_count"],
            "accepted_count": dataset["accepted_count"],
            "rejected_count": dataset["rejected_count"],
            "validation_summary": deepcopy(dataset["validation_summary"]),
            "source_run_ids": source_run_ids,
            "captured_against": deepcopy(dataset["captured_against"]),
            "research_state_mutation_performed": False,
        }

    def capture_survey_response_dataset(
        self,
        input_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._capture_dataset(input_value)

    def capture_survey_response(
        self,
        input_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        value = input_object(input_value, _RESPONSE_FIELDS, "Survey response capture")
        dataset_input = {key: deepcopy(item) for key, item in value.items() if key != "response"}
        dataset_input["responses"] = [deepcopy(value.get("response"))]
        result = dict(self._capture_dataset(dataset_input))
        response_id = None
        raw = value.get("response")
        if isinstance(raw, Mapping) and isinstance(raw.get("response_id"), str):
            response_id = raw["response_id"]
        result["response_id"] = response_id
        return result

    def capture_virtual_run_response_dataset(
        self,
        run_id: str,
        *,
        instrument_ref: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        run = self._application.execution_store.load_run(run_id)
        if run is None or str(run.project_ref) != self._project_id:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "Virtual Runner source Run was not found",
            )
        if _status_value(run.status) != "COMPLETED" or _status_value(run.execution_mode) != "virtual":
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "Survey response Dataset can only be captured from a completed virtual Run",
            )
        artifact_id = f"ART-VR-RESP-{run_id}"
        artifacts = {
            item.artifact_id: item
            for item in self._application.execution_store.artifacts_for(run_id)
        }
        metadata = artifacts.get(artifact_id)
        if metadata is None or metadata.role != "survey_virtual.synthetic_responses":
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "Virtual Runner response artifact is missing or has the wrong role",
            )
        provenance = dict(metadata.provenance)
        if provenance.get("instrument_digest") != instrument_ref.get("content_digest"):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001",
                "Virtual Runner response artifact Instrument digest does not match the pinned Instrument",
            )
        try:
            batch = json.loads(
                self._application.execution_store.load_artifact(artifact_id).content.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "Virtual Runner response artifact is not valid UTF-8 JSON",
            ) from exc
        if (
            not isinstance(batch, Mapping)
            or batch.get("object_type") != "survey_virtual_response_batch"
            or batch.get("evidence_status") != "SYNTHETIC_TEST_ONLY"
            or not isinstance(batch.get("responses"), list)
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "Virtual Runner response artifact does not satisfy the PR41 response batch boundary",
            )
        payload = {
            "instrument_id": str(instrument_ref["id"]),
            "instrument_version": str(instrument_ref["version"]),
            "instrument_digest": str(instrument_ref["content_digest"]),
            "response_origin": "synthetic",
            "epistemic_status": "SYNTHETIC_TEST_ONLY",
            "responses": [virtual_record_to_raw(item) for item in batch["responses"]],
            "source_run_id": run_id,
            "source_provenance": {
                "producer": (
                    "survey_virtual_runner.llm@1.0.0"
                    if provenance.get("generator_backend") == "llm"
                    else "survey_virtual_runner.structural@0.1.0"
                ),
                "response_artifact_id": artifact_id,
                "response_artifact_digest": metadata.digest,
                "scenario_class": batch.get("scenario_class"),
                "generator_backend": provenance.get("generator_backend", "structural"),
            },
            "capture_origin": "survey_virtual_runner",
        }
        return self._capture_dataset(payload, enforce_unique_participant=True)
