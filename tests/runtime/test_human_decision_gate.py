from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import tempfile
import threading
import unittest

from core.decision import HumanDecisionError, HumanDecisionService, make_response, with_response_digest
from core.execution.testing import StaticClock
from core.runtime import StateTransitionService, TransitionAction, TransitionKind, canonical_digest
from core.runtime.testing import InMemoryResearchStateRepository
from plugins.local_decision_store import LocalHumanDecisionStore
from runtime_fixtures import (
    SCHEMA_VALIDATOR, evidence, make_request, project, rq, seed_state, source,
)


ACTOR = {"actor_id": "HUMAN-1", "actor_type": "human"}
CLOCK = StaticClock("2026-08-27T04:00:00Z")


def action_wire(action):
    return {
        "kind": action.kind.value,
        "payload": deepcopy(dict(action.payload)),
        "decision_refs": list(action.decision_refs),
        "source_refs": list(action.source_refs),
    }


def candidate(state, actions, *, proposal_id="SDP-1"):
    value = {
        "proposal_id": proposal_id,
        "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref,
        "source_refs": ["RUN-1", "HND-1"],
        "proposed_actions": [action_wire(action) for action in actions],
        "affected_refs": [],
        "rationale": "fixture candidate",
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {
            "handoff_ref": "HND-1",
            "counterevidence_refs": ["CEV-1"],
            "conflict_refs": ["CONFLICT-1"],
            "unknown_refs": ["UNK-1"],
            "limitations": ["bounded fixture"],
        },
        "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


class HumanDecisionGateTests(unittest.TestCase):
    def make_service(self, state):
        temp = tempfile.TemporaryDirectory()
        store = LocalHumanDecisionStore(f"{temp.name}/decision.db")
        repo = InMemoryResearchStateRepository(state)
        transitions = StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR)
        service = HumanDecisionService(
            store=store, state_provider=repo,
            state_transition_service=transitions, clock=CLOCK,
        )
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        return store, repo, transitions, service

    def test_request_uses_pr20_requirement_and_does_not_mutate_state(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        store, repo, _, service = self.make_service(state)
        proposed = rq(revision=1, state="approved")
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": proposed})]),
            state=state, actor=ACTOR,
        )
        self.assertEqual(gate.status, "DECISION_REQUIRED")
        request = gate.decision_request
        self.assertEqual(request["decision_units"][0]["required_decision_kind"], "research_adoption")
        self.assertEqual(request["decision_units"][0]["required_choice"], "approve")
        self.assertEqual(request["decision_units"][0]["subject"], {"kind": "research_question", "id": "RQ-1"})
        self.assertEqual(repo.load_state_view("PRJ-1", "LIN-1").current_snapshot["id"], state.current_snapshot["id"])
        self.assertEqual(repo.load_state_view("PRJ-1", "LIN-1").decisions, ())
        self.assertEqual(store.get_status(request["request_id"]), "PENDING")

    def test_approve_exact_commits_decision_and_target_in_one_request(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        store, repo, _, service = self.make_service(state)
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": rq(revision=1, state="approved")})]),
            state=state, actor=ACTOR,
        )
        response = make_response(
            request=gate.decision_request, disposition="approve_exact",
            actor_id="HUMAN-1", responded_at=CLOCK.now(),
        )
        result = service.resolve(response)
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.commit_receipt.applied_typed_actions, ("RECORD_DECISION", "ADOPT_OBJECT"))
        current = repo.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(current.latest_object("research_question", "RQ-1")["adoption_state"], "approved")
        self.assertEqual(len(current.decisions), 1)
        decision = current.decisions[0]
        self.assertEqual(decision["actor_type"], "human")
        self.assertEqual(decision["decision_kind"], "research_adoption")
        self.assertIn(decision["id"], current.latest_object("research_question", "RQ-1")["decision_ids"])
        self.assertEqual(store.get_status(gate.decision_request["request_id"]), "RESOLVED")

    def test_same_approved_response_is_idempotently_recoverable(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        _, repo, _, service = self.make_service(state)
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": rq(revision=1, state="approved")})]),
            state=state, actor=ACTOR,
        )
        response = make_response(request=gate.decision_request, disposition="approve_exact", actor_id="HUMAN-1", responded_at=CLOCK.now())
        first = service.resolve(response)
        second = service.resolve(response)
        self.assertEqual(first.commit_receipt.commit_id, second.commit_receipt.commit_id)
        self.assertEqual(len(repo.load_state_view("PRJ-1", "LIN-1").decisions), 1)

    def test_decline_and_revision_do_not_create_reverse_research_decisions(self):
        for disposition, expected in (("decline", "DECLINED"), ("request_revision", "REVISION_REQUESTED")):
            with self.subTest(disposition=disposition):
                state = seed_state(objects=[project(), rq(state="candidate")], snapshot_id=f"SNP-{expected}")
                _, repo, _, service = self.make_service(state)
                gate = service.gate_candidate(
                    candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": rq(revision=1, state="approved")})], proposal_id=f"SDP-{expected}"),
                    state=state, actor=ACTOR,
                )
                result = service.resolve(make_response(
                    request=gate.decision_request, disposition=disposition,
                    actor_id="HUMAN-1", responded_at=CLOCK.now(),
                ))
                self.assertEqual(result.status, expected)
                current = repo.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(current.current_snapshot["id"], state.current_snapshot["id"])
                self.assertEqual(current.decisions, ())
                self.assertEqual(current.latest_object("research_question", "RQ-1")["adoption_state"], "candidate")

    def test_stale_request_fails_closed_without_decision(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        _, repo, transitions, service = self.make_service(state)
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": rq(revision=1, state="approved")})]),
            state=state, actor=ACTOR,
        )
        claim = {
            "schema_version": "0.1.0", "id": "CLM-ADVANCE", "kind": "claim", "revision": 0,
            "project_id": "PRJ-1", "question_id": "RQ-1", "statement": "advance head", "assessment": "proposed",
        }
        self.assertTrue(hasattr(transitions.apply(make_request(
            state, [TransitionAction(TransitionKind.CREATE_OBJECT, {"object": claim})], suffix="8"
        )), "new_snapshot_ref"))
        result = service.resolve(make_response(
            request=gate.decision_request, disposition="approve_exact",
            actor_id="HUMAN-1", responded_at=CLOCK.now(),
        ))
        self.assertEqual(result.status, "STALE")
        current = repo.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(current.decisions, ())
        self.assertEqual(current.latest_object("research_question", "RQ-1")["adoption_state"], "candidate")

    def test_evidence_verification_and_reclassification_require_both_decisions(self):
        state = seed_state(objects=[
            project(), source(), evidence(evidence_kind="counterevidence", verification="unverified")
        ])
        _, repo, _, service = self.make_service(state)
        revised = evidence(revision=1, evidence_kind="supporting", verification="verified")
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.VERIFY_EVIDENCE, {"object": revised})]),
            state=state, actor=ACTOR,
        )
        kinds = {(unit["required_decision_kind"], unit["required_choice"]) for unit in gate.decision_request["decision_units"]}
        self.assertEqual(kinds, {
            ("evidence_qualification", "verify"),
            ("evidence_reclassification", "reclassify"),
        })
        result = service.resolve(make_response(
            request=gate.decision_request, disposition="approve_exact",
            actor_id="HUMAN-1", responded_at=CLOCK.now(),
        ))
        self.assertEqual(result.status, "RESOLVED")
        current = repo.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(len(current.decisions), 2)
        self.assertEqual(len(current.latest_object("evidence", "EVD-1")["decision_ids"]), 2)

    def test_wrong_actor_and_different_terminal_response_fail_closed(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        _, _, _, service = self.make_service(state)
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": rq(revision=1, state="approved")})]),
            state=state, actor=ACTOR,
        )
        bad = with_response_digest({
            "schema_version": "0.1.0", "response_id": "RESP-BAD",
            "request_id": gate.decision_request["request_id"], "request_digest": gate.decision_request["request_digest"],
            "disposition": "approve_exact", "actor": {"actor_id": "BOT-1", "actor_type": "service"},
            "responded_at": CLOCK.now(),
        })
        with self.assertRaises(HumanDecisionError) as raised:
            service.resolve(bad)
        self.assertEqual(raised.exception.code, "DECISION-ACTOR-001")
        approved = make_response(request=gate.decision_request, disposition="approve_exact", actor_id="HUMAN-1", responded_at=CLOCK.now())
        service.resolve(approved)
        different = make_response(request=gate.decision_request, disposition="decline", actor_id="HUMAN-1", responded_at=CLOCK.now())
        with self.assertRaises(HumanDecisionError) as terminal:
            service.resolve(different)
        self.assertEqual(terminal.exception.code, "DECISION-TERMINAL-001")

    def test_concurrent_responses_allow_only_one_terminal_disposition(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        store, _, _, service = self.make_service(state)
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.ADOPT_OBJECT, {"object": rq(revision=1, state="approved")})]),
            state=state, actor=ACTOR,
        )
        approve = make_response(request=gate.decision_request, disposition="approve_exact", actor_id="HUMAN-1", responded_at=CLOCK.now())
        decline = make_response(request=gate.decision_request, disposition="decline", actor_id="HUMAN-1", responded_at=CLOCK.now())
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def resolve(response):
            barrier.wait()
            try:
                outcome = service.resolve(response).status
            except HumanDecisionError as exc:
                outcome = exc.code
            with lock:
                outcomes.append(outcome)

        a = threading.Thread(target=resolve, args=(approve,))
        b = threading.Thread(target=resolve, args=(decline,))
        a.start()
        b.start()
        a.join()
        b.join()
        self.assertEqual(sum(item in {"RESOLVED", "DECLINED"} for item in outcomes), 1)
        self.assertIn(store.get_status(gate.decision_request["request_id"]), {"RESOLVED", "DECLINED"})

    def test_active_lineage_switch_can_atomically_record_decision(self):
        state = seed_state(objects=[project(), rq(state="approved")])
        second = replace(
            state.lineages[0], lineage_id="LIN-2", lineage_kind="exploratory_fork",
            head_snapshot_ref=state.current_snapshot["id"],
            head_snapshot_digest=state.current_snapshot["content_digest"],
        )
        state = replace(state, lineages=(*state.lineages, second))
        _, repo, _, service = self.make_service(state)
        gate = service.gate_candidate(
            candidate(state, [TransitionAction(TransitionKind.SWITCH_ACTIVE_LINEAGE, {"target_lineage_ref": "LIN-2"})]),
            state=state, actor=ACTOR,
        )
        result = service.resolve(make_response(
            request=gate.decision_request, disposition="approve_exact",
            actor_id="HUMAN-1", responded_at=CLOCK.now(),
        ))
        self.assertEqual(result.status, "RESOLVED")
        current = repo.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(current.active_lineage_ref, "LIN-2")
        self.assertEqual(len(current.decisions), 1)


if __name__ == "__main__":
    unittest.main()
