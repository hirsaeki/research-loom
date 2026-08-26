from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .digest import canonical_extension_digest


def with_context_extension_digest(extension: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(extension))
    result["extension_digest"] = canonical_extension_digest(result)
    return result


def build_result_extension(
    handoff: Mapping[str, Any],
    context_pack: Mapping[str, Any],
    *,
    source_capture_details: Sequence[Mapping[str, Any]],
    citation_details: Sequence[Mapping[str, Any]],
    search_trace: Mapping[str, Any],
    null_results: Sequence[Mapping[str, Any]],
    evidence_gap_assessments: Sequence[Mapping[str, Any]],
    coverage_assessment: Mapping[str, Any],
    candidate_next_method_ids: Sequence[str],
) -> dict[str, Any]:
    """Build the canonical PR11 result extension, not a second Handoff format."""
    extension: dict[str, Any] = {
        "schema_version": "0.1.0",
        "extension_type": "desktop_research_result",
        "handoff_binding": {
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff["handoff_digest"],
            "invocation_id": handoff["invocation_id"],
            "run_id": handoff["run_id"],
            "context_pack_id": context_pack["context_pack_id"],
            "context_pack_digest": context_pack["context_pack_digest"],
            "capability_id": handoff["capability"]["capability_id"],
            "function_id": handoff["capability"]["function_id"],
        },
        "source_capture_details": [
            deepcopy(dict(item)) for item in source_capture_details
        ],
        "citation_details": [deepcopy(dict(item)) for item in citation_details],
        "search_trace": deepcopy(dict(search_trace)),
        "null_results": [deepcopy(dict(item)) for item in null_results],
        "evidence_gap_assessments": [
            deepcopy(dict(item)) for item in evidence_gap_assessments
        ],
        "coverage_assessment": deepcopy(dict(coverage_assessment)),
        "candidate_next_method_ids": list(candidate_next_method_ids),
    }
    extension["extension_digest"] = canonical_extension_digest(extension)
    return extension
