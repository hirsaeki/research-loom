from __future__ import annotations

from copy import deepcopy
import re
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
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def canonical_protocol_ref(protocol: Mapping[str, Any]) -> str:
    return (
        f"{protocol['protocol_id']}@{protocol['version']}"
        f"#{protocol['content_digest']}"
    )


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            f"{field} must be a non-empty string",
        )
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            f"{field} must be an array of unique non-empty strings",
        )
    return list(value)


def _payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "virtual_runner.survey.execute payload must be an object",
        )
    unknown = set(payload) - _ALLOWED_PAYLOAD
    if unknown:
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "unsupported or authority-like Virtual Runner payload fields: "
            + ", ".join(sorted(map(str, unknown))),
        )
    required = {
        "instrument_id", "instrument_version", "instrument_digest",
        "scenario_class", "core_method_id", "core_method_revision",
        "protocol", "evidence_gap_refs", "run_spec_id", "run_spec_version",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "missing Virtual Runner payload fields: " + ", ".join(missing),
        )
    if payload["scenario_class"] not in {"STANDARD", "STRESS"}:
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "scenario_class must be STANDARD or STRESS",
        )
    for field in ("instrument_id", "core_method_id", "run_spec_id"):
        _nonempty(payload.get(field), field)
    for field in ("instrument_version", "run_spec_version"):
        value = _nonempty(payload.get(field), field)
        if not _SEMVER.match(value):
            raise LocalApplicationError(
                "APPLICATION-VIRTUAL-PAYLOAD-001",
                f"{field} must be SemVer",
            )
    instrument_digest = _nonempty(payload.get("instrument_digest"), "instrument_digest")
    if not _DIGEST.match(instrument_digest):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "instrument_digest must be a sha256 digest",
        )
    if (
        not isinstance(payload.get("core_method_revision"), int)
        or isinstance(payload["core_method_revision"], bool)
        or payload["core_method_revision"] < 0
    ):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "core_method_revision must be a non-negative integer",
        )

    protocol = payload.get("protocol")
    required_protocol = {
        "protocol_id", "version", "content_digest", "material_revision",
    }
    optional_protocol = {"material_revision_decision_id"}
    if (
        not isinstance(protocol, Mapping)
        or set(protocol) - (required_protocol | optional_protocol)
        or not required_protocol.issubset(protocol)
    ):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "protocol must carry exact id/version/digest plus material-revision metadata; approval is derived from the approved Core Method",
        )
    _nonempty(protocol.get("protocol_id"), "protocol.protocol_id")
    version = _nonempty(protocol.get("version"), "protocol.version")
    digest = _nonempty(protocol.get("content_digest"), "protocol.content_digest")
    if not _SEMVER.match(version) or not _DIGEST.match(digest):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "protocol version/content_digest are invalid",
        )
    if not isinstance(protocol.get("material_revision"), bool):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "protocol.material_revision must be boolean",
        )
    if protocol["material_revision"]:
        _nonempty(
            protocol.get("material_revision_decision_id"),
            "protocol.material_revision_decision_id",
        )

    gaps = payload.get("evidence_gap_refs")
    gap_fields = {
        "gap_id", "source_handoff_id", "source_handoff_digest",
        "source_resource_reference_id",
    }
    if (
        not isinstance(gaps, list)
        or not gaps
        or any(not isinstance(item, Mapping) or set(item) != gap_fields for item in gaps)
    ):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "evidence_gap_refs must contain exact Research Method Evidence Gap references",
        )
    for index, item in enumerate(gaps):
        for field in ("gap_id", "source_handoff_id", "source_resource_reference_id"):
            _nonempty(item.get(field), f"evidence_gap_refs[{index}].{field}")
        if not _DIGEST.match(
            _nonempty(
                item.get("source_handoff_digest"),
                f"evidence_gap_refs[{index}].source_handoff_digest",
            )
        ):
            raise LocalApplicationError(
                "APPLICATION-VIRTUAL-PAYLOAD-001",
                f"evidence_gap_refs[{index}].source_handoff_digest is invalid",
            )

    population_size = payload.get("population_size", 8)
    if (
        not isinstance(population_size, int)
        or isinstance(population_size, bool)
        or not 1 <= population_size <= 128
    ):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "population_size must be an integer from 1 through 128",
        )
    faults = _string_list(payload.get("stress_faults", []), "stress_faults")
    if any(item not in _ALLOWED_STRESS_FAULTS for item in faults):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "stress_faults contains an unsupported structural fault",
        )
    prior = _string_list(payload.get("prior_virtual_run_ids", []), "prior_virtual_run_ids")
    if len(prior) > 16:
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "prior_virtual_run_ids may contain at most 16 Run IDs",
        )
    policy = payload.get(
        "readiness_policy",
        {
            "require_standard": True,
            "require_stress": True,
            "blocking_severities": ["critical"],
        },
    )
    if (
        not isinstance(policy, Mapping)
        or set(policy) != {
            "require_standard", "require_stress", "blocking_severities",
        }
        or not isinstance(policy.get("require_standard"), bool)
        or not isinstance(policy.get("require_stress"), bool)
    ):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "readiness_policy is invalid",
        )
    blocking = _string_list(
        policy.get("blocking_severities"),
        "readiness_policy.blocking_severities",
    )
    if any(item not in {"minor", "major", "critical"} for item in blocking):
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "readiness_policy.blocking_severities contains an unsupported severity",
        )

    synth = payload.get("synthetic_population", {})
    allowed_synth = {
        "composition_intent", "scenario_dimensions", "role_attribute_constraints",
        "allowed_variation_dimensions", "forbidden_inference_dimensions",
    }
    if not isinstance(synth, Mapping) or set(synth) - allowed_synth:
        raise LocalApplicationError(
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "synthetic_population may configure only structural test dimensions",
        )
    normalized_synth = deepcopy(dict(synth))
    if "composition_intent" in normalized_synth:
        _nonempty(
            normalized_synth["composition_intent"],
            "synthetic_population.composition_intent",
        )
    for field in (
        "scenario_dimensions", "role_attribute_constraints",
        "allowed_variation_dimensions", "forbidden_inference_dimensions",
    ):
        if field in normalized_synth:
            normalized_synth[field] = _string_list(
                normalized_synth[field],
                f"synthetic_population.{field}",
            )

    purpose = payload.get("purpose")
    if purpose is not None:
        _nonempty(purpose, "purpose")
    return {
        **deepcopy(dict(payload)),
        "protocol": deepcopy(dict(protocol)),
        "population_size": population_size,
        "readiness_policy": {
            "require_standard": bool(policy["require_standard"]),
            "require_stress": bool(policy["require_stress"]),
            "blocking_severities": blocking,
        },
        "prior_virtual_run_ids": prior,
        "stress_faults": faults,
        "synthetic_population": normalized_synth,
    }