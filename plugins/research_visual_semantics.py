"""Bounded Exhibit semantics; capture never grants research or publication authority."""
from __future__ import annotations

from typing import Any, Mapping
import hashlib
import rfc8785
from core.runtime import canonical_digest as research_object_digest


VISUAL_CLASSES = frozenset({"source_visual", "data_visualization", "explanatory_visual"})
SEMANTIC_CHANGES = frozenset({"value", "aggregation", "classification", "causality", "relation", "interpretation", "generalization"})


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(c in "0123456789abcdef" for c in value[7:])


def validate_visual_semantics(value: Any, exhibit: Mapping[str, Any]) -> None:
    """Validate persisted, harness-bound semantics, including exact content identity."""
    if not isinstance(value, Mapping) or set(value) != {
        "visual_class", "semantic_refs", "semantic_changes", "semantic_status",
        "generator", "spec_digest",
    }:
        raise ValueError("visual_semantics shape is invalid")
    if value["visual_class"] not in VISUAL_CLASSES:
        raise ValueError("visual class is unsupported")
    changes = value["semantic_changes"]
    if not isinstance(changes, list) or any(not isinstance(c, str) or c not in SEMANTIC_CHANGES for c in changes) or len(changes) != len(set(changes)):
        raise ValueError("semantic changes are invalid")
    expected_status = "research_required" if changes else "review_required"
    if value["semantic_status"] != expected_status:
        raise ValueError("capture cannot declare semantic review or research approval")
    if value["spec_digest"] != exhibit.get("content_digest") or not _digest(value["spec_digest"]):
        raise ValueError("visual spec must bind exact Exhibit content")
    refs = value["semantic_refs"]
    if not isinstance(refs, list) or not refs or len(refs) > 64:
        raise ValueError("visual requires bounded exact semantic references")
    seen = set()
    for ref in refs:
        if not isinstance(ref, Mapping) or set(ref) != {"kind", "id", "digest"}:
            raise ValueError("visual semantic reference shape is invalid")
        if ref["kind"] not in {"research_object", "exhibit"} or not isinstance(ref["id"], str) or not ref["id"].strip() or not _digest(ref["digest"]):
            raise ValueError("visual semantic reference is invalid")
        key = (ref["kind"], ref["id"])
        if key in seen:
            raise ValueError("duplicate visual semantic reference")
        seen.add(key)
    declared = {("research_object", i) for i in exhibit.get("source_object_ids", [])} | {("exhibit", i) for i in exhibit.get("derived_from_exhibit_ids", [])}
    if seen != declared:
        raise ValueError("visual semantic references must exactly bind declared Exhibit provenance")
    generator = value["generator"]
    if value["visual_class"] == "source_visual":
        if generator is not None or not isinstance(exhibit.get("visual_target"), Mapping):
            raise ValueError("source visual must retain source capture and cannot be generated")
    else:
        if exhibit.get("visual_target") is not None:
            raise ValueError("generated visual cannot masquerade as a source visual")
        if not isinstance(generator, Mapping) or set(generator) != {"identity", "version", "instruction", "instruction_digest"}:
            raise ValueError("generated visual needs retained generator and instruction")
        if any(not isinstance(generator[f], str) or not generator[f].strip() for f in ("identity", "version", "instruction")):
            raise ValueError("generator identity/version/instruction must be explicit; use 'not exposed' when necessary")
        if len(generator["identity"]) > 256 or len(generator["version"]) > 256 or len(generator["instruction"].encode("utf-8")) > 65536:
            raise ValueError("generator metadata exceeds bounded capture limits")
        if generator["instruction_digest"] != digest(generator["instruction"]):
            raise ValueError("generation instruction digest mismatch")


def validate_visual_package_bindings(exhibits: list, objects: list) -> None:
    """Reject orphan/stale visual semantics on package build and package consume."""
    object_index = {o["id"]: o for o in objects}
    exhibit_index = {e["exhibit_id"]: e for e in exhibits}
    for exhibit in exhibits:
        from plugins.local_application.research_chart import is_host_chart, validate_chart_exhibit
        from plugins.local_application.generated_explanation import REVIEW_SCHEMA, matching_review, validate_explanation
        validate_chart_exhibit(exhibit, objects)
        validate_explanation(exhibit)
        content = exhibit.get("content", {}).get("value")
        if isinstance(content, Mapping) and content.get("schema") == REVIEW_SCHEMA:
            candidate = exhibit_index.get(content.get("candidate_id"))
            if candidate is None or (not is_host_chart(candidate) and validate_explanation(candidate) is None):
                raise ValueError("visual review requires its exact selected generated candidate")
            if is_host_chart(candidate):
                validate_chart_exhibit(candidate, objects)
            matching_review(candidate, [exhibit])
        value = exhibit.get("visual_semantics")
        if value is None:
            continue
        validate_visual_semantics(value, exhibit)
        for ref in value["semantic_refs"]:
            if ref["kind"] == "research_object":
                obj = object_index.get(ref["id"])
                actual = research_object_digest(obj) if obj is not None else None
            else:
                obj = exhibit_index.get(ref["id"])
                actual = obj.get("content_digest") if obj is not None else None
            if actual != ref["digest"]:
                raise ValueError("visual semantic reference is missing or changed in selected Research Package: " + ref["id"])
