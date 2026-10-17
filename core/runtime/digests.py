"""RFC 8785 (JCS) SHA-256 digests shared by core and plugins.

These are distinct from ``core.runtime.transition_models.canonical_digest``,
which hashes sorted-key ``json.dumps`` output. The two encodings differ for
some values (for example floats), so a pinned digest must keep using the
encoding it was created with.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785


def jcs_digest(value: Any) -> str:
    """Return ``sha256:<hex>`` over the RFC 8785 encoding of ``value``.

    ``rfc8785`` raises ``TypeError`` / ``ValueError`` for values it cannot
    canonicalize; callers map those to their own errors.
    """
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def jcs_digest_without(document: Mapping[str, Any], *fields: str) -> str:
    """Digest ``document`` with the given top-level fields (typically its own digest) removed."""
    payload = {key: value for key, value in document.items() if key not in fields}
    return jcs_digest(payload)
