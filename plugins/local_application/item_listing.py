"""Read-only keyset paging and bounded diagnostics for saved-item inventories."""
from __future__ import annotations

import base64
import binascii
import hashlib
import heapq
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from .facade import LocalApplicationError
from .research_package_format import safe_component


ITEM_ERRORS = (LocalApplicationError, OSError, UnicodeError, ValueError,
               KeyError, TypeError, OverflowError, RecursionError)


def directory_page(root: Path, *, project_id: str, kind: str, limit: int,
                   maximum: int, cursor: str | None,
                   skip_prefix: str | None = None) -> tuple[list[Path], str | None]:
    """Scan names in O(n) time, retaining O(limit) names and no off-page content.

    Live keyset order is not a snapshot: insertions before the cursor require a
    fresh traversal. The cursor is a navigation token, not an authorization.
    """
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise LocalApplicationError("APPLICATION-LIST-INPUT-001", f"limit must be between 1 and {maximum}")
    binding = {"v": 1, "kind": kind, "project_id": project_id,
               "root": hashlib.sha256(os.fsencode(root.absolute())).hexdigest()}
    after = ""
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or not cursor or len(cursor) > 2048:
                raise ValueError("invalid cursor")
            value = json.loads(base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True))
            if not isinstance(value, dict) or set(value) != {*binding, "after"}:
                raise ValueError("invalid cursor shape")
            if any(value[key] != expected for key, expected in binding.items()):
                raise ValueError("cursor belongs to another inventory")
            after = value["after"]
            if not isinstance(after, str) or not after or len(after) > 255 or "/" in after or "\x00" in after:
                raise ValueError("invalid cursor identity")
        except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError) as exc:
            raise LocalApplicationError("APPLICATION-LIST-CURSOR-001", "invalid cursor or different project/inventory; restart without a cursor") from exc

    def names(entries):
        for entry in entries:
            if entry.name <= after or (skip_prefix and entry.name.startswith(skip_prefix)):
                continue
            try:
                candidate = entry.is_dir(follow_symlinks=False) or entry.is_symlink()
            except OSError:
                candidate = True
            if candidate:
                yield entry.name

    try:
        with os.scandir(root) as entries:
            selected = heapq.nsmallest(limit + 1, names(entries))
    except FileNotFoundError:
        selected = []
    except OSError as exc:
        raise LocalApplicationError("APPLICATION-LIST-READ-001", "inventory directory is inaccessible; resolve permissions/I/O or restore the exact store") from exc
    has_more = len(selected) > limit
    selected = selected[:limit]
    next_cursor = None
    if has_more:
        next_cursor = base64.urlsafe_b64encode(json.dumps(
            {**binding, "after": selected[-1]}, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")).decode("ascii")
    return [root / name for name in selected], next_cursor


def read_mapping(path: Path, maximum: int) -> Mapping[str, Any]:
    """Bound before allocation. Never follow static linked metadata paths."""
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise LocalApplicationError("APPLICATION-LIST-UNSAFE-PATH-001", "linked inventory paths are not read")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise LocalApplicationError("APPLICATION-LIST-METADATA-001", "item metadata is not a regular file")
    if info.st_size > maximum:
        raise LocalApplicationError("APPLICATION-LIST-BOUND-001", "item metadata exceeds the read bound")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise LocalApplicationError("APPLICATION-LIST-BOUND-001", "item metadata exceeds the read bound")
    if len(raw) != info.st_size:
        raise LocalApplicationError("APPLICATION-LIST-CHANGED-001", "item metadata changed during the read; retry")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise LocalApplicationError("APPLICATION-LIST-METADATA-001", "item metadata must be an object")
    return value


def unavailable(identity_field: str, identity: str, exc: Exception) -> dict[str, Any]:
    """No untrusted document content or exception text in the diagnostic."""
    chain = []
    cause: BaseException | None = exc
    while cause is not None and len(chain) < 8:
        chain.append(cause)
        cause = cause.__cause__
    code = getattr(exc, "code", "APPLICATION-LIST-METADATA-001")
    if any(isinstance(e, PermissionError) for e in chain):
        reason = "INACCESSIBLE"
    elif any(isinstance(e, FileNotFoundError) for e in chain) or code.endswith("-404"):
        reason = "MISSING"
    elif any(isinstance(e, OSError) for e in chain):
        reason = "IO_ERROR"
    elif any(isinstance(e, (json.JSONDecodeError, UnicodeError)) for e in chain):
        reason = "MALFORMED_JSON"
    elif "BOUND" in code:
        reason = "READ_BOUND_EXCEEDED"
    elif "UNSAFE-PATH" in code:
        reason = "UNSAFE_PATH"
    elif "digest" in str(exc).lower():
        reason = "DIGEST_MISMATCH"
    else:
        reason = "INVALID_METADATA_OR_BINDING"
    action = "Preserve this item. Resolve access/I/O or restore exact retained bytes, then retry. Use a new identity for rebuilt material."
    if reason == "READ_BOUND_EXCEEDED":
        action = "The inventory read bound was exceeded, not proof of corruption. Preserve the bytes; use explicit known-ID inspection with appropriate resources."
    row: dict[str, Any] = {"availability": "UNAVAILABLE", "identity_source": "directory_name",
        "project_scope": "UNVERIFIED", "diagnostic": {"code": code, "reason": reason, "next_action": action}}
    try:
        safe_component(identity, identity_field)
        if len(identity) > 255 or not identity.isprintable():
            raise ValueError("unsafe display identity")
        row[identity_field] = identity
    except (LocalApplicationError, ValueError):
        row["entry_fingerprint"] = hashlib.sha256(os.fsencode(identity)).hexdigest()
    return row
