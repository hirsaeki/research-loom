from __future__ import annotations

import hashlib

import rfc8785

ERROR_IDS = {
    "VR-DESCRIPTOR-001",
    "VR-CONTEXT-DIGEST-001",
    "VR-CONTEXT-BINDING-001",
    "VR-METHOD-BINDING-001",
    "VR-SYNTHETIC-PROVENANCE-001",
    "VR-IDENTITY-COLLISION-001",
    "VR-RESULT-DIGEST-001",
    "VR-RESULT-BINDING-001",
    "VR-EPISTEMIC-FIREWALL-001",
    "VR-DEFECT-AUTHORITY-001",
    "VR-READINESS-001",
    "VR-FREEZE-STALE-001",
    "VR-HUMAN-DECISION-001",
    "VR-REAL-ISOLATION-001",
    "VR-VIRTUAL-COPY-001",
    "VR-RUNTIME-AUTH-001",
    "VR-CONVERSATION-DECISION-001",
}


def canonical_digest(document, digest_field):
    body = {k: v for k, v in document.items() if k != digest_field}
    return "sha256:" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()


def descriptor_error(descriptor):
    if descriptor.get("capability_kind") != "execution_backend.virtual_runner":
        return "VR-DESCRIPTOR-001"
    functions = descriptor.get("declared_functions", [])
    if len(functions) != 1:
        return "VR-DESCRIPTOR-001"
    fn = functions[0]
    if fn.get("function_id") != "execute" or fn.get("supported_execution_modes") != ["virtual"]:
        return "VR-DESCRIPTOR-001"
    if fn.get("input_contract") != "capability-context-pack@0.1.0" or fn.get("output_contract") != "capability-handoff@0.1.0":
        return "VR-DESCRIPTOR-001"
    if descriptor.get("descriptor_digest") != canonical_digest(descriptor, "descriptor_digest"):
        return "VR-DESCRIPTOR-001"
    return None


def context_error(ctx, *, expected=None):
    if ctx.get("extension_digest") != canonical_digest(ctx, "extension_digest"):
        return "VR-CONTEXT-DIGEST-001"
    if ctx.get("execution_mode") != "virtual" or ctx.get("scenario_class") not in {"STANDARD", "STRESS"}:
        return "VR-CONTEXT-BINDING-001"
    bind = ctx.get("method_execute_binding", {})
    method = ctx.get("adopted_core_method", {})
    protocol = ctx.get("approved_protocol", {})
    if bind.get("function_id") != "execute" or method.get("adoption_state") != "approved" or protocol.get("approval_status") != "approved":
        return "VR-METHOD-BINDING-001"
    if any(x.get("approval_status") != "approved" for x in ctx.get("approved_instruments", [])):
        return "VR-METHOD-BINDING-001"
    auth = ctx.get("runtime_authorization", {})
    if not auth.get("authorization_id") or not auth.get("authorization_digest"):
        return "VR-RUNTIME-AUTH-001"
    pop = ctx.get("synthetic_population", {})
    ns = pop.get("identity_namespace")
    if not isinstance(ns, str) or not ns.startswith("synthetic:") or ns in set(pop.get("real_identity_namespaces", [])) or pop.get("real_identity_mapping_refs"):
        return "VR-IDENTITY-COLLISION-001"
    prov = ctx.get("generation_provenance", {})
    required = {
        "generator_identity",
        "prompt_template_version",
        "prompt_template_digest",
        "schema_version",
        "schema_digest",
        "runner_version",
        "runner_digest",
        "generation_configuration_digest",
    }
    if not required.issubset(prov) or prov.get("reproducibility_semantics") != "provenance_complete_replay_attempt_capable" or prov.get("byte_identical_rerun_assumed") is not False or prov.get("seed_proves_determinism") is not False:
        return "VR-SYNTHETIC-PROVENANCE-001"
    if expected:
        b = ctx.get("context_pack_binding", {})
        pins = ctx.get("pins", {})
        for key in ("context_pack_id", "context_pack_digest", "project_id"):
            if b.get(key) != expected.get(key):
                return "VR-CONTEXT-BINDING-001"
        for key in ("project_config_digest", "effective_profile_set_digest"):
            if pins.get(key) != expected.get(key):
                return "VR-CONTEXT-BINDING-001"
    return None


def result_error(result, ctx, *, expected_capability_id):
    if result.get("extension_digest") != canonical_digest(result, "extension_digest"):
        return "VR-RESULT-DIGEST-001"
    if result.get("scenario_class") != ctx.get("scenario_class") or result.get("evidence_status") != "SYNTHETIC_TEST_ONLY":
        return "VR-RESULT-BINDING-001"
    hb = result.get("handoff_binding", {})
    cb = ctx.get("context_pack_binding", {})
    if hb.get("context_pack_id") != cb.get("context_pack_id") or hb.get("context_pack_digest") != cb.get("context_pack_digest") or hb.get("capability_id") != expected_capability_id or hb.get("function_id") != "execute":
        return "VR-RESULT-BINDING-001"
    for output in result.get("synthetic_outputs", []):
        if output.get("evidence_status") != "SYNTHETIC_TEST_ONLY" or output.get("empirical_adoption_performed") is not False or not output.get("identity_namespace", "").startswith("synthetic:"):
            return "VR-EPISTEMIC-FIREWALL-001"
    if any(x.get("evidence_status") != "SYNTHETIC_TEST_ONLY" or x.get("core_analysis_adoption_performed") is not False for x in result.get("candidate_analyses", [])):
        return "VR-EPISTEMIC-FIREWALL-001"
    if any(x.get("evidence_status") != "SYNTHETIC_TEST_ONLY" or x.get("authoritative_finding") is not False for x in result.get("candidate_findings", [])):
        return "VR-EPISTEMIC-FIREWALL-001"
    if any(x.get("authoritative_change_applied") is not False for x in result.get("candidate_change_requests", [])):
        return "VR-DEFECT-AUTHORITY-001"
    readiness = result.get("readiness_assessment", {})
    if readiness.get("candidate_only") is not True or readiness.get("real_execution_started") is not False:
        return "VR-READINESS-001"
    if readiness.get("status") == "CANDIDATE_READY" and any(d.get("severity") == "critical" and d.get("disposition") != "resolved" for d in result.get("defects", [])):
        return "VR-READINESS-001"
    return None


def cutover_error(manifest, *, current_pins=None):
    if manifest.get("manifest_digest") != canonical_digest(manifest, "manifest_digest"):
        return "VR-FREEZE-STALE-001"
    freeze = manifest.get("freeze_package", {})
    required = {
        "method",
        "protocol",
        "instruments",
        "schemas",
        "prompt_templates",
        "runner_code",
        "validation_gate_contracts",
        "effective_profile_set_digest",
        "project_config_digest",
    }
    if not required.issubset(freeze):
        return "VR-FREEZE-STALE-001"
    if current_pins:
        for key, value in current_pins.items():
            if freeze.get(key) != value:
                return "VR-FREEZE-STALE-001"
    human = manifest.get("human_gate", {})
    if human.get("required") and (not human.get("decision_ref") or human.get("confirmation_is_human_decision") is not False):
        return "VR-HUMAN-DECISION-001"
    criteria = manifest.get("readiness_criteria", {})
    if manifest.get("status") == "CANDIDATE_READY" and (not criteria or not all(criteria.values())):
        return "VR-READINESS-001"
    b = manifest.get("real_start_boundary", {})
    if b.get("separate_authorized_invocation_required") is not True or b.get("virtual_runner_may_start_real") is not False:
        return "VR-REAL-ISOLATION-001"
    required_forbidden = {
        "virtual_response",
        "virtual_observation",
        "synthetic_raw_data",
        "virtual_evidence_candidate",
        "virtual_analysis_candidate",
        "virtual_finding_candidate",
        "virtual_participant_identity",
    }
    if set(manifest.get("forbidden_transfer_kinds", [])) != required_forbidden:
        return "VR-VIRTUAL-COPY-001"
    return None


def real_start_error(real_start, virtual_run_roots):
    if real_start.get("execution_mode") != "real" or not real_start.get("run_root_id") or not real_start.get("run_id") or not real_start.get("runtime_authorization_id"):
        return "VR-REAL-ISOLATION-001"
    if not real_start.get("raw_data_namespace", "").startswith("real:"):
        return "VR-REAL-ISOLATION-001"

    source_virtual_run_id = real_start.get("source_virtual_run_id")
    if source_virtual_run_id not in virtual_run_roots:
        return "VR-REAL-ISOLATION-001"
    if real_start.get("run_root_id") in set(virtual_run_roots.values()):
        return "VR-REAL-ISOLATION-001"

    if real_start.get("run_id") in set(virtual_run_roots) or real_start.get("copied_virtual_content_ids") or real_start.get("virtual_identity_mapping_refs"):
        return "VR-VIRTUAL-COPY-001"
    for key in ("access_zone", "owner", "permission_context"):
        if not real_start.get(key):
            return "VR-REAL-ISOLATION-001"
    return None
