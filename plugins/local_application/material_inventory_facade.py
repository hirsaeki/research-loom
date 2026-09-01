from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import json
from typing import Any, Mapping

from plugins.local_execution_store import external_capture_artifact_metadata_for_project

from .exhibit_guard_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .facade import LocalApplicationError
from .run_inspection_facade import _public_provenance


_ORIGINAL_ROLE = "desktop_research.original_capture"
_TEXT_ROLE = "desktop_research.text_rendition"
_MATERIAL_LIST_DEFAULT_LIMIT = 100
_MATERIAL_LIST_MAX_LIMIT = 100


def _required_provenance_string(provenance: Mapping[str, Any], field: str) -> str:
    value = provenance.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"external capture provenance is missing {field}")
    return value


def _encode_material_cursor(key: tuple[str, str]) -> str:
    raw = json.dumps(
        {"first_captured_at": key[0], "material_id": key[1]},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_material_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-INPUT-001",
            "external material cursor must be a non-empty string",
        )
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            (cursor + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-INPUT-001",
            "external material cursor is invalid",
        ) from exc
    if not isinstance(value, Mapping) or set(value) != {"first_captured_at", "material_id"}:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-INPUT-001",
            "external material cursor is invalid",
        )
    captured_at = value.get("first_captured_at")
    material_id = value.get("material_id")
    if (
        not isinstance(captured_at, str)
        or not captured_at
        or not isinstance(material_id, str)
        or not material_id
    ):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-INPUT-001",
            "external material cursor is invalid",
        )
    return captured_at, material_id


def _artifact_projection(artifact) -> Mapping[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "digest": artifact.digest,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size,
    }


def _capture_projection(original, rendition) -> Mapping[str, Any]:
    original_provenance = original.provenance
    rendition_provenance = rendition.provenance
    capture_id = _required_provenance_string(original_provenance, "capture_id")
    source_category = _required_provenance_string(original_provenance, "source_category")
    exact_locator = _required_provenance_string(original_provenance, "exact_locator")
    acquired_at = _required_provenance_string(original_provenance, "acquired_at")
    captured_at = _required_provenance_string(original_provenance, "stored_at")

    if _required_provenance_string(original_provenance, "source_run_id") != original.run_id:
        raise ValueError("external original capture Run provenance does not match artifact Run")
    if str(original_provenance.get("rendition_role")) != "original":
        raise ValueError("external original capture rendition role is invalid")

    for field, expected in (
        ("capture_id", capture_id),
        ("source_category", source_category),
        ("exact_locator", exact_locator),
        ("acquired_at", acquired_at),
        ("source_run_id", original.run_id),
    ):
        if _required_provenance_string(rendition_provenance, field) != expected:
            raise ValueError(f"external text rendition {field} does not match original capture")
    if str(rendition_provenance.get("rendition_role")) != "text":
        raise ValueError("external text rendition role is invalid")
    parent_refs = rendition_provenance.get("parent_artifact_refs")
    if parent_refs != [original.artifact_id]:
        raise ValueError("external text rendition does not reference its original capture")

    return {
        "run_id": original.run_id,
        "capture_id": capture_id,
        "source_locator": exact_locator,
        "source_category": source_category,
        "acquired_at": acquired_at,
        "captured_at": captured_at,
        "original": _artifact_projection(original),
        "renditions": [{**_artifact_projection(rendition), "kind": "utf8_text", "encoding": "UTF-8"}],
        "provenance": _public_provenance(deepcopy(dict(original_provenance))),
    }


def _material_projection(captures: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    ordered = sorted(
        captures,
        key=lambda item: (
            str(item["captured_at"]),
            str(item["run_id"]),
            str(item["capture_id"]),
            str(item["original"]["artifact_id"]),
        ),
    )
    canonical = ordered[0]
    material_id = str(canonical["original"]["digest"])
    return {
        "material_id": material_id,
        "original_digest": material_id,
        "original": deepcopy(dict(canonical["original"])),
        "renditions": deepcopy(list(canonical["renditions"])),
        "source_locators": sorted({str(item["source_locator"]) for item in ordered}),
        "run_ids": sorted({str(item["run_id"]) for item in ordered}),
        "first_captured_at": str(canonical["captured_at"]),
        "captures": ordered,
    }


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extended with captured external material inventory."""

    def list_external_materials(
        self,
        *,
        limit: int = _MATERIAL_LIST_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> Mapping[str, Any]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
            or limit > _MATERIAL_LIST_MAX_LIMIT
        ):
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INPUT-001",
                f"external material limit must be between 1 and {_MATERIAL_LIST_MAX_LIMIT}",
            )
        after = _decode_material_cursor(cursor)

        try:
            artifacts, next_after = external_capture_artifact_metadata_for_project(
                self._application.execution_store,
                self._project_id,
                limit=limit,
                after=after,
            )
            by_capture: dict[tuple[str, str], dict[str, Any]] = {}
            for artifact in artifacts:
                provenance = artifact.provenance
                capture_id = _required_provenance_string(provenance, "capture_id")
                key = (artifact.run_id, capture_id)
                slot = by_capture.setdefault(key, {})
                if artifact.role == _ORIGINAL_ROLE:
                    if "original" in slot:
                        raise ValueError("external capture has multiple original artifacts")
                    slot["original"] = artifact
                elif artifact.role == _TEXT_ROLE:
                    if "rendition" in slot:
                        raise ValueError("external capture has multiple UTF-8 renditions")
                    slot["rendition"] = artifact

            grouped: dict[str, list[Mapping[str, Any]]] = {}
            for key in sorted(by_capture):
                slot = by_capture[key]
                original = slot.get("original")
                rendition = slot.get("rendition")
                if original is None or rendition is None:
                    raise ValueError("persisted external capture pair is incomplete")
                capture = _capture_projection(original, rendition)
                grouped.setdefault(str(original.digest), []).append(capture)

            materials = [_material_projection(captures) for captures in grouped.values()]
            materials.sort(key=lambda item: (str(item["first_captured_at"]), str(item["material_id"])))
        except LocalApplicationError:
            raise
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-READ-001",
                "persisted external material inventory could not be read",
            ) from exc

        next_cursor = _encode_material_cursor(next_after) if next_after is not None else None
        return {
            "status": "OK",
            "project_id": self._project_id,
            "materials": materials,
            "limit": limit,
            "truncated": next_cursor is not None,
            "next_cursor": next_cursor,
        }
