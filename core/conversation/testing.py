"""Deterministic in-memory doubles for tests. Production code must not import this module."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

from .models import ActionDraft


class MappingResolver:
    """Test/local deterministic resolver. It is deliberately not an NLP planner."""

    def __init__(self, by_text: Mapping[str, ActionDraft]) -> None:
        self._by_text = dict(by_text)

    def resolve(
        self,
        conversation_input: Mapping[str, Any],
        bounded_state_summary: Any,
        registered_actions: Any,
    ) -> ActionDraft | None:
        return self._by_text.get(str(conversation_input["text"]))


class SequenceIdProvider:
    def __init__(self, values: Sequence[str]) -> None:
        self._values = deque(values)

    def new(self, prefix: str) -> str:
        if not self._values:
            raise RuntimeError("SequenceIdProvider exhausted")
        value = self._values.popleft()
        if not value.startswith(prefix):
            raise RuntimeError(f"expected {prefix} id, got {value}")
        return value
