from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from plugins.local_application.facade import LocalApplicationError

_DEFAULT_LIMITS = {
    "max_questions": 64,
    "max_research_object_references": 128,
    "max_resources": 0,
    "max_attention_items": 128,
    "max_project_guards": 128,
    "max_effective_constraints": 256,
}
_PROFILE_PIN_FIELDS = (
    "profile_id",
    "profile_type",
    "profile_version",
    "manifest_sha256",
)
_ALLOWED_PAYLOAD = {
    "instrument_id", "instrument_version", "instrument_digest", "scenario_class",
    "core_method_id", "core_method_revision", "protocol", "evidence_gap_refs",
    "run_spec_id", "run_spec_version", "population_size", "sampling_seed",
    "stress_faults", "readiness_policy", "prior_virtual_run_ids",
    "synthetic_population", "purpose",
}
_ALLOWED_STRESS_FAULTS = {
    "required_missing", "optional_missing", "invalid_choice", "out_of_range_scale",
    "branch_violation", "duplicate_record", "duplicate_identity", "partial_completion",
    "malformed_response", "extreme_valid", "unknown", "not_applicable",
    "prefer_not_to_answer",
}

def _payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "virtual_runner.survey.execute payload must be an object")
    unknown = set(payload) - _ALLOWED_PAYLOAD
    if unknown:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "unsupported or authority-like Virtual Runner payload fields: " + ", ".join(sorted(map(str, unknown))))
    required = {"instrument_id", "instrument_version", "instrument_digest", "scenario_class", "core_method_id", "core_method_revision", "protocol", "evidence_gap_refs", "run_spec_id", "run_spec_version"}
    missing = sorted(required - set(payload))
    if missing:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "missing Virtual Runner payload fields: " + ", ".join(missing))
    if payload["scenario_class"] not in {"STANDARD", "STRESS"}:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "scenario_class must be STANDARD or STRESS")
    for field in ("instrument_id", "instrument_version", "instrument_digest", "core_method_id", "run_spec_id", "run_spec_version"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", f"{field} must be a non-empty string")
    if not isinstance(payload.get("core_method_revision"), int) or payload["core_method_revision"] < 0:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "core_method_revision must be a non-negative integer")
    protocol = payload.get("protocol")
    required_protocol = {"protocol_id", "version", "content_digest", "approval_status", "material_revision"}
    if not isinstance(protocol, Mapping) or not required_protocol.issubset(protocol) or set(protocol) - (required_protocol | {"material_revision_decision_id"}):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "protocol must carry an exact approved id/version/digest and any required material-revision decision binding")
    if protocol["approval_status"] != "approved" or not isinstance(protocol["material_revision"], bool):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "Virtual Runner requires an approved Protocol pin")
    if protocol["material_revision"] and not protocol.get("material_revision_decision_id"):
        raise LocalApplicationError("VR-HUMAN-DECISION-001", "material Protocol revision requires material_revision_decision_id")
    gaps = payload.get("evidence_gap_refs")
    if not isinstance(gaps, list) or not gaps:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "Research Method execute contract requires at least one exact Evidence Gap reference")
    population_size = payload.get("population_size", 8)
    if not isinstance(population_size, int) or isinstance(population_size, bool) or not 1 <= population_size <= 128:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "population_size must be an integer from 1 through 128")
    faults = payload.get("stress_faults", [])
    if not isinstance(faults, list) or any(item not in _ALLOWED_STRESS_FAULTS for item in faults):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "stress_faults contains an unsupported structural fault")
    prior = payload.get("prior_virtual_run_ids", [])
    if not isinstance(prior, list) or any(not isinstance(item, str) or not item for item in prior) or len(prior) != len(set(prior)):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "prior_virtual_run_ids must be unique Run IDs")
    policy = payload.get("readiness_policy", {"require_standard": True, "require_stress": True, "blocking_severities": ["critical"]})
    if (not isinstance(policy, Mapping) or set(policy) != {"require_standard", "require_stress", "blocking_severities"} or not isinstance(policy.get("require_standard"), bool) or not isinstance(policy.get("require_stress"), bool) or not isinstance(policy.get("blocking_severities"), list) or any(item not in {"minor", "major", "critical"} for item in policy["blocking_severities"])):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "readiness_policy is invalid")
    synth = payload.get("synthetic_population", {})
    if not isinstance(synth, Mapping) or set(synth) - {"composition_intent", "scenario_dimensions", "role_attribute_constraints", "allowed_variation_dimensions", "forbidden_inference_dimensions"}:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "synthetic_population may configure only structural test dimensions")
    return {
        **deepcopy(dict(payload)),
        "population_size": population_size,
        "readiness_policy": deepcopy(dict(policy)),
        "prior_virtual_run_ids": list(prior),
        "stress_faults": list(faults),
        "synthetic_population": deepcopy(dict(synth)),
    }
