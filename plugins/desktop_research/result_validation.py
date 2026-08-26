from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from .attempts import (
    UNSUCCESSFUL_OUTCOMES,
    operational_terminations,
    reconstruct_attempts,
)
from .digest import canonical_extension_digest

ROOT = Path(__file__).resolve().parents[2]
DR = ROOT / "core" / "packages" / "desktop-research"
_SCHEMA = json.loads(
    (DR / "desktop-research-result-extension.schema.json").read_text(
        encoding="utf-8"
    )
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_SEMANTICS = yaml.safe_load(
    (DR / "desktop-research-semantics.yaml").read_text(encoding="utf-8")
)
_ERRORS = {str(item["id"]) for item in _SEMANTICS["errors"]}


def _utc(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    )


def _exact(locator: str) -> bool:
    if not locator.strip():
        return False
    if locator.startswith(("http://", "https://")):
        parsed = urlparse(locator)
        return bool(
            (parsed.path and parsed.path != "/")
            or parsed.query
            or parsed.fragment
        )
    return True


def _add(codes: list[str], code: str) -> None:
    if code not in _ERRORS:
        raise RuntimeError(f"uncataloged Desktop Research error: {code}")
    if code not in codes:
        codes.append(code)


def _outputs(
    handoff: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    spec = {
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
    return {
        (kind, str(item[field])): item
        for kind, (collection, field) in spec.items()
        for item in handoff["outputs"][collection]
    }


class DesktopResearchResultValidator:
    """Production PR11 validation using stored bytes and retrieval provenance."""

    def __init__(
        self,
        artifact_store,
        operational_store,
        diagnostic_store=None,
    ) -> None:
        self._artifacts = artifact_store
        self._operations = operational_store
        self._diagnostics = diagnostic_store

    def _record_capture_diagnostic(
        self,
        run_id: str,
        capture_id: str,
        reasons: list[str],
    ) -> None:
        """Record detailed reasons without changing the stable PR11 error code."""
        if not reasons or self._diagnostics is None:
            return
        try:
            self._diagnostics.store_diagnostic(
                run_id,
                "desktop_research.capture_provenance_validation",
                {
                    "capture_id": capture_id,
                    "error_code": "DR-CAPTURE-PROVENANCE-001",
                    "reasons": list(reasons),
                },
            )
        except Exception:
            # Diagnostic persistence must not mask the validation result itself.
            return

    def validate(
        self,
        handoff,
        extension,
        context_pack,
        context_extension,
        *,
        run_id: str,
    ) -> tuple[str, ...]:
        codes: list[str] = []
        if extension is None:
            return ("DR-RESULT-BINDING-001",)
        if list(_VALIDATOR.iter_errors(extension)):
            return ("DR-RESULT-BINDING-001",)
        if extension["extension_digest"] != canonical_extension_digest(extension):
            _add(codes, "DR-RESULT-DIGEST-001")

        expected = {
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff["handoff_digest"],
            "invocation_id": handoff["invocation_id"],
            "run_id": handoff["run_id"],
            "context_pack_id": context_pack["context_pack_id"],
            "context_pack_digest": context_pack["context_pack_digest"],
            "capability_id": handoff["capability"]["capability_id"],
            "function_id": handoff["capability"]["function_id"],
        }
        capability_binding = (
            handoff["capability"]["capability_id"],
            handoff["capability"]["capability_version"],
            handoff["capability"]["function_id"],
        )
        if (
            extension["handoff_binding"] != expected
            or run_id != handoff["run_id"]
            or capability_binding
            != ("desktop-research", "0.1.0", "investigate")
            or context_extension["context_binding"]["context_pack_digest"]
            != context_pack["context_pack_digest"]
        ):
            _add(codes, "DR-RESULT-BINDING-001")

        captures = {
            str(item["capture_id"]): item
            for item in handoff["outputs"]["source_captures"]
        }
        details = extension["source_capture_details"]
        detail_ids = {str(item["capture_id"]) for item in details}
        if len(detail_ids) != len(details) or detail_ids != set(captures):
            _add(codes, "DR-CAPTURE-PROVENANCE-001")

        detail_index = {
            str(item["capture_id"]): item for item in details
        }
        metadata = {
            item.artifact_id: item
            for item in self._artifacts.artifacts_for(run_id)
        }
        texts: dict[str, str] = {}
        original_bytes = 0
        text_bytes = 0
        refs: set[str] = set()
        allowed = set(context_extension["allowed_source_categories"])

        for detail in details:
            capture_id = str(detail["capture_id"])
            capture = captures.get(capture_id)
            reasons: list[str] = []

            if capture is None:
                reasons.append("capture detail has no matching Handoff source_capture")
            if detail["source_category"] not in allowed:
                reasons.append("source_category is outside the Context allowlist")
            if capture is not None and detail["exact_locator"] != capture["locator"]:
                reasons.append("exact_locator does not match the Handoff locator")
            if not _utc(str(detail["acquired_at"])):
                reasons.append("acquired_at is not an RFC3339 UTC timestamp")
            if not _exact(str(detail["exact_locator"])):
                reasons.append("exact_locator is not sufficiently specific")
            if (
                capture is not None
                and detail["original_capture"]["content_digest"]
                != capture["content_digest"]
            ):
                reasons.append(
                    "original_capture digest does not match Handoff source_capture"
                )

            for key, role in (
                ("original_capture", "desktop_research.original_capture"),
                ("text_rendition", "desktop_research.text_rendition"),
            ):
                declaration = detail[key]
                ref = str(declaration["content_reference"])
                refs.add(ref)
                meta = metadata.get(ref)
                if meta is None:
                    reasons.append(f"{key} artifact metadata is missing")
                    continue
                if meta.run_id != run_id:
                    reasons.append(f"{key} artifact is bound to another Run")
                if meta.role != role:
                    reasons.append(f"{key} artifact role is incorrect")
                if meta.digest != declaration["content_digest"]:
                    reasons.append(f"{key} metadata digest does not match declaration")
                if meta.media_type != declaration["media_type"]:
                    reasons.append(
                        f"{key} metadata media_type does not match declaration"
                    )
                if meta.size != declaration["byte_length"]:
                    reasons.append(f"{key} metadata size does not match declaration")
                if reasons and (
                    meta.run_id != run_id
                    or meta.role != role
                    or meta.digest != declaration["content_digest"]
                    or meta.media_type != declaration["media_type"]
                    or meta.size != declaration["byte_length"]
                ):
                    continue

                try:
                    payload = self._artifacts.load_artifact(ref)
                except Exception as exc:
                    reasons.append(
                        f"{key} artifact loading failed: {type(exc).__name__}"
                    )
                    continue
                if payload.digest != declaration["content_digest"]:
                    reasons.append(f"{key} stored digest does not match declaration")
                if len(payload.content) != declaration["byte_length"]:
                    reasons.append(f"{key} stored byte length does not match declaration")

                if key == "original_capture":
                    original_bytes += len(payload.content)
                    continue

                text_bytes += len(payload.content)
                try:
                    text = payload.content.decode("utf-8")
                except UnicodeDecodeError:
                    text = ""
                    reasons.append("text_rendition is not valid UTF-8")
                if payload.media_type != "text/plain":
                    reasons.append("text_rendition media_type is not text/plain")
                if (
                    declaration.get("inline_text") is not None
                    and declaration["inline_text"] != text
                ):
                    reasons.append(
                        "text_rendition inline_text does not match stored UTF-8 text"
                    )
                texts[capture_id] = text

            if reasons:
                _add(codes, "DR-CAPTURE-PROVENANCE-001")
                self._record_capture_diagnostic(run_id, capture_id, reasons)

        budget = context_extension["budget"]
        max_capture_artifacts = budget.get(
            "max_capture_artifacts",
            2 * budget["max_acquired_source_captures"],
        )
        if (
            len(details) > budget["max_acquired_source_captures"]
            or len(extension["search_trace"]["entries"])
            > budget["max_search_trace_entries"]
            or text_bytes > budget["max_text_rendition_bytes"]
            or len(refs) > max_capture_artifacts
            or (
                budget.get("max_original_capture_bytes") is not None
                and original_bytes > budget["max_original_capture_bytes"]
            )
        ):
            _add(codes, "DR-CAPTURE-BUDGET-001")

        output_index = _outputs(handoff)
        all_ids = {output_id for _, output_id in output_index}
        required_citations: set[tuple[str, str]] = set()
        citation_specs = (
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
        for kind, collection, field in citation_specs:
            for item in collection:
                if item["source_basis"]["basis_type"] == "source_capture":
                    required_citations.add((kind, str(item[field])))

        cited: set[tuple[str, str]] = set()
        citation_ids: set[str] = set()
        for citation in extension["citation_details"]:
            if citation["citation_id"] in citation_ids:
                _add(codes, "DR-CITATION-001")
            citation_ids.add(citation["citation_id"])
            key = (
                str(citation["handoff_output_kind"]),
                str(citation["handoff_output_id"]),
            )
            output = output_index.get(key)
            capture_id = str(citation["capture_id"])
            detail = detail_index.get(capture_id)
            text = texts.get(capture_id)
            expected_basis = {
                "basis_type": "source_capture",
                "capture_id": capture_id,
            }
            if (
                output is None
                or detail is None
                or text is None
                or output["source_basis"] != expected_basis
                or citation["text_rendition_digest"]
                != detail["text_rendition"]["content_digest"]
                or output["locator"] != citation["excerpt_locator"]
                or citation["excerpt"] not in text
            ):
                _add(codes, "DR-CITATION-001")
            cited.add(key)
        if (
            not required_citations.issubset(cited)
            or (
                "DR-CAPTURE-PROVENANCE-001" in codes
                and extension["citation_details"]
            )
        ):
            _add(codes, "DR-CITATION-001")

        entries = extension["search_trace"]["entries"]
        entry_index = {
            str(item["trace_entry_id"]): item for item in entries
        }
        dimensions = {
            str(item["dimension_id"])
            for item in context_extension["coverage_dimensions"]
        }
        if len(entry_index) != len(entries):
            _add(codes, "DR-SEARCH-TRACE-001")
        for entry in entries:
            if (
                not set(entry["coverage_dimension_ids"]).issubset(dimensions)
                or not set(entry["related_handoff_output_ids"]).issubset(all_ids)
                or not set(entry["source_capture_ids"]).issubset(captures)
            ):
                _add(codes, "DR-SEARCH-TRACE-001")

        try:
            attempts = reconstruct_attempts(self._operations, run_id)
        except Exception:
            attempts = {}
            _add(codes, "DR-SEARCH-TRACE-001")
        if set(attempts) != set(entry_index) or any(
            item.get("completed_at") is None for item in attempts.values()
        ):
            _add(codes, "DR-SEARCH-TRACE-001")
        for attempt_id, attempt in attempts.items():
            entry = entry_index.get(attempt_id)
            if entry is None:
                continue
            expected_captures = (
                [attempt["resulting_capture_id"]]
                if attempt["outcome"] == "source_captured"
                else []
            )
            if (
                entry["strategy"] != attempt["strategy"]
                or set(entry["coverage_dimension_ids"])
                != set(attempt["coverage_dimension_ids"])
                or entry["outcome"] != attempt["outcome"]
                or list(entry["source_capture_ids"]) != expected_captures
                or (
                    expected_captures
                    and expected_captures[0] not in captures
                )
            ):
                _add(codes, "DR-SEARCH-TRACE-001")
        unsuccessful = {
            attempt_id
            for attempt_id, attempt in attempts.items()
            if attempt.get("outcome") in UNSUCCESSFUL_OUTCOMES
        }
        if set(extension["search_trace"]["unsuccessful_entry_ids"]) != unsuccessful:
            _add(codes, "DR-SEARCH-TRACE-001")

        question_ids = set(context_pack["question_ids"])
        null_ids: set[str] = set()
        for null_result in extension["null_results"]:
            key = (
                str(null_result["handoff_projection"]["output_kind"]),
                str(null_result["handoff_projection"]["output_id"]),
            )
            if (
                null_result["null_id"] in null_ids
                or not set(null_result["question_ids"]).issubset(question_ids)
                or key not in output_index
            ):
                _add(codes, "DR-NULL-001")
            null_ids.add(null_result["null_id"])
        if extension["null_results"] and not any(
            attempt.get("outcome") == "no_relevant_source"
            for attempt in attempts.values()
        ):
            _add(codes, "DR-NULL-001")

        gaps = {
            str(item["gap_id"])
            for item in handoff["outputs"]["evidence_gaps"]
        }
        gap_assessments = extension["evidence_gap_assessments"]
        assessment_ids = {
            str(item["gap_id"]) for item in gap_assessments
        }
        if (
            len(assessment_ids) != len(gap_assessments)
            or assessment_ids != gaps
            or any(
                not set(item["coverage_dimension_ids"]).issubset(dimensions)
                for item in gap_assessments
            )
        ):
            _add(codes, "DR-EVIDENCE-GAP-001")

        dimension_assessments = extension["coverage_assessment"]["dimensions"]
        dimension_index = {
            str(item["dimension_id"]): item
            for item in dimension_assessments
        }
        if (
            len(dimension_index) != len(dimension_assessments)
            or set(dimension_index) != dimensions
            or any(
                not set(item["trace_entry_ids"]).issubset(entry_index)
                for item in dimension_assessments
            )
        ):
            _add(codes, "DR-COVERAGE-001")
        for dimension_id, assessment in dimension_index.items():
            relevant = [
                attempt
                for attempt in attempts.values()
                if dimension_id in attempt["coverage_dimension_ids"]
            ]
            if assessment["status"] == "covered" and not any(
                attempt.get("outcome") == "source_captured"
                for attempt in relevant
            ):
                _add(codes, "DR-COVERAGE-001")

        for attempt in attempts.values():
            if attempt.get("outcome") in {"blocked", "unavailable", "failed"}:
                related = entry_index.get(
                    attempt["attempt_id"],
                    {},
                ).get("related_handoff_output_ids", [])
                visible = any(
                    ("unknown", str(output_id)) in output_index
                    or ("evidence_gap", str(output_id)) in output_index
                    for output_id in related
                )
                limited = any(
                    dimension_index.get(dimension_id, {}).get("status")
                    in {"partial", "uncovered"}
                    for dimension_id in attempt["coverage_dimension_ids"]
                )
                if not (visible or limited):
                    _add(codes, "DR-COVERAGE-001")

        stop = extension["coverage_assessment"]["stopping_recommendation"]
        remaining_information_value = extension["coverage_assessment"][
            "remaining_information_value"
        ]["level"]
        if set(stop["basis"]) == {"source_count"} or (
            stop["stop_recommended"]
            and operational_terminations(self._operations, run_id)
        ):
            _add(codes, "DR-STOP-BASIS-001")
        if stop["stop_recommended"] and any(
            item["materiality"] in {"material", "unknown"}
            for item in gap_assessments
        ):
            _add(codes, "DR-STOP-GAP-001")
        if stop["stop_recommended"] and remaining_information_value in {
            "high",
            "unknown",
        }:
            _add(codes, "DR-STOP-RIV-001")

        methods = {
            str(item["proposal_id"])
            for item in handoff["outputs"]["candidate_next_methods"]
        }
        if set(extension["candidate_next_method_ids"]) != methods:
            _add(codes, "DR-NEXT-METHOD-001")
        return tuple(codes)
