from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .digest import canonical_extension_digest
from .normalization import DesktopResearchNormalizer as _BaseNormalizer
from .result_validation import DesktopResearchResultValidator as _BaseValidator


_VALIDATION_WHITESPACE = re.compile(r"[ \t\r\n]+")


def _normalized_whitespace(value: str) -> str:
    return _VALIDATION_WHITESPACE.sub(" ", value)


def _matching_whitespace_slice(text: str, excerpt: str) -> str | None:
    """Return the exact text slice when only allowed whitespace differs."""
    normalized_excerpt = _normalized_whitespace(excerpt)
    if not normalized_excerpt:
        return None
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character in " \t\r\n":
            end = index + 1
            while end < len(text) and text[end] in " \t\r\n":
                end += 1
            normalized.append(" ")
            spans.append((index, end))
            index = end
            continue
        normalized.append(character)
        spans.append((index, index + 1))
        index += 1
    normalized_text = "".join(normalized)
    start = normalized_text.find(normalized_excerpt)
    if start < 0:
        return None
    end = start + len(normalized_excerpt) - 1
    return text[spans[start][0] : spans[end][1]]


def _coverage_projection(
    extension: Mapping[str, Any],
    context_extension: Mapping[str, Any],
) -> dict[str, Any]:
    projected = deepcopy(dict(extension))
    dimensions = projected["coverage_assessment"]["dimensions"]
    declared = {
        str(item.get("dimension_id"))
        for item in dimensions
        if isinstance(item, Mapping) and item.get("dimension_id")
    }
    for configured in context_extension.get("coverage_dimensions", ()):
        dimension_id = str(configured.get("dimension_id") or "")
        if not dimension_id or dimension_id in declared:
            continue
        dimensions.append(
            {
                "dimension_id": dimension_id,
                "status": "unknown",
                "trace_entry_ids": [],
                "rationale": "Coverage was not declared by the submitted result; retained as unassessed.",
            }
        )
    projected["extension_digest"] = canonical_extension_digest(projected)
    return projected


class DesktopResearchResultValidator(_BaseValidator):
    """PR39 validation projection for omitted coverage and PDF whitespace."""

    def _citation_projection(
        self,
        extension: Mapping[str, Any],
        *,
        run_id: str,
    ) -> dict[str, Any]:
        projected = deepcopy(dict(extension))
        details = {
            str(item["capture_id"]): item
            for item in projected.get("source_capture_details", ())
            if isinstance(item, Mapping) and item.get("capture_id")
        }
        metadata = {
            item.artifact_id: item
            for item in self._artifacts.artifacts_for(run_id)
        }
        for citation in projected.get("citation_details", ()):
            capture_id = str(citation.get("capture_id") or "")
            detail = details.get(capture_id)
            if detail is None:
                continue
            rendition = detail.get("text_rendition")
            if not isinstance(rendition, Mapping):
                continue
            trusted_digest = str(rendition.get("content_digest") or "")
            if str(citation.get("text_rendition_digest") or "") != trusted_digest:
                continue
            ref = str(rendition.get("content_reference") or "")
            meta = metadata.get(ref)
            if (
                meta is None
                or meta.run_id != run_id
                or meta.role != "desktop_research.text_rendition"
                or meta.digest != trusted_digest
                or meta.media_type != "text/plain"
                or meta.size != rendition.get("byte_length")
            ):
                continue
            try:
                payload = self._artifacts.load_artifact(ref)
                if payload.digest != trusted_digest or len(payload.content) != meta.size:
                    continue
                text = payload.content.decode("utf-8")
            except Exception:
                continue
            excerpt = str(citation.get("excerpt") or "")
            if excerpt in text:
                continue
            matched = _matching_whitespace_slice(text, excerpt)
            if matched is not None:
                # Validation copy only; persisted/canonical citation text stays exact.
                citation["excerpt"] = matched
        projected["extension_digest"] = canonical_extension_digest(projected)
        return projected

    def validate(
        self,
        handoff,
        extension,
        context_pack,
        context_extension,
        *,
        run_id: str,
    ) -> tuple[str, ...]:
        if extension is None:
            return super().validate(
                handoff,
                extension,
                context_pack,
                context_extension,
                run_id=run_id,
            )
        # Do not repair a submission whose own declared digest is already invalid.
        if extension.get("extension_digest") != canonical_extension_digest(extension):
            return super().validate(
                handoff,
                extension,
                context_pack,
                context_extension,
                run_id=run_id,
            )
        projected = _coverage_projection(extension, context_extension)
        projected = self._citation_projection(projected, run_id=run_id)
        return super().validate(
            handoff,
            projected,
            context_pack,
            context_extension,
            run_id=run_id,
        )


class DesktopResearchNormalizer(_BaseNormalizer):
    """Base normalizer with explicit canonical unknown coverage completion."""

    def __init__(
        self,
        trace_store,
        context_extension_store,
        artifact_store,
        operational_store,
    ) -> None:
        super().__init__(
            trace_store,
            context_extension_store,
            artifact_store,
            operational_store,
        )
        self._validator = DesktopResearchResultValidator(
            artifact_store,
            operational_store,
            diagnostic_store=trace_store,
        )

    def normalize(
        self,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ):
        if extension is None:
            return super().normalize(handoff, extension, context)
        _run, _context_pack, context_extension = self._load_inputs(handoff)
        canonical = _coverage_projection(extension, context_extension)
        return super().normalize(handoff, canonical, context)
