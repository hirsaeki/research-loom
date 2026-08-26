from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class OperationalTraceEvent:
    """Append-only non-authoritative operational provenance for one Run."""

    run_id: str
    sequence: int
    event_id: str
    event_type: str
    occurred_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)


class OperationalTraceStore(Protocol):
    """Generic append-only Run-bound operational trace port."""

    def append(
        self,
        run_id: str,
        event_type: str,
        occurred_at: str,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
    ) -> OperationalTraceEvent:
        ...

    def events_for(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> tuple[OperationalTraceEvent, ...]:
        ...
