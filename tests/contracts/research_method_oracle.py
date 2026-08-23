from __future__ import annotations

import hashlib
import rfc8785

CANONICAL_FUNCTIONS = {"method_design", "instrument_design", "execute", "analyze"}


def canonical_digest(document, digest_field):
    body = {k: v for k, v in document.items() if k != digest_field}
    return "sha256:" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()


def descriptor_error(descriptor):
    if not descriptor.get("capability_kind", "").startswith("research_method."):
        return "RM-DESCRIPTOR-001"
    functions = descriptor.get("declared_functions", [])
    ids = [f.get("function_id") for f in functions]
    if set(ids) != CANONICAL_FUNCTIONS or len(ids) != len(CANONICAL_FUNCTIONS):
        return "RM-DESCRIPTOR-001"
    for function in functions:
        if function.get("input_contract") != "capability-context-pack@0.1.0" or function.get("output_contract") != "capability-handoff@0.1.0":
            return "RM-DESCRIPTOR-001"
    return None


def context_error(context, extension, execution_mode):
    if extension.get("extension_digest") != canonical_digest(extension, "extension_digest"):
        return "RM-CONTEXT-DIGEST-001"
    binding = extension.get("context_binding", {})
    if binding.get("context_pack_id") != context.get("context_pack_id") or binding.get("context_pack_digest") != context.get("context_pack_digest") or binding.get("project_id") != context.get("project_id"):
        return "RM-CONTEXT-BINDING-001"
    target_questions = set(extension.get("targets", {}).get("question_ids", []))
    if not target_questions or not target_questions.issubset(set(context.get("question_ids", []))):
        return "RM-CONTEXT-BINDING-001"

    fn = extension.get("function_id")
    method_basis = extension.get("method_basis")
    protocol = extension.get("protocol_basis")
    run_spec = extension.get("run_spec")
    prior = extension.get("prior_run_result_refs", [])
    decisions = extension.get("human_decision_bindings", {})

    if fn == "method_design":
        if run_spec is not None or prior:
            return "RM-FUNCTION-001"
    elif fn == "instrument_design":
        if method_basis is None:
            return "RM-FUNCTION-001"
    elif fn == "execute":
        if method_basis is None or protocol is None or run_spec is None:
            return "RM-FUNCTION-001"
        if execution_mode == "real":
            core_method = method_basis.get("core_method_ref") if isinstance(method_basis, dict) else None
            if not core_method or core_method.get("adoption_state") != "approved" or protocol.get("approval_status") != "approved":
                return "RM-REAL-EXECUTION-001"
            if not decisions.get("method_adoption_decision_ids"):
                return "RM-METHOD-DECISION-001"
            if protocol.get("material_revision") and not decisions.get("material_protocol_revision_decision_ids"):
                return "RM-PROTOCOL-DECISION-001"
    elif fn == "analyze":
        if not prior:
            return "RM-FUNCTION-001"
    else:
        return "RM-FUNCTION-001"
    return None


def result_error(extension, handoff, context, context_extension):
    if extension.get("extension_digest") != canonical_digest(extension, "extension_digest"):
        return "RM-RESULT-DIGEST-001"
    b = extension.get("handoff_binding", {})
    expected = {
        "handoff_id": handoff.get("handoff_id"),
        "handoff_digest": handoff.get("handoff_digest"),
        "invocation_id": handoff.get("invocation_id"),
        "run_id": handoff.get("run_id"),
        "context_pack_id": context.get("context_pack_id"),
        "context_pack_digest": context.get("context_pack_digest"),
        "capability_id": handoff.get("capability", {}).get("capability_id"),
        "function_id": handoff.get("capability", {}).get("function_id"),
    }
    if any(b.get(k) != v for k, v in expected.items()):
        return "RM-RESULT-BINDING-001"

    mode = handoff.get("execution_mode")
    run_ids = set()
    for run in extension.get("run_results", []):
        run_ids.add(run.get("run_result_id"))
        if run.get("input_digest") != context_extension.get("run_spec", {}).get("input_digest"):
            return "RM-PROTOCOL-001"
        if run.get("run_spec_ref", {}).get("content_digest") != context_extension.get("run_spec", {}).get("content_digest"):
            return "RM-PROTOCOL-001"
        if run.get("protocol_ref", {}).get("content_digest") != context_extension.get("protocol_basis", {}).get("content_digest"):
            return "RM-PROTOCOL-001"
        for raw in run.get("raw_data_refs", []):
            if raw.get("evidence_adoption_performed") is not False:
                return "RM-RAW-EVIDENCE-001"
            if mode in {"virtual", "synthetic_test"} and raw.get("epistemic_mode") == "empirical":
                return "RM-EPISTEMIC-MODE-001"
        if run.get("completion_status") in {"partial", "incomplete", "failed"}:
            vr = run.get("validity_report", {})
            if not run.get("missing_data") and not vr.get("limitations") and not vr.get("threats"):
                return "RM-COMPLETION-001"
        if run.get("research_completion_claimed") is not False:
            return "RM-COMPLETION-001"

    for analysis in extension.get("candidate_analyses", []):
        if analysis.get("core_analysis_adoption_performed") is not False or not set(analysis.get("source_run_result_ids", [])).issubset(run_ids):
            return "RM-ANALYSIS-001"

    outputs = handoff.get("outputs", {})
    expected_findings = {x.get("candidate_finding_id") for x in outputs.get("candidate_findings", [])}
    expected_actions = {x.get("proposal_id") for x in outputs.get("candidate_next_actions", [])}
    expected_methods = {x.get("proposal_id") for x in outputs.get("candidate_next_methods", [])}
    if set(extension.get("candidate_finding_ids", [])) != expected_findings or set(extension.get("candidate_next_action_ids", [])) != expected_actions or set(extension.get("candidate_next_method_ids", [])) != expected_methods:
        return "RM-HANDOFF-CANDIDATE-001"
    return None
