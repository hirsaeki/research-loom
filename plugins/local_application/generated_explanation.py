"""Exact explanatory PNG candidates and separate immutable host review notes."""
from __future__ import annotations

import base64
import hashlib
from typing import Mapping

from plugins.research_visual_semantics import SEMANTIC_CHANGES, digest
from .publication_exhibits import png_size

EXPLANATION_SCHEMA = "research-generated-explanation/v1"
REVIEW_SCHEMA = "research-visual-review/v1"


def retained_png(output: Mapping) -> bytes:
    if not isinstance(output, Mapping) or set(output) != {"media_type", "bytes_base64", "digest"} or output.get("media_type") != "image/png" or not isinstance(output.get("bytes_base64"), str) or len(output["bytes_base64"]) > 1048576:
        raise ValueError("explanatory output must be a bounded exact PNG")
    data = base64.b64decode(output["bytes_base64"], validate=True)
    if output["digest"] != "sha256:" + hashlib.sha256(data).hexdigest():
        raise ValueError("explanatory PNG digest mismatch")
    png_size(data)
    return data


def validate_request(value):
    if not isinstance(value, Mapping) or set(value) != {"purpose", "allowed_labels", "allowed_relations", "must_not_add"}:
        raise ValueError("explanation request needs purpose, allowed_labels, allowed_relations and must_not_add")
    if not isinstance(value["purpose"], str) or not value["purpose"].strip() or len(value["purpose"]) > 2048:
        raise ValueError("explanation purpose must be bounded")
    for field in ("allowed_labels", "allowed_relations", "must_not_add"):
        rows = value[field]
        if not isinstance(rows, list) or len(rows) > 64 or any(not isinstance(s, str) or not s.strip() or len(s) > 2048 for s in rows) or len(rows) != len(set(rows)):
            raise ValueError("explanation " + field + " must be bounded explicit strings")
    if not value["allowed_labels"] or not value["must_not_add"]:
        raise ValueError("explanation must declare allowed labels and forbidden added semantics")


def validate_explanation(exhibit):
    value = exhibit.get("content", {}).get("value")
    if not isinstance(value, Mapping) or value.get("schema") != EXPLANATION_SCHEMA:
        return None
    if set(value) != {"schema", "request", "generation_input_digest", "package_binding", "output"}:
        raise ValueError("explanation content shape is invalid")
    semantics = exhibit.get("visual_semantics")
    if not isinstance(semantics, Mapping) or semantics.get("visual_class") != "explanatory_visual":
        raise ValueError("explanation must preserve generated explanatory semantics")
    validate_request(value["request"])
    expected = digest({"request": value["request"], "semantic_refs": semantics["semantic_refs"], "generator": semantics["generator"]})
    if value["generation_input_digest"] != expected:
        raise ValueError("explanation generation input digest mismatch")
    binding = value["package_binding"]
    if not isinstance(binding, Mapping) or set(binding) != {"package_id", "package_digest"} or not isinstance(binding["package_id"], str) or not binding["package_id"].strip() or not isinstance(binding["package_digest"], str) or len(binding["package_digest"]) != 71 or not binding["package_digest"].startswith("sha256:"):
        raise ValueError("explanation must retain exact generation Package context")
    return retained_png(value["output"])


def matching_review(candidate, exhibits):
    """Review attestations are explicit operational records, not Research authority."""
    matches = []
    for note in exhibits:
        value = note.get("content", {}).get("value")
        if not isinstance(value, Mapping) or value.get("schema") != REVIEW_SCHEMA or value.get("candidate_id") != candidate["exhibit_id"]:
            continue
        if set(value) != {"schema", "candidate_id", "candidate_content_digest", "candidate_semantics_digest", "disposition", "semantic_changes", "reviewer", "rationale", "reviewed_at"}:
            raise ValueError("visual review note shape is invalid")
        if note.get("derived_from_exhibit_ids") != [candidate["exhibit_id"]] or value["candidate_content_digest"] != candidate["content_digest"] or value["candidate_semantics_digest"] != digest(candidate["visual_semantics"]):
            raise ValueError("visual review must pin the exact candidate and semantic contract")
        reviewer = value["reviewer"]
        if not isinstance(reviewer, Mapping) or set(reviewer) != {"actor_id", "actor_type"} or reviewer["actor_type"] not in {"human", "host"} or not isinstance(reviewer["actor_id"], str) or not reviewer["actor_id"].strip():
            raise ValueError("visual review requires explicit host/human attribution")
        for field in ("rationale", "reviewed_at"):
            if not isinstance(value[field], str) or not value[field].strip():
                raise ValueError("visual review rationale/time is missing")
        changes = value["semantic_changes"]
        if not isinstance(changes, list) or any(not isinstance(s, str) or s not in SEMANTIC_CHANGES for s in changes) or len(changes) != len(set(changes)):
            raise ValueError("visual review semantic changes are invalid")
        if value["disposition"] not in {"existing_meaning_only", "research_required"} or (value["disposition"] == "existing_meaning_only" and (changes or candidate["visual_semantics"]["semantic_changes"])):
            raise ValueError("visual review cannot waive declared research-changing meaning")
        matches.append(value)
    if not matches:
        return None
    # No majority vote or last-writer approval: conflicting review requires a
    # revised candidate, preserving all historical attestations.
    if any(v["disposition"] == "research_required" for v in matches):
        return "research_required"
    return "existing_meaning_only"
