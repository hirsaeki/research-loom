from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest

from core.conversation import ActionDraft, with_document_digest
from core.conversation.testing import MappingResolver, SequenceIdProvider
from core.execution.testing import StaticClock
from core.runtime import TransitionAction, TransitionKind, canonical_digest
from plugins.local_application import LocalResearchApplication
from runtime_fixtures import project, rq, seed_state


CLOCK = StaticClock("2026-08-27T06:30:00Z")
ACTOR = {"actor_id": "HUMAN-1", "actor_type": "human"}


def _input(input_id, classification, text, *, target=None):
    value = {
        "schema_version": "0.1.0",
        "message_type": "conversation_input",
        "input_id": input_id,
        "conversation_id": "CONV-26-STATE-GUARD",
        "project_id": "PRJ-1",
        "actor": deepcopy(ACTOR),
        "classification": classification,
        "text": text,
        "received_at": CLOCK.now(),
    }
    if target is not None:
        value["target"] = target
    return with_document_digest(value)


def _profile_provider(project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
        "profile_pins": [{
            "profile_id": "fixture.research",
            "profile_type": "research",
            "profile_version": "1.0.0",
            "manifest_sha256": "1" * 64,
        }],
        "content_digest": expected_digest,
    }


def _wire(action):
    return {
        "kind": action.kind.value,
        "payload": deepcopy(dict(action.payload)),
        "decision_refs": list(action.decision_refs),
        "source_refs": list(action.source_refs),
    }


def _candidate(state, actions, proposal_id):
    value = {
        "proposal_id": proposal_id,
        "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref,
        "source_refs": [],
        "proposed_actions": [_wire(action) for action in actions],
        "affected_refs": [],
        "rationale": "pending state-changing guard fixture",
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {},
        "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


class PendingStateChangingGuardTests(unittest.TestCase):
    def test_pending_decision_blocks_confirmed_decision_free_state_apply(self):
        seed = seed_state(
            objects=[project(), rq(state="approved")],
            mode="real",
            snapshot_id="SNP-PENDING-STATE-0",
        )
        mapping = {
            "apply guarded": ActionDraft(
                "state.apply_candidate",
                {"state_delta_proposal_id": "SDP-GUARDED"},
            ),
            "apply second": ActionDraft(
                "state.apply_candidate",
                {"state_delta_proposal_id": "SDP-SECOND"},
            ),
        }
        ids = [
            "PROP-A", "CONFREQ-A", "CONFREC-A", "ACTREC-A", "CONVTRACE-A",
            "PROP-B", "CONFREQ-B", "CONFREC-B", "ACTREC-B", "CONVTRACE-B",
        ]
        with tempfile.TemporaryDirectory() as temp:
            app = LocalResearchApplication(
                temp,
                resolver=MappingResolver(mapping),
                effective_profile_set_provider=_profile_provider,
                seed_state=seed,
                clock=CLOCK,
                id_provider=SequenceIdProvider(ids),
            )
            try:
                current = app.state_repository.load_state_view("PRJ-1", "LIN-1")
                revised = deepcopy(dict(current.latest_object("research_question", "RQ-1")))
                revised["revision"] += 1
                revised["text"] = "Material revision requiring Human Decision"
                guarded = _candidate(
                    current,
                    [TransitionAction(TransitionKind.REVISE_OBJECT, {"object": revised})],
                    "SDP-GUARDED",
                )
                app.conversation_store.store_state_delta_proposal("SDP-GUARDED", guarded)

                claim = {
                    "schema_version": "0.1.0",
                    "id": "CLM-SECOND",
                    "kind": "claim",
                    "revision": 0,
                    "project_id": "PRJ-1",
                    "question_id": "RQ-1",
                    "statement": "A decision-free candidate that must still wait",
                    "assessment": "proposed",
                }
                second = _candidate(
                    current,
                    [TransitionAction(TransitionKind.CREATE_OBJECT, {"object": claim})],
                    "SDP-SECOND",
                )
                app.conversation_store.store_state_delta_proposal("SDP-SECOND", second)

                first = app.coordinator.process_input(_input(
                    "IN-A", "COMMITTABLE_ACTION", "apply guarded"
                ))
                self.assertEqual(first.status, "CONFIRMATION_REQUIRED")
                gated = app.coordinator.process_input(_input(
                    "IN-AC",
                    "CONFIRMATION",
                    "yes",
                    target={"target_type": "confirmation_request", "target_id": "CONFREQ-A"},
                ))
                request_id = gated.data["decision_request"]["request_id"]
                before = app.state_repository.load_state_view("PRJ-1", "LIN-1")

                second_confirmation = app.coordinator.process_input(_input(
                    "IN-B", "COMMITTABLE_ACTION", "apply second"
                ))
                self.assertEqual(second_confirmation.status, "CONFIRMATION_REQUIRED")
                blocked = app.coordinator.process_input(_input(
                    "IN-BC",
                    "CONFIRMATION",
                    "yes",
                    target={"target_type": "confirmation_request", "target_id": "CONFREQ-B"},
                ))
                self.assertEqual(blocked.status, "DECISION_PENDING")
                self.assertEqual(
                    blocked.data["pending_human_decision_request_ids"],
                    [request_id],
                )
                after = app.state_repository.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(
                    after.current_snapshot["content_digest"],
                    before.current_snapshot["content_digest"],
                )
                self.assertIsNone(after.latest_object("claim", "CLM-SECOND"))
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
