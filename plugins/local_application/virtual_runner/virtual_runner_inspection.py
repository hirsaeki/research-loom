from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from plugins.application_errors import LocalApplicationError


def show_run_stage(facade, proceed: Callable[..., Any], run_id: str) -> Mapping[str, Any]:
    result = deepcopy(dict(proceed(run_id)))
    run = result.get("run")
    if not isinstance(run, Mapping) or run.get("capability_id") != "virtual-runner":
        return result
    metas = [
        meta
        for meta in facade._application.execution_store.artifacts_for(str(run_id))
        if meta.role == "survey_virtual.virtual_runner_result"
    ]
    if not metas and run.get("status") != "COMPLETED":
        return result
    if len(metas) != 1:
        raise LocalApplicationError(
            "APPLICATION-RUN-INSPECTION-001",
            "completed Virtual Runner Run must have exactly one persisted result artifact",
        )
    payload = facade._application.execution_store.load_artifact(metas[0].artifact_id)
    try:
        extension = json.loads(payload.content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-RUN-INSPECTION-001", "Virtual Runner result artifact is unreadable"
        ) from exc
    if not isinstance(extension, Mapping):
        raise LocalApplicationError(
            "APPLICATION-RUN-INSPECTION-001", "Virtual Runner result artifact is malformed"
        )
    response_dataset = None
    aggregate_result = None
    if hasattr(facade, "_survey_response_store"):
        response_store = facade._survey_response_store()
        response_dataset = response_store.load_dataset(facade._project_id, f"SRD-{run_id}")
        if response_dataset is None:
            legacy_datasets = response_store.find_datasets_by_source_run(
                facade._project_id, str(run_id)
            )
            if len(legacy_datasets) > 1:
                raise LocalApplicationError(
                    "APPLICATION-RUN-INSPECTION-001",
                    "Virtual Runner Run resolves to multiple Survey response datasets",
                )
            response_dataset = legacy_datasets[0] if legacy_datasets else None
        if response_dataset is not None and hasattr(facade, "_survey_analysis_store"):
            aggregates = facade._survey_analysis_store().find_results_by_dataset(
                facade._project_id, str(response_dataset["dataset_id"])
            )
            if aggregates:
                aggregate_result = aggregates[-1]
    # The artifact is runner-written; a missing or mistyped field means it is
    # malformed, reported like an unreadable or non-object artifact above.
    try:
        virtual_result = extension["virtual_runner_result"]
        generated_attempts = extension.get("generation_attempts", [])
        result["virtual_runner"] = {
            "execution_mode": "virtual",
            "scenario_class": virtual_result["scenario_class"],
            "evidence_status": extension["evidence_status"],
            "completion_status": virtual_result["completion_status"],
            "input_pins": deepcopy(extension["input_pins"]),
            "synthetic_population": deepcopy(extension["synthetic_population"]),
            "generation_provenance": deepcopy(extension["generation_provenance"]),
            "generator_backend": extension.get("generator_backend", "structural"),
            "respondent_plan": deepcopy(extension.get("respondent_plan")),
            "generation_attempts": deepcopy(extension.get("generation_attempts", [])),
            "generation_summary": {
                "requested": len((extension.get("respondent_plan") or {}).get("profile_ids", [])),
                "generated": sum(
                    1 for item in generated_attempts if item.get("status") == "generated"
                ),
                "valid": None
                if response_dataset is None
                else int(response_dataset["accepted_count"]),
                "rejected": None
                if response_dataset is None
                else int(response_dataset["rejected_count"]),
                "failed": sum(1 for item in generated_attempts if item.get("status") == "failed"),
            },
            "response_dataset_ref": None
            if response_dataset is None
            else {
                "dataset_id": response_dataset["dataset_id"],
                "content_digest": response_dataset["content_digest"],
            },
            "aggregate_result_ref": None
            if aggregate_result is None
            else {
                "aggregate_result_id": aggregate_result["aggregate_result_id"],
                "content_digest": aggregate_result["content_digest"],
            },
            "synthetic_outputs": deepcopy(virtual_result["synthetic_outputs"]),
            "validation_failures": deepcopy(extension["validation_failures"]),
            "preservation_events": deepcopy(extension["preservation_events"]),
            "defects": deepcopy(extension["defects"]),
            "warnings": deepcopy(extension["warnings"]),
            "unresolved_ambiguities": deepcopy(virtual_result["unresolved_ambiguities"]),
            "candidate_change_requests": deepcopy(extension["candidate_change_requests"]),
            "readiness_assessment": deepcopy(extension["readiness_assessment"]),
            "execution_trace": deepcopy(virtual_result["execution_trace"]),
            "research_state_mutation_performed": False,
            "real_execution_started": False,
        }
    except (KeyError, TypeError, AttributeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-RUN-INSPECTION-001", "Virtual Runner result artifact is malformed"
        ) from exc
    return result


class VirtualRunnerInspectionMixin:
    """Virtual Runner run inspection now lives in ``show_run_stage`` below."""

    _STAGES = {
        "show_run": show_run_stage,
    }
