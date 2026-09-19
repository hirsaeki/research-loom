from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from tests.runtime.survey_analysis_test_support import analysis_questionnaire
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, make_virtual_app
from tests.runtime.test_survey_production import state_signature
from tests.runtime.test_survey_response_dataset import intake, raw_response


def real_response(response_id: str, participant_id: str, answers: dict) -> dict:
    return raw_response(
        response_id,
        participant_id,
        namespace="real:issue221",
        answers=answers,
    )


class Issue221RealSurveyIntakeTests(SurveyVirtualRunnerTestBase):
    def _fixture(self, temp: str):
        root = Path(temp)
        app = make_virtual_app(root)
        facade = LocalApplicationFacade(app, "PRJ-1", workspace_root=root)
        questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
        responses = [
            real_response(
                "REAL-A",
                "P-A",
                {
                    "role": "manager",
                    "usefulness": 4,
                    "notes": "manager note",
                    "approval": "yes",
                    "actions": ["assist", "recommend"],
                    "segment": "east",
                    "readiness": "ready",
                },
            ),
            real_response(
                "REAL-B",
                "P-B",
                {
                    "role": "contributor",
                    "notes": "contributor note",
                    "actions": ["recommend", "execute"],
                    "segment": "west",
                    "readiness": {"state": "not_applicable"},
                },
            ),
            raw_response(
                "SYN-WRONG",
                "SYN-P-WRONG",
                namespace="synthetic:issue221",
                answers={
                    "role": "manager",
                    "usefulness": 3,
                    "notes": "must remain rejected",
                    "approval": "no",
                    "actions": ["assist"],
                    "segment": "east",
                    "readiness": "ready",
                },
            ),
        ]
        source = root / "real-responses.json"
        source.write_text(json.dumps({"responses": responses}), encoding="utf-8")
        payload = {
            "file": source.name,
            "instrument_id": questionnaire["questionnaire_id"],
            "instrument_version": questionnaire["version"],
            "instrument_digest": questionnaire["content_digest"],
            "analysis_items": [
                {"item_id": "APPROVAL-MISS", "analysis_type": "missingness", "question_id": "Q5"},
                {"item_id": "ACTIONS", "analysis_type": "frequency", "question_id": "Q6", "denominator_rule": "valid_responses"},
                {"item_id": "USEFULNESS", "analysis_type": "scale_summary", "question_id": "Q2"},
                {"item_id": "NOTES", "analysis_type": "free_text_listing", "question_id": "Q4"},
            ],
        }
        return app, facade, questionnaire, payload

    def test_real_file_flows_through_canonical_dataset_shared_aggregation_and_joined_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, questionnaire, payload = self._fixture(temp)
            try:
                before = state_signature(app)
                captured = facade.capture_real_survey_intake(payload)
                self.assertEqual(captured["status"], "CAPTURED")
                self.assertEqual(captured["response_origin"], "real")
                self.assertEqual(captured["epistemic_status"], "EMPIRICAL")
                self.assertEqual(captured["instrument_ref"]["content_digest"], questionnaire["content_digest"])
                self.assertEqual(captured["accepted_count"], 2)
                self.assertEqual(captured["rejected_count"], 1)
                self.assertIn(
                    "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                    captured["validation_summary"]["issue_code_counts"],
                )
                self.assertEqual(
                    captured["candidate_interpretation"],
                    {
                        "status": "candidate_research_material",
                        "aggregate_result_id": captured["aggregate_result_id"],
                        "authoritative_finding_created": False,
                    },
                )
                self.assertFalse(captured["research_state_mutation_performed"])

                shown = facade.show_real_survey_intake(captured["dataset_id"], limit=100)
                self.assertEqual(shown["intake_source"]["intake_file"], "real-responses.json")
                self.assertTrue(shown["intake_source"]["intake_file_digest"].startswith("sha256:"))
                self.assertEqual(shown["accepted_count"], 2)
                self.assertEqual(shown["rejected_count"], 1)
                self.assertEqual(shown["aggregate_result"]["population"]["accepted_response_count"], 2)
                self.assertEqual(shown["aggregate_result"]["exclusions"]["rejected_count"], 1)

                accepted = {
                    row["canonical_response"]["response_id"]: row
                    for row in shown["responses"]
                    if row["kind"] == "accepted_response"
                }
                contributor = accepted["REAL-B"]["canonical_response"]
                approval = next(item for item in contributor["answers"] if item["response_key"] == "approval")
                usefulness = next(item for item in contributor["answers"] if item["response_key"] == "usefulness")
                actions = next(item for item in contributor["answers"] if item["response_key"] == "actions")
                notes = next(item for item in contributor["answers"] if item["response_key"] == "notes")
                self.assertEqual(approval["state"], "not_asked")
                self.assertEqual(usefulness["state"], "not_asked")
                self.assertEqual(actions["value"], ["recommend", "execute"])
                self.assertEqual(notes["value"], "contributor note")

                rejected = next(row for row in shown["responses"] if row["kind"] == "rejected_raw_input")
                self.assertEqual(rejected["raw_input"]["response_id"], "SYN-WRONG")
                self.assertTrue(any(issue["code"] == "SURVEY_RESPONSE_ORIGIN_MISMATCH" for issue in rejected["issues"]))

                aggregate_items = {item["item_id"]: item for item in shown["aggregate_items"]}
                self.assertEqual(aggregate_items["APPROVAL-MISS"]["counts"]["not_asked"], 1)
                self.assertEqual(aggregate_items["ACTIONS"]["selection_count_total"], 4)
                self.assertEqual(aggregate_items["USEFULNESS"]["count"], 1)
                self.assertEqual(aggregate_items["NOTES"]["non_empty_count"], 2)
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()

    def test_repeated_intake_verifies_and_reuses_first_dataset_history(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, payload = self._fixture(temp)
            try:
                first = facade.capture_real_survey_intake(payload)
                first_dataset = deepcopy(
                    facade.show_survey_response_dataset(first["dataset_id"])["dataset"]
                )
                second = facade.capture_real_survey_intake(payload)
                second_dataset = facade.show_survey_response_dataset(second["dataset_id"])["dataset"]
                self.assertEqual(second["status"], "ALREADY_CAPTURED")
                self.assertEqual(second["dataset_id"], first["dataset_id"])
                self.assertEqual(second["content_digest"], first["content_digest"])
                self.assertEqual(second["aggregate_result_id"], first["aggregate_result_id"])
                self.assertEqual(second_dataset, first_dataset)
            finally:
                app.close()

    def test_instrument_and_origin_guards_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, questionnaire, payload = self._fixture(temp)
            try:
                stale = deepcopy(payload)
                stale["instrument_digest"] = "sha256:" + "0" * 64
                with self.assertRaises(LocalApplicationError) as instrument_error:
                    facade.capture_real_survey_intake(stale)
                self.assertEqual(
                    instrument_error.exception.code,
                    "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001",
                )

                synthetic = facade.capture_survey_response_dataset(
                    intake(
                        questionnaire,
                        responses=[raw_response("SYN-ONLY", "SYN-P-ONLY")],
                    )
                )
                with self.assertRaises(LocalApplicationError) as origin_error:
                    facade.show_real_survey_intake(synthetic["dataset_id"])
                self.assertEqual(origin_error.exception.code, "SURVEY_RESPONSE_ORIGIN_MISMATCH")

                traversal = deepcopy(payload)
                traversal["file"] = "../real-responses.json"
                with self.assertRaises(LocalApplicationError) as file_error:
                    facade.capture_real_survey_intake(traversal)
                self.assertEqual(
                    file_error.exception.code,
                    "APPLICATION-SURVEY-REAL-INTAKE-FILE-001",
                )
            finally:
                app.close()

    def test_public_action_surface_uses_same_real_intake_and_joined_show(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, payload = self._fixture(temp)
            try:
                before = state_signature(app)
                captured = facade.submit_action(
                    {
                        "action_type": "survey_real_intake.capture",
                        "payload": payload,
                        "actor_id": "HUMAN-SURVEY",
                    }
                )
                self.assertEqual(captured["status"], "SUCCEEDED")
                dataset_id = captured["data"]["dataset_id"]
                aggregate_result_id = captured["data"]["aggregate_result_id"]

                shown = facade.submit_action(
                    {
                        "action_type": "survey_real_intake.show",
                        "payload": {
                            "dataset_id": dataset_id,
                            "aggregate_result_id": aggregate_result_id,
                            "limit": 100,
                            "offset": 0,
                        },
                        "actor_id": "HUMAN-SURVEY",
                    }
                )
                self.assertEqual(shown["status"], "SUCCEEDED")
                self.assertEqual(shown["data"]["dataset"]["dataset_id"], dataset_id)
                self.assertEqual(shown["data"]["aggregate_result"]["aggregate_result_id"], aggregate_result_id)
                self.assertEqual(shown["data"]["response_origin"], "real")
                self.assertEqual(shown["data"]["epistemic_status"], "EMPIRICAL")
                self.assertFalse(shown["data"]["research_state_mutation_performed"])
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
