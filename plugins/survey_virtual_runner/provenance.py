from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from core.conversation.validation import canonical_digest
from core.execution.models import CapabilityExecutionError

from .contracts import document_digest, validate_virtual_document
from .digest import file_digest, text_digest

ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_ID = "plugin.survey-virtual-runner.structural"
IMPLEMENTATION_VERSION = "0.1.0"
RUNNER_VERSION = "0.1.0"
STRUCTURAL_TEMPLATE_VERSION = "1.0.0"
STRUCTURAL_TEMPLATE = (
    "Structural Survey generator v1: use only pinned Questionnaire structure and stable values; "
    "preserve explicit missing states; inject only configured structural STRESS faults."
)
RESPONSE_SCHEMA_PATH = ROOT / "core/packages/survey/survey-response.schema.json"


def runner_digest(*, implementation_id: str = IMPLEMENTATION_ID, implementation_version: str = IMPLEMENTATION_VERSION, template_digest: str | None = None) -> str:
    return canonical_digest({
        "implementation_id": implementation_id,
        "implementation_version": implementation_version,
        "runner_version": RUNNER_VERSION,
        "template_digest": template_digest or text_digest(STRUCTURAL_TEMPLATE),
        "response_schema_digest": file_digest(RESPONSE_SCHEMA_PATH),
    })


def survey_binding_digest() -> str:
    return canonical_digest({"schema_version": "0.1.0", "binding_type": "survey_virtual_runner"})


def generation_provenance(request, extension: Mapping[str, Any]) -> dict[str, Any]:
    backend = str(extension.get("generator_backend", "structural"))
    if backend == "llm":
        backend_config = extension["llm_backend_configuration"]
        prompt = extension["prompt_template"]
        implementation_id = "plugin.survey-virtual-runner.llm"
        implementation_version = "1.0.0"
        template_version = str(prompt["template_version"])
        template_digest = str(prompt["template_digest"])
        configuration_payload = {
            "scenario_class": extension["scenario_class"],
            "synthetic_population": extension["synthetic_population"],
            "respondent_plan": extension["respondent_plan"],
            "backend_config_digest": extension["llm_backend_config_digest"],
            "prompt_template": prompt,
        }
    else:
        backend_config = {}
        implementation_id = IMPLEMENTATION_ID
        implementation_version = IMPLEMENTATION_VERSION
        template_version = STRUCTURAL_TEMPLATE_VERSION
        template_digest = text_digest(STRUCTURAL_TEMPLATE)
        configuration_payload = {
            "scenario_class": extension["scenario_class"],
            "synthetic_population": extension["synthetic_population"],
            "runner_configuration": extension["runner_configuration"],
        }
    configuration_digest = canonical_digest(configuration_payload)
    value = {
        "generator_identity": implementation_id,
        "prompt_template_version": template_version,
        "prompt_template_digest": template_digest,
        "schema_version": "1.0.0",
        "schema_digest": file_digest(RESPONSE_SCHEMA_PATH),
        "runner_version": RUNNER_VERSION,
        "runner_digest": runner_digest(implementation_id=implementation_id, implementation_version=implementation_version, template_digest=template_digest),
        "sampling_seed": extension["runner_configuration"].get("sampling_seed"),
        "generated_at": request.run.started_at or request.run.prepared_at,
        "generation_configuration_digest": configuration_digest,
        "reproducibility_semantics": "provenance_complete_replay_attempt_capable",
        "byte_identical_rerun_assumed": False,
        "seed_proves_determinism": False,
    }
    if backend == "llm":
        value.update({
            "provider_identity": str(backend_config["backend_id"]),
            "model_identity": str(backend_config["model_id"]),
            "model_version_ref": str(backend_config["model_id"]),
        })
    return value


def input_pins(request, extension: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    run_spec = extension["run_spec"]
    research_method = extension["research_method_context"]
    pins = {
        "project_id": str(request.context_pack["project_id"]),
        "design": deepcopy(dict(extension["design_ref"])),
        "instrument": deepcopy(dict(extension["instrument_ref"])),
        "rq_ids": list(request.context_pack["question_ids"]),
        "evidence_gap_refs": deepcopy(list(research_method["targets"]["evidence_gap_refs"])),
        "human_decision_bindings": deepcopy(dict(research_method["human_decision_bindings"])),
        "core_method": deepcopy(dict(extension["core_method_ref"])),
        "protocol": deepcopy(dict(extension["protocol_ref"])),
        "run_spec": {
            "id": str(run_spec["run_spec_id"]),
            "version": str(run_spec["version"]),
            "content_digest": str(run_spec["content_digest"]),
            "input_digest": str(run_spec["input_digest"]),
        },
        "research_snapshot": deepcopy(dict(request.context_pack["pins"]["research_snapshot"])),
        "project_config_digest": str(request.context_pack["pins"]["project_config"]["configuration_digest"]),
        "effective_profile_set_digest": str(request.context_pack["pins"]["effective_profile_set"]["content_digest"]),
        "virtual_runner_descriptor": {
            "capability_id": str(request.descriptor["capability_id"]),
            "version": str(request.descriptor["capability_version"]),
            "descriptor_digest": str(request.descriptor["descriptor_digest"]),
        },
        "runner_digest": str(provenance["runner_digest"]),
        "survey_binding_digest": survey_binding_digest(),
    }
    if extension.get("generator_backend") == "llm":
        pins["generator_backend"] = "llm"
        pins["respondent_plan"] = deepcopy(dict(extension["respondent_plan"]))
        pins["backend"] = {
            "backend_id": str(extension["llm_backend_configuration"]["backend_id"]),
            "model_id": str(extension["llm_backend_configuration"]["model_id"]),
            "backend_config_digest": str(extension["llm_backend_config_digest"]),
        }
        pins["prompt_template"] = deepcopy(dict(extension["prompt_template"]))
    return pins


def build_virtual_context(request, extension: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    protocol = extension["protocol_ref"]
    instrument = extension["instrument_ref"]
    run_spec = extension["run_spec"]
    authorization = request.invocation["runtime_authorization_evidence"]
    document = {
        "schema_version": "0.1.0",
        "object_type": "virtual_runner_context",
        "context_pack_binding": deepcopy(dict(extension["context_pack_binding"])),
        "execution_mode": "virtual",
        "scenario_class": str(extension["scenario_class"]),
        "method_execute_binding": {
            "method_family": "survey",
            "method_capability_id": "research-method.survey",
            "function_id": "execute",
            "research_method_context_extension_digest": str(extension["research_method_context"]["extension_digest"]),
        },
        "adopted_core_method": {
            "method_id": str(extension["core_method_ref"]["method_id"]),
            "revision": int(extension["core_method_ref"]["revision"]),
            "adoption_state": "approved",
        },
        "approved_protocol": {
            "id": str(protocol["protocol_id"]),
            "version": str(protocol["version"]),
            "content_digest": str(protocol["content_digest"]),
            "approval_status": "approved",
        },
        "approved_instruments": [{
            "id": str(instrument["id"]),
            "version": str(instrument["version"]),
            "content_digest": str(instrument["content_digest"]),
            "approval_status": "approved",
        }],
        "run_spec": {
            "id": str(run_spec["run_spec_id"]),
            "version": str(run_spec["version"]),
            "content_digest": str(run_spec["content_digest"]),
            "input_digest": str(run_spec["input_digest"]),
        },
        "pins": {
            "project_config_digest": str(request.context_pack["pins"]["project_config"]["configuration_digest"]),
            "effective_profile_set_digest": str(request.context_pack["pins"]["effective_profile_set"]["content_digest"]),
            "research_snapshot": deepcopy(dict(request.context_pack["pins"]["research_snapshot"])),
        },
        "runtime_authorization": {
            "authorization_id": str(authorization["authorization_id"]),
            "authorization_digest": str(authorization["authorization_digest"]),
        },
        "synthetic_population": deepcopy(dict(extension["synthetic_population"])),
        "generation_provenance": deepcopy(dict(provenance)),
        "runner_configuration_pin": {
            "runner_id": "survey-llm-respondent" if extension.get("generator_backend") == "llm" else "survey-structural-runner",
            "version": RUNNER_VERSION,
            "content_digest": canonical_digest(extension["runner_configuration"]),
        },
    }
    document["extension_digest"] = document_digest(document, "extension_digest")
    error = validate_virtual_document(document)
    if error:
        raise CapabilityExecutionError(
            "VR-CONTEXT-BINDING-001",
            f"canonical Virtual Runner context is invalid: {error}",
        )
    return document
