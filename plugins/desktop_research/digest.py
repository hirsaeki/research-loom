from __future__ import annotations

import hashlib
from typing import Any, Mapping

import rfc8785


def canonical_extension_digest(document: Mapping[str, Any]) -> str:
    """Return the RFC 8785 SHA-256 digest excluding extension_digest."""
    payload = dict(document)
    payload.pop("extension_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
