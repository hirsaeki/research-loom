from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from core.execution import CapabilityExecutionOutput
from core.execution.models import CapabilityExecutionError

from .contracts import document_digest, validate_virtual_document
from .provenance import IMPLEMENTATION_ID, IMPLEMENTATION_VERSION


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _artifact(request, *, role: str, artifact_id: str, value: Any, provenance: Mapping[str, Any]):
    return request.artifacts.put_bytes(
        role=role,
        media_type="application/json",
        content=_json_bytes(value),
        artifact_id=artifact_id,
        provenance=provenance,
    )


def build_output(
    request,
    extension: Mapping[str, Any],
    *,
    records: Sequence[Any],
    validation: Mapping[str, Any],
    defects: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    change_requests: Sequence[Mapping[str, Any]],
    readiness: Mapping[str, Any],
    provenance: Mapping[str, Any],
    pins: Mapping[str, Any],
    implementation_id: str = IMPLEMENTATION_ID,
    implementation_version: str = IMPLEMENTATION_VERSION,
    generation_attempts: Sequence[Mapping[str, Any]] = (),
    respondent_profiles: Sequence[Mapping[str, Any]] = (),
) -> CapabilityExecutionOutput:
    run_id = str(request.run.run_id)
    artifact_provenance = {
        "evidence_status": "SYNTHETIC_TEST_ONLY",
        "scenario_class": str(extension["scenario_class"]),
        "instrument_digest": str(extension["instrument_ref"]["content_digest"]),
        "generator_backend": str(extension.get("generator_backend", "structural")),
    }
    response_batch = {
        "schema_version": "0.1.0",
        "object_type": "survey_virtual_response_batch",
        "scenario_class": str(extension["scenario_class"]),
        "identity_namespace": str(extension["synthetic_population"]["identity_namespace"]),
        "evidence_status": "SYNTHETIC_TEST_ONLY",
        "responses": list(records),
    }
    response_artifact = _artifact(
        request,
        role="survey_virtual.synthetic_responses",
        artifact_id=f"ART-VR-RESP-{run_id}",
        value=response_batch,
        provenance=artifact_provenance,
    )
    validation_artifact = _artifact(
        request,
        role="survey_virtual.validation_report",
        artifact_id=f"ART-VR-VAL-{run_id}",
        value=validation,
        provenance=artifact_provenance,
    )
    defect_artifact = _artifact(
        request,
        role="survey_virtual.defect_register",
        artifact_id=f"ART-VR-DEF-{run_id}",
        value={"defects": list(defects), "warnings": list(warnings)},
        provenance=artifact_provenance,
    )
    readiness_artifact = _artifact(
        request,
        role="survey_virtual.readiness_assessment",
        artifact_id=f"ART-VR-READY-{run_id}",
        value=readiness,
        provenance=artifact_provenance,
    )

    generation_artifact = None
    if generation_attempts or respondent_profiles:
        generation_artifact = _artifact(
            request,
            role="survey_virtual.generation_report",
            artifact_id=f"ART-VR-GEN-{run_id}",
            value={
                "generator_backend": str(extension.get("generator_backend", "structural")),
                "respondent_profiles": list(respondent_profiles),
                "generation_attempts": list(generation_attempts),
                "prompt_template": deepcopy(extension.get("prompt_template")),
                "backend_config_digest": extension.get("llm_backend_config_digest"),
            },
            provenance=artifact_provenance,
        )

    next_action = {
        "proposal_id": f"VRNEXT-{run_id}",
        "action_type": "review",
        "instruction": "Review the candidate pre-REAL readiness and any Virtual Runner defects.",
        "rationale": "Synthetic validation cannot authorize REAL Survey execution.",
        "status": "candidate",
    }
    handoff = {
        "schema_version": "0.1.0",
        "handoff_id": f"HND-{run_id}",
        "invocation_id": str(request.run.invocation_id),
        "run_id": run_id,
        "project_id": str(request.run.project_ref),
        "capability": {
            "capability_id": str(request.run.capability_id),
            "capability_version": str(request.run.capability_version),
            "descriptor_digest": str(request.run.descriptor_digest),
            "function_id": str(request.run.function_id),
        },
        "execution_mode": "virtual",
        "input_pins": {
            "invocation_digest": str(request.run.invocation_digest),
            "context_pack_digest": str(request.run.context_pack_digest),
            "project_config_digest": str(request.context_pack["pins"]["project_config"]["configuration_digest"]),
            "effective_profile_set_digest": str(request.context_pack["pins"]["effective_profile_set"]["content_digest"]),
            "research_snapshot": deepcopy(dict(request.context_pack["pins"]["research_snapshot"])),
        },
        "preserved_context": {
            "research_attention_ids": [str(item["attention_id"]) for item in request.context_pack["research_attention"]],
            "project_guard_ids": [
                str(item["guard_id"])
                for group in ("requirements", "prohibitions", "must_not_claim")
                for item in request.context_pack["project_constraints"][group]
            ],
            "effective_constraint_paths": [str(item["path"]) for item in request.context_pack["effective_constraints"]],
        },
        "validation": {"status": "valid", "issues": []},
        "outputs": {
            "observations": [],
            "source_captures": [],
            "evidence_candidates": [],
            "candidate_findings": [],
            "counterevidence": [],
            "conflicts": [],
            "unknowns": [],
            "evidence_gaps": [],
            "candidate_next_actions": [next_action],
            "candidate_next_methods": [],
        },
        "provenance": {
            "trace_id": str(request.invocation["trace"]["trace_id"]),
            "produced_at": str(provenance["generated_at"]),
            "implementation_id": implementation_id,
            "implementation_version": implementation_version,
            "input_content_digests": [
                str(request.run.descriptor_digest),
                str(request.run.context_pack_digest),
                str(request.run.invocation_digest),
            ],
        },
        "adoption_boundary": {
            "research_state_mutation_performed": False,
            "outputs_are_candidates": True,
            "human_decision_required_for_authoritative_transition": True,
        },
    }
    handoff["handoff_digest"] = document_digest(handoff, "handoff_digest")

    completion_status = "complete"
    if extension.get("generator_backend") == "llm":
        failed_generations = sum(1 for item in generation_attempts if item.get("status") == "failed")
        if failed_generations == len(respondent_profiles) and respondent_profiles:
            completion_status = "failed"
        elif failed_generations or validation.get("issues"):
            completion_status = "partial"

    vr_result = {
        "schema_version": "0.1.0",
        "object_type": "virtual_runner_result",
        "handoff_binding": {
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff["handoff_digest"],
            "invocation_id": handoff["invocation_id"],
            "run_id": run_id,
            "context_pack_id": str(request.run.context_pack_id),
            "context_pack_digest": str(request.run.context_pack_digest),
            "capability_id": "virtual-runner",
            "function_id": "execute",
        },
        "scenario_class": str(extension["scenario_class"]),
        "evidence_status": "SYNTHETIC_TEST_ONLY",
        "completion_status": completion_status,
        "synthetic_outputs": [{
            "output_id": response_artifact.artifact_id,
            "kind": "raw_data",
            "identity_namespace": str(extension["synthetic_population"]["identity_namespace"]),
            "content_digest": response_artifact.digest,
            "evidence_status": "SYNTHETIC_TEST_ONLY",
            "empirical_adoption_performed": False,
        }],
        "candidate_analyses": [],
        "candidate_findings": [],
        "defects": list(defects),
        "warnings": list(warnings),
        "unresolved_ambiguities": [],
        "human_gate_requirements": ["A separate Human-authorized REAL Survey invocation is required."],
        "candidate_change_requests": list(change_requests),
        "readiness_assessment": deepcopy(dict(readiness)),
        "execution_trace": [
            "exact Survey/Research Method pins validated",
            (f"LLM synthetic respondent generation ({extension['scenario_class']})" if extension.get("generator_backend") == "llm" else f"structural synthetic generation ({extension['scenario_class']})"),
            "canonical Survey response validation",
            "defect and preservation classification",
            "candidate pre-REAL readiness assessment",
        ],
    }
    vr_result["extension_digest"] = document_digest(vr_result, "extension_digest")
    error = validate_virtual_document(vr_result)
    if error:
        raise CapabilityExecutionError(
            "VR-RESULT-BINDING-001",
            f"canonical Virtual Runner result is invalid: {error}",
        )

    result_extension = {
        "schema_version": "0.1.0",
        "extension_type": "survey_virtual_runner_result",
        "handoff_binding": deepcopy(dict(vr_result["handoff_binding"])),
        "evidence_status": "SYNTHETIC_TEST_ONLY",
        "input_pins": deepcopy(dict(pins)),
        "synthetic_population": deepcopy(dict(extension["synthetic_population"])),
        "generation_provenance": deepcopy(dict(provenance)),
        "generator_backend": str(extension.get("generator_backend", "structural")),
        **({"respondent_plan": deepcopy(extension.get("respondent_plan")), "generation_attempts": deepcopy(list(generation_attempts))} if extension.get("generator_backend") == "llm" else {}),
        "validation_failures": deepcopy(list(validation["issues"])),
        "preservation_events": deepcopy(list(validation["preservation_events"])),
        "defects": deepcopy(list(defects)),
        "warnings": list(warnings),
        "candidate_change_requests": deepcopy(list(change_requests)),
        "readiness_assessment": deepcopy(dict(readiness)),
        "virtual_runner_result": vr_result,
        "research_state_mutation_performed": False,
        "real_execution_started": False,
    }
    result_extension["extension_digest"] = document_digest(result_extension, "extension_digest")
    result_artifact = _artifact(
        request,
        role="survey_virtual.virtual_runner_result",
        artifact_id=f"ART-VR-RESULT-{run_id}",
        value=result_extension,
        provenance=artifact_provenance,
    )

    artifacts = [response_artifact, validation_artifact, defect_artifact, readiness_artifact, result_artifact]
    if generation_artifact is not None:
        artifacts.append(generation_artifact)
    return CapabilityExecutionOutput(
        handoff=handoff,
        extension=result_extension,
        artifacts=tuple(artifacts),
    )
