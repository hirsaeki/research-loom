from __future__ import annotations

from copy import deepcopy
from typing import Any


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index canonical Research quality constraint specifications by path."""
    return {entry["path"]: entry for entry in catalog["constraint_paths"]}


def research_quality_constraint_error(profile: dict[str, Any], catalog: dict[str, Any]) -> str | None:
    """Return the first fixture-level Research quality declaration error, if any."""
    index = catalog_index(catalog)
    vocabularies = catalog["vocabularies"]
    for constraint in profile.get("constraints", []):
        path = constraint["path"]
        if not path.startswith("research_quality."):
            continue
        if profile["profile_type"] != "research":
            return "PROFILE-RESEARCH-QUALITY-OWNER-001"
        spec = index.get(path)
        if spec is None:
            return "PROFILE-RESEARCH-QUALITY-PATH-001"
        if constraint["merge_strategy"] != spec["merge_strategy"]:
            return "PROFILE-RESEARCH-QUALITY-MERGE-001"
        value = constraint["value"]
        if spec["value_shape"] == "enum_set":
            if not isinstance(value, list) or len(value) != len({repr(item) for item in value}):
                return "PROFILE-RESEARCH-QUALITY-VALUE-001"
            allowed = set(vocabularies[spec["vocabulary"]])
            if any(not isinstance(item, str) or item not in allowed for item in value):
                return "PROFILE-RESEARCH-QUALITY-VALUE-001"
        elif spec["value_shape"] == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return "PROFILE-RESEARCH-QUALITY-VALUE-001"
            if "minimum" in spec and value < spec["minimum"]:
                return "PROFILE-RESEARCH-QUALITY-VALUE-001"
            if "maximum" in spec and value > spec["maximum"]:
                return "PROFILE-RESEARCH-QUALITY-VALUE-001"
        else:
            raise AssertionError(f"unknown value_shape: {spec['value_shape']}")
    return None


def apply_mutations(base: dict[str, Any], mutations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply deterministic fixture mutations to a deep copy of the base state."""
    state = deepcopy(base)
    for mutation in mutations:
        parts = mutation["path"].split(".")
        parent: Any = state
        for part in parts[:-1]:
            parent = parent[part]
        if mutation["op"] == "set":
            parent[parts[-1]] = deepcopy(mutation["value"])
        elif mutation["op"] == "remove":
            parent.pop(parts[-1], None)
        else:
            raise AssertionError(f"unknown mutation op: {mutation['op']}")
    return state


def _constraints(profile: dict[str, Any]) -> dict[str, Any]:
    """Project a fixture profile's constraint declarations into path/value pairs."""
    return {constraint["path"]: constraint["value"] for constraint in profile.get("constraints", [])}


def research_quality_state_error(state: dict[str, Any], profile: dict[str, Any]) -> str | None:
    """Evaluate only the canonical Research quality semantics exercised by fixtures."""
    c = _constraints(profile)
    objects = state["objects"]
    assessments = state["assessments"]
    finding = objects["FND-1"]
    claim = objects["CLM-1"]
    method = objects["MTH-1"]
    evidence_ids = finding.get("evidence_ids", [])

    # Evidence admissibility: quality tier, verification, directness, and indirect support.
    sole_forbidden = set(c["research_quality.source.forbidden_as_sole_material_support_tiers"])
    source_tiers = [assessments["sources"][objects[eid]["source_id"]]["quality_tier"] for eid in evidence_ids]
    if source_tiers and all(tier in sole_forbidden for tier in source_tiers):
        return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"
    allowed_verification = set(c["research_quality.evidence.material_support.required_verification_statuses"])
    allowed_directness = set(c["research_quality.evidence.claim_support.allowed_directness"])
    indirect_requirements = set(c["research_quality.evidence.indirect_support.requirements"])
    for eid in evidence_ids:
        evidence = objects[eid]
        assessment = assessments["evidence"][eid]
        if evidence["verification_status"] not in allowed_verification:
            return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"
        if assessment["directness"] not in allowed_directness:
            return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"
        if assessment["directness"] == "indirect" and "explicit_qualification" in indirect_requirements \
                and not assessment.get("explicit_qualification"):
            return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"
        tier = assessments["sources"][evidence["source_id"]]["quality_tier"]
        scope = assessment["support_scope"]
        if tier == "low_confidence" and scope not in set(c["research_quality.source.low_confidence.allowed_support_scopes"]):
            return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"
        if tier == "low_trust" and scope not in set(c["research_quality.source.low_trust.allowed_support_scopes"]):
            return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"
        role = assessments["sources"][evidence["source_id"]]["source_role"]
        if role == "company_primary" and scope not in set(c["research_quality.source.company_primary.allowed_support_scopes"]):
            return "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001"

    claim_assessment = assessments["claims"][claim["id"]]
    claim_family = claim_assessment["claim_family"]
    evidence_scopes = {assessments["evidence"][eid]["support_scope"] for eid in evidence_ids}
    if claim_family == "independent_effect" and not evidence_scopes.issubset(
            set(c["research_quality.claim.independent_effect.allowed_support_scopes"])):
        return "RESEARCH-QUALITY-CLAIM-SUPPORT-001"
    if claim_family == "causal" and not evidence_scopes.issubset(
            set(c["research_quality.claim.causal.allowed_support_scopes"])):
        return "RESEARCH-QUALITY-CLAIM-SUPPORT-001"

    independence_requirements = set(c["research_quality.evidence.independence.requirements"])
    if "same_evidence_not_self_validate" in independence_requirements:
        formation = set(claim_assessment.get("formation_evidence_ids", []))
        supporting = set(claim.get("supporting_evidence_ids", []))
        if formation and supporting and supporting.issubset(formation):
            return "RESEARCH-QUALITY-INDEPENDENCE-001"
    if "synthesis_overlap_accounted" in independence_requirements:
        if any(not assessments["evidence"][eid].get("synthesis_overlap_accounted", False) for eid in evidence_ids):
            return "RESEARCH-QUALITY-INDEPENDENCE-001"
    if claim_family in set(c["research_quality.evidence.independence.required_claim_families"]):
        groups = {objects[eid].get("independence_group") for eid in evidence_ids}
        groups.discard(None)
        minimum_groups = c["research_quality.thresholds.material_finding.min_independent_evidence_groups"]
        if "distinct_independence_group" in independence_requirements and len(groups) < minimum_groups:
            return "RESEARCH-QUALITY-INDEPENDENCE-001"

    if claim_family == "causal":
        prohibited = set(c["research_quality.claim.causal.prohibited_inference_bases"])
        for eid in evidence_ids:
            if prohibited.intersection(assessments["evidence"][eid].get("inference_bases", [])):
                return "RESEARCH-QUALITY-CAUSAL-SUPPORT-001"

    for field in c["research_quality.finding.required_qualifier_fields"]:
        if not finding.get(field):
            return "RESEARCH-QUALITY-FINDING-QUALIFICATION-001"

    method_family = assessments["methods"][method["id"]]["method_family"]
    if method_family in set(c["research_quality.methods.protocol_required_for_families"]) and not method.get("protocol_ref"):
        return "RESEARCH-QUALITY-METHOD-001"
    if method_family in set(c["research_quality.methods.limitations_required_for_families"]) and not method.get("limitations"):
        return "RESEARCH-QUALITY-METHOD-001"

    reviews = [obj for obj in objects.values() if obj.get("kind") == "counter_review" and obj["target"]["id"] == finding["id"]]
    required_lenses = set(c["research_quality.counter_review.required_lenses"])
    if not required_lenses.issubset({review.get("review_lens") for review in reviews}):
        return "RESEARCH-QUALITY-COUNTER-REVIEW-001"
    blocking = set(c["research_quality.counter_review.blocking_severities"])
    if any(review["severity"] in blocking and review["disposition"] == "open" for review in reviews):
        return "RESEARCH-QUALITY-COUNTER-REVIEW-001"

    if len(evidence_ids) < c["research_quality.thresholds.material_finding.min_supporting_evidence_count"]:
        return "RESEARCH-QUALITY-SUFFICIENCY-001"
    checks = set(c["research_quality.evidence_sufficiency.required_checks"])
    sufficiency = state["sufficiency"]
    cannot_resolve_tiers = set(c["research_quality.source.cannot_resolve_material_gap_tiers"])
    for eid in sufficiency.get("gap_resolution_evidence_ids", []):
        source_id = objects[eid]["source_id"]
        if assessments["sources"][source_id]["quality_tier"] in cannot_resolve_tiers:
            return "RESEARCH-QUALITY-SUFFICIENCY-001"
    if "counterevidence_considered" in checks and not sufficiency["counterevidence_considered"]:
        return "RESEARCH-QUALITY-SUFFICIENCY-001"
    if "material_gaps_resolved" in checks and sufficiency["material_gap_ids"]:
        return "RESEARCH-QUALITY-SUFFICIENCY-001"
    if "source_overlap_accounted" in checks and not sufficiency["source_overlap_accounted"]:
        return "RESEARCH-QUALITY-SUFFICIENCY-001"
    if "remaining_information_value_not_high" in checks and sufficiency["remaining_information_value"] == "high":
        return "RESEARCH-QUALITY-SUFFICIENCY-001"

    for gate in c["research_quality.gates.required"]:
        if not state["quality_gate_results"].get(gate, False):
            return "RESEARCH-QUALITY-GATE-001"
    return None
