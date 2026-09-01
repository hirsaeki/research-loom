from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from core.execution.models import CapabilityExecutionError

EXPECTED_CODES = {
    "required_missing": {"SURVEY_RESPONSE_REQUIRED_MISSING"},
    "invalid_choice": {"SURVEY_RESPONSE_INVALID_CHOICE", "SURVEY_RESPONSE_BRANCH_VIOLATION"},
    "out_of_range_scale": {"SURVEY_RESPONSE_OUT_OF_RANGE"},
    "branch_violation": {"SURVEY_RESPONSE_BRANCH_VIOLATION"},
    "duplicate_record": {"SURVEY_RESPONSE_DUPLICATE_RECORD"},
    "duplicate_identity": {"SURVEY_RESPONSE_DUPLICATE_IDENTITY"},
    "malformed_response": {"SURVEY_RESPONSE_MALFORMED"},
    "unknown": {"SURVEY_RESPONSE_MISSING_SEMANTICS"},
    "not_applicable": {"SURVEY_RESPONSE_MISSING_SEMANTICS"},
    "prefer_not_to_answer": {"SURVEY_RESPONSE_MISSING_SEMANTICS"},
}


def expected_issue_codes(faults: Sequence[str]) -> set[str]:
    result: set[str] = set()
    for fault in faults:
        result.update(EXPECTED_CODES.get(str(fault), ()))
    return result


def defects_from_issues(issues: Sequence[Mapping[str, Any]], *, run_id: str, instrument_id: str, expected_codes: set[str]) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    for index, item in enumerate(issues, start=1):
        code = str(item.get("code") or "SURVEY_RESPONSE_UNKNOWN")
        expected = code in expected_codes
        refs = [
            str(value) for value in (item.get("response_id"), item.get("response_key"))
            if isinstance(value, str) and value
        ]
        defects.append({
            "defect_id": f"VRDEF-{index:04d}",
            "taxonomy": "INSTRUMENT_DEFECT" if "BRANCH" in code or "CHOICE" in code else "EXECUTION_DEFECT",
            "severity": "major" if str(item.get("severity")) == "error" else "minor",
            "affected_ref": instrument_id,
            "detecting_run_id": run_id,
            "reproduction_refs": refs,
            "observed_behavior": str(item.get("message") or code),
            "expected_contract_behavior": "The exact pinned Survey response must satisfy canonical Survey response semantics.",
            "proposed_correction": (
                "No canonical change is required for an intentionally injected STRESS fault."
                if expected
                else "Review the pinned Instrument or runner implementation and revise only through the authoritative path if required."
            ),
            "disposition": "resolved" if expected else "open",
            "resolution_refs": [f"stress:{code}"] if expected else [],
        })
    return defects


def candidate_change_requests(defects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "change_request_id": f"VRCHG-{index:04d}",
            "target_ref": str(defect["affected_ref"]),
            "proposal": str(defect["proposed_correction"]),
            "authoritative_change_applied": False,
        }
        for index, defect in enumerate(defects, start=1)
        if defect.get("disposition") == "open"
    ]


def _freeze_signature(pins: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "project_id", "design", "instrument", "rq_ids", "evidence_gap_refs",
        "human_decision_bindings", "core_method", "protocol", "research_snapshot",
        "project_config_digest", "effective_profile_set_digest",
        "virtual_runner_descriptor", "runner_digest", "survey_binding_digest",
    )
    return {key: deepcopy(pins.get(key)) for key in keys}


def prior_scenarios(
    execution_store,
    prior_run_ids: Sequence[str],
    *,
    current_pins: Mapping[str, Any],
    current_project_ref: str,
) -> set[str]:
    scenarios: set[str] = set()
    expected = _freeze_signature(current_pins)
    for run_id in prior_run_ids:
        run = execution_store.load_run(str(run_id))
        if (
            run is None
            or str(run.project_ref) != str(current_project_ref)
            or run.status.value != "COMPLETED"
            or run.capability_id != "virtual-runner"
            or run.execution_mode != "virtual"
        ):
            raise CapabilityExecutionError(
                "VR-FREEZE-STALE-001",
                f"prior Virtual Run is missing, cross-project, incomplete, or incompatible: {run_id}",
            )
        context = execution_store.load_context_pack(run.context_pack_id)
        if (
            not isinstance(context, Mapping)
            or str(context.get("project_id")) != str(current_project_ref)
            or str(context.get("context_pack_digest")) != str(run.context_pack_digest)
        ):
            raise CapabilityExecutionError(
                "VR-FREEZE-STALE-001",
                f"prior Virtual Run Context Pack project/binding is incompatible: {run_id}",
            )
        metas = [
            meta
            for meta in execution_store.artifacts_for(str(run_id))
            if meta.role == "survey_virtual.virtual_runner_result"
        ]
        if len(metas) != 1:
            raise CapabilityExecutionError(
                "VR-FREEZE-STALE-001",
                f"prior Virtual Run has no exact persisted result: {run_id}",
            )
        try:
            extension = json.loads(
                execution_store.load_artifact(metas[0].artifact_id).content.decode("utf-8")
            )
        except Exception as exc:
            raise CapabilityExecutionError(
                "VR-FREEZE-STALE-001",
                f"prior Virtual Run result is unreadable: {run_id}",
            ) from exc
        if (
            not isinstance(extension, Mapping)
            or _freeze_signature(extension.get("input_pins", {})) != expected
        ):
            raise CapabilityExecutionError(
                "VR-FREEZE-STALE-001",
                f"prior Virtual Run input pins do not match the current freeze: {run_id}",
            )
        result = extension.get("virtual_runner_result")
        if (
            not isinstance(result, Mapping)
            or result.get("scenario_class") not in {"STANDARD", "STRESS"}
        ):
            raise CapabilityExecutionError(
                "VR-FREEZE-STALE-001",
                f"prior Virtual Run scenario is invalid: {run_id}",
            )
        scenarios.add(str(result["scenario_class"]))
    return scenarios


def readiness_assessment(*, scenario_class: str, prior: set[str], defects: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    completed = set(prior)
    completed.add(str(scenario_class))
    reasons: list[str] = []
    if policy.get("require_standard") and "STANDARD" not in completed:
        reasons.append("required STANDARD scenario has not completed under the same freeze")
    if policy.get("require_stress") and "STRESS" not in completed:
        reasons.append("required STRESS scenario has not completed under the same freeze")
    blocking = set(map(str, policy.get("blocking_severities", ())))
    open_blocking = [
        item
        for item in defects
        if item.get("disposition") == "open"
        and item.get("severity") in blocking
    ]
    if open_blocking:
        reasons.append("open blocking Virtual Runner defects remain")
    ready = not reasons
    if ready:
        reasons.append(
            "required virtual scenarios completed under matching pins with no open blocking defects"
        )
    return {
        "status": "CANDIDATE_READY" if ready else "CANDIDATE_BLOCKED",
        "candidate_only": True,
        "real_execution_started": False,
        "reasons": reasons,
    }
