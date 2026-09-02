from __future__ import annotations

from copy import deepcopy

from plugins.local_application.facade import LocalApplicationError
from plugins.survey_virtual_runner.contracts import document_digest, validate_survey_context
from plugins.survey_virtual_runner.llm_backend import prompt_template_pin
from core.conversation.validation import canonical_digest


def build_survey_virtual_extension(record, design_record, payload, *, context_pack_id, binding, questionnaire, method, protocol_ref, run_spec, research_method):
    survey_context = {
        "schema_version": "0.1.0",
        "object_type": "survey_context_extension",
        "research_method_context_digest": research_method["extension_digest"],
        "function_id": "execute",
        "survey_design_ref": {"id": record["design_ref"]["survey_design_id"], "version": record["design_ref"]["version"], "content_digest": record["design_ref"]["content_digest"]},
        "questionnaire_ref": {"id": questionnaire["questionnaire_id"], "version": questionnaire["version"], "content_digest": questionnaire["content_digest"]},
        "duplicate_response_policy": "exclude_all",
        "missing_data_policy": "preserve",
        "questionnaire_decision_ids": [str(questionnaire["approval_decision_id"]), *([str(questionnaire["material_revision_decision_id"])] if questionnaire.get("material_revision_decision_id") else [])],
    }
    survey_context["extension_digest"] = document_digest(survey_context, "extension_digest")
    error = validate_survey_context(survey_context)
    if error:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", f"Survey execute context is invalid: {error}")

    synth_config = payload["synthetic_population"]
    profiles = payload.get("respondent_profiles", [])
    profile_dimensions = sorted({str(key) for profile in profiles for key in profile.get("attributes", {})})
    population = {
        "identity_namespace": f"synthetic:survey:{context_pack_id}",
        "real_identity_namespaces": ["real:survey"],
        "population_size": int(payload["population_size"]),
        "composition_intent": str(synth_config.get("composition_intent") or "Exercise Survey contract paths without claiming empirical representation."),
        "scenario_dimensions": list(synth_config.get("scenario_dimensions") or (profile_dimensions if payload.get("generator_backend") == "llm" and profile_dimensions else ["branching", "missingness", "validation"])),
        "role_attribute_constraints": list(synth_config.get("role_attribute_constraints") or (["explicit synthetic respondent profiles only; no real-person identity"] if payload.get("generator_backend") == "llm" else ["structural synthetic labels only; no real employee personas"])),
        "allowed_variation_dimensions": list(synth_config.get("allowed_variation_dimensions") or ((profile_dimensions + ["sampling_parameters"]) if payload.get("generator_backend") == "llm" else ["stable_response_value", "missing_value_state", "branch_path"])),
        "forbidden_inference_dimensions": list(synth_config.get("forbidden_inference_dimensions") or ["real-person-identity", "population-prevalence", "organizational-distribution"]),
        "real_identity_mapping_refs": [],
        "synthetic_personas_are_real_people": False,
        "empirical_distribution_claimed": False,
        "target_population_representation_claimed": False,
    }
    runner_config = {
        "generator_backend": payload.get("generator_backend", "structural"),
        "sampling_seed": payload.get("sampling_seed", 0),
        "stress_faults": payload["stress_faults"],
        "readiness_policy": payload["readiness_policy"],
        "prior_virtual_run_ids": payload["prior_virtual_run_ids"],
        "minimum_valid_response_count": payload.get("minimum_valid_response_count", 1),
    }
    extension = {
        "schema_version": "0.1.0",
        "binding_type": "survey_virtual_runner",
        "context_pack_binding": binding,
        "scenario_class": payload["scenario_class"],
        "research_method_context": research_method,
        "survey_context": survey_context,
        "core_method_ref": {"method_id": str(method["id"]), "revision": int(method["revision"])},
        "protocol_ref": protocol_ref,
        "design_ref": deepcopy(dict(record["design_ref"])),
        "instrument_ref": {"id": str(questionnaire["questionnaire_id"]), "version": str(questionnaire["version"]), "content_digest": str(questionnaire["content_digest"])},
        "run_spec": run_spec,
        "design": deepcopy(dict(design_record["design"])),
        "instrument": questionnaire,
        "synthetic_population": population,
        "runner_configuration": runner_config,
        "generator_backend": payload.get("generator_backend", "structural"),
        **({
            "respondent_profiles": deepcopy(payload["respondent_profiles"]),
            "respondent_plan": {
                "profile_ids": [item["profile_id"] for item in payload["respondent_profiles"]],
                "profile_digests": [
                    {"profile_id": item["profile_id"], "content_digest": canonical_digest(item)}
                    for item in payload["respondent_profiles"]
                ],
                "profiles_digest": canonical_digest(payload["respondent_profiles"]),
                "composition_intent": population["composition_intent"],
                "interaction_model": "full_instrument_single_call",
            },
            "llm_backend_configuration": deepcopy(payload["llm_backend"]),
            "llm_backend_config_digest": canonical_digest(payload["llm_backend"]),
            "prompt_template": prompt_template_pin(),
        } if payload.get("generator_backend") == "llm" else {}),
    }
    extension["extension_digest"] = document_digest(extension, "extension_digest")
    return extension
