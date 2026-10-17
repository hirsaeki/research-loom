"""Research Package checks that tie selected Exhibits to their visual semantics."""

from __future__ import annotations

from collections.abc import Mapping

from core.runtime import canonical_digest as research_object_digest
from plugins.research_visual_semantics import validate_visual_semantics


def validate_visual_package_bindings(exhibits: list, objects: list) -> None:
    """Reject orphan/stale visual semantics on package build and package consume."""
    object_index = {o["id"]: o for o in objects}
    exhibit_index = {e["exhibit_id"]: e for e in exhibits}
    # Imported here: generated_explanation reaches research_package_format, which imports us.
    from .generated_explanation import REVIEW_SCHEMA, matching_review, validate_explanation
    from .research_chart import is_host_chart, validate_chart_exhibit

    for exhibit in exhibits:
        validate_chart_exhibit(exhibit, objects)
        validate_explanation(exhibit)
        content = exhibit.get("content", {}).get("value")
        if isinstance(content, Mapping) and content.get("schema") == REVIEW_SCHEMA:
            candidate = exhibit_index.get(content.get("candidate_id"))
            if candidate is None or (
                not is_host_chart(candidate) and validate_explanation(candidate) is None
            ):
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
                raise ValueError(
                    "visual semantic reference is missing or changed in selected Research Package: "
                    + ref["id"]
                )
