from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from runtime_fixtures import evidence, finding, project, rq, seed_state, source
from test_survey_production import NullResolver


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
        "profile_pins": [],
        "content_digest": expected_digest,
    }


class Issue134ArgumentProposalTests(unittest.TestCase):
    def make_facade(
        self, root: str, *, finding_state: str = "approved"
    ) -> LocalApplicationFacade:
        seed = seed_state(
            objects=[
                project(),
                rq(state="approved"),
                source(),
                evidence(evidence_kind="supporting", verification="unverified"),
                finding(state=finding_state),
            ],
            snapshot_id="SNP-ARG-0",
        )
        app = LocalResearchApplication(
            root,
            resolver=NullResolver(),
            effective_profile_set_provider=profile_provider,
            seed_state=seed,
        )
        return LocalApplicationFacade(app, "PRJ-1", owns_application=True)

    @staticmethod
    def proposal_input(**overrides):
        payload = {
            "conclusion": "The supported finding warrants a bounded conclusion.",
            "warrant": "The current Research Snapshot contains direct supporting research content.",
            "question_ids": ["RQ-1"],
            "finding_ids": ["FND-1"],
            "evidence_ids": ["EVD-1"],
            "qualifier": "Within the fixture scope.",
            "implications": ["Carry the bounded conclusion into composition."],
        }
        payload.update(overrides)
        return {"action_type": "research.argument.propose", "payload": payload, "actor_id": "HUMAN-ARG"}

    def test_arg1_candidate_is_bound_to_current_snapshot_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                before = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1")
                result = facade.submit_action(self.proposal_input())
                after = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(result["status"], "SUCCEEDED")
                candidate = result["data"]["state_delta_proposal"]
                self.assertTrue(candidate["candidate_only"])
                self.assertEqual(candidate["current_snapshot_ref"], before.current_snapshot["id"])
                self.assertEqual(candidate["current_snapshot_digest"], before.current_snapshot["content_digest"])
                self.assertEqual(before.current_snapshot, after.current_snapshot)
                self.assertEqual(result["data"]["argument_candidate"]["kind"], "argument")
            finally:
                facade.close()

    def test_arg2_apply_uses_existing_confirmation_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            app = facade._application
            result = facade.submit_action(self.proposal_input())
            proposal_id = result["data"]["state_delta_proposal_id"]
            argument_id = result["data"]["argument_candidate"]["id"]
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposal_id},
                "actor_id": "HUMAN-ARG",
            })
            self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")
            committed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-ARG",
            })
            self.assertEqual(committed["status"], "SUCCEEDED")
            state = app.state_repository.load_state_view("PRJ-1", "LIN-1")
            argument = next(obj for obj in state.effective_objects() if obj.get("id") == argument_id)
            self.assertEqual(argument["kind"], "argument")
            self.assertEqual(argument["finding_ids"], ["FND-1"])
            facade.close()

    def test_arg3_rejects_refs_not_in_exact_current_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                before = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                bad = self.proposal_input(finding_ids=["CF-RUN-ONLY"], evidence_ids=[])
                with self.assertRaises(ConversationRuntimeError) as raised:
                    facade.submit_action(bad)
                self.assertEqual(raised.exception.code, "ARGUMENT-SUPPORT-001")
                after = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                self.assertEqual(before, after)
            finally:
                facade.close()

    def test_arg3_rejects_candidate_finding_in_current_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp, finding_state="candidate")
            try:
                before = facade._application.state_repository.load_state_view(
                    "PRJ-1", "LIN-1"
                ).current_snapshot
                with self.assertRaises(ConversationRuntimeError) as raised:
                    facade.submit_action(self.proposal_input())
                self.assertEqual(raised.exception.code, "ARGUMENT-SUPPORT-001")
                after = facade._application.state_repository.load_state_view(
                    "PRJ-1", "LIN-1"
                ).current_snapshot
                self.assertEqual(before, after)
            finally:
                facade.close()

    def test_arg3_bounds_support_references_before_state_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                oversized = self.proposal_input(
                    finding_ids=[],
                    evidence_ids=[f"EVD-{index}" for index in range(257)],
                )
                with self.assertRaises(LocalApplicationError) as raised:
                    facade.submit_action(oversized)
                self.assertEqual(raised.exception.code, "APPLICATION-PAYLOAD-001")
            finally:
                facade.close()

    def test_ablation_disabling_support_guard_allows_invalid_argument_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                invalid = self.proposal_input(finding_ids=["CF-RUN-ONLY"], evidence_ids=[])
                with patch(
                    "plugins.local_application.argument_facade._current_authoritative_argument_support",
                    return_value=True,
                ):
                    result = facade.submit_action(invalid)
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["data"]["argument_candidate"]["finding_ids"], ["CF-RUN-ONLY"])
            finally:
                facade.close()

    def test_arg3_stale_candidate_is_rejected_by_existing_apply_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                result = facade.submit_action(self.proposal_input())
                stale_id = result["data"]["state_delta_proposal_id"]
                advancing = facade.submit_action(self.proposal_input(
                    conclusion="A second valid Argument advances the current Snapshot."
                ))
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {
                        "state_delta_proposal_id": advancing["data"]["state_delta_proposal_id"]
                    },
                    "actor_id": "HUMAN-ARG",
                })
                committed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-ARG",
                })
                self.assertEqual(committed["status"], "SUCCEEDED")
                head = facade._application.state_repository.load_state_view(
                    "PRJ-1", "LIN-1"
                ).current_snapshot
                stale_pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": stale_id},
                    "actor_id": "HUMAN-ARG",
                })
                self.assertEqual(stale_pending["status"], "CONFIRMATION_REQUIRED")
                failed = facade.submit_confirmation({
                    "confirmation_request_id": stale_pending["confirmation_request"][
                        "confirmation_request_id"
                    ],
                    "actor_id": "HUMAN-ARG",
                })
                self.assertEqual(failed["status"], "FAILED")
                after = facade._application.state_repository.load_state_view(
                    "PRJ-1", "LIN-1"
                ).current_snapshot
                self.assertEqual(after, head)
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
