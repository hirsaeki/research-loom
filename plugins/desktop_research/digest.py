from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.runtime.digests import jcs_digest_without


def canonical_extension_digest(document: Mapping[str, Any]) -> str:
    """Return the RFC 8785 SHA-256 digest excluding extension_digest."""
    return jcs_digest_without(document, "extension_digest")
