from __future__ import annotations

import tempfile
import unittest

from plugins.local_application import (
    LocalApplicationError,
    LocalApplicationFacade,
    LocalResearchApplication,
)
from runtime_fixtures import project, rq, seed_state
from test_survey_production import (
    NullResolver,
    design_payload,
    instrument_payload,
    make_app,
    profile_provider,
)


class SurveyReviewFixTests(unittest.TestCase):
    def test_design_must_match_exact_current_snapshot_before_instrument_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                design = facade.capture_survey_design(design_payload())
                bound_snapshot = design["captured_against"]

                proposed = facade.submit_action({
                    "action_type": "research_question.propose",
                    "payload": {"text": "Advance the current Research State HEAD."},
                    "actor_id": "HUMAN-SURVEY-REVIEW",
                })
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {
                        "state_delta_proposal_id": proposed["data"][
                            "state_delta_proposal_id"
                        ]
                    },
                    "actor_id": "HUMAN-SURVEY-REVIEW",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_request"][
                        "confirmation_request_id"
                    ],
                    "actor_id": "HUMAN-SURVEY-REVIEW",
                })
                request = confirmed["decision_request"]
                resolved = facade.resolve_human_decision({
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-SURVEY-REVIEW",
                })
                self.assertEqual(resolved["status"], "RESOLVED")

                state = facade._state()
                self.assertEqual(
                    bound_snapshot["lineage_ref"], str(state.active_lineage_ref)
                )
                self.assertNotEqual(
                    bound_snapshot["snapshot_ref"], str(state.current_snapshot["id"])
                )

                with self.assertRaises(LocalApplicationError) as stale:
                    facade.capture_survey_instrument(instrument_payload())
                self.assertEqual(
                    stale.exception.code,
                    "APPLICATION-SURVEY-DESIGN-BINDING-001",
                )
            finally:
                app.close()

    def test_revised_research_question_remains_authoritative_for_survey_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            seed = seed_state(
                objects=[project(), rq(state="revised")],
                snapshot_id="SNP-SURVEY-REVISED",
            )
            app = LocalResearchApplication(
                temp,
                resolver=NullResolver(),
                effective_profile_set_provider=profile_provider,
                seed_state=seed,
            )
            try:
                result = LocalApplicationFacade(app, "PRJ-1").capture_survey_design(
                    design_payload()
                )
                self.assertEqual(result["status"], "CAPTURED")
                self.assertEqual(result["rq_ids"], ["RQ-1"])
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
