from __future__ import annotations

from collections import deque
from typing import Mapping, Sequence

from .models import ActionDraft


class MappingResolver:
    """Test/local deterministic resolver. It is deliberately not an NLP planner."""

    def __init__(self, by_text: Mapping[str, ActionDraft]) -> None:
        self._by_text = dict(by_text)

    def resolve(self, conversation_input, bounded_state_summary, registered_actions):
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
