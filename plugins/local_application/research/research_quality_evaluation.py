from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .research_quality_support import (
    ResearchQualityEvaluationError,
    _all_evidence_ids,
    _constraint_map,
    _lookup_assessment,
    _objects,
    _policy,
    _row,
    _target,
    _validate_assessment_vocab,
    _validate_basis_object_refs,
)


def evaluate(state, normalized: Mapping[str, Any]) -> dict[str, Any]:
    policy = _policy()
    _validate_assessment_vocab(normalized, policy)
    objects = _objects(state)
    _validate_basis_object_refs(objects, normalized)
    project_id = str(state.project_ref)
    rq_id = str(normalized["rq_id"])
    rq = objects.get(("research_question", rq_id))
    if (
        rq is None
        or str(rq.get("project_id")) != project_id
        or rq.get("adoption_state") not in {"approved", "revised"}
    ):
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-RQ-001",
            "rq_id must resolve to a current adopted Research Question",
        )

    finding = _target(objects, "finding", normalized.get("finding_id"), project_id, rq_id)
    claim = _target(objects, "claim", normalized.get("claim_id"), project_id, rq_id)
    method = _target(objects, "method", normalized.get("method_id"), project_id, rq_id)
    constraints = _constraint_map(state)
    research = {
        path: row for path, row in constraints.items() if path.startswith("research_quality.")
    }
    organization = {
        path: row
        for path, row in constraints.items()
        if any(source.get("profile_type") == "organization" for source in row.get("provenance", []))
    }
    assessments = normalized["assessments"]
    results: list[dict[str, Any]] = []

    def emit(
        path: str,
        status: str,
        mode: str,
        code: str | None = None,
        *,
        missing: list[str] | None = None,
        note: str | None = None,
    ) -> None:
        if path in research:
            results.append(
                _row(
                    path,
                    status,
                    provenance=research[path].get("provenance", []),
                    configured_value=research[path].get("value"),
                    mode=mode,
                    code=code,
                    missing=missing,
                    note=note,
                )
            )

    finding_evidence = [str(item) for item in (finding or {}).get("evidence_ids", [])]
    claim_evidence = [str(item) for item in (claim or {}).get("supporting_evidence_ids", [])]
    all_evidence = _all_evidence_ids(finding, claim)

    path = "research_quality.source.forbidden_as_sole_material_support_tiers"
    if path in research:
        if finding is None:
            emit(
                path, "unevaluated", "machine_check_on_explicit_assessment", missing=["finding_id"]
            )
        elif not finding_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            values: list[str] = []
            missing: list[str] = []
            for evidence_id in finding_evidence:
                evidence = objects.get(("evidence", evidence_id))
                source_id = str(evidence.get("source_id")) if evidence else ""
                ok, value = _lookup_assessment(assessments, "sources", source_id, "quality_tier")
                if ok:
                    values.append(value)
                else:
                    missing.append(f"sources.{source_id}.quality_tier")
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif values and all(value in set(research[path]["value"]) for value in values):
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment",
                    "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.source.cannot_resolve_material_gap_tiers"
    if path in research:
        item = assessments["sufficiency"].get("gap_resolution_evidence_ids")
        if item is None:
            emit(
                path,
                "unevaluated",
                "machine_check_on_explicit_assessment",
                missing=["sufficiency.gap_resolution_evidence_ids"],
            )
        elif not item["value"]:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            violation = False
            for evidence_id in item["value"]:
                evidence = objects.get(("evidence", evidence_id))
                if evidence is None:
                    raise ResearchQualityEvaluationError(
                        "APPLICATION-RESEARCH-QUALITY-TARGET-001",
                        f"gap resolution evidence is not current: {evidence_id}",
                    )
                source_id = str(evidence["source_id"])
                ok, value = _lookup_assessment(assessments, "sources", source_id, "quality_tier")
                if not ok:
                    missing.append(f"sources.{source_id}.quality_tier")
                elif value in set(research[path]["value"]):
                    violation = True
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif violation:
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment",
                    "RESEARCH-QUALITY-SUFFICIENCY-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    for tier, path in (
        ("low_confidence", "research_quality.source.low_confidence.allowed_support_scopes"),
        ("low_trust", "research_quality.source.low_trust.allowed_support_scopes"),
    ):
        if path not in research:
            continue
        if not all_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
            continue
        missing: list[str] = []
        relevant: list[str] = []
        for evidence_id in all_evidence:
            evidence = objects.get(("evidence", evidence_id))
            source_id = str(evidence.get("source_id")) if evidence else ""
            ok_tier, quality_tier = _lookup_assessment(
                assessments, "sources", source_id, "quality_tier"
            )
            if not ok_tier:
                missing.append(f"sources.{source_id}.quality_tier")
                continue
            if quality_tier == tier:
                ok_scope, support_scope = _lookup_assessment(
                    assessments, "evidence", evidence_id, "support_scope"
                )
                if ok_scope:
                    relevant.append(support_scope)
                else:
                    missing.append(f"evidence.{evidence_id}.support_scope")
        if missing:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
        elif not relevant:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        elif any(value not in set(research[path]["value"]) for value in relevant):
            emit(
                path,
                "violation",
                "machine_check_on_explicit_assessment",
                "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.source.company_primary.allowed_support_scopes"
    if path in research:
        if not all_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            relevant: list[str] = []
            for evidence_id in all_evidence:
                evidence = objects.get(("evidence", evidence_id))
                source_id = str(evidence.get("source_id")) if evidence else ""
                ok_role, source_role = _lookup_assessment(
                    assessments, "sources", source_id, "source_role"
                )
                if not ok_role:
                    missing.append(f"sources.{source_id}.source_role")
                    continue
                if source_role == "company_primary":
                    ok_scope, support_scope = _lookup_assessment(
                        assessments, "evidence", evidence_id, "support_scope"
                    )
                    if ok_scope:
                        relevant.append(support_scope)
                    else:
                        missing.append(f"evidence.{evidence_id}.support_scope")
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif not relevant:
                emit(path, "not_applicable", "machine_check_on_explicit_assessment")
            elif any(value not in set(research[path]["value"]) for value in relevant):
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment",
                    "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.evidence.material_support.required_verification_statuses"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif not finding_evidence:
            emit(path, "not_applicable", "machine_check_on_core_state")
        elif any(
            objects.get(("evidence", evidence_id), {}).get("verification_status")
            not in set(research[path]["value"])
            for evidence_id in finding_evidence
        ):
            emit(
                path,
                "violation",
                "machine_check_on_core_state",
                "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_core_state")

    path = "research_quality.evidence.claim_support.allowed_directness"
    if path in research:
        if claim is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["claim_id"])
        elif not claim_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            values: list[str] = []
            for evidence_id in claim_evidence:
                ok, value = _lookup_assessment(assessments, "evidence", evidence_id, "directness")
                if ok:
                    values.append(value)
                else:
                    missing.append(f"evidence.{evidence_id}.directness")
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif any(value not in set(research[path]["value"]) for value in values):
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment",
                    "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.evidence.indirect_support.requirements"
    if path in research:
        if claim is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["claim_id"])
        elif not claim_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            indirect: list[str] = []
            for evidence_id in claim_evidence:
                ok, directness = _lookup_assessment(
                    assessments, "evidence", evidence_id, "directness"
                )
                if not ok:
                    missing.append(f"evidence.{evidence_id}.directness")
                elif directness == "indirect":
                    indirect.append(evidence_id)
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif not indirect:
                emit(path, "not_applicable", "machine_check_on_explicit_assessment")
            elif "explicit_qualification" in set(research[path]["value"]):
                missing_qualifier: list[str] = []
                violation = False
                for evidence_id in indirect:
                    ok, value = _lookup_assessment(
                        assessments, "evidence", evidence_id, "explicit_qualification"
                    )
                    if not ok:
                        missing_qualifier.append(f"evidence.{evidence_id}.explicit_qualification")
                    elif not value:
                        violation = True
                if missing_qualifier:
                    emit(
                        path,
                        "unevaluated",
                        "machine_check_on_explicit_assessment",
                        missing=missing_qualifier,
                    )
                elif violation:
                    emit(
                        path,
                        "violation",
                        "machine_check_on_explicit_assessment",
                        "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001",
                    )
                else:
                    emit(path, "conformant", "machine_check_on_explicit_assessment")
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    claim_family_ok, claim_family = (
        (False, None)
        if claim is None
        else _lookup_assessment(assessments, "claims", str(claim["id"]), "claim_family")
    )
    selector = "research_quality.evidence.independence.required_claim_families"
    independence_applies: bool | None = None
    if selector in research:
        if claim is None:
            emit(
                selector,
                "unevaluated",
                "machine_check_on_explicit_assessment",
                missing=["claim_id"],
            )
        elif not claim_family_ok:
            emit(
                selector,
                "unevaluated",
                "machine_check_on_explicit_assessment",
                missing=[f"claims.{claim['id']}.claim_family"],
            )
        elif claim_family not in set(research[selector]["value"]):
            emit(selector, "not_applicable", "machine_check_on_explicit_assessment")
            independence_applies = False
        else:
            emit(
                selector,
                "conformant",
                "machine_check_on_explicit_assessment",
                note="claim family selects independence checks",
            )
            independence_applies = True

    path = "research_quality.evidence.independence.requirements"
    if path in research:
        applies = independence_applies if independence_applies is not None else True
        if claim is None:
            emit(
                path,
                "unevaluated",
                "machine_check_on_explicit_assessment_and_core_state",
                missing=["claim_id"],
            )
        elif not applies or not claim_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment_and_core_state")
        else:
            requirements = set(research[path]["value"])
            missing: list[str] = []
            violation = False
            if "distinct_independence_group" in requirements:
                groups = [
                    objects.get(("evidence", evidence_id), {}).get("independence_group")
                    for evidence_id in claim_evidence
                ]
                violation = any(not group for group in groups) or (
                    len(groups) > 1 and len(set(groups)) != len(groups)
                )
            if "synthesis_overlap_accounted" in requirements:
                for evidence_id in claim_evidence:
                    ok, value = _lookup_assessment(
                        assessments, "evidence", evidence_id, "synthesis_overlap_accounted"
                    )
                    if not ok:
                        missing.append(f"evidence.{evidence_id}.synthesis_overlap_accounted")
                    elif not value:
                        violation = True
            if "same_evidence_not_self_validate" in requirements:
                ok, formation = _lookup_assessment(
                    assessments, "claims", str(claim["id"]), "formation_evidence_ids"
                )
                if not ok:
                    missing.append(f"claims.{claim['id']}.formation_evidence_ids")
                elif claim_evidence and set(claim_evidence).issubset(set(formation)):
                    violation = True
            if missing:
                emit(
                    path,
                    "unevaluated",
                    "machine_check_on_explicit_assessment_and_core_state",
                    missing=missing,
                )
            elif violation:
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment_and_core_state",
                    "RESEARCH-QUALITY-INDEPENDENCE-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment_and_core_state")

    for family, path in (
        ("independent_effect", "research_quality.claim.independent_effect.allowed_support_scopes"),
        ("causal", "research_quality.claim.causal.allowed_support_scopes"),
    ):
        if path not in research:
            continue
        if claim is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["claim_id"])
        elif not claim_family_ok:
            emit(
                path,
                "unevaluated",
                "machine_check_on_explicit_assessment",
                missing=[f"claims.{claim['id']}.claim_family"],
            )
        elif claim_family != family:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            values: list[str] = []
            for evidence_id in claim_evidence:
                ok, value = _lookup_assessment(
                    assessments, "evidence", evidence_id, "support_scope"
                )
                if ok:
                    values.append(value)
                else:
                    missing.append(f"evidence.{evidence_id}.support_scope")
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif any(value not in set(research[path]["value"]) for value in values):
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment",
                    "RESEARCH-QUALITY-CLAIM-SUPPORT-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.claim.causal.prohibited_inference_bases"
    if path in research:
        if claim is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["claim_id"])
        elif not claim_family_ok:
            emit(
                path,
                "unevaluated",
                "machine_check_on_explicit_assessment",
                missing=[f"claims.{claim['id']}.claim_family"],
            )
        elif claim_family != "causal":
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            violation = False
            for evidence_id in claim_evidence:
                ok, value = _lookup_assessment(
                    assessments, "evidence", evidence_id, "inference_bases"
                )
                if not ok:
                    missing.append(f"evidence.{evidence_id}.inference_bases")
                elif set(value).intersection(set(research[path]["value"])):
                    violation = True
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif violation:
                emit(
                    path,
                    "violation",
                    "machine_check_on_explicit_assessment",
                    "RESEARCH-QUALITY-CAUSAL-SUPPORT-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.finding.required_qualifier_fields"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif any(not finding.get(field) for field in research[path]["value"]):
            emit(
                path,
                "violation",
                "machine_check_on_core_state",
                "RESEARCH-QUALITY-FINDING-QUALIFICATION-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_core_state")

    reviews = (
        []
        if finding is None
        else [
            obj
            for (kind, _object_id), obj in objects.items()
            if kind == "counter_review"
            and obj.get("target", {}).get("kind") == "finding"
            and obj.get("target", {}).get("id") == finding.get("id")
        ]
    )
    path = "research_quality.counter_review.required_lenses"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif not set(research[path]["value"]).issubset(
            {review.get("review_lens") for review in reviews}
        ):
            emit(
                path,
                "violation",
                "machine_check_on_core_state",
                "RESEARCH-QUALITY-COUNTER-REVIEW-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_core_state")

    path = "research_quality.counter_review.blocking_severities"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif any(
            review.get("severity") in set(research[path]["value"])
            and review.get("disposition") == "open"
            for review in reviews
        ):
            emit(
                path,
                "violation",
                "machine_check_on_core_state",
                "RESEARCH-QUALITY-COUNTER-REVIEW-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_core_state")

    path = "research_quality.evidence_sufficiency.required_checks"
    if path in research:
        required = set(research[path]["value"])
        missing: list[str] = []
        violation = False
        mapping = {
            "counterevidence_considered": "counterevidence_considered",
            "material_gaps_resolved": "material_gap_ids",
            "source_overlap_accounted": "source_overlap_accounted",
            "remaining_information_value_not_high": "remaining_information_value",
        }
        for check in required:
            field = mapping[check]
            item = assessments["sufficiency"].get(field)
            if item is None:
                missing.append(f"sufficiency.{field}")
                continue
            value = item["value"]
            if check in {"counterevidence_considered", "source_overlap_accounted"} and not value:
                violation = True
            elif check == "material_gaps_resolved" and value:
                violation = True
            elif check == "remaining_information_value_not_high" and value in {"high", "unknown"}:
                violation = True
        if missing:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
        elif violation:
            emit(
                path,
                "violation",
                "machine_check_on_explicit_assessment",
                "RESEARCH-QUALITY-SUFFICIENCY-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_explicit_assessment")

    method_family_ok, method_family = (
        (False, None)
        if method is None
        else _lookup_assessment(assessments, "methods", str(method["id"]), "method_family")
    )
    for path, field in (
        ("research_quality.methods.protocol_required_for_families", "protocol_ref"),
        ("research_quality.methods.limitations_required_for_families", "limitations"),
    ):
        if path not in research:
            continue
        if method is None:
            emit(
                path,
                "unevaluated",
                "machine_check_on_explicit_assessment_and_core_state",
                missing=["method_id"],
            )
        elif not method_family_ok:
            emit(
                path,
                "unevaluated",
                "machine_check_on_explicit_assessment_and_core_state",
                missing=[f"methods.{method['id']}.method_family"],
            )
        elif method_family not in set(research[path]["value"]):
            emit(path, "not_applicable", "machine_check_on_explicit_assessment_and_core_state")
        elif not method.get(field):
            emit(
                path,
                "violation",
                "machine_check_on_explicit_assessment_and_core_state",
                "RESEARCH-QUALITY-METHOD-001",
            )
        else:
            emit(path, "conformant", "machine_check_on_explicit_assessment_and_core_state")

    path = "research_quality.thresholds.material_finding.min_supporting_evidence_count"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif len(finding_evidence) < int(research[path]["value"]):
            emit(
                path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-SUFFICIENCY-001"
            )
        else:
            emit(path, "conformant", "machine_check_on_core_state")

    path = "research_quality.thresholds.material_finding.min_independent_evidence_groups"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        else:
            groups = {
                objects.get(("evidence", evidence_id), {}).get("independence_group")
                for evidence_id in finding_evidence
            }
            groups.discard(None)
            if len(groups) < int(research[path]["value"]):
                emit(
                    path,
                    "violation",
                    "machine_check_on_core_state",
                    "RESEARCH-QUALITY-INDEPENDENCE-001",
                )
            else:
                emit(path, "conformant", "machine_check_on_core_state")

    gate_path = "research_quality.gates.required"
    gate_results: list[dict[str, Any]] = []
    if gate_path in research:
        gate_groups = {
            "evidence_admissibility": {
                path
                for path in research
                if path.startswith("research_quality.source.")
                or path.startswith("research_quality.evidence.material_support")
                or path.startswith("research_quality.evidence.claim_support")
                or path.startswith("research_quality.evidence.indirect_support")
            },
            "claim_support": {
                path
                for path in research
                if path.startswith("research_quality.evidence.independence")
                or path.startswith("research_quality.claim.")
                or path.endswith("min_independent_evidence_groups")
            },
            "finding_sufficiency": {
                path
                for path in research
                if path.startswith("research_quality.finding.")
                or path.startswith("research_quality.evidence_sufficiency")
                or path.startswith("research_quality.thresholds.material_finding.min_supporting")
                or path.startswith("research_quality.methods.")
            },
            "counter_review": {
                path for path in research if path.startswith("research_quality.counter_review.")
            },
        }
        by_path = {row["path"]: row for row in results}
        for gate in research[gate_path]["value"]:
            related = (
                set().union(*gate_groups.values())
                if gate == "research_freeze"
                else gate_groups.get(gate, set())
            )
            present = [by_path[path] for path in related if path in by_path]
            if not present:
                status = "unevaluated"
                missing = ["configured predicate for required gate"]
            elif any(row["status"] == "violation" for row in present):
                status = "violation"
                missing = []
            elif any(row["status"] == "unevaluated" for row in present):
                status = "unevaluated"
                missing = sorted({item for row in present for item in row["unevaluated_inputs"]})
            else:
                status = "conformant"
                missing = []
            gate_results.append(
                {
                    "gate": gate,
                    "status": status,
                    "diagnostic_codes": ["RESEARCH-QUALITY-GATE-001"]
                    if status == "violation"
                    else [],
                    "unevaluated_inputs": missing,
                }
            )
        if any(row["status"] == "violation" for row in gate_results):
            gate_status = "violation"
        elif any(row["status"] == "unevaluated" for row in gate_results):
            gate_status = "unevaluated"
        else:
            gate_status = "conformant"
        emit(
            gate_path,
            gate_status,
            "aggregate_of_configured_quality_checks",
            "RESEARCH-QUALITY-GATE-001" if gate_status == "violation" else None,
            missing=sorted({item for row in gate_results for item in row["unevaluated_inputs"]}),
        )

    organization_results: list[dict[str, Any]] = []
    for path, row in sorted(organization.items()):
        assessment = normalized["organization_assessments"].get(path)
        if assessment is None:
            organization_results.append(
                _row(
                    path,
                    "unevaluated",
                    provenance=row.get("provenance", []),
                    configured_value=row.get("value"),
                    mode="host_or_human_assessment",
                    missing=[f"organization_assessments.{path}"],
                )
            )
        else:
            organization_results.append(
                _row(
                    path,
                    str(assessment["status"]),
                    provenance=row.get("provenance", []),
                    configured_value=row.get("value"),
                    mode="host_or_human_assessment",
                    note=assessment["rationale"],
                )
            )

    statuses = [row["status"] for row in results + organization_results]
    if not statuses:
        overall = "not_applicable"
    elif "violation" in statuses:
        overall = "violation"
    elif "unevaluated" in statuses:
        overall = "unevaluated"
    else:
        overall = "conformant"

    snapshot = state.current_snapshot
    return {
        "schema_version": "0.1.0",
        "evaluation_contract": "research-quality-evaluation@0.1.0",
        "project_id": project_id,
        "rq_id": rq_id,
        "target": {
            key: normalized[key]
            for key in ("finding_id", "claim_id", "method_id")
            if key in normalized
        },
        "captured_against": {
            "lineage_ref": str(state.active_lineage_ref),
            "snapshot_ref": str(snapshot["id"]),
            "snapshot_digest": str(snapshot["content_digest"]),
        },
        "effective_profile_set_digest": str(state.effective_profile_set_digest),
        "semantic_assessment_boundary": {
            "classification_truth_verified": False,
            "meaning": (
                "Explicit semantic labels are caller/Host/Human assessments with provenance. "
                "Machine checks validate configured Profile semantics against those labels and Core facts; "
                "they do not prove the labels semantically correct."
            ),
        },
        "assessment_inputs": deepcopy(normalized["assessments"]),
        "organization_assessment_inputs": deepcopy(normalized["organization_assessments"]),
        "constraint_results": sorted(results, key=lambda row: row["path"]),
        "organization_results": organization_results,
        "gate_results": gate_results,
        "evaluation_status": overall,
        "authoritative_state_changed": False,
        "human_decision_performed": False,
    }
