"""Module-level helpers of the writer composition service (#494)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

from core.resources import resource_path
from core.runtime import canonical_digest
from plugins.application_errors import LocalApplicationError

from ..research_package.research_package_format import package_required_refs

SCHEMA_VERSION = "0.1.0"
MAX_COMPOSITIONS = 64
MAX_VERSIONS = 64
MAX_SECTIONS = 64
MAX_SECTION_REFS = 128
MAX_SECTION_INPUT_BYTES = 4 * 1024 * 1024
MAX_SELECTION_EVENTS = 256
SCHEMA = resource_path("core/packages/writer-publication/writer-composition.schema.json")


def _validate_schema(value: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
            key=lambda e: list(e.absolute_path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
            "canonical Writer Composition schema is unavailable",
        ) from exc
    if errors:
        first = errors[0]
        path = ".".join(map(str, first.absolute_path)) or "$"
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-SCHEMA-001",
            f"Writer Composition contract violation at {path}: {first.message}",
        )


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{field} must be a non-empty string"
        )
    return value


def _strings(value: Any, field: str, limit: int = MAX_SECTION_REFS) -> list[str]:
    if value is None:
        return []
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(x, str) or not x for x in value)
    ):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{field} must be a bounded array of IDs"
        )
    if len(set(value)) != len(value):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{field} must not contain duplicates"
        )
    return list(value)


def _digest_document(value: Mapping[str, Any], digest_field: str) -> str:
    basis = deepcopy(dict(value))
    basis.pop(digest_field, None)
    return canonical_digest(basis)


def _profile_constraint_map(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(row.get("path")): deepcopy(row.get("value"))
        for row in package.get("resolved_profiles", {}).get("effective_constraints", [])
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }


def _profile_key(
    value: Mapping[str, Any], *, digest_field: str
) -> tuple[str, str, str, str] | None:
    profile_type = value.get("profile_type")
    profile_id = value.get("profile_id")
    profile_version = value.get("profile_version")
    digest = value.get(digest_field)
    if not all(
        isinstance(item, str) and item
        for item in (profile_type, profile_id, profile_version, digest)
    ):
        return None
    return (
        str(profile_type),
        str(profile_id),
        str(profile_version),
        str(digest).removeprefix("sha256:"),
    )


def _writer_profile_delivery(package: Mapping[str, Any]) -> Mapping[str, Any] | None:
    effective = package.get("effective_profile_set", {})
    if not isinstance(effective, Mapping):
        return None
    resources = effective.get("effective_resources", [])
    pins = effective.get("profile_pins", [])
    if not isinstance(resources, list) or not isinstance(pins, list):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
            "Research Package Profile delivery is malformed",
        )
    rule_resources = [
        row for row in resources if isinstance(row, Mapping) and row.get("role") == "WRITER_RULES"
    ]
    if not rule_resources:
        return None

    source_profile_keys: set[tuple[str, str, str, str]] = set()
    rules_by_class: dict[str, set[str]] = {}
    seen_rule_ids: set[str] = set()
    for resource in rule_resources:
        provenance = resource.get("provenance", [])
        if not isinstance(provenance, list):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                "Writer Profile resource provenance is malformed",
            )
        for source in provenance:
            if isinstance(source, Mapping):
                key = _profile_key(source, digest_field="manifest_sha256")
                if key is not None:
                    source_profile_keys.add(key)
        try:
            body = json.loads(str(resource["content"]))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                "WRITER_RULES resource is not valid JSON",
            ) from exc
        items = body.get("items") if isinstance(body, Mapping) else None
        if not isinstance(items, list):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                "WRITER_RULES resource has no item inventory",
            )
        review_version = body.get("review_contract_version")
        if review_version is not None and review_version != "1.0.0":
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                "unsupported Writer rule review contract",
            )
        for item in items:
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("id"), str)
                or not isinstance(item.get("class"), str)
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                    "WRITER_RULES item inventory is malformed",
                )
            if review_version is not None:
                review = item.get("review")
                if (
                    not isinstance(review, Mapping)
                    or review.get("check_kind") not in {"structural", "semantic", "editorial"}
                    or review.get("scope") not in {"section", "document"}
                    or review.get("normativity")
                    not in {"required", "recommendation", "source_defined"}
                    or any(
                        not isinstance(review.get(key), str) or not review[key].strip()
                        for key in ("applicability", "violation_action")
                    )
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                        "Writer rule review metadata is malformed",
                    )
            rule_id = str(item["id"])
            rule_class = str(item["class"])
            if rule_id in seen_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
                    f"duplicate Writer rule identity: {rule_id}",
                )
            seen_rule_ids.add(rule_id)
            rules_by_class.setdefault(rule_class, set()).add(rule_id)
    if not source_profile_keys or not seen_rule_ids:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
            "Writer Profile delivery lacks pinned rules",
        )

    delivered_resources = []
    for resource in resources:
        if not isinstance(resource, Mapping) or not str(resource.get("role", "")).startswith(
            "WRITER_"
        ):
            continue
        provenance = resource.get("provenance", [])
        if any(
            isinstance(source, Mapping)
            and _profile_key(source, digest_field="manifest_sha256") in source_profile_keys
            for source in provenance
            if isinstance(provenance, list)
        ):
            delivered_resources.append(deepcopy(dict(resource)))
    delivered_pins = [
        deepcopy(dict(pin))
        for pin in pins
        if isinstance(pin, Mapping)
        and _profile_key(pin, digest_field="content_digest") in source_profile_keys
    ]
    if not delivered_pins or not delivered_resources:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-PROFILE-001",
            "Writer Profile pins/resources no longer match",
        )
    review_plan = [
        {"review_id": rule_class, "rule_ids": sorted(rule_ids)}
        for rule_class, rule_ids in sorted(rules_by_class.items())
    ]
    return {
        "profile_pins": delivered_pins,
        "resources": delivered_resources,
        "review_plan": review_plan,
        "rule_count": len(seen_rule_ids),
    }


def _package_ref_sets(package: Mapping[str, Any]) -> dict[str, set[str]]:
    content = package.get("content", {})
    source_refs = content.get("source_refs", []) if isinstance(content, Mapping) else []
    exhibits = (
        package.get("resolved_content", {}).get("working_material", {}).get("research_exhibits", [])
    )
    gaps = package.get("resolved_content", {}).get("unresolved_gaps", [])
    return {
        "argument_refs": set(map(str, content.get("argument_refs", []))),
        "finding_refs": set(map(str, content.get("finding_refs", []))),
        "evidence_refs": set(map(str, content.get("evidence_refs", []))),
        "source_refs": {
            str(x.get("source_id"))
            for x in source_refs
            if isinstance(x, Mapping) and x.get("source_id")
        },
        "counter_review_refs": set(map(str, content.get("counter_review_refs", []))),
        "qualifier_refs": set(map(str, content.get("qualifier_refs", []))),
        "limitation_refs": {
            str(x.get("limitation_id"))
            for x in content.get("limitations", [])
            if isinstance(x, Mapping) and x.get("limitation_id")
        },
        "contribution_refs": set(map(str, content.get("contribution_refs", []))),
        "recommendation_refs": {
            oid
            for oid, obj in _object_index(package).items()
            if obj.get("kind") == "recommendation"
        },
        "exhibit_refs": {
            str(x.get("exhibit_id"))
            for x in exhibits
            if isinstance(x, Mapping) and x.get("exhibit_id")
        },
        "gap_refs": {
            str(x.get("gap_id")) for x in gaps if isinstance(x, Mapping) and x.get("gap_id")
        },
        "material_refs": {
            f"{x.get('run_id')}:{x.get('capture', {}).get('capture_id')}"
            for x in package.get("resolved_content", {}).get("materials", [])
            if isinstance(x, Mapping)
            and x.get("run_id")
            and isinstance(x.get("capture"), Mapping)
            and x.get("capture", {}).get("capture_id")
        },
    }


def _object_index(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(x.get("id")): x
        for x in package.get("resolved_content", {}).get("research_objects", [])
        if isinstance(x, Mapping) and x.get("id")
    }


def _package_epistemic(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "package_mode": str(package.get("package_mode")),
        "source_epistemic_status": str(package.get("source_epistemic_status")),
        "preview_only": bool(package.get("preview_only")),
        "authoritative_research_freeze": bool(package.get("authoritative_research_freeze")),
        "release_eligible": bool(package.get("release_eligible")),
    }


def _object_is_authoritative(obj: Mapping[str, Any]) -> bool:
    state = obj.get("adoption_state")
    if isinstance(state, str):
        return state == "approved"
    assessment = obj.get("assessment")
    if isinstance(assessment, str):
        return assessment not in {"proposed", "candidate"}
    return True


def _material_ref(material: Mapping[str, Any]) -> str | None:
    capture = material.get("capture")
    capture_id = capture.get("capture_id") if isinstance(capture, Mapping) else None
    run_id = material.get("run_id")
    if isinstance(run_id, str) and isinstance(capture_id, str):
        return f"{run_id}:{capture_id}"
    return None


def _known_locators_for_source(package: Mapping[str, Any], source_id: str) -> set[str]:
    result: set[str] = set()
    source = _object_index(package).get(source_id)
    if source is not None and isinstance(source.get("canonical_locator"), str):
        result.add(str(source["canonical_locator"]))
    for obj in _object_index(package).values():
        if (
            obj.get("kind") == "evidence"
            and obj.get("source_id") == source_id
            and isinstance(obj.get("locator"), str)
        ):
            result.add(str(obj["locator"]))
    for material in package.get("resolved_content", {}).get("materials", []):
        if not isinstance(material, Mapping) or material.get("source_id") != source_id:
            continue
        capture = material.get("capture")
        if not isinstance(capture, Mapping):
            continue
        for key in ("source_locator", "exact_locator"):
            value = capture.get(key)
            if isinstance(value, str) and value:
                result.add(value)
    return result


def _citation_inventory(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = package.get("inventories", {}).get("citation_inventory", [])
    return {
        str(row.get("evidence_id")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("evidence_id"), str)
    }


def _source_exhibit_inventory(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = package.get("inventories", {}).get("source_exhibit_inventory", [])
    return {
        str(row.get("exhibit_id")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("exhibit_id"), str)
    }


def verify_section_input_root(root: str | Path) -> Mapping[str, Any]:
    root = Path(root)
    payload_path = root / "section-writer-input.json"
    manifest_path = root / "manifest.json"
    try:
        payload_bytes = payload_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        document = json.loads(payload_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
            "detached section Writer input is unreadable",
        ) from exc
    _validate_schema(document)
    _validate_schema(manifest)
    if _digest_document(document, "section_input_digest") != document.get("section_input_digest"):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "detached section input digest mismatch"
        )
    if _digest_document(manifest, "manifest_digest") != manifest.get("manifest_digest"):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
            "detached section manifest digest mismatch",
        )
    files = manifest.get("files", [])
    if len(files) != 1 or files[0].get("path") != "section-writer-input.json":
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
            "detached section manifest binding is invalid",
        )
    entry = files[0]
    if (
        entry.get("byte_length") != len(payload_bytes)
        or entry.get("content_digest") != "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
    ):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
            "detached section manifest content mismatch",
        )
    section = document["section_contract"]
    if _digest_document(section, "section_digest") != section.get("section_digest"):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
            "detached section contract digest mismatch",
        )
    objects = {
        str(row.get("id")): row
        for row in document["resolved_research_objects"]
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    expected_ids = set(document.get("resolved_object_ids", []))
    if expected_ids != set(objects):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
            "detached section research-object binding mismatch",
        )
    section_ref_ids = set()
    for field in (
        "argument_refs",
        "finding_refs",
        "evidence_refs",
        "source_refs",
        "counter_review_refs",
        "qualifier_refs",
        "limitation_refs",
        "contribution_refs",
        "recommendation_refs",
    ):
        section_ref_ids.update(section.get(field, []))
    if not section_ref_ids <= expected_ids:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
            "detached section references unresolved research objects",
        )
    for object_id, obj in objects.items():
        for expected_kind, ref_id in package_required_refs(obj):
            target = objects.get(ref_id)
            if target is None or target.get("kind") != expected_kind:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                    f"detached research-object closure is incomplete: {object_id}->{expected_kind}:{ref_id}",
                )
    if not any(obj.get("kind") == "research_question" for obj in objects.values()):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
            "detached section omits its Research Question",
        )
    materials = {
        row.get("material_ref"): row
        for row in document["resolved_materials"]
        if isinstance(row, Mapping)
    }
    expected_materials = set(document.get("resolved_material_refs", []))
    if expected_materials != set(materials):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
            "detached section material binding mismatch",
        )
    for ref, row in materials.items():
        text = row.get("text_rendition")
        if not isinstance(text, Mapping) or not isinstance(text.get("content"), str):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"detached material body is missing: {ref}",
            )
        data = text["content"].encode("utf-8")
        if (
            isinstance(text.get("byte_length"), bool)
            or not isinstance(text.get("byte_length"), int)
            or text["byte_length"] != len(data)
            or not isinstance(text.get("content_digest"), str)
            or text["content_digest"] != "sha256:" + hashlib.sha256(data).hexdigest()
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"detached material body size/digest mismatch: {ref}",
            )
        if _material_ref(row) != ref:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                f"detached material is misbound: {ref}",
            )
        source_id = row.get("source_id")
        if source_id is not None:
            if source_id not in objects or objects[source_id].get("kind") != "source":
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                    f"detached material Source binding is invalid: {ref}",
                )
            capture = row.get("capture")
            original = capture.get("original") if isinstance(capture, Mapping) else None
            source_obj = objects[source_id]
            if (
                not isinstance(capture, Mapping)
                or not isinstance(original, Mapping)
                or str(source_obj.get("canonical_locator", ""))
                != str(capture.get("source_locator", ""))
                or str(source_obj.get("content_digest", "")) != str(original.get("digest", ""))
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                    f"detached material Source/capture binding mismatch: {ref}",
                )
    exhibits = {
        str(row.get("exhibit_id")): row
        for row in document["resolved_exhibits"]
        if isinstance(row, Mapping) and isinstance(row.get("exhibit_id"), str)
    }
    if len(exhibits) != len(document["resolved_exhibits"]) or set(
        section.get("exhibit_refs", [])
    ) != set(exhibits):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001", "detached Exhibit binding mismatch"
        )
    exhibit_pins = {
        str(row.get("exhibit_id")): str(row.get("content_digest"))
        for row in section.get("exhibit_pins", [])
        if isinstance(row, Mapping)
    }
    if set(exhibit_pins) != set(exhibits):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001", "detached Exhibit pins are incomplete"
        )
    for exhibit_id, exhibit in exhibits.items():
        actual = _exhibit_content_digest(exhibit)
        if exhibit.get("content_digest") != actual or exhibit_pins[exhibit_id] != actual:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"detached Exhibit content mismatch: {exhibit_id}",
            )
    gaps = {
        str(row.get("gap_id")): row
        for row in document["unresolved_gaps"]
        if isinstance(row, Mapping) and isinstance(row.get("gap_id"), str)
    }
    if len(gaps) != len(document["unresolved_gaps"]) or set(section.get("gap_refs", [])) != set(
        gaps
    ):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001", "detached Gap binding mismatch"
        )
    gap_pins = {
        str(row.get("gap_id")): str(row.get("content_digest"))
        for row in section.get("gap_pins", [])
        if isinstance(row, Mapping)
    }
    if set(gap_pins) != set(gaps):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001", "detached Gap pins are incomplete"
        )
    for gap_id, gap in gaps.items():
        actual = canonical_digest(gap)
        if gap_pins[gap_id] != actual:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"detached Gap content mismatch: {gap_id}",
            )
    direct_materials = set(section.get("material_refs", []))
    if not direct_materials <= expected_materials:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
            "detached section references an unresolved material",
        )
    resolved_source_ids = {oid for oid, obj in objects.items() if obj.get("kind") == "source"}
    material_source_ids = {
        str(row.get("source_id"))
        for row in materials.values()
        if isinstance(row.get("source_id"), str)
    }
    if not resolved_source_ids <= material_source_ids:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
            "detached section omits a required Source body",
        )
    for binding in section.get("citation_bindings", []):
        if binding.get("evidence_id") not in objects or binding.get("argument_id") not in objects:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                "detached citation binding is unresolved",
            )
    for binding in section.get("exhibit_bindings", []):
        if binding.get("exhibit_id") not in exhibits:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                "detached source Exhibit binding is unresolved",
            )
    for citation in section.get("citation_requirements", []):
        source_id = citation.get("source_ref")
        if source_id not in resolved_source_ids:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                "detached citation Source is unresolved",
            )
        locator = citation.get("locator_ref")
        if locator is not None:
            known = set()
            source_obj = objects[source_id]
            if isinstance(source_obj.get("canonical_locator"), str):
                known.add(source_obj["canonical_locator"])
            for obj in objects.values():
                if (
                    obj.get("kind") == "evidence"
                    and obj.get("source_id") == source_id
                    and isinstance(obj.get("locator"), str)
                ):
                    known.add(obj["locator"])
            for row in materials.values():
                if row.get("source_id") == source_id and isinstance(row.get("capture"), Mapping):
                    for key in ("source_locator", "exact_locator"):
                        value = row["capture"].get(key)
                        if isinstance(value, str) and value:
                            known.add(value)
            if locator not in known:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                    f"detached citation locator is unresolved: {locator}",
                )
    source = document["source"]
    for key in (
        "composition_id",
        "composition_version",
        "composition_digest",
        "research_package_id",
        "research_package_digest",
        "project_id",
        "lineage_ref",
        "research_snapshot_id",
        "research_snapshot_digest",
        "effective_profile_set_ref",
        "effective_profile_set_digest",
        "package_mode",
        "source_epistemic_status",
        "preview_only",
        "authoritative_research_freeze",
        "release_eligible",
    ):
        if key not in source:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"detached source pin is incomplete: {key}",
            )
    return {
        "status": "VERIFIED",
        "section_id": section["section_id"],
        "section_input_digest": document["section_input_digest"],
    }


def _exhibit_content_digest(exhibit: Mapping[str, Any]) -> str:
    content = exhibit.get("content")
    if not isinstance(content, Mapping):
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "detached Exhibit content is invalid"
        )
    representation = content.get("representation")
    value = content.get("value")
    try:
        if representation == "json":
            if not isinstance(value, (dict, list)):
                raise TypeError
            data = rfc8785.dumps(value)
        elif representation in {"markdown", "text"}:
            if not isinstance(value, str):
                raise TypeError
            data = value.encode("utf-8")
        else:
            raise TypeError
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "detached Exhibit content is invalid"
        ) from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _linked_ids(value: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    target = value.get("target")
    if isinstance(target, Mapping) and isinstance(target.get("id"), str):
        ids.add(str(target["id"]))
    for key, item in value.items():
        if key.endswith("_id") and isinstance(item, str):
            ids.add(item)
        elif key.endswith("_ids") and isinstance(item, list):
            ids.update(str(x) for x in item if isinstance(x, str))
        elif key.endswith("_refs") and isinstance(item, list):
            ids.update(str(x) for x in item if isinstance(x, str))
    return ids
