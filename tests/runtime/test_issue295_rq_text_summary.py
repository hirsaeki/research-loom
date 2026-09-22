from __future__ import annotations

import tempfile

from core.conversation import ActionDraft
from core.conversation.testing import SequenceIdProvider
from core.execution.testing import StaticClock
from plugins.local_application import LocalResearchApplication
from test_work_conversation_runtime import input_document, profile_provider, state


class QuestionTextResolver:
    def __init__(self, expected_text: str) -> None:
        self.expected_text = expected_text
        self.seen_summary = None

    def resolve(self, conversation_input, bounded_state_summary, registered_actions):
        self.seen_summary = bounded_state_summary
        if any(
            item.get("kind") == "research_question"
            and item.get("text") == self.expected_text
            for item in bounded_state_summary["objects"]
        ):
            return ActionDraft("research.status", {"kinds": ["research_question"]})
        return None


def test_rq_text_is_available_to_resolver_without_changing_authority_path():
    resolver = QuestionTextResolver("What is supported?")
    with tempfile.TemporaryDirectory() as temp:
        app = LocalResearchApplication(
            temp,
            resolver=resolver,
            effective_profile_set_provider=profile_provider,
            seed_state=state(),
            clock=StaticClock("2026-08-27T00:00:00Z"),
            id_provider=SequenceIdProvider(["PROP-295", "ACTREC-295", "CONVTRACE-295"]),
        )
        try:
            result = app.coordinator.process_input(
                input_document("IN-295", "QUERY", "the question about what is supported")
            )
            assert result.status == "SUCCEEDED"
            rq_summary = next(
                item
                for item in resolver.seen_summary["objects"]
                if item.get("kind") == "research_question"
            )
            assert rq_summary["id"] == "RQ-1"
            assert rq_summary["text"] == "What is supported?"
            assert result.action_receipt["research_state_mutation_performed"] is False
        finally:
            app.close()


def test_ablation_resolver_cannot_match_without_rq_text():
    resolver = QuestionTextResolver("What is supported?")
    actions = ()
    without_text = {"objects": [{"kind": "research_question", "id": "RQ-1"}]}
    with_text = {
        "objects": [
            {
                "kind": "research_question",
                "id": "RQ-1",
                "text": "What is supported?",
            }
        ]
    }

    assert resolver.resolve({}, without_text, actions) is None
    resolved = resolver.resolve({}, with_text, actions)
    assert resolved is not None
    assert resolved.action_type == "research.status"
