from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade
from plugins.local_survey_store import canonical_document_digest
from plugins.survey_virtual_runner.llm_backend import DeterministicFakeVirtualRespondentBackend
from tests.runtime.survey_analysis_test_support import analysis_questionnaire
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, make_virtual_app
from tests.runtime.test_survey_llm_virtual_respondent import ANSWERS, PROFILES, llm_payload
from tests.runtime.test_survey_production import instrument_payload, state_signature


class Issue222SurveyVirtualPretestComparisonTests(SurveyVirtualRunnerTestBase):
    @staticmethod
    def _defective_questionnaire() -> dict:
        questionnaire = analysis_questionnaire()
        branch = questionnaire["questions"][4]["branching"][0]
        assert branch["target_question_id"] == "Q5"
        branch["value"] = "contributor"
        questionnaire["content_digest"] = canonical_document_digest(
            questionnaire, "content_digest"
        )
        return questionnaire

    @staticmethod
    def _fixed_revision(defective: dict) -> dict:
        fixed = deepcopy(defective)
        fixed["version"] = "1.1.0"
        fixed["supersedes_version"] = defective["version"]
        fixed["material_revision"] = True
        fixed["material_revision_decision_id"] = "DEC-QNR-MAT-2"
        fixed["questions"][4]["branching"][0]["value"] = "manager"
        fixed["revision_changes"] = [
            {"question_id": "Q5", "change_kind": "branching", "material": True}
        ]
        fixed["content_digest"] = canonical_document_digest(fixed, "content_digest")
        return fixed

    @staticmethod
    def _run(facade: LocalApplicationFacade, questionnaire: dict, *, model_id: str = "gpt-test") -> dict:
        payload = llm_payload(questionnaire)
        payload["minimum_valid_response_count"] = 1
        payload["llm_backend"]["model_id"] = model_id
        facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(
            ANSWERS, backend_id="openai_responses"
        )
        return facade.submit_action(
            {
                "action_type": "virtual_runner.survey.execute",
                "payload": payload,
                "actor_id": "HUMAN-ISSUE-222",
            }
        )

    def test_revision_comparison_isolates_branch_defect_and_fix(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                defective = self._defective_questionnaire()
                rev_a = self._capture(facade, questionnaire=defective)
                before = state_signature(app)
                run_a = self._run(facade, rev_a)
                self.assertEqual(run_a["response_dataset"]["rejected_count"], 3)
                self.assertIsNotNone(run_a["aggregate_result"])

                fixed = self._fixed_revision(defective)
                captured = facade.capture_survey_instrument(
                    instrument_payload(questionnaire=fixed)
                )
                rev_b = facade.show_survey_instrument(
                    captured["instrument_id"], captured["version"]
                )["instrument"]["questionnaire"]
                run_b = self._run(facade, rev_b)
                self.assertEqual(run_b["response_dataset"]["rejected_count"], 0)
                self.assertIsNotNone(run_b["aggregate_result"])

                compared = facade.compare_survey_virtual_pretests(
                    run_a["run_id"], run_b["run_id"]
                )
                self.assertEqual(compared["object_type"], "survey_virtual_pretest_comparison")
                self.assertEqual(compared["comparability"]["status"], "COMPARABLE")
                self.assertNotEqual(
                    compared["instrument_refs"]["a"]["content_digest"],
                    compared["instrument_refs"]["b"]["content_digest"],
                )
                self.assertEqual(
                    compared["comparison"]["validation"]["branch_rule_violations"],
                    {"before": 3, "after": 0},
                )
                self.assertEqual(
                    compared["comparison"]["generation_summary"]["before"]["generated"], 4
                )
                self.assertEqual(
                    compared["comparison"]["generation_summary"]["after"]["generated"], 4
                )
                self.assertTrue(compared["comparison"]["aggregate_changes"])
                changed_profiles = {
                    row["profile_id"]
                    for row in compared["comparison"]["per_profile_changes"]
                    if row["changed"]
                }
                self.assertEqual(
                    changed_profiles,
                    {profile["profile_id"] for profile in PROFILES},
                )
                self.assertEqual(
                    compared["synthetic_firewall"]["epistemic_status"],
                    "SYNTHETIC_TEST_ONLY",
                )
                self.assertFalse(compared["research_state_mutation_performed"])
                self.assertFalse(compared["validity_judgment_performed"])
                self.assertFalse(compared["instrument_revision_performed"])
                self.assertEqual(state_signature(app), before)

                routed = facade.submit_action(
                    {
                        "action_type": "survey_virtual_pretest.compare",
                        "payload": {
                            "run_a_id": run_a["run_id"],
                            "run_b_id": run_b["run_id"],
                        },
                        "actor_id": "HUMAN-ISSUE-222",
                    }
                )
                self.assertEqual(routed["status"], "SUCCEEDED")
                self.assertEqual(
                    routed["data"]["comparability"]["status"], "COMPARABLE"
                )
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()

    def test_material_backend_pin_mismatch_is_non_comparable(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(
                    facade, questionnaire=analysis_questionnaire()
                )
                before = state_signature(app)
                run_a = self._run(facade, questionnaire, model_id="gpt-test-a")
                run_b = self._run(facade, questionnaire, model_id="gpt-test-b")

                compared = facade.compare_survey_virtual_pretests(
                    run_a["run_id"], run_b["run_id"]
                )
                self.assertEqual(compared["comparability"]["status"], "NON_COMPARABLE")
                self.assertIn(
                    "backend",
                    {item["pin"] for item in compared["comparability"]["mismatches"]},
                )
                self.assertNotIn("comparison", compared)
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
