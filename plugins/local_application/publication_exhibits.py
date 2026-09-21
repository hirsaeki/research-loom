"""The deliberately small, lossless Exhibit subset understood by Publication."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import struct
from typing import Any, Mapping
import zlib

from .facade import LocalApplicationError
from .item_listing import _require_unlinked
from .research_package_format import MAX_ITEM_BYTES, safe_component

MAX_ROWS = 512
MAX_COLUMNS = 8
MAX_CELL_CHARS = 2048
MAX_PIXELS = 4 * 1024 * 1024


def table_rows(content: Mapping[str, Any]) -> list[list[str]]:
    """Literal pipe cells or explicit string columns/rows; never infer a matrix."""
    value = content.get("value")
    if content.get("representation") == "markdown" and isinstance(value, str):
        lines = value.strip().splitlines()
        if len(lines) < 2 or any(not line.strip().startswith("|") or not line.strip().endswith("|") for line in lines):
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
    elif content.get("representation") == "json" and isinstance(value, dict) and set(value) == {"columns", "rows"}:
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


def png_size(data: bytes) -> tuple[int, int]:
    """Validate bounded, non-interlaced 8-bit RGB/RGBA PNG without re-encoding.

    PNG signature, CRC, chunk ordering, IHDR and filtered scanlines follow
    https://www.w3.org/TR/png-3/. Other image encodings require an explicit
    retained conversion; Publication does not invent an image from a label.
    """
    if len(data) > MAX_ITEM_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a bounded PNG")
    pos = 8
    width = height = channels = 0
    chunks = []
    compressed = bytearray()
    ended = False
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + size
        if end > len(data) or zlib.crc32(data[pos + 4:end - 4]) != int.from_bytes(data[end - 4:end], "big"):
            raise ValueError("PNG chunk/CRC mismatch")
        payload = data[pos + 8:end - 4]
        if not chunks and kind != b"IHDR":
            raise ValueError("PNG header is missing")
        if kind == b"IHDR":
            if chunks or size != 13:
                raise ValueError("invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not width or not height or width * height > MAX_PIXELS or depth != 8 or color not in {2, 6} or compression or filtering or interlace:
                raise ValueError("unsupported PNG dimensions/encoding")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            if b"IDAT" in chunks and chunks[-1] != b"IDAT":
                raise ValueError("noncontiguous PNG image data")
            compressed.extend(payload)
        elif kind == b"IEND":
            if size or not compressed or end != len(data):
                raise ValueError("invalid PNG end")
            ended = True
        elif kind == b"PLTE":
            if b"PLTE" in chunks or compressed or not 3 <= size <= 768 or size % 3:
                raise ValueError("invalid PNG palette")
        elif kind in {b"acTL", b"fcTL", b"fdAT"} or not (kind[0] & 32):
            raise ValueError("unsupported PNG chunk")
        chunks.append(kind)
        pos = end
        if ended:
            break
    if not ended:
        raise ValueError("incomplete PNG")
    stride = width * channels + 1
    expected = stride * height
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as exc:
        raise ValueError("invalid PNG compression") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG scanline size mismatch")
    if any(raw[offset] > 4 for offset in range(0, expected, stride)):
        raise ValueError("invalid PNG scanline filter")
    return width, height


def _asset(root: Path, package: Mapping[str, Any], path: str, digest: str, size: int, media: str) -> bytes:
    rel = Path(path)
    if rel.is_absolute() or PureWindowsPath(path).drive or ".." in rel.parts or "\\" in path:
        raise ValueError("unsafe visual attachment path")
    rows = [row for row in package["attachments"] if row["path"] == path]
    if len(rows) != 1 or (rows[0]["content_digest"], rows[0]["byte_length"], rows[0]["media_type"]) != (digest, size, media):
        raise ValueError("visual attachment pin mismatch")
    target = root / rel
    _require_unlinked(target)
    if not 0 <= size <= MAX_ITEM_BYTES:
        raise ValueError("visual attachment size/type mismatch")
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != size:
        raise ValueError("visual attachment size/type mismatch")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != size or not os.path.samestat(before, opened):
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


def prepare_exhibits(inspection: Mapping[str, Any], workspace: Path) -> dict[str, dict[str, Any]]:
    package = inspection["source_package_document"]
    root = workspace / ".research-loom" / "research-packages" / safe_component(package["package_id"], "package_id")
    selected = {ref for row in inspection["revision"]["sections"] for ref in row.get("exhibit_refs", [])}
    result = {}
    asset_cache: dict[tuple[str, str, int, str], bytes] = {}

    def asset(path: str, digest: str, size: int, media: str) -> bytes:
        key = (path, digest, size, media)
        if key not in asset_cache:
            asset_cache[key] = _asset(root, package, path, digest, size, media)
        return asset_cache[key]

    for exhibit in package["resolved_content"]["working_material"]["research_exhibits"]:
        ref = exhibit["exhibit_id"]
        if ref not in selected:
            continue
        provenance = {key: deepcopy(exhibit[key]) for key in (
            "exhibit_id", "content_digest", "source_run_ids", "source_artifact_refs", "source_object_ids",
            "derived_from_exhibit_ids", "captured_against",
        )}
        visual = exhibit.get("visual_target")
        try:
            if visual is not None:
                provenance["visual_target"] = deepcopy(visual)
                capture = next(item["capture"] for item in package["resolved_content"]["materials"]
                               if item["run_id"] == visual["source_run_id"] and item["capture"]["capture_id"] == visual["capture_id"])
                provenance["source_capture"] = deepcopy(capture)
                # The original must still verify even when a retained crop is used.
                original = asset(visual["source_attachment_path"], visual["source_digest"],
                                 visual["source_byte_length"], visual["source_media_type"])
                derived = visual.get("derived_artifact")
                if derived:
                    if derived["derived_from_artifact_ref"] != visual["source_artifact_ref"]:
                        raise ValueError("derived image does not belong to this original")
                    data = asset(derived["attachment_path"], derived["digest"], derived["byte_length"], derived["media_type"])
                    media = derived["media_type"]
                else:
                    if visual["locator"].get("region") or visual["locator"].get("page", 1) != 1:
                        raise ValueError("selected page/region needs a retained derived image")
                    data, media = original, visual["source_media_type"]
                if media != "image/png":
                    raise ValueError("only retained PNG images are supported")
                width, height = png_size(data)
                result[ref] = {"kind": "image", "data": data, "width": width, "height": height,
                               "provenance": provenance, "asset_digest": "sha256:" + hashlib.sha256(data).hexdigest()}
            elif exhibit["kind"] in {"table", "matrix"}:
                result[ref] = {"kind": "table", "rows": table_rows(exhibit["content"]), "provenance": provenance}
            else:
                raise ValueError("unsupported Exhibit representation; no implicit text fallback")
        except (LocalApplicationError, OSError, ValueError, KeyError, TypeError, StopIteration):
            result[ref] = {"kind": "unavailable", "code": "VISUAL_ASSET_UNAVAILABLE" if visual is not None else "UNSUPPORTED_EXHIBIT",
                           "provenance": provenance}
    return result


def render_input_digest(blocks: Mapping[str, Any], diagnostics: list) -> str:
    # Bytes are already verified once and retained for this invocation. A repaired
    # asset gets a different build from its diagnostic preview, without overwriting it.
    basis = {"exhibits": {ref: {k: v for k, v in block.items() if k != "data"} for ref, block in blocks.items()},
             "visual_diagnostics": diagnostics}
    return "sha256:" + hashlib.sha256(json.dumps(basis, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
