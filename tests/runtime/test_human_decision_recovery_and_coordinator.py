from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest

from core.conversation import ActionDraft, with_document_digest
from core.conversation.testing import MappingResolver, SequenceIdProvider
from core.decision import HumanDecisionService, make_response
from core.execution.testing import StaticClock
from core.runtime import (
    StateTransitionService, TransitionAction, TransitionKind, canonical_digest,
)
from core.runtime.testing import InMemoryResearchStateRepository
from plugins.local_application import LocalResearchApplication
from plugins.local_decision_store import LocalHumanDecisionStore
from runtime_fixtures import (
    SCHEMA_VALIDATOR, finding, project, rq, seed_state,
)


CLOCK = StaticClock("2026-08-27T05:00:00Z")
ACTOR = {"actor_id": "HUMAN-1", "actor_type": "human"}


def _wire(action):
    return {
        "kind": action.kind.value,
        "payload": deepcopy(dict(action.payload)),
        "decision_refs": list(action.decision_refs),
        "source_refs": list(action.source_refs),
    }


def _candidate(state, actions, proposal_id="SDP-RECOVERY"):
    value = {
        "proposal_id": proposal_id,
        "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref,
        "source_refs": ["HND-RECOVERY"],
        "proposed_actions": [_wire(action) for action in actions],
        "affected_refs": [],
        "rationale": "PR26 recovery fixture",
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {"handoff_ref": "HND-RECOVERY", "limitations": ["fixture"]},
        "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


class FailOnceFinalizeStore(LocalHumanDecisionStore):
    def __init__(self, path):
        super().__init__(path)
        self.fail_resolved_once = True

    def finalize(self, request_id, response_digest, status, **kwargs):
        if status == "RESOLVED" and self.fail_resolved_once:
            self.fail_resolved_once = False
            raise RuntimeError("simulated post-Research-State operational finalize failure")
        return super().finalize(request_id, response_digest, status, **kwargs)


class MutableSourceBindings:
    def __init__(self, candidate, proposal=None):
        self.candidate = candidate
        self.proposal = proposal

    def load_state_delta_proposal(self, proposal_id):
        if self.candidate is not None and self.candidate.get("proposal_id") == proposal_id:
            return deepcopy(self.candidate)
        return None

    def load_proposal(self, proposal_id):
        if self.proposal is not None and self.proposal.get("proposal_id") == proposal_id:
            return deepcopy(self.proposal)
        return None


class HumanDecisionRecoveryTests(unittest.TestCase):
    def test_commit_receipt_recovers_after_operational_finalize_failure(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        repo = InMemoryResearchStateRepository(state)
        transitions = StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR)
        with tempfile.TemporaryDirectory() as temp:
            store = FailOnceFinalizeStore(f"{temp}/decision.db")
            service = HumanDecisionService(
                store=store,
                state_provider=repo,
                state_transition_service=transitions,
                clock=CLOCK,
            )
            try:
                candidate = _candidate(state, [
                    TransitionAction(
                        TransitionKind.ADOPT_OBJECT,
                        {"object": rq(revision=1, state="approved")},
                    )
                ])
                gate = service.gate_candidate(candidate, state=state, actor=ACTOR)
                response = make_response(
                    request=gate.decision_request,
                    disposition="approve_exact",
                    actor_id="HUMAN-1",
                    responded_at="2026-08-27T05:01:00Z",
                )
                with self.assertRaisesRegex(RuntimeError, "operational finalize failure"):
                    service.resolve(response)
                after_commit = repo.load_state_view("PRJ-1", "LIN-1")
                first_head = after_commit.current_snapshot["content_digest"]
                self.assertEqual(len(after_commit.decisions), 1)
                self.assertEqual(store.get_status(gate.decision_request["request_id"]), "RESOLVING")

                recovered = service.resolve(response)
                self.assertEqual(recovered.status, "RESOLVED")
                self.assertIsNotNone(recovered.commit_receipt)
                final = repo.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(final.current_snapshot["content_digest"], first_head)
                self.assertEqual(len(final.decisions), 1)
                self.assertEqual(store.get_status(gate.decision_request["request_id"]), "RESOLVED")
            finally:
                store.close()

    def test_source_candidate_binding_is_revalidated_before_human_response(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        repo = InMemoryResearchStateRepository(state)
        transitions = StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR)
        candidate = _candidate(state, [
            TransitionAction(
                TransitionKind.ADOPT_OBJECT,
                {"object": rq(revision=1, state="approved")},
            )
        ], proposal_id="SDP-SOURCE-BIND")
        source_bindings = MutableSourceBindings(candidate)
        with tempfile.TemporaryDirectory() as temp:
            store = LocalHumanDecisionStore(f"{temp}/decision.db")
            service = HumanDecisionService(
                store=store,
                state_provider=repo,
                state_transition_service=transitions,
                clock=CLOCK,
                source_binding_provider=source_bindings,
            )
            try:
                gate = service.gate_candidate(candidate, state=state, actor=ACTOR)
                source_bindings.candidate = None
                result = service.resolve(make_response(
                    request=gate.decision_request,
                    disposition="approve_exact",
                    actor_id="HUMAN-1",
                    responded_at="2026-08-27T05:01:00Z",
                ))
                self.assertEqual(result.status, "STALE")
                current = repo.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(current.decisions, ())
                self.assertEqual(current.current_snapshot["content_digest"], state.current_snapshot["content_digest"])
            finally:
                store.close()

    def test_lineage_reconfirm_binds_one_atomic_plan_and_reconfirmation_decisions(self):
        objects = [project(), rq(state="approved"), finding(state="approved")]
        state = seed_state(objects=objects)
        repo = InMemoryResearchStateRepository(state)
        transitions = StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR)
        derived = finding(revision=1, statement="Reconfirmed by explicit Human Decision", state="approved")
        action = TransitionAction(TransitionKind.APPLY_LINEAGE_PLAN, {
            "plan_ref": "PLAN-HD",
            "target_lineage_id": "LIN-HD",
            "lineage_kind": "exploratory_fork",
            "baseline_snapshot_ref": state.current_snapshot["id"],
            "baseline_snapshot_digest": state.current_snapshot["content_digest"],
            "treatments": [
                {"object_kind": "project", "source_ref": "PRJ-1", "treatment": "PRESERVE"},
                {"object_kind": "research_question", "source_ref": "RQ-1", "treatment": "PRESERVE"},
                {
                    "object_kind": "finding",
                    "source_ref": "FND-1",
                    "treatment": "RECONFIRM",
                    "derived_object": derived,
                },
            ],
        })
        with tempfile.TemporaryDirectory() as temp:
            store = LocalHumanDecisionStore(f"{temp}/decision.db")
            service = HumanDecisionService(
                store=store,
                state_provider=repo,
                state_transition_service=transitions,
                clock=CLOCK,
            )
            try:
                gate = service.gate_candidate(
                    _candidate(state, [action], proposal_id="SDP-LINEAGE"),
                    state=state,
                    actor=ACTOR,
                )
                kinds = {unit["required_decision_kind"] for unit in gate.decision_request["decision_units"]}
                self.assertEqual(kinds, {"lineage_plan", "lineage_reconfirmation"})
                result = service.resolve(make_response(
                    request=gate.decision_request,
                    disposition="approve_exact",
                    actor_id="HUMAN-1",
                    responded_at="2026-08-27T05:01:00Z",
                ))
                self.assertEqual(result.status, "RESOLVED")
                self.assertEqual(
                    result.commit_receipt.applied_typed_actions,
                    ("RECORD_DECISION", "RECORD_DECISION", "APPLY_LINEAGE_PLAN"),
                )
                child = repo.load_state_view("PRJ-1", "LIN-HD")
                reconfirmed = child.latest_object("finding", "FND-1")
                reconfirm_decision = next(
                    item for item in child.decisions
                    if item["decision_kind"] == "lineage_reconfirmation"
                )
                self.assertIn(reconfirm_decision["id"], reconfirmed["decision_ids"])
                self.assertEqual(len(child.decisions), 2)
            finally:
                store.close()

    def test_candidate_without_pr20_requirement_uses_ordinary_confirmed_commit(self):
        state = seed_state(objects=[project(), rq(state="approved")])
        repo = InMemoryResearchStateRepository(state)
        transitions = StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR)
        claim = {
            "schema_version": "0.1.0",
            "id": "CLM-NO-GATE",
            "kind": "claim",
            "revision": 0,
            "project_id": "PRJ-1",
            "question_id": "RQ-1",
            "statement": "Candidate claim without an authority transition",
            "assessment": "proposed",
        }
        with tempfile.TemporaryDirectory() as temp:
            store = LocalHumanDecisionStore(f"{temp}/decision.db")
            service = HumanDecisionService(
                store=store,
                state_provider=repo,
                state_transition_service=transitions,
                clock=CLOCK,
            )
            try:
                gate = service.gate_candidate(
                    _candidate(state, [TransitionAction(TransitionKind.CREATE_OBJECT, {"object": claim})], proposal_id="SDP-NO-GATE"),
                    state=state,
                    actor=ACTOR,
                )
                self.assertEqual(gate.status, "READY_TO_COMMIT")
                self.assertIsNone(gate.decision_request)
                receipt = transitions.apply(gate.transition_request)
                self.assertEqual(receipt.applied_typed_actions, ("CREATE_OBJECT",))
                self.assertEqual(repo.load_state_view("PRJ-1", "LIN-1").decisions, ())
            finally:
                store.close()


def _input(input_id, classification, text, *, target=None):
    value = {
        "schema_version": "0.1.0",
        "message_type": "conversation_input",
        "input_id": input_id,
        "conversation_id": "CONV-26-PENDING",
        "project_id": "PRJ-1",
        "actor": deepcopy(ACTOR),
        "classification": classification,
        "text": text,
        "received_at": "2026-08-27T05:00:00Z",
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


class PendingDecisionCoordinatorTests(unittest.TestCase):
    def test_pending_decision_blocks_next_research_capability_and_is_visible_in_status(self):
        seed = seed_state(
            objects=[project(), rq(state="approved")],
            mode="real",
            snapshot_id="SNP-PENDING-0",
        )
        mapping = {
            "apply": ActionDraft("state.apply_candidate", {"state_delta_proposal_id": "SDP-PENDING"}),
            "run next": ActionDraft("desktop_research.investigate", {"question_id": "RQ-1"}),
            "status": ActionDraft("research.status", {}),
        }
        ids = [
            "PROP-A", "CONFREQ-A", "CONFREC-A", "ACTREC-A", "CONVTRACE-A",
            "PROP-D", "CTX-D", "ACTREC-D", "CONVTRACE-D",
            "PROP-S", "ACTREC-S", "CONVTRACE-S",
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
                revised["text"] = "Materially revised question"
                candidate = _candidate(
                    current,
                    [TransitionAction(TransitionKind.REVISE_OBJECT, {"object": revised})],
                    proposal_id="SDP-PENDING",
                )
                app.conversation_store.store_state_delta_proposal("SDP-PENDING", candidate)

                confirmation = app.coordinator.process_input(_input("IN-A", "COMMITTABLE_ACTION", "apply"))
                self.assertEqual(confirmation.status, "CONFIRMATION_REQUIRED")
                gated = app.coordinator.process_input(_input(
                    "IN-C",
                    "CONFIRMATION",
                    "yes",
                    target={"target_type": "confirmation_request", "target_id": "CONFREQ-A"},
                ))
                self.assertTrue(gated.data["decision_required"])
                request_id = gated.data["decision_request"]["request_id"]

                blocked = app.coordinator.process_input(_input("IN-D", "COMMITTABLE_ACTION", "run next"))
                self.assertEqual(blocked.status, "DECISION_PENDING")
                self.assertEqual(blocked.data["pending_human_decision_request_ids"], [request_id])
                self.assertEqual(app.execution_store.diagnose_integrity(), ())

                status = app.coordinator.process_input(_input("IN-S", "QUERY", "status"))
                visible = status.data["pending_human_decisions"]
                self.assertEqual([item["request_id"] for item in visible], [request_id])
                self.assertEqual(visible[0]["decision_kinds"], ["research_revision"])
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
