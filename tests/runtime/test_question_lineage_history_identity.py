from __future__ import annotations

import unittest

from core.runtime import TransitionAction, TransitionKind
from core.runtime.transition_models import CommitReceipt
from runtime_fixtures import decision, make_request, project, rq, seed_state, service


class QuestionLineageHistoryIdentityTests(unittest.TestCase):
    def test_lineage_identity_may_outlive_current_source_membership(self) -> None:
        source_question = rq(state="approved")
        derived_question = {
            "schema_version": "0.1.0",
            "id": "RQ-2",
            "kind": "research_question",
            "revision": 0,
            "project_id": "PRJ-1",
            "text": "Derived question",
            "adoption_state": "approved",
            "question_lineage_id": "RQ-1",
            "derived_from_question_revisions": [{"id": "RQ-1", "revision": 0}],
        }
        plan = decision("DEC-FORK", "lineage_plan", "apply", "lineage_plan", "PLAN-1")
        base = seed_state(objects=[project(), source_question, derived_question], decisions=(plan,))
        action = TransitionAction(
            TransitionKind.APPLY_LINEAGE_PLAN,
            {
                "plan_ref": "PLAN-1",
                "target_lineage_id": "LIN-CHILD",
                "lineage_kind": "exploratory_fork",
                "baseline_snapshot_ref": base.current_snapshot["id"],
                "baseline_snapshot_digest": base.current_snapshot["content_digest"],
                "treatments": [
                    {"object_kind": "project", "source_ref": "PRJ-1", "treatment": "PRESERVE"},
                    {"object_kind": "research_question", "source_ref": "RQ-1", "treatment": "INVALIDATE"},
                    {"object_kind": "research_question", "source_ref": "RQ-2", "treatment": "PRESERVE"},
                ],
            },
            decision_refs=("DEC-FORK",),
        )
        repo, transition = service(base)
        receipt = transition.apply(make_request(base, [action]))
        self.assertIsInstance(receipt, CommitReceipt)
        child = repo.load_state_view("PRJ-1", "LIN-CHILD")
        effective_ids = {(item.get("kind"), item.get("id")) for item in child.effective_objects()}
        self.assertNotIn(("research_question", "RQ-1"), effective_ids)
        self.assertIsNotNone(child.exact_object("research_question", "RQ-1", 0))
        self.assertEqual(
            child.latest_object("research_question", "RQ-2")["question_lineage_id"],
            "RQ-1",
        )


if __name__ == "__main__":
    unittest.main()
