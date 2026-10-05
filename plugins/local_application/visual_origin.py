"""Verify exact generation context, independently of model-provided provenance."""
from typing import Mapping

from core.runtime import canonical_digest
from plugins.research_visual_semantics import digest


def verify_visual_origin(exhibit, origin):
    content = exhibit["content"]["value"]
    binding = content["package_binding"]
    if not isinstance(origin, Mapping) or origin.get("package_id") != binding["package_id"] or origin.get("package_digest") != binding["package_digest"]:
        raise ValueError("visual generation Package identity/digest mismatch")
    body = dict(origin); body.pop("package_digest", None)
    if digest(body) != binding["package_digest"]:
        raise ValueError("visual generation Package document digest mismatch")
    objects = {o["id"]: o for o in origin["resolved_content"]["research_objects"]}
    exhibits = {e["exhibit_id"]: e for e in origin["resolved_content"]["working_material"]["research_exhibits"]}
    for ref in exhibit["visual_semantics"]["semantic_refs"]:
        obj = objects.get(ref["id"]) if ref["kind"] == "research_object" else exhibits.get(ref["id"])
        actual = canonical_digest(obj) if obj is not None and ref["kind"] == "research_object" else obj.get("content_digest") if obj is not None else None
        if actual != ref["digest"]:
            raise ValueError("visual input is not exact selected generation-Package research: " + ref["id"])
