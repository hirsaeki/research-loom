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
    "synthetic_population", "purpose", "generator_backend", "respondent_profiles",
    "llm_backend", "analysis_items", "minimum_valid_response_count",
}
_ALLOWED_STRESS_FAULTS = {
    "required_missing", "optional_missing", "invalid_choice", "out_of_range_scale",
    "branch_violation", "duplicate_record", "duplicate_identity", "partial_completion",
    "malformed_response", "extreme_valid", "unknown", "not_applicable",
    "prefer_not_to_answer",
}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

_SENSITIVE_PROFILE_KEYS = {"name", "full_name", "email", "email_address", "employee_id", "employee_number", "staff_id"}
_PII_TEXT_PATTERNS = (
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?i)\b(?:employee|staff)[ _-]?(?:id|number)\s*[:=#-]?\s*[A-Z0-9][A-Z0-9._-]{2,}\b"),
)
_TRUSTED_LLM_ENDPOINT = "https://api.openai.com/v1/responses"
_TRUSTED_LLM_CREDENTIAL_ENV = "OPENAI_API_KEY"
_MAX_LLM_PROFILES = 8
_MAX_LLM_TIMEOUT_SECONDS = 30
_ALLOWED_LLM_BACKEND_FIELDS = {
    "backend_id", "model_id", "endpoint", "credential_env", "temperature", "top_p",
    "max_output_tokens", "timeout_seconds", "max_transport_retries", "max_repair_attempts",
}


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


def _contains_profile_identifier(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in _SENSITIVE_PROFILE_KEYS or _contains_profile_identifier(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_profile_identifier(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _PII_TEXT_PATTERNS)
    return False


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

    generator_backend = payload.get("generator_backend", "structural")
    if not isinstance(generator_backend, str) or generator_backend not in {"structural", "llm"}:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "generator_backend must be structural or llm")

    profiles = payload.get("respondent_profiles", [])
    llm_backend = payload.get("llm_backend")
    analysis_items = payload.get("analysis_items")
    minimum_valid = payload.get("minimum_valid_response_count", 1)
    if not isinstance(minimum_valid, int) or isinstance(minimum_valid, bool) or minimum_valid < 1:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "minimum_valid_response_count must be a positive integer")
    normalized_profiles = []
    normalized_llm = None
    if generator_backend == "llm":
        if payload["scenario_class"] != "STANDARD":
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "LLM Virtual Respondent backend currently supports scenario_class STANDARD only")
        if faults:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "stress_faults belong to the structural generator and are not accepted by the LLM backend")
        if not isinstance(profiles, list) or not profiles or len(profiles) > _MAX_LLM_PROFILES:
            raise LocalApplicationError(
                "PROFILE_INVALID",
                f"respondent_profiles must contain 1 through {_MAX_LLM_PROFILES} explicit synthetic profiles for the bounded LLM backend",
            )
        seen_profiles = set()
        for index, profile in enumerate(profiles):
            if not isinstance(profile, Mapping) or set(profile) - {"profile_id", "attributes", "knowledge_scope", "scenario_notes"}:
                raise LocalApplicationError("PROFILE_INVALID", f"respondent_profiles[{index}] has unsupported fields")
            profile_id = _nonempty(profile.get("profile_id"), f"respondent_profiles[{index}].profile_id")
            if not profile_id.startswith("SYN-PROFILE-") or profile_id in seen_profiles:
                raise LocalApplicationError("PROFILE_INVALID", "synthetic profile IDs must be unique and use the SYN-PROFILE- namespace")
            seen_profiles.add(profile_id)
            attributes = profile.get("attributes", {})
            if not isinstance(attributes, Mapping):
                raise LocalApplicationError("PROFILE_INVALID", f"respondent_profiles[{index}].attributes must be an object")
            if _contains_profile_identifier(attributes):
                raise LocalApplicationError("PROFILE_INVALID", "synthetic profiles must not contain direct real-person identifiers")
            knowledge_scope = profile.get("knowledge_scope", [])
            if not isinstance(knowledge_scope, list) or any(not isinstance(item, str) or not item.strip() for item in knowledge_scope):
                raise LocalApplicationError("PROFILE_INVALID", f"respondent_profiles[{index}].knowledge_scope must be an array of strings")
            if _contains_profile_identifier(knowledge_scope):
                raise LocalApplicationError("PROFILE_INVALID", "synthetic profile free text must not contain direct real-person identifiers")
            scenario_notes = None
            if profile.get("scenario_notes") is not None:
                scenario_notes = _nonempty(profile["scenario_notes"], f"respondent_profiles[{index}].scenario_notes")
                if _contains_profile_identifier(scenario_notes):
                    raise LocalApplicationError("PROFILE_INVALID", "synthetic profile free text must not contain direct real-person identifiers")
            normalized_profiles.append({
                "profile_id": profile_id,
                "attributes": deepcopy(dict(attributes)),
                "knowledge_scope": list(knowledge_scope),
                **({"scenario_notes": scenario_notes} if scenario_notes is not None else {}),
            })
        if "population_size" in payload and population_size != len(normalized_profiles):
            raise LocalApplicationError("PROFILE_INVALID", "population_size must equal the number of explicit respondent_profiles for the LLM backend")
        population_size = len(normalized_profiles)
        if not isinstance(llm_backend, Mapping) or set(llm_backend) - _ALLOWED_LLM_BACKEND_FIELDS:
            raise LocalApplicationError("BACKEND_UNAVAILABLE", "llm_backend configuration is missing or contains unsupported fields")
        backend_id = _nonempty(llm_backend.get("backend_id"), "llm_backend.backend_id")
        if backend_id != "openai_responses":
            raise LocalApplicationError("BACKEND_UNAVAILABLE", "only the openai_responses production backend is configured")
        model_id = _nonempty(llm_backend.get("model_id"), "llm_backend.model_id")
        normalized_llm = deepcopy(dict(llm_backend))
        normalized_llm["backend_id"] = backend_id
        normalized_llm["model_id"] = model_id
        normalized_llm.setdefault("credential_env", _TRUSTED_LLM_CREDENTIAL_ENV)
        normalized_llm.setdefault("endpoint", _TRUSTED_LLM_ENDPOINT)
        normalized_llm.setdefault("timeout_seconds", 30)
        normalized_llm.setdefault("max_transport_retries", 1)
        normalized_llm.setdefault("max_repair_attempts", 1)
        if normalized_llm["credential_env"] != _TRUSTED_LLM_CREDENTIAL_ENV:
            raise LocalApplicationError("BACKEND_UNAVAILABLE", "llm_backend.credential_env is not allowed")
        if normalized_llm["endpoint"] != _TRUSTED_LLM_ENDPOINT:
            raise LocalApplicationError("BACKEND_UNAVAILABLE", "llm_backend.endpoint is not allowed")
        for field in ("max_transport_retries", "max_repair_attempts"):
            value = normalized_llm[field]
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1:
                raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", f"llm_backend.{field} must be 0 or 1 for the bounded LLM backend")
        if (
            not isinstance(normalized_llm["timeout_seconds"], (int, float))
            or isinstance(normalized_llm["timeout_seconds"], bool)
            or not 0 < float(normalized_llm["timeout_seconds"]) <= _MAX_LLM_TIMEOUT_SECONDS
        ):
            raise LocalApplicationError(
                "APPLICATION-VIRTUAL-PAYLOAD-001",
                f"llm_backend.timeout_seconds must be greater than 0 and at most {_MAX_LLM_TIMEOUT_SECONDS}",
            )
        for field in ("temperature", "top_p"):
            if normalized_llm.get(field) is not None and (
                not isinstance(normalized_llm[field], (int, float))
                or isinstance(normalized_llm[field], bool)
            ):
                raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", f"llm_backend.{field} must be numeric when supplied")
        if normalized_llm.get("temperature") is not None and not 0 <= float(normalized_llm["temperature"]) <= 2:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "llm_backend.temperature must be between 0 and 2")
        if normalized_llm.get("top_p") is not None and not 0 <= float(normalized_llm["top_p"]) <= 1:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "llm_backend.top_p must be between 0 and 1")
        if normalized_llm.get("max_output_tokens") is not None and (
            not isinstance(normalized_llm["max_output_tokens"], int)
            or isinstance(normalized_llm["max_output_tokens"], bool)
            or normalized_llm["max_output_tokens"] <= 0
        ):
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "llm_backend.max_output_tokens must be a positive integer")
        _nonempty(normalized_llm["credential_env"], "llm_backend.credential_env")
        if minimum_valid > len(normalized_profiles):
            raise LocalApplicationError("PROFILE_INVALID", "minimum_valid_response_count cannot exceed respondent profile count")
        if analysis_items is not None and not isinstance(analysis_items, list):
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "analysis_items must be an array when supplied")
    else:
        if profiles or llm_backend is not None or analysis_items is not None or "minimum_valid_response_count" in payload:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PAYLOAD-001", "LLM respondent fields are only valid when generator_backend=llm")

    purpose = payload.get("purpose")
    if purpose is not None:
        _nonempty(purpose, "purpose")
    normalized = {
        **deepcopy(dict(payload)),
        "protocol": deepcopy(dict(protocol)),
        "population_size": population_size,
        "generator_backend": generator_backend,
        "readiness_policy": {
            "require_standard": bool(policy["require_standard"]),
            "require_stress": bool(policy["require_stress"]),
            "blocking_severities": blocking,
        },
        "prior_virtual_run_ids": prior,
        "stress_faults": faults,
        "synthetic_population": normalized_synth,
    }
    if generator_backend == "llm":
        normalized.update({
            "respondent_profiles": normalized_profiles,
            "llm_backend": normalized_llm,
            "analysis_items": deepcopy(analysis_items),
            "minimum_valid_response_count": minimum_valid,
        })
    else:
        for field in (
            "respondent_profiles", "llm_backend", "analysis_items",
            "minimum_valid_response_count",
        ):
            normalized.pop(field, None)
    return normalized
