from __future__ import annotations

from research_method_oracle import canonical_digest

CANONICAL_FUNCTIONS = {"method_design", "instrument_design", "execute", "analyze"}
CASE_ERROR_CODES = {
    "CASE-DESCRIPTOR-001", "CASE-DESIGN-BINDING-001", "CASE-BOUNDARY-001",
    "CASE-SELECTION-001", "CASE-REPRESENTATIVENESS-001", "CASE-ANALYSIS-INTENT-001",
    "CASE-PROTOCOL-001", "CASE-PROTOCOL-TRACE-001", "CASE-BLOCKED-001",
    "CASE-OBSERVATION-PROVENANCE-001", "CASE-MISSINGNESS-001", "CASE-NEGATIVE-DEVIANT-001",
    "CASE-CROSS-CASE-001", "CASE-TRIANGULATION-001", "CASE-CAUSAL-BOUNDARY-001",
    "CASE-EPISTEMIC-MODE-001", "CASE-STOPPING-001", "CASE-AUTHORITY-001",
}
EPISTEMIC_MODE_BY_EXECUTION = {"real": "empirical", "virtual": "virtual", "synthetic_test": "synthetic"}


def descriptor_error(descriptor):
    """Return the first Case Study descriptor semantic error, if any."""
    if descriptor.get("descriptor_digest") != canonical_digest(descriptor, "descriptor_digest"):
        return "CASE-DESCRIPTOR-001"
    if descriptor.get("capability_kind") != "research_method.case_study":
        return "CASE-DESCRIPTOR-001"
    functions = descriptor.get("declared_functions", [])
    ids = [item.get("function_id") for item in functions]
    if set(ids) != CANONICAL_FUNCTIONS or len(ids) != len(CANONICAL_FUNCTIONS):
        return "CASE-DESCRIPTOR-001"
    for function in functions:
        if function.get("input_contract") != "capability-context-pack@0.1.0" or function.get("output_contract") != "capability-handoff@0.1.0":
            return "CASE-DESCRIPTOR-001"
    return None


def design_error(design):
    """Return the first Case Study method-design semantic error, if any."""
    if design.get("content_digest") != canonical_digest(design, "content_digest"):
        return "CASE-DESIGN-BINDING-001"
    purpose = design.get("purpose", {})
    if not purpose.get("target_question_ids") or not purpose.get("evidence_gap_refs"):
        return "CASE-DESIGN-BINDING-001"

    boundary = design.get("case_boundary")
    if not isinstance(boundary, dict) or boundary.get("content_digest") != canonical_digest(boundary, "content_digest") or not boundary.get("boundary_id") or not boundary.get("definition"):
        return "CASE-BOUNDARY-001"
    boundary_type = boundary.get("boundary_type")
    required_scope = {
        "organizational": "organizational_scope",
        "temporal": "temporal_scope",
        "process_event": "process_event_scope",
        "system_product": "system_product_scope",
        "other": "other_scope",
    }.get(boundary_type)
    if required_scope is None or boundary.get(required_scope) in (None, ""):
        return "CASE-BOUNDARY-001"
    temporal_scope = boundary.get("temporal_scope")
    if temporal_scope is not None and (not isinstance(temporal_scope, dict) or not temporal_scope.get("start") or not temporal_scope.get("end")):
        return "CASE-BOUNDARY-001"

    selection = design.get("selection", {})
    strategy = selection.get("strategy")
    selected = selection.get("selected_cases", [])
    case_ids = [item.get("case_id") for item in selected]
    if not selected or len(case_ids) != len(set(case_ids)) or any(not item.get("rationale") for item in selected) or not selection.get("number_of_cases_rationale"):
        return "CASE-SELECTION-001"
    if selection.get("convenience_only") and strategy != "convenience":
        return "CASE-SELECTION-001"
    if strategy == "comparative" and len(selected) < 2:
        return "CASE-SELECTION-001"
    universe = selection.get("case_universe", {})
    candidate_ids = universe.get("candidate_case_ids", [])
    if len(candidate_ids) != len(set(candidate_ids)):
        return "CASE-SELECTION-001"
    if universe.get("known") is True and not set(case_ids).issubset(set(candidate_ids)):
        return "CASE-SELECTION-001"

    rep = design.get("representativeness_transferability", {})
    stopping = design.get("stopping", {})
    if selection.get("selected_cases_are_population_sample") is not False or rep.get("population_representativeness_claimed") is not False or stopping.get("fixed_case_count_alone_is_sufficient") is not False:
        return "CASE-REPRESENTATIVENESS-001"
    intent = design.get("analysis_intent", {})
    if (len(selected) > 1 and intent.get("cross_case") is not True) or (len(selected) == 1 and intent.get("cross_case") is True):
        return "CASE-ANALYSIS-INTENT-001"
    return None


def protocol_error(protocol):
    """Return the first Case Protocol semantic error, if any."""
    if protocol.get("content_digest") != canonical_digest(protocol, "content_digest"):
        return "CASE-PROTOCOL-001"
    if protocol.get("approval_status") == "approved" and not protocol.get("approval_decision_id"):
        return "CASE-PROTOCOL-001"
    if protocol.get("material_revision") and not protocol.get("material_revision_decision_id"):
        return "CASE-PROTOCOL-001"
    field_ids = [item.get("field_id") for item in protocol.get("fields", [])]
    if not field_ids or len(field_ids) != len(set(field_ids)):
        return "CASE-PROTOCOL-001"
    triangulation = protocol.get("triangulation_plan", {})
    if any(triangulation.get(key) is not True for key in ("required_source_role_diversity", "independence_by_primary_source", "conflicts_must_be_preserved")):
        return "CASE-PROTOCOL-001"
    negative_rival = protocol.get("negative_rival_capture", {})
    if any(negative_rival.get(key) is not True for key in ("negative_evidence_required", "rival_explanation_required", "unresolved_ambiguity_required")):
        return "CASE-PROTOCOL-001"
    for field in protocol.get("fields", []):
        trace = field.get("traceability", {})
        if not (trace.get("research_question_ids") or trace.get("evidence_gap_refs") or trace.get("construct_ids")):
            return "CASE-PROTOCOL-TRACE-001"
    return None


def context_error(context, design, protocol):
    """Return the first fail-closed Case Study context error, if any."""
    if context.get("extension_digest") != canonical_digest(context, "extension_digest"):
        return "CASE-BLOCKED-001"
    dref = context.get("case_design_ref", {})
    expected_design = {"id": design.get("case_study_design_id"), "version": design.get("version"), "content_digest": design.get("content_digest")}
    if any(dref.get(k) != v for k, v in expected_design.items()):
        return "CASE-BLOCKED-001"
    pref = context.get("protocol_ref", {})
    expected_protocol = {"id": protocol.get("protocol_id"), "version": protocol.get("version"), "content_digest": protocol.get("content_digest")}
    if any(pref.get(k) != v for k, v in expected_protocol.items()):
        return "CASE-BLOCKED-001"
    gates = ("required_inputs_complete", "runtime_authorized", "human_decision_complete", "rq_gap_binding_complete", "case_boundary_pins_valid", "protocol_pin_compatible")
    if context.get("function_id") == "execute" and any(context.get(key) is not True for key in gates):
        return "CASE-BLOCKED-001"
    if protocol.get("approval_status") != "approved" or protocol.get("approval_decision_id") not in set(context.get("protocol_decision_ids", [])):
        return "CASE-BLOCKED-001"
    expected_cases = {item.get("case_id") for item in design.get("selection", {}).get("selected_cases", [])}
    pins = context.get("case_boundary_pins", [])
    pin_case_ids = [item.get("case_id") for item in pins]
    if len(pin_case_ids) != len(set(pin_case_ids)) or set(pin_case_ids) != expected_cases:
        return "CASE-BOUNDARY-001"
    boundary = design.get("case_boundary", {})
    for pin in pins:
        if pin.get("boundary_id") != boundary.get("boundary_id") or pin.get("boundary_digest") != boundary.get("content_digest"):
            return "CASE-BOUNDARY-001"
    return None


def result_error(result, design, protocol):
    """Return the first Case Study result semantic error, if any."""
    if result.get("extension_digest") != canonical_digest(result, "extension_digest"):
        return "CASE-AUTHORITY-001"
    if (result.get("raw_observation_is_verified_evidence") is not False or result.get("coding_label_is_finding") is not False or result.get("interpretation_is_observed_fact") is not False or result.get("finding_adoption_performed") is not False or result.get("next_method_selection_performed") is not False or result.get("next_case_selection_performed") is not False):
        return "CASE-AUTHORITY-001"

    expected_cases = {item.get("case_id") for item in design.get("selection", {}).get("selected_cases", [])}
    runs = result.get("case_runs", [])
    if runs and {run.get("case_id") for run in runs} != expected_cases:
        return "CASE-BOUNDARY-001"
    boundary = design.get("case_boundary", {})
    expected_protocol = {"id": protocol.get("protocol_id"), "version": protocol.get("version"), "content_digest": protocol.get("content_digest")}
    obs_by_id = {}
    negative_ids, contradictory_ids, independence_groups = set(), set(), set()
    expected_mode = EPISTEMIC_MODE_BY_EXECUTION.get(result.get("execution_mode"))

    for run in runs:
        pin = run.get("case_boundary_pin", {})
        if pin.get("boundary_id") != boundary.get("boundary_id") or pin.get("boundary_digest") != boundary.get("content_digest"):
            return "CASE-BOUNDARY-001"
        ppin = run.get("protocol_pin", {})
        if any(ppin.get(k) != v for k, v in expected_protocol.items()):
            return "CASE-PROTOCOL-001"
        incomplete = run.get("completion_status") in {"partial", "incomplete", "failed", "unusable"} or run.get("dropout")
        if incomplete and not (run.get("access_failures") or run.get("missingness") or run.get("protocol_deviations") or run.get("exclusions") or run.get("unavailable_sources") or run.get("unresolved_ambiguities")):
            return "CASE-MISSINGNESS-001"
        for observation in run.get("observations", []):
            oid = observation.get("observation_id")
            if not oid or oid in obs_by_id or observation.get("case_id") != run.get("case_id"):
                return "CASE-OBSERVATION-PROVENANCE-001"
            obs_by_id[oid] = observation
            kind, role = observation.get("observation_kind"), observation.get("assertion_role")
            if kind == "researcher_interpretation":
                if role != "researcher_interpretation" or not observation.get("source_observation_refs"):
                    return "CASE-OBSERVATION-PROVENANCE-001"
            elif kind in {"direct_observation", "source_extraction"}:
                if role != "observed_fact":
                    return "CASE-OBSERVATION-PROVENANCE-001"
            else:
                return "CASE-OBSERVATION-PROVENANCE-001"
            if not observation.get("original_source_ref") or not observation.get("locator") or not observation.get("provenance"):
                return "CASE-OBSERVATION-PROVENANCE-001"
            if observation.get("evidence_adoption_performed") is not False or any(label.get("finding_adoption_performed") is not False for label in observation.get("coding_labels", [])):
                return "CASE-AUTHORITY-001"
            if expected_mode and observation.get("epistemic_mode") != expected_mode:
                return "CASE-EPISTEMIC-MODE-001"
            if observation.get("negative_evidence"):
                negative_ids.add(oid)
            if observation.get("contradictory"):
                contradictory_ids.add(oid)
            independence_groups.add(observation.get("independence_group"))

    for oid, observation in obs_by_id.items():
        if observation.get("observation_kind") != "researcher_interpretation":
            continue
        source_refs = set(observation.get("source_observation_refs", []))
        if oid in source_refs or not source_refs.issubset(obs_by_id):
            return "CASE-OBSERVATION-PROVENANCE-001"
        if any(obs_by_id[source_id].get("case_id") != observation.get("case_id") for source_id in source_refs):
            return "CASE-OBSERVATION-PROVENANCE-001"

    referenced_negative, referenced_contradictory = set(), set()
    analyzed_cases = set()
    for analysis in result.get("within_case_analyses", []):
        if analysis.get("candidate_only") is not True:
            return "CASE-AUTHORITY-001"
        case_id = analysis.get("case_id")
        if case_id not in expected_cases:
            return "CASE-CROSS-CASE-001"
        analyzed_cases.add(case_id)
        referenced_negative.update(analysis.get("negative_observation_refs", []))
        referenced_contradictory.update(analysis.get("contradictory_observation_refs", []))

        refs = []
        refs.extend(item.get("observation_ref") for item in analysis.get("chronology", []))
        for item in analysis.get("pattern_candidates", []):
            refs.extend(item.get("observation_refs", []))
        for item in analysis.get("mechanism_candidates", []):
            refs.extend(item.get("observation_refs", []))
        for item in analysis.get("rival_explanations", []):
            refs.extend(item.get("observation_refs", []))
        for item in analysis.get("expected_vs_observed", []):
            refs.extend(item.get("observed_refs", []))
        refs.extend(analysis.get("negative_observation_refs", []))
        refs.extend(analysis.get("contradictory_observation_refs", []))
        if any(ref not in obs_by_id or obs_by_id[ref].get("case_id") != case_id for ref in refs):
            return "CASE-OBSERVATION-PROVENANCE-001"

        if any(item.get("causal_claim_adopted") is not False for item in analysis.get("mechanism_candidates", [])):
            return "CASE-CAUSAL-BOUNDARY-001"
        if any(item.get("is_finding") is not False for item in analysis.get("pattern_candidates", [])):
            return "CASE-AUTHORITY-001"

    unreferenced_negative = {
        oid for oid in negative_ids if obs_by_id[oid].get("case_id") in analyzed_cases
    } - referenced_negative
    unreferenced_contradictory = {
        oid for oid in contradictory_ids if obs_by_id[oid].get("case_id") in analyzed_cases
    } - referenced_contradictory
    if unreferenced_negative or unreferenced_contradictory:
        return "CASE-NEGATIVE-DEVIANT-001"

    for analysis in result.get("cross_case_analyses", []):
        if analysis.get("candidate_only") is not True:
            return "CASE-AUTHORITY-001"
        if set(analysis.get("case_ids", [])) != expected_cases:
            return "CASE-CROSS-CASE-001"
        common_constructs = set(analysis.get("common_construct_ids", []))
        values = analysis.get("case_values", [])
        if not values or any(not item.get("observation_refs") for item in values):
            return "CASE-CROSS-CASE-001"
        value_case_ids = {item.get("case_id") for item in values}
        if not expected_cases.issubset(value_case_ids):
            return "CASE-CROSS-CASE-001"
        for item in values:
            case_id = item.get("case_id")
            if case_id not in expected_cases or item.get("construct_id") not in common_constructs:
                return "CASE-CROSS-CASE-001"
            if any(ref not in obs_by_id or obs_by_id[ref].get("case_id") != case_id for ref in item.get("observation_refs", [])):
                return "CASE-OBSERVATION-PROVENANCE-001"
        if any(item.get("generalizability_claimed") is not False for item in analysis.get("similarity_difference_candidates", [])) or any(item.get("causal_mechanism_claimed") is not False for item in analysis.get("pattern_candidates", [])):
            return "CASE-CAUSAL-BOUNDARY-001"
        deviant = set(analysis.get("negative_deviant_case_ids", []))
        observed_deviant = {obs.get("case_id") for obs in obs_by_id.values() if obs.get("negative_evidence") or obs.get("contradictory")}
        if not observed_deviant.issubset(deviant):
            return "CASE-NEGATIVE-DEVIANT-001"

    tri = result.get("triangulation_assessment", {})
    claimed_groups = tri.get("independent_primary_source_group_ids", [])
    if len(claimed_groups) != len(set(claimed_groups)) or tri.get("claimed_independent_source_count") != len(set(claimed_groups)) or not set(claimed_groups).issubset(independence_groups) or tri.get("observations_same_primary_source_not_independent") is not True:
        return "CASE-TRIANGULATION-001"
    if contradictory_ids and not tri.get("conflicts") and result.get("cross_case_analyses") == []:
        return "CASE-TRIANGULATION-001"
    if result.get("recurring_pattern_is_causal_mechanism") is not False or result.get("sequence_consistency_is_causal_proof") is not False or result.get("cross_case_similarity_is_generalizable") is not False:
        return "CASE-CAUSAL-BOUNDARY-001"
    if result.get("execution_mode") in {"virtual", "synthetic_test"} and result.get("virtual_content_may_be_empirical") is not False:
        return "CASE-EPISTEMIC-MODE-001"
    stop = result.get("stopping_assessment", {})
    if stop.get("fixed_case_count_only") is not False or stop.get("research_completion_claimed") is not False or stop.get("human_decision_performed") is not False:
        return "CASE-STOPPING-001"
    if stop.get("additional_case_recommendation", {}).get("recommended") and not stop.get("remaining_information_value"):
        return "CASE-STOPPING-001"
    return None
