from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from runtime_fixtures import finding, project, rq, seed_state
from test_survey_production import NullResolver


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
        "profile_pins": [],
        "content_digest": expected_digest,
    }


class Issue135RecommendationProposalTests(unittest.TestCase):
    def make_facade(self, root: str, *, finding_state: str = "approved", finding_project: str = "PRJ-1") -> LocalApplicationFacade:
        seed = seed_state(
            objects=[
                project(),
                rq(state="approved"),
                finding(project_id=finding_project, state=finding_state),
            ],
            snapshot_id="SNP-REC-0",
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
            "statement": "Adopt the bounded operating control supported by the Finding.",
            "finding_ids": ["FND-1"],
            "conditions": ["Within the validated fixture scope."],
            "scope": ["Operational planning"],
        }
        payload.update(overrides)
        return {
            "action_type": "research.recommendation.propose",
            "payload": payload,
            "actor_id": "HUMAN-REC",
        }

    def test_rec1_public_candidate_is_snapshot_bound_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                definitions = {item["action_type"]: item for item in facade.list_actions()["actions"]}
                definition = definitions["research.recommendation.propose"]
                self.assertEqual(definition["effect"], "read_only")
                self.assertFalse(definition["confirmation_required"])
                before = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1")
                result = facade.submit_action(self.proposal_input())
                after = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(result["status"], "SUCCEEDED")
                candidate = result["data"]["state_delta_proposal"]
                recommendation = result["data"]["recommendation_candidate"]
                self.assertTrue(candidate["candidate_only"])
                self.assertEqual(candidate["current_snapshot_ref"], before.current_snapshot["id"])
                self.assertEqual(candidate["current_snapshot_digest"], before.current_snapshot["content_digest"])
                self.assertEqual(recommendation["kind"], "recommendation")
                self.assertEqual(recommendation["finding_ids"], ["FND-1"])
                self.assertEqual(recommendation["adoption_state"], "approved")
                self.assertEqual(before.current_snapshot, after.current_snapshot)
            finally:
                facade.close()

    def test_rec2_existing_confirmation_and_human_decision_adopt_recommendation(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                proposed = facade.submit_action(self.proposal_input())
                proposal_id = proposed["data"]["state_delta_proposal_id"]
                recommendation_id = proposed["data"]["recommendation_candidate"]["id"]
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": proposal_id},
                    "actor_id": "HUMAN-REC",
                })
                self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-REC",
                })
                self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
                request = confirmed["decision_request"]
                unit = request["decision_units"][0]
                self.assertEqual(unit["required_decision_kind"], "research_adoption")
                self.assertEqual(unit["required_choice"], "approve")
                self.assertEqual(unit["subject"], {"kind": "recommendation", "id": recommendation_id})
                resolved = facade.resolve_human_decision({
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-REC",
                })
                self.assertEqual(resolved["status"], "RESOLVED")
                state = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1")
                recommendation = state.latest_object("recommendation", recommendation_id)
                self.assertIsNotNone(recommendation)
                self.assertEqual(recommendation["adoption_state"], "approved")
                self.assertEqual(recommendation["finding_ids"], ["FND-1"])
                self.assertEqual(len(recommendation["decision_ids"]), 1)
            finally:
                facade.close()

    def test_rec3_rejects_missing_cross_project_and_candidate_findings(self):
        cases = (
            ("missing", "approved", "PRJ-1", ["FND-MISSING"]),
            ("cross-project", "approved", "PRJ-OTHER", ["FND-1"]),
            ("candidate", "candidate", "PRJ-1", ["FND-1"]),
        )
        for label, state, project_id, finding_ids in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                facade = self.make_facade(temp, finding_state=state, finding_project=project_id)
                try:
                    before = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                    with self.assertRaises(ConversationRuntimeError) as raised:
                        facade.submit_action(self.proposal_input(finding_ids=finding_ids))
                    self.assertEqual(raised.exception.code, "RECOMMENDATION-SUPPORT-001")
                    after = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                    self.assertEqual(before, after)
                finally:
                    facade.close()

    def test_rec3_stale_proposal_application_leaves_state_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                stale = facade.submit_action(self.proposal_input(statement="First recommendation."))
                fresh = facade.submit_action(self.proposal_input(statement="Second recommendation."))
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": fresh["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-REC",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-REC",
                })
                request = confirmed["decision_request"]
                facade.resolve_human_decision({
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-REC",
                })
                head = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                stale_pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": stale["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-REC",
                })
                failed = facade.submit_confirmation({
                    "confirmation_request_id": stale_pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-REC",
                })
                self.assertEqual(failed["status"], "FAILED")
                after = facade._application.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                self.assertEqual(after, head)
            finally:
                facade.close()

    def test_payload_rejects_authority_fields_and_unbounded_finding_refs(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp)
            try:
                with self.assertRaises(LocalApplicationError):
                    facade.submit_action(self.proposal_input(decision_ids=["DEC-X"]))
                with self.assertRaises(LocalApplicationError) as raised:
                    facade.submit_action(self.proposal_input(finding_ids=[f"FND-{i}" for i in range(257)]))
                self.assertEqual(raised.exception.code, "APPLICATION-PAYLOAD-001")
            finally:
                facade.close()

    def test_ablation_disabling_finding_authority_guard_allows_invalid_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self.make_facade(temp, finding_state="candidate")
            try:
                with patch(
                    "plugins.local_application.recommendation_facade._current_authoritative_finding",
                    return_value=True,
                ):
                    result = facade.submit_action(self.proposal_input())
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["data"]["recommendation_candidate"]["finding_ids"], ["FND-1"])
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
