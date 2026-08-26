from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest

from core.conversation import ActionDraft, ConversationRuntimeError, with_document_digest
from core.conversation.testing import MappingResolver, SequenceIdProvider
from core.execution.testing import StaticClock
from plugins.local_application import LocalResearchApplication
from plugins.local_conversation_store import LocalConversationStore
from runtime_fixtures import project, rq, seed_state


ACTOR = {"actor_id": "HUMAN-1", "actor_type": "human"}


def input_document(input_id, classification, text, *, target=None):
    document = {
        "schema_version": "0.1.0",
        "message_type": "conversation_input",
        "input_id": input_id,
        "conversation_id": "CONV-25",
        "project_id": "PRJ-1",
        "actor": deepcopy(ACTOR),
        "classification": classification,
        "text": text,
        "received_at": "2026-08-27T00:00:00Z",
    }
    if target is not None:
        document["target"] = target
    return with_document_digest(document)


def profile_provider(project_ref, expected_digest):
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


def state():
    return seed_state(
        objects=[project(), rq(state="approved")],
        mode="real",
        snapshot_id="SNP-CONV-0",
    )


class WorkConversationProductionRuntimeTests(unittest.TestCase):
    def make_app(self, root, mapping, ids, *, seed=True):
        return LocalResearchApplication(
            root,
            resolver=MappingResolver(mapping),
            effective_profile_set_provider=profile_provider,
            seed_state=state() if seed else None,
            clock=StaticClock("2026-08-27T00:00:00Z"),
            id_provider=SequenceIdProvider(ids),
        )

    def test_proposal_only_desktop_does_not_create_run_or_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(
                temp,
                {"consider desktop": ActionDraft("desktop_research.investigate", {"question_id": "RQ-1"})},
                ["PROP-1", "CTX-1"],
            )
            try:
                result = app.coordinator.process_input(input_document("IN-P", "PROPOSAL", "consider desktop"))
                self.assertEqual(result.status, "PROPOSED")
                self.assertEqual(result.proposal["commitment_mode"], "proposal_only")
                self.assertIsNone(result.confirmation_request)
                self.assertEqual(app.execution_store.diagnose_integrity(), ())
                self.assertEqual(len(app.conversation_store.list_pending("CONV-25")), 1)
            finally:
                app.close()

    def test_query_is_read_only_and_snapshot_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(
                temp,
                {"status": ActionDraft("research.status", {"kinds": ["research_question"]})},
                ["PROP-2", "ACTREC-2", "CONVTRACE-2"],
            )
            try:
                result = app.coordinator.process_input(input_document("IN-Q", "QUERY", "status"))
                self.assertEqual(result.status, "SUCCEEDED")
                receipt = result.action_receipt
                self.assertEqual(receipt["state_before"], receipt["state_after"])
                self.assertFalse(receipt["research_state_mutation_performed"])
                self.assertEqual([item["kind"] for item in result.data["objects"]], ["research_question"])
            finally:
                app.close()

    def test_desktop_committable_action_materializes_exact_pr9_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(
                temp,
                {"run desktop": ActionDraft("desktop_research.investigate", {"question_id": "RQ-1"})},
                ["PROP-3", "CTX-3", "INV-3", "RUN-3", "TRACE-3", "ACTREC-3", "CONVTRACE-3"],
            )
            try:
                before = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot["content_digest"]
                result = app.coordinator.process_input(input_document("IN-D", "COMMITTABLE_ACTION", "run desktop"))
                self.assertEqual(result.status, "EXECUTION_PREPARED")
                self.assertEqual(result.prepared_execution.run.run_id, "RUN-3")
                invocation = app.execution_store.load_invocation("INV-3")
                self.assertEqual(invocation["capability"]["capability_id"], "desktop-research")
                self.assertEqual(invocation["capability"]["function_id"], "investigate")
                self.assertEqual(invocation["context_pack"], result.proposal["route"]["context_pack"])
                self.assertNotEqual(
                    invocation["runtime_authorization_evidence"]["authorization_digest"],
                    result.proposal["proposal_digest"],
                )
                after = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot["content_digest"]
                self.assertEqual(before, after)
                self.assertFalse(result.action_receipt["research_state_mutation_performed"])
            finally:
                app.close()

    def test_explicit_run_abort_requires_confirmation_and_keeps_research_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            mapping = {
                "run desktop": ActionDraft("desktop_research.investigate", {"question_id": "RQ-1"}),
                "abort": ActionDraft("run.abort", {"run_id": "RUN-1", "reason": "human requested"}),
            }
            app = self.make_app(
                temp, mapping,
                [
                    "PROP-1", "CTX-1", "INV-1", "RUN-1", "TRACE-1", "ACTREC-1", "CONVTRACE-1",
                    "PROP-2", "CONFREQ-2", "CONFREC-2", "ACTREC-2", "CONVTRACE-2",
                ],
            )
            try:
                app.coordinator.process_input(input_document("IN-RUN", "COMMITTABLE_ACTION", "run desktop"))
                snapshot = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot["content_digest"]
                pending = app.coordinator.process_input(input_document("IN-A", "COMMITTABLE_ACTION", "abort"))
                self.assertEqual(pending.status, "CONFIRMATION_REQUIRED")
                confirmed = app.coordinator.process_input(input_document(
                    "IN-C", "CONFIRMATION", "yes",
                    target={"target_type": "confirmation_request", "target_id": "CONFREQ-2"},
                ))
                self.assertEqual(confirmed.status, "SUCCEEDED")
                self.assertEqual(app.execution_store.load_run("RUN-1").status.value, "ABORTED")
                current = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot["content_digest"]
                self.assertEqual(snapshot, current)
                self.assertFalse(confirmed.action_receipt["research_state_mutation_performed"])
            finally:
                app.close()

    def test_confirmation_is_not_human_decision_and_replay_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(
                temp,
                {"adopt": ActionDraft("state.apply_candidate", {"state_delta_proposal_id": "SDP-MISSING"})},
                ["PROP-5", "CONFREQ-5", "CONFREC-5", "ACTREC-5", "CONVTRACE-5", "CONFREC-REPLAY"],
            )
            try:
                pending = app.coordinator.process_input(input_document("IN-S", "COMMITTABLE_ACTION", "adopt"))
                self.assertEqual(pending.status, "CONFIRMATION_REQUIRED")
                confirmation = input_document(
                    "IN-C1", "CONFIRMATION", "ok",
                    target={"target_type": "confirmation_request", "target_id": "CONFREQ-5"},
                )
                result = app.coordinator.process_input(confirmation)
                self.assertEqual(result.status, "DECISION_REQUIRED")
                self.assertEqual(result.issues[0]["code"], "CONV-HUMAN-DECISION-001")
                with self.assertRaises(ConversationRuntimeError) as raised:
                    app.coordinator.process_input(input_document(
                        "IN-C2", "CONFIRMATION", "again",
                        target={"target_type": "confirmation_request", "target_id": "CONFREQ-5"},
                    ))
                self.assertEqual(raised.exception.code, "CONV-CONFIRMATION-REPLAY-001")
            finally:
                app.close()

    def test_confirmation_request_survives_conversation_store_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(
                temp,
                {"adopt": ActionDraft("state.apply_candidate", {"state_delta_proposal_id": "SDP-MISSING"})},
                ["PROP-R", "CONFREQ-R"],
            )
            try:
                app.coordinator.process_input(input_document("IN-R", "COMMITTABLE_ACTION", "adopt"))
            finally:
                app.close()
            reopened = self.make_app(
                temp,
                {},
                ["CONFREC-R", "ACTREC-R", "CONVTRACE-R"],
                seed=False,
            )
            try:
                result = reopened.coordinator.process_input(input_document(
                    "IN-RC", "CONFIRMATION", "confirm after restart",
                    target={"target_type": "confirmation_request", "target_id": "CONFREQ-R"},
                ))
                self.assertEqual(result.status, "DECISION_REQUIRED")
            finally:
                reopened.close()

    def test_atomic_confirmation_store_race_allows_one_consumer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "conversation.db"
            setup = LocalConversationStore(path)
            proposal = with_document_digest({
                "schema_version": "0.1.0", "message_type": "action_proposal", "proposal_id": "PROP-X",
                "conversation_id": "CONV-X", "project_id": "PRJ-1",
                "source": {"source_type": "human_input", "input_id": "IN-X"},
                "initiating_actor": deepcopy(ACTOR),
                "action": {"action_type": "run.abort", "effect": "state_changing", "payload_contract": "x@1",
                           "payload": {"run_id": "RUN-X"}, "payload_digest": "sha256:" + "1" * 64},
                "commitment_mode": "commit_requested",
                "confirmation_policy": {"required_on_commit": True, "human_confirmation_only": True},
                "human_decision_boundary": {"required": False, "confirmation_is_human_decision": False},
                "bindings": {"current_state": {"state_id": "S", "revision": 0, "content_digest": "sha256:" + "2" * 64}},
                "route": {"route_type": "harness_service", "service_id": "run.abort"},
                "created_at": "2026-08-27T00:00:00Z",
            })
            setup.store_proposal(proposal)
            request = with_document_digest({
                "schema_version": "0.1.0", "message_type": "confirmation_request", "confirmation_request_id": "REQ-X",
                "conversation_id": "CONV-X", "project_id": "PRJ-1",
                "proposal_binding": {"proposal_id": "PROP-X", "proposal_digest": proposal["proposal_digest"]},
                "actor_binding": deepcopy(ACTOR),
                "action_binding": {"action_type": "run.abort", "payload_digest": proposal["action"]["payload_digest"]},
                "state_binding": {"state_id": "S", "revision": 0, "content_digest": "sha256:" + "2" * 64},
                "issued_at": "2026-08-27T00:00:00Z", "expires_at": "2026-08-27T00:15:00Z", "single_use": True,
            })
            setup.store_confirmation_request(request)
            setup.close()
            barrier = threading.Barrier(2)
            outcomes = []
            lock = threading.Lock()

            def consume(suffix):
                store = LocalConversationStore(path)
                receipt = {
                    "schema_version": "0.1.0", "message_type": "confirmation_receipt",
                    "confirmation_receipt_id": "REC-" + suffix,
                    "receipt_digest": "sha256:" + ("a" if suffix == "A" else "b") * 64,
                }
                barrier.wait()
                value = store.consume_confirmation_request("REQ-X", request["request_digest"], receipt)
                with lock:
                    outcomes.append(value)
                store.close()

            a = threading.Thread(target=consume, args=("A",)); b = threading.Thread(target=consume, args=("B",))
            a.start(); b.start(); a.join(); b.join()
            self.assertEqual(sorted(outcomes), [False, True])


if __name__ == "__main__":
    unittest.main()
