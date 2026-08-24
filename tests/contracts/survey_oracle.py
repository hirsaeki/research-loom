from __future__ import annotations

from research_method_oracle import canonical_digest

CANONICAL_FUNCTIONS = {"method_design", "instrument_design", "execute", "analyze"}


def descriptor_error(descriptor):
    if descriptor.get("descriptor_digest") != canonical_digest(descriptor, "descriptor_digest"):
        return "SV-DESCRIPTOR-001"
    if descriptor.get("capability_kind") != "research_method.survey":
        return "SV-DESCRIPTOR-001"
    functions = descriptor.get("declared_functions", [])
    ids = [item.get("function_id") for item in functions]
    if set(ids) != CANONICAL_FUNCTIONS or len(ids) != len(CANONICAL_FUNCTIONS):
        return "SV-DESCRIPTOR-001"
    for function in functions:
        if function.get("input_contract") != "capability-context-pack@0.1.0":
            return "SV-DESCRIPTOR-001"
        if function.get("output_contract") != "capability-handoff@0.1.0":
            return "SV-DESCRIPTOR-001"
    return None


def questionnaire_error(questionnaire):
    if questionnaire.get("content_digest") != canonical_digest(questionnaire, "content_digest"):
        return "SV-QUESTIONNAIRE-DIGEST-001"
    question_ids = [item.get("question_id") for item in questionnaire.get("questions", [])]
    if len(question_ids) != len(set(question_ids)):
        return "SV-QUESTIONNAIRE-IDENTITY-001"
    if questionnaire.get("approval_status") == "approved" and not questionnaire.get("approval_decision_id"):
        return "SV-QUESTIONNAIRE-APPROVAL-001"
    if questionnaire.get("material_revision") and not questionnaire.get("material_revision_decision_id"):
        return "SV-QUESTIONNAIRE-APPROVAL-001"
    for change in questionnaire.get("revision_changes", []):
        if change.get("change_kind") in {"wording", "scale"} and change.get("material") is not True:
            return "SV-QUESTIONNAIRE-REVISION-001"
    return None


def context_error(extension, questionnaire, execution_mode):
    if extension.get("extension_digest") != canonical_digest(extension, "extension_digest"):
        return "SV-CONTEXT-DIGEST-001"
    if extension.get("function_id") == "execute":
        qref = extension.get("questionnaire_ref")
        if not isinstance(qref, dict):
            return "SV-FUNCTION-001"
        expected = {
            "id": questionnaire.get("questionnaire_id"),
            "version": questionnaire.get("version"),
            "content_digest": questionnaire.get("content_digest"),
        }
        if any(qref.get(key) != value for key, value in expected.items()):
            return "SV-CONTEXT-BINDING-001"
        if execution_mode == "real":
            if questionnaire.get("approval_status") != "approved":
                return "SV-REAL-EXECUTION-001"
            approval_decision_id = questionnaire.get("approval_decision_id")
            decision_ids = set(extension.get("questionnaire_decision_ids", []))
            if not approval_decision_id or approval_decision_id not in decision_ids:
                return "SV-REAL-EXECUTION-001"
            if questionnaire.get("material_revision"):
                material_decision_id = questionnaire.get("material_revision_decision_id")
                if not material_decision_id or material_decision_id not in decision_ids:
                    return "SV-REAL-EXECUTION-001"
    return None


def result_error(result, execution_mode):
    if result.get("extension_digest") != canonical_digest(result, "extension_digest"):
        return "SV-RESULT-DIGEST-001"
    for response in result.get("responses", []):
        if response.get("verified_evidence_claimed") is not False:
            return "SV-RESPONSE-EVIDENCE-001"
        if execution_mode in {"virtual", "synthetic_test"} and response.get("epistemic_mode") == "empirical":
            return "SV-EPISTEMIC-MODE-001"
        if response.get("eligibility_status") == "excluded" and not response.get("exclusion_reason"):
            return "SV-DISPOSITION-001"
    disposition = result.get("sample_disposition", {})
    if disposition.get("response_count") != disposition.get("completed_count", 0) + disposition.get("partial_count", 0):
        return "SV-DISPOSITION-001"
    if disposition.get("partial_count", 0) or disposition.get("nonresponse_count", 0) or disposition.get("dropout_count", 0):
        if result.get("missing_data_preserved") is not True:
            return "SV-MISSINGNESS-001"
    for item in result.get("item_summaries", []):
        if item.get("denominator_count") != item.get("answered_count", 0) + item.get("missing_count", 0) + item.get("excluded_count", 0):
            return "SV-ANALYSIS-DENOMINATOR-001"
    if result.get("aggregate_is_finding") is not False or result.get("finding_adoption_performed") is not False:
        return "SV-ANALYSIS-AUTHORITY-001"
    if result.get("target_sample_achieved") and result.get("research_sufficiency_claimed") is not False:
        return "SV-SUFFICIENCY-001"
    return None
