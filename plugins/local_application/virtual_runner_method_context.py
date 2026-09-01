from __future__ import annotations

from copy import deepcopy

from core.conversation import canonical_digest
from plugins.local_application.facade import LocalApplicationError
from plugins.survey_virtual_runner.contracts import document_digest, validate_research_method_context
from .virtual_runner_input import _DEFAULT_LIMITS


def build_method_context(state, record, payload, *, context_pack_id, questionnaire, rq_ids, rq_objects, method, method_decisions, protocol, material_decisions, snapshot, effective, attention, project_constraints, effective_constraints):
    research_refs = [{"kind": "research_question", "id": str(item["id"]), "revision": int(item.get("revision", 0))} for item in rq_objects] + [{"kind": "method", "id": str(method["id"]), "revision": int(method.get("revision", 0))}]
    context = {
        "schema_version": "0.1.0", "context_pack_id": context_pack_id,
        "project_id": state.project_ref,
        "purpose": str(payload.get("purpose") or f"Pre-REAL Survey structural validation for {record['questionnaire']['questionnaire_id']}."),
        "pins": {
            "project_config": {"configuration_digest": state.project_config_digest},
            "effective_profile_set": effective,
            "research_snapshot": {"snapshot_id": str(snapshot["id"]), "revision": int(snapshot.get("revision", 0)), "content_digest": str(snapshot["content_digest"])},
        },
        "question_ids": rq_ids,
        "research_object_references": research_refs,
        "resources": [], "research_attention": attention,
        "project_constraints": project_constraints,
        "effective_constraints": effective_constraints,
        "bounds": {
            **_DEFAULT_LIMITS,
            "max_questions": len(rq_ids),
            "max_research_object_references": len(research_refs),
            "max_attention_items": len(attention),
            "max_project_guards": sum(len(value) for value in project_constraints.values()),
            "max_effective_constraints": len(effective_constraints),
        },
    }
    context["context_pack_digest"] = canonical_digest(context)
    binding = {"context_pack_id": context_pack_id, "context_pack_digest": context["context_pack_digest"], "project_id": state.project_ref}
    protocol_ref = {"protocol_id": str(protocol["protocol_id"]), "version": str(protocol["version"]), "content_digest": str(protocol["content_digest"]), "approval_status": "approved", "material_revision": bool(protocol["material_revision"])}
    gaps = deepcopy(list(payload["evidence_gap_refs"]))
    run_input_basis = {
        "survey_design": record["design_ref"],
        "instrument": {"id": questionnaire["questionnaire_id"], "version": questionnaire["version"], "content_digest": questionnaire["content_digest"]},
        "core_method": {"method_id": method["id"], "revision": method["revision"]},
        "protocol": protocol_ref, "rq_ids": rq_ids,
        "research_snapshot": context["pins"]["research_snapshot"],
        "scenario_class": payload["scenario_class"], "population_size": payload["population_size"],
        "sampling_seed": payload.get("sampling_seed", 0),
        "synthetic_population": payload["synthetic_population"], "stress_faults": payload["stress_faults"],
        "readiness_policy": payload["readiness_policy"], "prior_virtual_run_ids": payload["prior_virtual_run_ids"],
    }
    run_spec = {
        "run_spec_id": str(payload["run_spec_id"]), "version": str(payload["run_spec_version"]),
        "input_digest": canonical_digest(run_input_basis),
        "data_roles": ["synthetic_response", "validation_report", "defect_report", "readiness_assessment"],
        "coverage_dimensions": ["survey_schema", "branching", "missingness", "execution_flow"],
    }
    run_spec["content_digest"] = canonical_digest(run_spec)
    research_method = {
        "schema_version": "0.1.0", "extension_type": "research_method_context", "context_binding": binding,
        "function_id": "execute", "targets": {"question_ids": rq_ids, "evidence_gap_refs": gaps},
        "method_basis": {"core_method_ref": {"method_id": str(method["id"]), "revision": int(method["revision"]), "adoption_state": "approved"}},
        "protocol_basis": protocol_ref,
        "instrument_refs": [{"instrument_id": str(questionnaire["questionnaire_id"]), "version": str(questionnaire["version"]), "content_digest": str(questionnaire["content_digest"]), "approval_status": "approved"}],
        "run_spec": run_spec, "prior_run_result_refs": [],
        "human_decision_bindings": {"method_adoption_decision_ids": method_decisions, "material_protocol_revision_decision_ids": material_decisions},
    }
    research_method["extension_digest"] = document_digest(research_method, "extension_digest")
    error = validate_research_method_context(research_method)
    if error:
        raise LocalApplicationError("VR-METHOD-BINDING-001", f"Research Method execute context is invalid: {error}")
    return context, binding, protocol_ref, run_spec, research_method
