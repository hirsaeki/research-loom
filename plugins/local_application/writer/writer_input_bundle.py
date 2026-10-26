"""Compact, content-addressed material bodies for Writer input receipts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.runtime import canonical_digest
from plugins.application_errors import LocalApplicationError

from .writer_composition_support import _digest_document
from .writer_round_trip_support import SCHEMA_VERSION, _sha256_text


def _fingerprint(value: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "source": value["source"],
            "sections": value["sections"],
            "shared_material_texts": value["shared_material_texts"],
        }
    )


def compact_input(source: Mapping[str, Any], sections: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a self-contained receipt with each distinct material body stored once."""
    rows = deepcopy(sections)
    texts: dict[str, str] = {}
    for row in rows:
        for material in row["section_input"]["resolved_materials"]:
            rendition = material["text_rendition"]
            content = rendition.pop("content")
            if not isinstance(content, str):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "canonical material body is not text",
                )
            digest = _sha256_text(content)
            if digest in texts and texts[digest] != content:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "material content digest collision",
                )
            texts[digest] = content
            rendition["content_ref"] = digest
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "object_type": "writer_round_trip_input",
        "input_id": "",
        "source": deepcopy(dict(source)),
        "sections": rows,
        "shared_material_texts": texts,
        "authority_boundary": {
            "research_state_mutation_performed": False,
            "evidence_verification_performed": False,
            "finding_adoption_performed": False,
            "recommendation_adoption_performed": False,
        },
        "input_digest": "",
    }
    document["input_id"] = "WRI-" + _fingerprint(document).split(":", 1)[1][:24]
    document["input_digest"] = _digest_document(document, "input_digest")
    return document


def expand_input(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate shared bodies and rehydrate canonical standalone section inputs."""
    if value.get("schema_version") != SCHEMA_VERSION:
        return deepcopy(dict(value))
    if value.get("input_id") != "WRI-" + _fingerprint(value).split(":", 1)[1][:24]:
        raise LocalApplicationError(
            "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
            "Writer input identity does not match its compact content",
        )
    result = deepcopy(dict(value))
    texts = result["shared_material_texts"]
    used: set[str] = set()
    for row in result["sections"]:
        for material in row["section_input"]["resolved_materials"]:
            rendition = material["text_rendition"]
            ref = rendition.pop("content_ref", None)
            if (
                not isinstance(ref, str)
                or "content" in rendition
                or ref not in texts
                or _sha256_text(texts[ref]) != ref
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "Writer input has a missing or altered shared material body",
                )
            used.add(ref)
            rendition["content"] = texts[ref]
    if used != set(texts):
        raise LocalApplicationError(
            "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
            "Writer input contains an unreferenced shared material body",
        )
    return result
