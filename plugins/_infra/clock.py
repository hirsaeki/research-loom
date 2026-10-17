"""Wall-clock timestamps in the persisted ``...Z`` form."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    """Return the current UTC time as ISO 8601 with a ``Z`` suffix."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
