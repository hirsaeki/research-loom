from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "profiles/contracts/research-quality-policy.yaml"
_STATUS = {"conformant", "violation", "unevaluated", "not_applicable"}
_ORGANIZATION_STATUS = {"conformant", "violation", "not_applicable"}
_MAX_ASSESSMENT_SUBJECTS = 256
_MAX_ASSESSMENT_FIELDS = 64
_MAX_BASIS_REFS = 256
_MAX_RATIONALE_CHARS = 8192


class ResearchQualityEvaluationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _policy() -> Mapping[str, Any]:
    value = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("canonical Research quality policy is malformed")
    return value


def _objects(state) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (str(item.get("kind")), str(item.get("id"))): item
        for item in state.effective_objects()
        if isinstance(item, Mapping) and item.get("kind") and item.get("id")
    }


def _string_list(value: Any, field: str, *, maximum: int = _MAX_BASIS_REFS) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001",
            f"{field} must be an array of non-empty strings",
        )
    if len(value) > maximum:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-BOUND-001",
            f"{field} exceeds the evaluation bound",
        )
    if len(value) != len(set(value)):
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001",
            f"{field} must not contain duplicates",
        )
    return list(value)


def _basis(value: Any, field: str) -> dict[str, list[str]]:
    if not isinstance(value, Mapping) or set(value) != {"object_ids", "exhibit_ids", "run_ids"}:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001",
            f"{field}.basis must contain object_ids, exhibit_ids, and run_ids",
        )
    result = {
        "object_ids": _string_list(value["object_ids"], f"{field}.basis.object_ids"),
        "exhibit_ids": _string_list(value["exhibit_ids"], f"{field}.basis.exhibit_ids"),
        "run_ids": _string_list(value["run_ids"], f"{field}.basis.run_ids"),
    }
    if not any(result.values()):
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-PROVENANCE-001",
            f"{field} requires at least one basis reference",
        )
    return result


def _assessment(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"value", "basis", "rationale"}:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001",
            f"{field} must contain value, basis, and rationale",
        )
    rationale = value.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > _MAX_RATIONALE_CHARS:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001",
            f"{field}.rationale must be a bounded non-empty string",
        )
    return {
        "value": deepcopy(value["value"]),
        "basis": _basis(value["basis"], field),
        "rationale": rationale,
    }


def _assessment_map(value: Any, field: str) -> dict[str, dict[str, dict[str, Any]]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > _MAX_ASSESSMENT_SUBJECTS:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-BOUND-001",
            f"{field} must be a bounded object",
        )
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for subject_id, fields in value.items():
        if not isinstance(subject_id, str) or not subject_id or not isinstance(fields, Mapping):
            raise ResearchQualityEvaluationError(
                "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                f"{field} subject entries are invalid",
            )
        if len(fields) > _MAX_ASSESSMENT_FIELDS:
            raise ResearchQualityEvaluationError(
                "APPLICATION-RESEARCH-QUALITY-BOUND-001",
                f"{field}.{subject_id} has too many assessment fields",
            )
        result[subject_id] = {
            str(name): _assessment(item, f"{field}.{subject_id}.{name}")
            for name, item in fields.items()
        }
    return result


def normalize_input(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "rq_id",
        "finding_id",
        "claim_id",
        "method_id",
        "assessments",
        "organization_assessments",
    }
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001",
            "Research quality evaluation input contains unknown fields",
        )
    rq_id = value.get("rq_id")
    if not isinstance(rq_id, str) or not rq_id:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001", "rq_id is required"
        )
    result: dict[str, Any] = {"rq_id": rq_id}
    for field in ("finding_id", "claim_id", "method_id"):
        item = value.get(field)
        if item is not None and (not isinstance(item, str) or not item):
            raise ResearchQualityEvaluationError(
                "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                f"{field} must be a non-empty string",
            )
        if item is not None:
            result[field] = item

    assessments = value.get("assessments", {})
    allowed_assessments = {"sources", "evidence", "claims", "methods", "sufficiency"}
    if not isinstance(assessments, Mapping) or set(assessments) - allowed_assessments:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-INPUT-001", "assessments shape is invalid"
        )
    sufficiency = assessments.get("sufficiency") or {}
    if not isinstance(sufficiency, Mapping) or len(sufficiency) > _MAX_ASSESSMENT_FIELDS:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-BOUND-001",
            "assessments.sufficiency must be a bounded object",
        )
    result["assessments"] = {
        "sources": _assessment_map(assessments.get("sources"), "assessments.sources"),
        "evidence": _assessment_map(assessments.get("evidence"), "assessments.evidence"),
        "claims": _assessment_map(assessments.get("claims"), "assessments.claims"),
        "methods": _assessment_map(assessments.get("methods"), "assessments.methods"),
        "sufficiency": {
            str(name): _assessment(item, f"assessments.sufficiency.{name}")
            for name, item in sufficiency.items()
        },
    }

    organization = value.get("organization_assessments", {})
    if not isinstance(organization, Mapping) or len(organization) > _MAX_ASSESSMENT_SUBJECTS:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-BOUND-001",
            "organization_assessments must be a bounded object",
        )
    normalized_org: dict[str, dict[str, Any]] = {}
    for path, item in organization.items():
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(item, Mapping)
            or set(item) != {"status", "basis", "rationale"}
        ):
            raise ResearchQualityEvaluationError(
                "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                "organization assessment shape is invalid",
            )
        status = item.get("status")
        rationale = item.get("rationale")
        if (
            not isinstance(status, str)
            or status not in _ORGANIZATION_STATUS
            or not isinstance(rationale, str)
            or not rationale.strip()
            or len(rationale) > _MAX_RATIONALE_CHARS
        ):
            raise ResearchQualityEvaluationError(
                "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                "organization assessment status/rationale is invalid",
            )
        normalized_org[path] = {
            "status": status,
            "basis": _basis(item["basis"], f"organization_assessments.{path}"),
            "rationale": rationale,
        }
    result["organization_assessments"] = normalized_org
    return result


def basis_refs(normalized: Mapping[str, Any]) -> dict[str, list[str]]:
    result = {"object_ids": [], "exhibit_ids": [], "run_ids": []}

    def add(basis: Mapping[str, Any]) -> None:
        for key in result:
            for item in basis.get(key, []):
                if item not in result[key]:
                    result[key].append(item)

    for group in ("sources", "evidence", "claims", "methods"):
        for fields in normalized["assessments"][group].values():
            for item in fields.values():
                add(item["basis"])
    for item in normalized["assessments"]["sufficiency"].values():
        add(item["basis"])
    for item in normalized["organization_assessments"].values():
        add(item["basis"])
    return result


def _row(
    path: str,
    status: str,
    *,
    provenance: Any,
    configured_value: Any,
    mode: str,
    code: str | None = None,
    missing: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in _STATUS:
        raise AssertionError(status)
    result = {
        "path": path,
        "status": status,
        "verification_mode": mode,
        "diagnostic_codes": [code] if code else [],
        "unevaluated_inputs": sorted(set(missing or [])),
        "provenance": deepcopy(provenance),
        "configured_value": deepcopy(configured_value),
    }
    if note:
        result["note"] = note
    return result


def _lookup_assessment(
    assessments: Mapping[str, Any], group: str, subject_id: str, field: str
) -> tuple[bool, Any]:
    item = assessments[group].get(subject_id, {}).get(field)
    return (item is not None, deepcopy(item.get("value")) if item is not None else None)


def _valid_unique_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value))
    )


def _validate_assessment_vocab(normalized: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    vocab = policy["vocabularies"]
    specs = {
        ("sources", "quality_tier"): ("enum", set(vocab["source_quality_tier"])),
        ("sources", "source_role"): ("enum", set(vocab["source_role"])),
        ("evidence", "directness"): ("enum", set(vocab["evidence_directness"])),
        ("evidence", "support_scope"): ("enum", set(vocab["support_scope"])),
        ("evidence", "explicit_qualification"): ("bool", None),
        ("evidence", "synthesis_overlap_accounted"): ("bool", None),
        ("evidence", "inference_bases"): ("enum_list", set(vocab["causal_inference_basis"])),
        ("claims", "claim_family"): ("enum", set(vocab["claim_family"])),
        ("claims", "formation_evidence_ids"): ("string_list", None),
        ("methods", "method_family"): ("enum", set(vocab["method_family"])),
    }
    for group in ("sources", "evidence", "claims", "methods"):
        for subject_id, fields in normalized["assessments"][group].items():
            for field, item in fields.items():
                spec = specs.get((group, field))
                if spec is None:
                    raise ResearchQualityEvaluationError(
                        "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                        f"unsupported semantic assessment field {group}.{field}",
                    )
                shape, allowed = spec
                value = item["value"]
                valid = False
                if shape == "enum":
                    valid = isinstance(value, str) and value in allowed
                elif shape == "bool":
                    valid = isinstance(value, bool)
                elif shape == "enum_list":
                    valid = _valid_unique_string_list(value) and all(item in allowed for item in value)
                elif shape == "string_list":
                    valid = _valid_unique_string_list(value)
                if not valid:
                    raise ResearchQualityEvaluationError(
                        "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                        f"invalid semantic assessment value at {group}.{subject_id}.{field}",
                    )

    suff_specs = {
        "counterevidence_considered": "bool",
        "source_overlap_accounted": "bool",
        "remaining_information_value": "riv",
        "material_gap_ids": "string_list",
        "gap_resolution_evidence_ids": "string_list",
    }
    for field, item in normalized["assessments"]["sufficiency"].items():
        shape = suff_specs.get(field)
        value = item["value"]
        valid = (
            shape == "bool" and isinstance(value, bool)
            or shape == "riv" and isinstance(value, str) and value in {"low", "medium", "high", "unknown"}
            or shape == "string_list" and _valid_unique_string_list(value)
        )
        if not valid:
            raise ResearchQualityEvaluationError(
                "APPLICATION-RESEARCH-QUALITY-INPUT-001",
                f"invalid sufficiency assessment value at {field}",
            )


def _constraint_map(state) -> dict[str, Mapping[str, Any]]:
    raw = state.effective_constraints
    if isinstance(raw, Mapping):
        return {str(path): row for path, row in raw.items() if isinstance(row, Mapping)}
    return {
        str(row["path"]): row
        for row in raw
        if isinstance(row, Mapping) and row.get("path")
    }


def _target(
    objects: Mapping[tuple[str, str], Mapping[str, Any]],
    kind: str,
    object_id: str | None,
    project_id: str,
    rq_id: str,
) -> Mapping[str, Any] | None:
    if object_id is None:
        return None
    obj = objects.get((kind, object_id))
    if obj is None or str(obj.get("project_id")) != project_id:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-TARGET-001",
            f"{kind} target is not current in this project: {object_id}",
        )
    if kind == "claim" and str(obj.get("question_id")) != rq_id:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-TARGET-001",
            f"claim does not belong to rq_id: {object_id}",
        )
    if kind in {"finding", "method"} and rq_id not in obj.get("question_ids", []):
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-TARGET-001",
            f"{kind} does not belong to rq_id: {object_id}",
        )
    return obj


def _all_evidence_ids(
    finding: Mapping[str, Any] | None, claim: Mapping[str, Any] | None
) -> list[str]:
    values: list[str] = []
    for item in (finding or {}).get("evidence_ids", []):
        if str(item) not in values:
            values.append(str(item))
    for item in (claim or {}).get("supporting_evidence_ids", []):
        if str(item) not in values:
            values.append(str(item))
    return values


def _validate_basis_object_refs(
    objects: Mapping[tuple[str, str], Mapping[str, Any]], normalized: Mapping[str, Any]
) -> None:
    current_ids = {object_id for _kind, object_id in objects}
    missing = [object_id for object_id in basis_refs(normalized)["object_ids"] if object_id not in current_ids]
    if missing:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-PROVENANCE-001",
            "assessment basis references unknown current Research objects: " + ", ".join(missing),
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
    research = {path: row for path, row in constraints.items() if path.startswith("research_quality.")}
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
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["finding_id"])
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
                emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001")
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.source.cannot_resolve_material_gap_tiers"
    if path in research:
        item = assessments["sufficiency"].get("gap_resolution_evidence_ids")
        if item is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["sufficiency.gap_resolution_evidence_ids"])
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
                emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-SUFFICIENCY-001")
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
            ok_tier, quality_tier = _lookup_assessment(assessments, "sources", source_id, "quality_tier")
            if not ok_tier:
                missing.append(f"sources.{source_id}.quality_tier")
                continue
            if quality_tier == tier:
                ok_scope, support_scope = _lookup_assessment(assessments, "evidence", evidence_id, "support_scope")
                if ok_scope:
                    relevant.append(support_scope)
                else:
                    missing.append(f"evidence.{evidence_id}.support_scope")
        if missing:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
        elif not relevant:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        elif any(value not in set(research[path]["value"]) for value in relevant):
            emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001")
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
                ok_role, source_role = _lookup_assessment(assessments, "sources", source_id, "source_role")
                if not ok_role:
                    missing.append(f"sources.{source_id}.source_role")
                    continue
                if source_role == "company_primary":
                    ok_scope, support_scope = _lookup_assessment(assessments, "evidence", evidence_id, "support_scope")
                    if ok_scope:
                        relevant.append(support_scope)
                    else:
                        missing.append(f"evidence.{evidence_id}.support_scope")
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif not relevant:
                emit(path, "not_applicable", "machine_check_on_explicit_assessment")
            elif any(value not in set(research[path]["value"]) for value in relevant):
                emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001")
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
            emit(path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001")
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
                emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001")
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
                ok, directness = _lookup_assessment(assessments, "evidence", evidence_id, "directness")
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
                    ok, value = _lookup_assessment(assessments, "evidence", evidence_id, "explicit_qualification")
                    if not ok:
                        missing_qualifier.append(f"evidence.{evidence_id}.explicit_qualification")
                    elif not value:
                        violation = True
                if missing_qualifier:
                    emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing_qualifier)
                elif violation:
                    emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-EVIDENCE-ADMISSIBILITY-001")
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
            emit(selector, "unevaluated", "machine_check_on_explicit_assessment", missing=["claim_id"])
        elif not claim_family_ok:
            emit(selector, "unevaluated", "machine_check_on_explicit_assessment", missing=[f"claims.{claim['id']}.claim_family"])
        elif claim_family not in set(research[selector]["value"]):
            emit(selector, "not_applicable", "machine_check_on_explicit_assessment")
            independence_applies = False
        else:
            emit(selector, "conformant", "machine_check_on_explicit_assessment", note="claim family selects independence checks")
            independence_applies = True

    path = "research_quality.evidence.independence.requirements"
    if path in research:
        applies = independence_applies if independence_applies is not None else True
        if claim is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment_and_core_state", missing=["claim_id"])
        elif not applies or not claim_evidence:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment_and_core_state")
        else:
            requirements = set(research[path]["value"])
            missing: list[str] = []
            violation = False
            if "distinct_independence_group" in requirements:
                groups = [objects.get(("evidence", evidence_id), {}).get("independence_group") for evidence_id in claim_evidence]
                violation = any(not group for group in groups) or (
                    len(groups) > 1 and len(set(groups)) != len(groups)
                )
            if "synthesis_overlap_accounted" in requirements:
                for evidence_id in claim_evidence:
                    ok, value = _lookup_assessment(assessments, "evidence", evidence_id, "synthesis_overlap_accounted")
                    if not ok:
                        missing.append(f"evidence.{evidence_id}.synthesis_overlap_accounted")
                    elif not value:
                        violation = True
            if "same_evidence_not_self_validate" in requirements:
                ok, formation = _lookup_assessment(assessments, "claims", str(claim["id"]), "formation_evidence_ids")
                if not ok:
                    missing.append(f"claims.{claim['id']}.formation_evidence_ids")
                elif claim_evidence and set(claim_evidence).issubset(set(formation)):
                    violation = True
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment_and_core_state", missing=missing)
            elif violation:
                emit(path, "violation", "machine_check_on_explicit_assessment_and_core_state", "RESEARCH-QUALITY-INDEPENDENCE-001")
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
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=[f"claims.{claim['id']}.claim_family"])
        elif claim_family != family:
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            values: list[str] = []
            for evidence_id in claim_evidence:
                ok, value = _lookup_assessment(assessments, "evidence", evidence_id, "support_scope")
                if ok:
                    values.append(value)
                else:
                    missing.append(f"evidence.{evidence_id}.support_scope")
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif any(value not in set(research[path]["value"]) for value in values):
                emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-CLAIM-SUPPORT-001")
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.claim.causal.prohibited_inference_bases"
    if path in research:
        if claim is None:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=["claim_id"])
        elif not claim_family_ok:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=[f"claims.{claim['id']}.claim_family"])
        elif claim_family != "causal":
            emit(path, "not_applicable", "machine_check_on_explicit_assessment")
        else:
            missing: list[str] = []
            violation = False
            for evidence_id in claim_evidence:
                ok, value = _lookup_assessment(assessments, "evidence", evidence_id, "inference_bases")
                if not ok:
                    missing.append(f"evidence.{evidence_id}.inference_bases")
                elif set(value).intersection(set(research[path]["value"])):
                    violation = True
            if missing:
                emit(path, "unevaluated", "machine_check_on_explicit_assessment", missing=missing)
            elif violation:
                emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-CAUSAL-SUPPORT-001")
            else:
                emit(path, "conformant", "machine_check_on_explicit_assessment")

    path = "research_quality.finding.required_qualifier_fields"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif any(not finding.get(field) for field in research[path]["value"]):
            emit(path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-FINDING-QUALIFICATION-001")
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
        elif not set(research[path]["value"]).issubset({review.get("review_lens") for review in reviews}):
            emit(path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-COUNTER-REVIEW-001")
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
            emit(path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-COUNTER-REVIEW-001")
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
            emit(path, "violation", "machine_check_on_explicit_assessment", "RESEARCH-QUALITY-SUFFICIENCY-001")
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
            emit(path, "unevaluated", "machine_check_on_explicit_assessment_and_core_state", missing=["method_id"])
        elif not method_family_ok:
            emit(path, "unevaluated", "machine_check_on_explicit_assessment_and_core_state", missing=[f"methods.{method['id']}.method_family"])
        elif method_family not in set(research[path]["value"]):
            emit(path, "not_applicable", "machine_check_on_explicit_assessment_and_core_state")
        elif not method.get(field):
            emit(path, "violation", "machine_check_on_explicit_assessment_and_core_state", "RESEARCH-QUALITY-METHOD-001")
        else:
            emit(path, "conformant", "machine_check_on_explicit_assessment_and_core_state")

    path = "research_quality.thresholds.material_finding.min_supporting_evidence_count"
    if path in research:
        if finding is None:
            emit(path, "unevaluated", "machine_check_on_core_state", missing=["finding_id"])
        elif len(finding_evidence) < int(research[path]["value"]):
            emit(path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-SUFFICIENCY-001")
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
                emit(path, "violation", "machine_check_on_core_state", "RESEARCH-QUALITY-INDEPENDENCE-001")
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
                missing = sorted(
                    {
                        item
                        for row in present
                        for item in row["unevaluated_inputs"]
                    }
                )
            else:
                status = "conformant"
                missing = []
            gate_results.append(
                {
                    "gate": gate,
                    "status": status,
                    "diagnostic_codes": ["RESEARCH-QUALITY-GATE-001"] if status == "violation" else [],
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
            missing=sorted(
                {
                    item
                    for row in gate_results
                    for item in row["unevaluated_inputs"]
                }
            ),
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
