from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation.validation import canonical_digest
from core.execution import CapabilityExecutionError
from core.execution.validation import CanonicalCapabilityExecutionValidator
from plugins.desktop_research import DesktopResearchResultValidator, build_result_extension
from plugins.desktop_research.attempts import UNSUCCESSFUL_OUTCOMES
from plugins.local_execution_store import LocalExecutionStoreError

from .facade import LocalApplicationError


class CorrectableExternalSubmissionError(LocalApplicationError):
    """Operator-owned submission content can be corrected on the same RUNNING Run."""



_RESULT_FIELDS = {
    "validation", "outputs", "capture_ids", "citation_details", "search_trace",
    "null_results", "evidence_gap_assessments", "coverage_assessment",
    "candidate_next_method_ids",
}
_OUTPUT_FIELDS = {
    "observations", "evidence_candidates", "candidate_findings", "counterevidence",
    "conflicts", "unknowns", "evidence_gaps", "candidate_next_actions",
    "candidate_next_methods",
}
_CITATION_FIELDS = {
    "citation_id", "handoff_output_kind", "handoff_output_id", "capture_id",
    "excerpt", "excerpt_locator",
}
_SEARCH_LINK_FIELDS = {"attempt_id", "related_handoff_output_ids", "notes"}


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CorrectableExternalSubmissionError("APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001", f"{field} must be an object")
    return deepcopy(dict(value))


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise CorrectableExternalSubmissionError("APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001", f"{field} must be an array")
    return deepcopy(value)


def assemble_external_submission(
    application,
    run,
    research_result: Mapping[str, Any],
    attempts: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _mapping(research_result, "research_result")
    unknown = set(value) - _RESULT_FIELDS
    if unknown:
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-SUBMISSION-001",
            "research_result contains internal, unknown, or forbidden fields: "
            + ", ".join(sorted(unknown)),
        )

    store = application.execution_store
    context = store.load_context_pack(run.context_pack_id)
    invocation = store.load_invocation(run.invocation_id)
    descriptor = store.load_descriptor(run.descriptor_digest)
    if not all(isinstance(item, Mapping) for item in (context, invocation, descriptor)):
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-BINDING-001",
            "pinned execution documents do not resolve for external submission assembly",
        )

    outputs = _mapping(value.get("outputs"), "outputs")
    extra = sorted(set(outputs) - _OUTPUT_FIELDS)
    if extra:
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-SUBMISSION-001",
            "outputs contains internal, unknown, or forbidden fields: " + ", ".join(extra),
        )
    missing = sorted(_OUTPUT_FIELDS - set(outputs))
    if missing:
        raise CorrectableExternalSubmissionError(
            "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
            "outputs is missing required research result collections: " + ", ".join(missing),
        )

    capture_ids = _list(value.get("capture_ids", []), "capture_ids")
    if any(not isinstance(item, str) or not item for item in capture_ids) or len(capture_ids) != len(set(capture_ids)):
        raise CorrectableExternalSubmissionError(
            "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
            "capture_ids must contain unique non-empty strings",
        )
    source_captures, capture_details, texts = _resolve_captures(application, run.run_id, capture_ids)
    outputs["source_captures"] = source_captures

    handoff: dict[str, Any] = {
        "schema_version": "0.1.0",
        "handoff_id": f"HND-{run.run_id}",
        "invocation_id": run.invocation_id,
        "run_id": run.run_id,
        "project_id": run.project_ref,
        "capability": deepcopy(dict(invocation["capability"])),
        "execution_mode": run.execution_mode,
        "input_pins": {
            "invocation_digest": run.invocation_digest,
            "context_pack_digest": run.context_pack_digest,
            "project_config_digest": context["pins"]["project_config"]["configuration_digest"],
            "effective_profile_set_digest": context["pins"]["effective_profile_set"]["content_digest"],
            "research_snapshot": deepcopy(dict(context["pins"]["research_snapshot"])),
        },
        "preserved_context": {
            "research_attention_ids": [str(item["attention_id"]) for item in context["research_attention"]],
            "project_guard_ids": [
                str(guard["guard_id"])
                for key in ("requirements", "prohibitions", "must_not_claim")
                for guard in context["project_constraints"][key]
            ],
            "effective_constraint_paths": [str(item["path"]) for item in context["effective_constraints"]],
        },
        "validation": _mapping(value.get("validation"), "validation"),
        "outputs": outputs,
        "provenance": {
            "trace_id": invocation["trace"]["trace_id"],
            "produced_at": application.clock.now(),
            "implementation_id": run.implementation_id,
            "implementation_version": run.implementation_version,
            "input_content_digests": [run.descriptor_digest, run.context_pack_digest, run.invocation_digest],
        },
        "adoption_boundary": {
            "research_state_mutation_performed": False,
            "outputs_are_candidates": True,
            "human_decision_required_for_authoritative_transition": True,
        },
    }
    handoff["handoff_digest"] = canonical_digest(handoff)

    extension = build_result_extension(
        handoff,
        context,
        source_capture_details=capture_details,
        citation_details=_citations(value, capture_details, texts),
        search_trace=_search_trace(value, attempts),
        null_results=_list(value.get("null_results", []), "null_results"),
        evidence_gap_assessments=_list(value.get("evidence_gap_assessments", []), "evidence_gap_assessments"),
        coverage_assessment=_mapping(value.get("coverage_assessment"), "coverage_assessment"),
        candidate_next_method_ids=_list(value.get("candidate_next_method_ids", []), "candidate_next_method_ids"),
    )
    return handoff, extension


def validate_external_submission(
    application,
    run,
    context_extension: Mapping[str, Any],
    handoff: Mapping[str, Any],
    extension: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Read-only canonical + Desktop Research validation before terminal intake."""
    store = application.execution_store
    invocation = store.load_invocation(run.invocation_id)
    context = store.load_context_pack(run.context_pack_id)
    descriptor = store.load_descriptor(run.descriptor_digest)
    if not all(isinstance(item, Mapping) for item in (invocation, context, descriptor)):
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-BINDING-001",
            "pinned execution documents do not resolve for external submission validation",
        )

    validator = CanonicalCapabilityExecutionValidator()
    try:
        validator.validate_documents(descriptor, invocation, context)
    except CapabilityExecutionError as exc:
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-BINDING-001", exc.issue.message
        ) from exc
    if (
        invocation.get("invocation_digest") != run.invocation_digest
        or context.get("context_pack_digest") != run.context_pack_digest
        or descriptor.get("descriptor_digest") != run.descriptor_digest
    ):
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-BINDING-001",
            "stored execution documents no longer match Run pins",
        )
    decision = application.authorization.validate(
        invocation["runtime_authorization_evidence"],
        invocation=invocation,
        context_pack=context,
        now=application.clock.now(),
    )
    if not decision.allowed:
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-BINDING-001",
            "; ".join(item.message for item in decision.issues)
            or "runtime authorization denied",
        )
    required = {str(item["reference_id"]) for item in context["resources"]}
    if not required.issubset(set(decision.resource_reference_ids)):
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-BINDING-001",
            "authorization provider did not grant every bounded Context Pack resource",
        )
    try:
        validator.validate_handoff(handoff, invocation, context)
    except CapabilityExecutionError as exc:
        return [_issue(exc.issue.code, exc.issue.message, retryable=exc.issue.retryable)]

    provenance = handoff["provenance"]
    if (
        provenance["implementation_id"] != run.implementation_id
        or provenance["implementation_version"] != run.implementation_version
    ):
        return [_issue("CAP-HANDOFF-PROVENANCE-001", "Handoff implementation provenance does not match the pinned adapter")]
    codes = DesktopResearchResultValidator(store, application.operational_store).validate(
        handoff,
        extension,
        context,
        context_extension,
        run_id=run.run_id,
    )
    if str(handoff["validation"]["status"]) == "rejected":
        if codes:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                "rejected Handoff has an invalid Desktop Research result extension: "
                + ", ".join(str(code) for code in codes),
            )
        return []
    return [_issue(str(code), str(code)) for code in codes]


def _issue(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def _resolve_captures(application, run_id: str, capture_ids: list[str]):
    store = application.execution_store
    by_capture: dict[str, dict[str, Any]] = {}
    for artifact in store.artifacts_for(run_id):
        capture_id = artifact.provenance.get("capture_id")
        if not isinstance(capture_id, str) or capture_id not in capture_ids:
            continue
        key = (
            "original" if artifact.role == "desktop_research.original_capture"
            else "text" if artifact.role == "desktop_research.text_rendition"
            else None
        )
        if key is None:
            continue
        slot = by_capture.setdefault(capture_id, {})
        if key in slot:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                f"selected capture has duplicate persisted {key} artifacts: {capture_id}",
            )
        slot[key] = artifact

    source_captures, details, texts = [], [], {}
    for capture_id in capture_ids:
        slot = by_capture.get(capture_id, {})
        original, text = slot.get("original"), slot.get("text")
        if not slot:
            raise CorrectableExternalSubmissionError(
                "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
                f"selected capture does not resolve for this Run: {capture_id}",
            )
        if original is None or text is None:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                f"selected capture has an incomplete persisted original/text pair: {capture_id}",
            )
        provenance = original.provenance
        if any(not isinstance(provenance.get(field), str) or not provenance.get(field) for field in ("source_category", "exact_locator", "acquired_at")):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                f"selected capture provenance is incomplete: {capture_id}",
            )
        try:
            original_payload = store.load_artifact(original.artifact_id)
            text_payload = store.load_artifact(text.artifact_id)
        except (KeyError, OSError, ValueError, LocalExecutionStoreError) as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                f"selected capture bytes failed integrity verification: {capture_id}",
            ) from exc
        if original_payload.digest != original.digest or text_payload.digest != text.digest:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                f"selected capture digest does not match verified bytes: {capture_id}",
            )
        try:
            decoded = text_payload.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INTEGRITY-001",
                f"selected capture rendition is not valid UTF-8: {capture_id}",
            ) from exc
        locator = str(provenance["exact_locator"])
        source_captures.append({
            "capture_id": capture_id,
            "origin": {
                "origin_type": "acquired_source",
                "acquisition_locator": str(provenance.get("acquisition_locator") or locator),
            },
            "locator": locator,
            "content_digest": original.digest,
        })
        details.append({
            "capture_id": capture_id,
            "source_category": str(provenance["source_category"]),
            "exact_locator": locator,
            "acquired_at": str(provenance["acquired_at"]),
            "original_capture": {
                "content_reference": original.artifact_id,
                "content_digest": original.digest,
                "media_type": original.media_type,
                "byte_length": original.size,
            },
            "text_rendition": {
                "content_reference": text.artifact_id,
                "content_digest": text.digest,
                "media_type": text.media_type,
                "byte_length": text.size,
                "encoding": "UTF-8",
            },
        })
        texts[capture_id] = decoded
    return source_captures, details, texts


def _citations(value, capture_details, texts):
    details = {str(item["capture_id"]): item for item in capture_details}
    assembled = []
    for raw in _list(value.get("citation_details", []), "citation_details"):
        citation = _mapping(raw, "citation_details[]")
        extra = sorted(set(citation) - _CITATION_FIELDS)
        if extra:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-SUBMISSION-001",
                "citation_details contains internal, unknown, or forbidden fields: "
                + ", ".join(extra),
            )
        missing = sorted(_CITATION_FIELDS - set(citation))
        if missing:
            raise CorrectableExternalSubmissionError(
                "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
                "citation_details entry is missing required fields: " + ", ".join(missing),
            )
        capture_id = str(citation["capture_id"])
        detail, text = details.get(capture_id), texts.get(capture_id)
        if detail is None or text is None:
            raise CorrectableExternalSubmissionError(
                "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
                f"citation references unresolved selected capture: {capture_id}",
            )
        excerpt = citation.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt:
            raise CorrectableExternalSubmissionError("APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001", "citation excerpt must be a non-empty string")
        assembled.append({
            **citation,
            "text_rendition_digest": detail["text_rendition"]["content_digest"],
            "capture_integrity_verified": True,
            "excerpt_containment_verified": excerpt in text,
            "evidence_adoption_performed": False,
        })
    return assembled


def _search_trace(value, attempts):
    search = _mapping(value.get("search_trace"), "search_trace")
    extra = sorted(set(search) - {"entries"})
    if extra:
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-SUBMISSION-001",
            "search_trace contains internal, unknown, or forbidden fields: " + ", ".join(extra),
        )
    if "entries" not in search:
        raise CorrectableExternalSubmissionError(
            "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
            "search_trace is missing required entries",
        )
    links = {}
    for raw in _list(search.get("entries"), "search_trace.entries"):
        link = _mapping(raw, "search_trace.entries[]")
        extra = sorted(set(link) - _SEARCH_LINK_FIELDS)
        if extra:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-SUBMISSION-001",
                "search_trace entry contains internal, unknown, or forbidden fields: "
                + ", ".join(extra),
            )
        missing = sorted({"attempt_id", "related_handoff_output_ids"} - set(link))
        if missing:
            raise CorrectableExternalSubmissionError(
                "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
                "search_trace entry is missing required fields: " + ", ".join(missing),
            )
        attempt_id = str(link["attempt_id"])
        if attempt_id in links:
            raise CorrectableExternalSubmissionError("APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001", f"duplicate search_trace attempt_id: {attempt_id}")
        links[attempt_id] = link
    if set(links) != set(attempts):
        raise CorrectableExternalSubmissionError(
            "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001",
            "search_trace must link every persisted retrieval attempt exactly once",
        )
    entries = []
    for attempt_id in sorted(attempts):
        attempt, link = attempts[attempt_id], links[attempt_id]
        entry = {
            "trace_entry_id": attempt_id,
            "strategy": attempt["strategy"],
            "coverage_dimension_ids": list(attempt["coverage_dimension_ids"]),
            "outcome": attempt["outcome"],
            "related_handoff_output_ids": _list(link["related_handoff_output_ids"], "related_handoff_output_ids"),
            "source_capture_ids": [str(attempt["resulting_capture_id"])] if attempt.get("outcome") == "source_captured" else [],
        }
        if link.get("notes") is not None:
            entry["notes"] = str(link["notes"])
        entries.append(entry)
    return {
        "entries": entries,
        "unsuccessful_entry_ids": sorted(
            attempt_id for attempt_id, attempt in attempts.items()
            if attempt.get("outcome") in UNSUCCESSFUL_OUTCOMES
        ),
    }
