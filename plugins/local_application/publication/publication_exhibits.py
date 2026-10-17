"""The deliberately small, lossless Exhibit subset understood by Publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any

from plugins.application_errors import LocalApplicationError

from ..research_package.item_listing import require_unlinked
from ..research_package.png_validation import png_size
from ..research_package.research_package_format import MAX_ITEM_BYTES, safe_component

MAX_ROWS = 512
MAX_COLUMNS = 8
MAX_CELL_CHARS = 2048


def table_rows(content: Mapping[str, Any]) -> list[list[str]]:
    """Literal pipe cells or explicit string columns/rows; never infer a matrix."""
    value = content.get("value")
    if content.get("representation") == "markdown" and isinstance(value, str):
        lines = value.strip().splitlines()
        if len(lines) < 2 or any(
            not line.strip().startswith("|") or not line.strip().endswith("|") for line in lines
        ):
            raise ValueError("not a standalone pipe table")
        rows = []
        for line in lines:
            cells = re.split(r"(?<!\\)\|", line.strip()[1:-1])
            # Only escaped pipes are interpreted. Rich Markdown is not silently
            # flattened into a table with different meaning or hidden assets.
            cells = [cell.strip().replace(r"\|", "|") for cell in cells]
            if any(re.search(r"[\\`<>]|!\[", cell) for cell in cells):
                raise ValueError("unsupported cell markup")
            rows.append(cells)
        if any(not re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
            raise ValueError("missing table separator")
        if any(cell.startswith(":") or cell.endswith(":") for cell in rows[1]):
            raise ValueError("explicit column alignment is not supported")
        if len(rows[1]) != len(rows[0]):
            raise ValueError("inconsistent table separator")
        rows.pop(1)
    elif (
        content.get("representation") == "json"
        and isinstance(value, dict)
        and set(value) == {"columns", "rows"}
    ):
        if not isinstance(value["columns"], list) or not isinstance(value["rows"], list):
            raise ValueError("matrix needs columns and rows arrays")
        rows = [value["columns"], *value["rows"]]
    else:
        raise ValueError("unsupported table representation")
    if not 1 <= len(rows) <= MAX_ROWS or not 1 <= len(rows[0]) <= MAX_COLUMNS:
        raise ValueError("table shape exceeds supported bounds")
    if any(not isinstance(row, list) or len(row) != len(rows[0]) for row in rows):
        raise ValueError("table is not rectangular")
    if any(not isinstance(cell, str) or len(cell) > MAX_CELL_CHARS for row in rows for cell in row):
        raise ValueError("cells must be bounded literal strings")
    return deepcopy(rows)


def _asset(
    root: Path, package: Mapping[str, Any], path: str, digest: str, size: int, media: str
) -> bytes:
    rel = Path(path)
    if rel.is_absolute() or PureWindowsPath(path).drive or ".." in rel.parts or "\\" in path:
        raise ValueError("unsafe visual attachment path")
    rows = [row for row in package["attachments"] if row["path"] == path]
    if len(rows) != 1 or (
        rows[0]["content_digest"],
        rows[0]["byte_length"],
        rows[0]["media_type"],
    ) != (digest, size, media):
        raise ValueError("visual attachment pin mismatch")
    target = root / rel
    require_unlinked(target)
    if not 0 <= size <= MAX_ITEM_BYTES:
        raise ValueError("visual attachment size/type mismatch")
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != size:
        raise ValueError("visual attachment size/type mismatch")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size != size
            or not os.path.samestat(before, opened)
        ):
            raise ValueError("visual attachment changed during verification")
        after = target.lstat()
        if not stat.S_ISREG(after.st_mode) or not os.path.samestat(opened, after):
            raise ValueError("visual attachment changed during verification")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_ITEM_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) != size or "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("visual attachment digest mismatch")
    return data


def _visual_sources(exhibit, package, *, strict=False):
    """Follow existing research and Exhibit provenance, including represented Findings."""
    from ..research_package.research_package_builder import required_object_refs

    resolved = package["resolved_content"]
    objects = {o["id"]: o for o in resolved["research_objects"]}
    exhibits = {e["exhibit_id"]: e for e in resolved["working_material"]["research_exhibits"]}
    source_cache = {}
    visiting_exhibits = set()

    def object_sources(oid, seen=None):
        seen = set() if seen is None else seen
        if oid in seen:
            return set()
        seen.add(oid)
        obj = objects.get(oid)
        if obj is None:
            return set()  # legacy working-object labels are not authority
        if obj["kind"] == "source":
            return {oid}
        return set().union(*(object_sources(ref, seen) for _, ref in required_object_refs(obj)))

    def exhibit_sources(row):
        eid = row["exhibit_id"]
        if eid in source_cache:
            return set(source_cache[eid])
        if eid in visiting_exhibits:
            raise ValueError("cyclic visual provenance")
        visiting_exhibits.add(eid)
        ids = set().union(*(object_sources(oid) for oid in row["source_object_ids"]))
        for parent in row["derived_from_exhibit_ids"]:
            if parent in exhibits:
                ids.update(exhibit_sources(exhibits[parent]))
        visual = row.get("visual_target")
        if visual is not None:
            capture = next(
                m["capture"]
                for m in resolved.get("materials", [])
                if m["run_id"] == visual["source_run_id"]
                and m["capture"]["capture_id"] == visual["capture_id"]
            )
            ids.update(
                o["id"]
                for o in objects.values()
                if o["kind"] == "source"
                and o.get("content_digest") == visual["source_digest"]
                and o.get("canonical_locator")
                in {capture.get("source_locator"), *(capture.get("source_locators") or [])}
            )
        if (
            strict
            and (visual is not None or row["source_run_ids"] or row["source_artifact_refs"])
            and not ids
        ):
            raise ValueError("external visual context lacks explicit Source metadata")
        visiting_exhibits.remove(eid)
        source_cache[eid] = set(ids)
        return ids

    return [objects[oid] for oid in sorted(exhibit_sources(exhibit))]


def prepare_exhibits(inspection: Mapping[str, Any], workspace: Path) -> dict[str, dict[str, Any]]:
    package = inspection["source_package_document"]
    root = (
        workspace
        / ".research-loom"
        / "research-packages"
        / safe_component(package["package_id"], "package_id")
    )
    selected = {
        ref for row in inspection["revision"]["sections"] for ref in row.get("exhibit_refs", [])
    }
    use_bindings: dict[str, list[dict[str, str]]] = {}
    for row in inspection.get("composition", {}).get("sections", []):
        for binding in row.get("exhibit_bindings", []):
            if isinstance(binding, Mapping) and binding.get("status") == "selected":
                use_bindings.setdefault(str(binding.get("exhibit_id")), []).append(
                    {
                        "section_id": str(row.get("section_id")),
                        "use_mode": str(binding.get("use_mode")),
                    }
                )
    result = {}
    asset_cache: dict[tuple[str, str, int, str], bytes] = {}

    def asset(path: str, digest: str, size: int, media: str) -> bytes:
        key = (path, digest, size, media)
        if key not in asset_cache:
            asset_cache[key] = _asset(root, package, path, digest, size, media)
        return asset_cache[key]

    objects = {o["id"]: o for o in package["resolved_content"]["research_objects"]}
    misco = inspection.get("publication_profile", {}).get("profile_id") == "misco.publication"
    permissions = inspection.get("publication_policy", {}).get("permissions", [])
    all_exhibits = package["resolved_content"]["working_material"]["research_exhibits"]
    for exhibit in all_exhibits:
        ref = exhibit["exhibit_id"]
        if ref not in selected:
            continue
        provenance = {
            key: deepcopy(exhibit[key])
            for key in (
                "exhibit_id",
                "content_digest",
                "source_run_ids",
                "source_artifact_refs",
                "source_object_ids",
                "derived_from_exhibit_ids",
                "captured_against",
            )
        }
        if ref in use_bindings:
            provenance["source_use_bindings"] = deepcopy(use_bindings[ref])
        visual = exhibit.get("visual_target")
        generated = exhibit.get("generated_visual")
        unavailable_code = (
            "VISUAL_ASSET_UNAVAILABLE"
            if visual is not None or generated is not None
            else "UNSUPPORTED_EXHIBIT"
        )
        semantics = exhibit.get("visual_semantics")
        if semantics is not None:
            provenance["visual_semantics"] = deepcopy(semantics)
        try:
            if not isinstance(exhibit.get("title"), str) or not exhibit["title"].strip():
                unavailable_code = "VISUAL_CAPTION_REQUIRED"
                raise ValueError("visual title is missing")
            if isinstance(semantics, Mapping) and semantics["semantic_changes"]:
                unavailable_code = "VISUAL_RESEARCH_REQUIRED"
                raise ValueError("new meaning requires Research")
            if generated is not None:
                from ..research_package.generated_explanation import (
                    REVIEW_SCHEMA,
                    matching_review,
                    validate_explanation,
                )
                from ..research_package.research_chart import is_host_chart, validate_chart_exhibit
                from ..research_package.visual_origin import verify_visual_origin

                expected = validate_chart_exhibit(
                    exhibit, package["resolved_content"]["research_objects"]
                )
                legend = None
                value = exhibit["content"]["value"]
                if expected is None:
                    expected = validate_explanation(exhibit)
                    if expected is None:
                        raise ValueError("unsupported generated visual")
                else:
                    legend = table_rows({"representation": "json", "value": value["legend"]})
                if value.get("schema") == "research-generated-explanation/v1" or is_host_chart(
                    exhibit
                ):
                    disposition = matching_review(exhibit, all_exhibits)
                    if disposition != "existing_meaning_only":
                        unavailable_code = (
                            "VISUAL_RESEARCH_REQUIRED"
                            if disposition == "research_required"
                            else "VISUAL_CONFORMANCE_FAILED"
                            if disposition == "nonconforming"
                            else "VISUAL_REVIEW_REQUIRED"
                        )
                        raise ValueError("selected generated candidate has no conforming review")
                    provenance["visual_reviews"] = [
                        deepcopy(e)
                        for e in all_exhibits
                        if isinstance(e.get("content", {}).get("value"), Mapping)
                        and e["content"]["value"].get("schema") == REVIEW_SCHEMA
                        and e["content"]["value"].get("candidate_id") == ref
                    ]
                context = generated["generation_context"]
                origin = json.loads(
                    asset(
                        context["attachment_path"],
                        context["content_digest"],
                        context["byte_length"],
                        "application/json",
                    ).decode("utf-8")
                )
                verify_visual_origin(exhibit, origin)
                data = asset(
                    generated["attachment_path"],
                    generated["digest"],
                    generated["byte_length"],
                    generated["media_type"],
                )
                if data != expected:
                    raise ValueError("selected PNG differs from generated Exhibit")
                width, height = png_size(data)
                unavailable_code = "VISUAL_SOURCE_METADATA_REQUIRED"
                citation_sources = _visual_sources(exhibit, package, strict=misco)
                source_ids = {o["id"] for o in citation_sources}
                from ..research_package.research_package_builder import bibliography_readiness

                if misco and any(
                    not bibliography_readiness(o)[0]
                    or not str(o.get("canonical_locator", "")).strip()
                    for o in citation_sources
                ):
                    unavailable_code = "VISUAL_SOURCE_METADATA_REQUIRED"
                    raise ValueError("external data source needs explicit bibliographic metadata")
                provenance["citation_sources"] = deepcopy(citation_sources)
                provenance["publication_permissions"] = deepcopy(
                    [p for p in permissions if p.get("source_ref") in source_ids]
                )
                provenance["generated_visual"] = deepcopy(generated)
                provenance["generation_input"] = {
                    k: deepcopy(v) for k, v in value.items() if k != "output"
                }
                provenance["selected_output"] = {
                    k: v for k, v in value["output"].items() if k != "bytes_base64"
                }
                result[ref] = {
                    "kind": "image",
                    "data": data,
                    "width": width,
                    "height": height,
                    "provenance": provenance,
                    "asset_digest": generated["digest"],
                    **({"legend_rows": legend} if legend is not None else {}),
                }
            elif visual is not None:
                provenance["visual_target"] = deepcopy(visual)
                capture = next(
                    item["capture"]
                    for item in package["resolved_content"]["materials"]
                    if item["run_id"] == visual["source_run_id"]
                    and item["capture"]["capture_id"] == visual["capture_id"]
                )
                provenance["source_capture"] = deepcopy(capture)
                citation_sources = [
                    o
                    for o in objects.values()
                    if o.get("kind") == "source"
                    and o.get("content_digest") == visual["source_digest"]
                    and o.get("canonical_locator")
                    in {capture.get("source_locator"), *(capture.get("source_locators") or [])}
                ]
                from ..research_package.research_package_builder import bibliography_readiness

                if misco and (
                    len(citation_sources) != 1 or not bibliography_readiness(citation_sources[0])[0]
                ):
                    unavailable_code = "VISUAL_SOURCE_METADATA_REQUIRED"
                    raise ValueError("external visual needs exact Source bibliographic metadata")
                provenance["citation_sources"] = deepcopy(citation_sources)
                provenance["publication_permissions"] = deepcopy(
                    [
                        p
                        for p in permissions
                        if p.get("source_ref") in {o["id"] for o in citation_sources}
                    ]
                )
                # The original must still verify even when a retained crop is used.
                original = asset(
                    visual["source_attachment_path"],
                    visual["source_digest"],
                    visual["source_byte_length"],
                    visual["source_media_type"],
                )
                derived = visual.get("derived_artifact")
                if derived:
                    if derived["derived_from_artifact_ref"] != visual["source_artifact_ref"]:
                        raise ValueError("derived image does not belong to this original")
                    data = asset(
                        derived["attachment_path"],
                        derived["digest"],
                        derived["byte_length"],
                        derived["media_type"],
                    )
                    media = derived["media_type"]
                else:
                    if visual["locator"].get("region") or visual["locator"].get("page", 1) != 1:
                        raise ValueError("selected page/region needs a retained derived image")
                    data, media = original, visual["source_media_type"]
                if media != "image/png":
                    raise ValueError("only retained PNG images are supported")
                width, height = png_size(data)
                result[ref] = {
                    "kind": "image",
                    "data": data,
                    "width": width,
                    "height": height,
                    "provenance": provenance,
                    "asset_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                }
            elif exhibit["kind"] in {"table", "matrix"}:
                if inspection.get("publication_policy", {}).get("document_mode") == "formal_report":
                    provenance["citation_sources"] = deepcopy(
                        _visual_sources(exhibit, package, strict=True)
                    )
                result[ref] = {
                    "kind": "table",
                    "rows": table_rows(exhibit["content"]),
                    "provenance": provenance,
                }
            else:
                raise ValueError("unsupported Exhibit representation; no implicit text fallback")
        except (LocalApplicationError, OSError, ValueError, KeyError, TypeError, StopIteration):
            result[ref] = {
                "kind": "unavailable",
                "code": unavailable_code,
                "provenance": provenance,
            }
    return result


def render_input_digest(blocks: Mapping[str, Any], diagnostics: list) -> str:
    # Bytes are already verified once and retained for this invocation. A repaired
    # asset gets a different build from its diagnostic preview, without overwriting it.
    basis = {
        "exhibits": {
            ref: {k: v for k, v in block.items() if k != "data"} for ref, block in blocks.items()
        },
        "visual_diagnostics": diagnostics,
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(basis, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
