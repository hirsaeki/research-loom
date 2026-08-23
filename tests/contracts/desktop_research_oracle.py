from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from typing import Any

import rfc8785


REQUIRED_FORBIDDEN_ROLES = {
    "writer_material",
    "publication_material",
    "publication_feedback",
    "archive_provenance",
}
UNSUCCESSFUL_SEARCH_OUTCOMES = {
    "no_relevant_source",
    "unavailable",
    "blocked",
    "duplicate",
    "out_of_scope",
}


def canonical_digest(document: dict[str, Any], digest_field: str) -> str:
    """Return the RFC 8785 SHA-256 digest without the document digest field."""
    payload = deepcopy(document)
    payload.pop(digest_field, None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def expected_context_extension_digest(document: dict[str, Any]) -> str:
    """Return the expected Desktop Research Context extension digest."""
    return canonical_digest(document, "extension_digest")


def expected_result_extension_digest(document: dict[str, Any]) -> str:
    """Return the expected Desktop Research result extension digest."""
    return canonical_digest(document, "extension_digest")


def _has_duplicates(values: list[str]) -> bool:
    """Return whether a list contains duplicate identities."""
    return len(values) != len(set(values))


def _output_index(handoff: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index PR9 Handoff outputs by Desktop Research output kind and identifier."""
    outputs = handoff["outputs"]
    index: dict[tuple[str, str], dict[str, Any]] = {}
    mappings = {
        "observation": ("observations", "observation_id"),
        "source_capture": ("source_captures", "capture_id"),
        "evidence_candidate": ("evidence_candidates", "evidence_candidate_id"),
        "candidate_finding": ("candidate_findings", "candidate_finding_id"),
        "counterevidence": ("counterevidence", "counterevidence_id"),
        "conflict": ("conflicts", "conflict_id"),
        "unknown": ("unknowns", "unknown_id"),
        "evidence_gap": ("evidence_gaps", "gap_id"),
        "next_action": ("candidate_next_actions", "proposal_id"),
        "next_method": ("candidate_next_methods", "proposal_id"),
    }
    for kind, (collection, id_field) in mappings.items():
        for item in outputs[collection]:
            index[(kind, item[id_field])] = item
    return index


def _all_output_ids(handoff: dict[str, Any]) -> set[str]:
    """Return all PR9 Handoff output identifiers."""
    return {identifier for _, identifier in _output_index(handoff)}


def _is_utc(value: str) -> bool:
    """Return whether an RFC 3339 timestamp carries a UTC offset."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    )


def context_semantic_error(
    extension: dict[str, Any],
    context_pack: dict[str, Any],
) -> str | None:
    """Return the first Desktop Research Context semantic error, if any."""
    if extension["extension_digest"] != expected_context_extension_digest(extension):
        return "DR-CONTEXT-DIGEST-001"

    expected_binding = {
        "context_pack_id": context_pack["context_pack_id"],
        "context_pack_digest": context_pack["context_pack_digest"],
        "project_id": context_pack["project_id"],
    }
    if extension["context_binding"] != expected_binding:
        return "DR-CONTEXT-BINDING-001"

    target = extension["target"]
    question_ids = set(context_pack["question_ids"])
    if target["target_type"] == "research_question":
        if target["question_id"] not in question_ids:
            return "DR-CONTEXT-BINDING-001"
    else:
        attention_ids = {
            item["attention_id"] for item in context_pack["research_attention"]
        }
        if (
            target["source_attention_id"] not in attention_ids
            or not set(target.get("related_question_ids", [])).issubset(question_ids)
        ):
            return "DR-CONTEXT-BINDING-001"

    role_bindings = extension["resource_role_bindings"]
    role_reference_ids = [item["reference_id"] for item in role_bindings]
    dimension_ids = [
        item["dimension_id"] for item in extension["coverage_dimensions"]
    ]
    if _has_duplicates(role_reference_ids) or _has_duplicates(dimension_ids):
        return "DR-CONTEXT-IDENTITY-001"

    resources = {item["reference_id"]: item for item in context_pack["resources"]}
    if set(role_reference_ids) != set(resources):
        return "DR-CONTEXT-RESOURCE-ROLE-001"

    forbidden_roles = set(extension["forbidden_resource_roles"])
    if not REQUIRED_FORBIDDEN_ROLES.issubset(forbidden_roles):
        return "DR-CONTEXT-RESOURCE-ROLE-001"

    for binding in role_bindings:
        role = binding["role"]
        resource = resources[binding["reference_id"]]
        if role in forbidden_roles:
            return "DR-CONTEXT-RESOURCE-ROLE-001"
        if role == "candidate_source" and not (
            resource["reference_type"] == "source"
            and resource["evidentiary_use"] == "candidate_source"
        ):
            return "DR-CONTEXT-RESOURCE-ROLE-001"
        if role == "research_artifact" and resource["reference_type"] != "artifact":
            return "DR-CONTEXT-RESOURCE-ROLE-001"
        if role == "research_context" and resource["evidentiary_use"] != "context_only":
            return "DR-CONTEXT-RESOURCE-ROLE-001"

    budget = extension["budget"]
    candidate_source_count = sum(
        item["role"] == "candidate_source" for item in role_bindings
    )
    artifact_count = sum(
        item["role"] == "research_artifact" for item in role_bindings
    )
    if (
        budget["max_candidate_source_resources"] > budget["max_total_resources"]
        or budget["max_artifact_resources"] > budget["max_total_resources"]
        or len(resources) > budget["max_total_resources"]
        or candidate_source_count > budget["max_candidate_source_resources"]
        or artifact_count > budget["max_artifact_resources"]
    ):
        return "DR-CONTEXT-BUDGET-001"

    return None


def result_semantic_error(
    extension: dict[str, Any],
    context_extension: dict[str, Any],
    context_pack: dict[str, Any],
    handoff: dict[str, Any],
) -> str | None:
    """Return the first Desktop Research result semantic error, if any."""
    if extension["extension_digest"] != expected_result_extension_digest(extension):
        return "DR-RESULT-DIGEST-001"

    expected_binding = {
        "handoff_id": handoff["handoff_id"],
        "handoff_digest": handoff["handoff_digest"],
        "invocation_id": handoff["invocation_id"],
        "run_id": handoff["run_id"],
        "context_pack_id": context_pack["context_pack_id"],
        "context_pack_digest": context_pack["context_pack_digest"],
        "capability_id": handoff["capability"]["capability_id"],
        "function_id": handoff["capability"]["function_id"],
    }
    if (
        extension["handoff_binding"] != expected_binding
        or handoff["capability"]["capability_id"] != "desktop-research"
        or handoff["capability"]["function_id"] != "investigate"
        or handoff["project_id"] != context_pack["project_id"]
        or handoff["input_pins"]["context_pack_digest"]
        != context_pack["context_pack_digest"]
        or context_extension["context_binding"]["context_pack_digest"]
        != context_pack["context_pack_digest"]
    ):
        return "DR-RESULT-BINDING-001"

    captures = handoff["outputs"]["source_captures"]
    capture_index = {item["capture_id"]: item for item in captures}
    capture_details = extension["source_capture_details"]
    detail_ids = [item["capture_id"] for item in capture_details]
    if _has_duplicates(detail_ids) or set(detail_ids) != set(capture_index):
        return "DR-CAPTURE-PROVENANCE-001"

    allowed_categories = set(context_extension["allowed_source_categories"])
    detail_index = {item["capture_id"]: item for item in capture_details}
    for detail in capture_details:
        capture = capture_index[detail["capture_id"]]
        if (
            detail["source_category"] not in allowed_categories
            or detail["exact_locator"] != capture["locator"]
            or detail["original_capture"]["content_digest"]
            != capture["content_digest"]
            or not _is_utc(detail["acquired_at"])
        ):
            return "DR-CAPTURE-PROVENANCE-001"

        rendition = detail["text_rendition"]
        inline_text = rendition.get("inline_text")
        if inline_text is not None:
            encoded = inline_text.encode("utf-8")
            expected_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
            if (
                rendition["byte_length"] != len(encoded)
                or rendition["content_digest"] != expected_digest
            ):
                return "DR-CAPTURE-PROVENANCE-001"

    budget = context_extension["budget"]
    total_rendition_bytes = sum(
        item["text_rendition"]["byte_length"] for item in capture_details
    )
    if (
        len(capture_details) > budget["max_acquired_source_captures"]
        or len(extension["search_trace"]["entries"])
        > budget["max_search_trace_entries"]
        or total_rendition_bytes > budget["max_text_rendition_bytes"]
    ):
        return "DR-CAPTURE-BUDGET-001"

    output_index = _output_index(handoff)
    citation_ids = [item["citation_id"] for item in extension["citation_details"]]
    if _has_duplicates(citation_ids):
        return "DR-CITATION-001"

    captured_output_keys: set[tuple[str, str]] = set()
    captured_collections = (
        (
            "evidence_candidate",
            handoff["outputs"]["evidence_candidates"],
            "evidence_candidate_id",
        ),
        (
            "counterevidence",
            handoff["outputs"]["counterevidence"],
            "counterevidence_id",
        ),
    )
    for kind, collection, id_field in captured_collections:
        for item in collection:
            if item["source_basis"]["basis_type"] == "source_capture":
                captured_output_keys.add((kind, item[id_field]))

    cited_output_keys: set[tuple[str, str]] = set()
    for citation in extension["citation_details"]:
        key = (citation["handoff_output_kind"], citation["handoff_output_id"])
        output = output_index.get(key)
        detail = detail_index.get(citation["capture_id"])
        if output is None or detail is None:
            return "DR-CITATION-001"
        basis = output["source_basis"]
        if (
            basis["basis_type"] != "source_capture"
            or basis["capture_id"] != citation["capture_id"]
            or citation["text_rendition_digest"]
            != detail["text_rendition"]["content_digest"]
            or output["locator"] != citation["excerpt_locator"]
        ):
            return "DR-CITATION-001"
        inline_text = detail["text_rendition"].get("inline_text")
        if inline_text is not None and citation["excerpt"] not in inline_text:
            return "DR-CITATION-001"
        cited_output_keys.add(key)

    if not captured_output_keys.issubset(cited_output_keys):
        return "DR-CITATION-001"

    entries = extension["search_trace"]["entries"]
    trace_ids = [item["trace_entry_id"] for item in entries]
    if _has_duplicates(trace_ids):
        return "DR-SEARCH-TRACE-001"
    trace_id_set = set(trace_ids)
    declared_dimensions = {
        item["dimension_id"] for item in context_extension["coverage_dimensions"]
    }
    handoff_output_ids = _all_output_ids(handoff)
    capture_ids = set(capture_index)

    expected_unsuccessful = {
        item["trace_entry_id"]
        for item in entries
        if item["outcome"] in UNSUCCESSFUL_SEARCH_OUTCOMES
    }
    if set(extension["search_trace"]["unsuccessful_entry_ids"]) != expected_unsuccessful:
        return "DR-SEARCH-TRACE-001"

    for entry in entries:
        if (
            not set(entry["coverage_dimension_ids"]).issubset(declared_dimensions)
            or not set(entry["related_handoff_output_ids"]).issubset(
                handoff_output_ids
            )
            or not set(entry["source_capture_ids"]).issubset(capture_ids)
        ):
            return "DR-SEARCH-TRACE-001"

    null_ids = [item["null_id"] for item in extension["null_results"]]
    if _has_duplicates(null_ids):
        return "DR-NULL-001"
    question_ids = set(context_pack["question_ids"])
    for null_result in extension["null_results"]:
        projection = null_result["handoff_projection"]
        if (
            not set(null_result["question_ids"]).issubset(question_ids)
            or (projection["output_kind"], projection["output_id"])
            not in output_index
        ):
            return "DR-NULL-001"

    handoff_gap_ids = {item["gap_id"] for item in handoff["outputs"]["evidence_gaps"]}
    gap_assessments = extension["evidence_gap_assessments"]
    assessed_gap_ids = [item["gap_id"] for item in gap_assessments]
    if (
        _has_duplicates(assessed_gap_ids)
        or set(assessed_gap_ids) != handoff_gap_ids
        or any(
            not set(item["coverage_dimension_ids"]).issubset(declared_dimensions)
            for item in gap_assessments
        )
    ):
        return "DR-EVIDENCE-GAP-001"

    dimension_assessments = extension["coverage_assessment"]["dimensions"]
    assessed_dimension_ids = [item["dimension_id"] for item in dimension_assessments]
    if (
        _has_duplicates(assessed_dimension_ids)
        or set(assessed_dimension_ids) != declared_dimensions
        or any(
            not set(item["trace_entry_ids"]).issubset(trace_id_set)
            for item in dimension_assessments
        )
    ):
        return "DR-COVERAGE-001"

    stop = extension["coverage_assessment"]["stopping_recommendation"]
    if set(stop["basis"]) == {"source_count"}:
        return "DR-STOP-BASIS-001"
    if stop["stop_recommended"] and any(
        item["materiality"] == "material" for item in gap_assessments
    ):
        return "DR-STOP-GAP-001"
    if (
        stop["stop_recommended"]
        and extension["coverage_assessment"]["remaining_information_value"]["level"]
        == "high"
    ):
        return "DR-STOP-RIV-001"

    expected_next_methods = {
        item["proposal_id"] for item in handoff["outputs"]["candidate_next_methods"]
    }
    if set(extension["candidate_next_method_ids"]) != expected_next_methods:
        return "DR-NEXT-METHOD-001"

    return None
