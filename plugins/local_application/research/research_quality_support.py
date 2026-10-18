"""Research quality input normalization, policy and lookup helpers (#494)."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import yaml

from core.resources import resource_path

POLICY_PATH = resource_path("profiles/contracts/research-quality-policy.yaml")
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
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or len(rationale) > _MAX_RATIONALE_CHARS
    ):
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
                    valid = _valid_unique_string_list(value) and all(
                        item in allowed for item in value
                    )
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
            shape == "bool"
            and isinstance(value, bool)
            or shape == "riv"
            and isinstance(value, str)
            and value in {"low", "medium", "high", "unknown"}
            or shape == "string_list"
            and _valid_unique_string_list(value)
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
    return {str(row["path"]): row for row in raw if isinstance(row, Mapping) and row.get("path")}


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
    missing = [
        object_id
        for object_id in basis_refs(normalized)["object_ids"]
        if object_id not in current_ids
    ]
    if missing:
        raise ResearchQualityEvaluationError(
            "APPLICATION-RESEARCH-QUALITY-PROVENANCE-001",
            "assessment basis references unknown current Research objects: " + ", ".join(missing),
        )
