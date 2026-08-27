from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import tempfile
import unittest

from core.decision import HumanDecisionError, HumanDecisionService, with_response_digest
from core.execution.testing import StaticClock
from core.runtime import (
    ReductionError,
    StateTransitionService,
    TransitionAction,
    TransitionKind,
    canonical_digest,
    reduce_state,
)
from core.runtime.testing import InMemoryResearchStateRepository
from plugins.local_decision_store import LocalHumanDecisionStore
from runtime_fixtures import SCHEMA_VALIDATOR, finding, make_request, project, rq, seed_state


CLOCK = StaticClock("2026-08-27T06:00:00Z")
ACTOR = {"actor_id": "HUMAN-1", "actor_type": "human"}


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
        "rationale": "PR26 review regression fixture",
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {},
        "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


class PR26ReviewRegressionTests(unittest.TestCase):
    def _service(self, state):
        temp = tempfile.TemporaryDirectory()
        store = LocalHumanDecisionStore(f"{temp.name}/decision.db")
        repo = InMemoryResearchStateRepository(state)
        service = HumanDecisionService(
            store=store,
            state_provider=repo,
            state_transition_service=StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR),
            clock=CLOCK,
        )
        self.addCleanup(store.close)
        self.addCleanup(temp.cleanup)
        return service

    def test_malformed_response_actor_fails_closed_as_human_decision_error(self):
        state = seed_state(objects=[project(), rq(state="candidate")])
        service = self._service(state)
        gate = service.gate_candidate(
            _candidate(
                state,
                [TransitionAction(
                    TransitionKind.ADOPT_OBJECT,
                    {"object": rq(revision=1, state="approved")},
                )],
                "SDP-MALFORMED-ACTOR",
            ),
            state=state,
            actor=ACTOR,
        )
        response = with_response_digest({
            "schema_version": "0.1.0",
            "response_id": "HDRESP-MALFORMED",
            "request_id": gate.decision_request["request_id"],
            "request_digest": gate.decision_request["request_digest"],
            "disposition": "approve_exact",
            "actor": "HUMAN-1",
            "responded_at": CLOCK.now(),
        })
        with self.assertRaises(HumanDecisionError) as raised:
            service.resolve(response)
        self.assertEqual(raised.exception.code, "DECISION-RESPONSE-001")

    def test_lineage_candidate_cannot_smuggle_uninherited_decision_provenance(self):
        state = seed_state(objects=[project(), rq(state="approved"), finding(state="approved")])
        service = self._service(state)
        derived = finding(
            revision=1,
            statement="Reconfirmed candidate",
            state="approved",
        )
        derived["decision_ids"] = ["DEC-FORGED"]
        action = TransitionAction(TransitionKind.APPLY_LINEAGE_PLAN, {
            "plan_ref": "PLAN-FORGED",
            "target_lineage_id": "LIN-FORGED",
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
        with self.assertRaises(HumanDecisionError) as raised:
            service.gate_candidate(
                _candidate(state, [action], "SDP-FORGED-LINEAGE"),
                state=state,
                actor=ACTOR,
            )
        self.assertEqual(raised.exception.code, "DECISION-FORGED-REF-001")

    def test_lineage_provenance_uses_pinned_baseline_not_sibling_latest_revision(self):
        state = seed_state(objects=[project(), rq(state="approved"), finding(state="approved")])
        sibling_revision = finding(
            revision=1,
            statement="Sibling-lineage revision",
            state="approved",
        )
        sibling_revision["decision_ids"] = ["DEC-SIBLING"]
        state = replace(state, objects=(*state.objects, sibling_revision))
        service = self._service(state)

        derived = finding(
            revision=2,
            statement="Reconfirmed from pinned baseline",
            state="approved",
        )
        derived["decision_ids"] = ["DEC-SIBLING"]
        action = TransitionAction(TransitionKind.APPLY_LINEAGE_PLAN, {
            "plan_ref": "PLAN-PINNED",
            "target_lineage_id": "LIN-PINNED",
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

        self.assertEqual(state.latest_object("finding", "FND-1")["revision"], 1)
        self.assertEqual(state.exact_object("finding", "FND-1", 0).get("decision_ids", []), [])
        with self.assertRaises(HumanDecisionError) as raised:
            service.gate_candidate(
                _candidate(state, [action], "SDP-PINNED-LINEAGE"),
                state=state,
                actor=ACTOR,
            )
        self.assertEqual(raised.exception.code, "DECISION-FORGED-REF-001")

    def test_normal_reducer_rejects_duplicate_record_decision_identity(self):
        state = seed_state(objects=[project(), rq(state="approved")])
        decision = {
            "schema_version": "0.1.0",
            "id": "DEC-DUPLICATE",
            "kind": "decision",
            "revision": 0,
            "project_id": "PRJ-1",
            "decision_kind": "research_adoption",
            "subjects": [{"kind": "research_question", "id": "RQ-1"}],
            "choice": "approve",
            "actor_type": "human",
            "decided_by": "HUMAN-1",
            "decided_at": CLOCK.now(),
        }
        request = make_request(
            state,
            [
                TransitionAction(TransitionKind.RECORD_DECISION, {"object": decision}),
                TransitionAction(TransitionKind.RECORD_DECISION, {"object": deepcopy(decision)}),
            ],
            suffix="PR26-DUP",
        )
        with self.assertRaisesRegex(ReductionError, "duplicate RECORD_DECISION identity"):
            reduce_state(state, request)


if __name__ == "__main__":
    unittest.main()
