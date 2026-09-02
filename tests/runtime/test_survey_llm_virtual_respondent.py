from __future__ import annotations

import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.survey_virtual_runner.llm_backend import DeterministicFakeVirtualRespondentBackend
from tests.runtime.survey_analysis_test_support import analysis_questionnaire
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    execution_payload,
    make_virtual_app,
)
from tests.runtime.test_survey_production import NullResolver, profile_provider, state_signature


PROFILES = [
    {"profile_id": "SYN-PROFILE-MANAGER-A", "attributes": {"role_level": "manager", "business_area": "sales"}, "knowledge_scope": ["own work"]},
    {"profile_id": "SYN-PROFILE-MANAGER-B", "attributes": {"role_level": "manager", "business_area": "engineering"}, "knowledge_scope": ["own work"]},
    {"profile_id": "SYN-PROFILE-CONTRIB-A", "attributes": {"role_level": "contributor", "business_area": "sales"}, "knowledge_scope": ["own work"]},
    {"profile_id": "SYN-PROFILE-MANAGER-C", "attributes": {"role_level": "manager", "business_area": "backoffice"}, "knowledge_scope": ["own work"]},
]

ANSWERS = {
    "SYN-PROFILE-MANAGER-A": {
        "role": "manager", "usefulness": 4, "count": 3, "notes": "synthetic manager note",
        "approval": "yes", "actions": ["assist", "recommend"], "segment": "east", "readiness": "ready",
    },
    "SYN-PROFILE-MANAGER-B": {
        "role": "manager", "usefulness": {"state": "missing"}, "count": 2, "notes": "synthetic engineering note",
        "approval": "no", "actions": ["assist", "execute"], "segment": "west", "readiness": {"state": "unknown"},
    },
    "SYN-PROFILE-CONTRIB-A": {
        "role": "contributor", "notes": "synthetic contributor note",
        "actions": ["recommend"], "segment": "east", "readiness": {"state": "not_applicable"},
    },
    "SYN-PROFILE-MANAGER-C": {
        "role": "manager", "usefulness": 2, "count": 1, "notes": "synthetic backoffice note",
        "approval": "yes", "actions": ["assist", "recommend", "execute"], "segment": "west", "readiness": {"state": "prefer_not_to_answer"},
    },
}


def llm_payload(questionnaire):
    payload = execution_payload(
        scenario="STANDARD",
        instrument_version=questionnaire["version"],
        instrument_digest=questionnaire["content_digest"],
    )
    payload.update({
        "run_spec_id": "RUNSPEC-LLM-STANDARD",
        "population_size": len(PROFILES),
        "generator_backend": "llm",
        "respondent_profiles": PROFILES,
        "llm_backend": {
            "backend_id": "openai_responses",
            "model_id": "gpt-test",
            "credential_env": "OPENAI_API_KEY",
            "temperature": 0.2,
            "max_output_tokens": 500,
            "max_transport_retries": 1,
            "max_repair_attempts": 1,
        },
        "analysis_items": [
            {"item_id": "FREQ-ROLE", "analysis_type": "frequency", "question_id": "Q1", "denominator_rule": "valid_responses"},
            {"item_id": "MULTI-ACTIONS", "analysis_type": "frequency", "question_id": "Q6", "denominator_rule": "valid_responses"},
            {"item_id": "MISS-READY", "analysis_type": "missingness", "question_id": "Q8"},
            {"item_id": "SCALE-USEFUL", "analysis_type": "scale_summary", "question_id": "Q2"},
            {"item_id": "XTAB", "analysis_type": "cross_tab", "row_question_id": "Q1", "column_question_id": "Q7"},
            {"item_id": "TEXT", "analysis_type": "free_text_listing", "question_id": "Q4", "max_rows": 20},
        ],
        "minimum_valid_response_count": 3,
    })
    return payload


class SurveyLlmVirtualRespondentProductionTests(SurveyVirtualRunnerTestBase):
    def test_fake_backend_flows_through_canonical_dataset_shared_aggregation_and_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                before = state_signature(app)
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(
                    ANSWERS, backend_id="openai_responses"
                )
                run = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": llm_payload(questionnaire),
                    "actor_id": "HUMAN-LLM-VR",
                })
                self.assertEqual(run["status"], "SUCCEEDED")
                data = run
                self.assertEqual(data["execution_mode"], "virtual")
                self.assertEqual(data["generator_backend"], "llm")
                self.assertEqual(data["response_dataset"]["accepted_count"], 4)
                self.assertEqual(data["response_dataset"]["rejected_count"], 0)
                self.assertEqual(data["response_dataset"]["response_origin"], "synthetic")
                self.assertEqual(data["response_dataset"]["epistemic_status"], "SYNTHETIC_TEST_ONLY")
                self.assertIsNotNone(data["aggregate_result"])
                shown_aggregate = facade.show_survey_aggregate_result(data["aggregate_result"]["aggregate_result_id"], limit=100)
                self.assertEqual(shown_aggregate["aggregate_result"]["epistemic_status"], "SYNTHETIC_TEST_ONLY")
                self.assertEqual({item["analysis_type"] for item in shown_aggregate["result_items"]}, {
                    "frequency", "missingness", "scale_summary", "cross_tab", "free_text_listing",
                })
                self.assertEqual(state_signature(app), before)

                shown = facade.show_run(data["run_id"])["virtual_runner"]
                self.assertEqual(shown["generator_backend"], "llm")
                self.assertEqual(shown["generation_summary"], {"requested": 4, "generated": 4, "valid": 4, "rejected": 0, "failed": 0})
                self.assertEqual(shown["respondent_plan"]["interaction_model"], "full_instrument_single_call")
                self.assertEqual(shown["input_pins"]["instrument"]["content_digest"], questionnaire["content_digest"])
                self.assertEqual(shown["input_pins"]["backend"]["backend_id"], "openai_responses")
                self.assertEqual(shown["input_pins"]["prompt_template"]["template_id"], "survey-virtual-respondent")
                self.assertEqual(shown["response_dataset_ref"]["dataset_id"], data["response_dataset"]["dataset_id"])
                self.assertEqual(shown["aggregate_result_ref"]["aggregate_result_id"], data["aggregate_result"]["aggregate_result_id"])
                run_id = data["run_id"]
                dataset_id = data["response_dataset"]["dataset_id"]
                aggregate_id = data["aggregate_result"]["aggregate_result_id"]
            finally:
                app.close()

            reopened = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                shown = reopened_facade.show_run(run_id)["virtual_runner"]
                self.assertEqual(shown["generation_summary"]["valid"], 4)
                self.assertEqual(shown["response_dataset_ref"]["dataset_id"], dataset_id)
                self.assertEqual(shown["aggregate_result_ref"]["aggregate_result_id"], aggregate_id)
                dataset = reopened_facade.show_survey_response_dataset(dataset_id, limit=100)
                self.assertEqual(dataset["dataset"]["epistemic_status"], "SYNTHETIC_TEST_ONLY")
                aggregate = reopened_facade.show_survey_aggregate_result(aggregate_id, limit=100)
                self.assertEqual(aggregate["aggregate_result"]["warnings"][0]["code"], "SURVEY_AGGREGATE_SYNTHETIC_NOT_POPULATION_ESTIMATE")
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_generation_failure_is_partial_and_minimum_rule_prevents_aggregate(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                partial_answers = dict(ANSWERS)
                partial_answers.pop("SYN-PROFILE-MANAGER-C")
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(
                    partial_answers, backend_id="openai_responses"
                )
                payload = llm_payload(questionnaire)
                payload["minimum_valid_response_count"] = 4
                run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": payload, "actor_id": "HUMAN-LLM-VR"})
                self.assertEqual(run["status"], "ERROR")
                data = run
                self.assertEqual(data["response_dataset"]["accepted_count"], 3)
                self.assertIsNone(data["aggregate_result"])
                shown = facade.show_run(data["run_id"])["virtual_runner"]
                self.assertEqual(shown["completion_status"], "partial")
                self.assertEqual(shown["generation_summary"], {"requested": 4, "generated": 3, "valid": 3, "rejected": 0, "failed": 1})
                failure = next(item for item in shown["generation_attempts"] if item["status"] == "failed")
                self.assertEqual(failure["failure_code"], "PROVIDER_ERROR")
            finally:
                app.close()

    def test_semantic_invalidity_reaches_canonical_validation_without_backend_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                invalid_answers = dict(ANSWERS)
                invalid_answers["SYN-PROFILE-MANAGER-B"] = {
                    **ANSWERS["SYN-PROFILE-MANAGER-B"],
                    "role": "not-a-stable-choice",
                }
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(
                    invalid_answers, backend_id="openai_responses"
                )
                payload = llm_payload(questionnaire)
                payload["minimum_valid_response_count"] = 3
                run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": payload, "actor_id": "HUMAN-LLM-VR"})
                self.assertEqual(run["status"], "SUCCEEDED")
                self.assertEqual(run["response_dataset"]["accepted_count"], 3)
                self.assertEqual(run["response_dataset"]["rejected_count"], 1)
                shown = facade.show_run(run["run_id"])["virtual_runner"]
                self.assertEqual(shown["generation_summary"], {"requested": 4, "generated": 4, "valid": 3, "rejected": 1, "failed": 0})
                self.assertTrue(any(item["code"] == "SURVEY_RESPONSE_INVALID_CHOICE" for item in shown["validation_failures"]))
                self.assertTrue(all(item["status"] == "generated" for item in shown["generation_attempts"]))
                dataset = facade.show_survey_response_dataset(run["response_dataset"]["dataset_id"], limit=100)
                self.assertEqual(dataset["dataset"]["rejected_count"], 1)
                self.assertTrue(any(
                    issue["code"] == "SURVEY_RESPONSE_INVALID_CHOICE"
                    for item in dataset["entries"] if item["kind"] == "rejected_response"
                    for issue in item["issues"]
                ))
            finally:
                app.close()

    def test_profile_and_backend_boundaries_fail_closed_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                payload = llm_payload(questionnaire)
                payload["respondent_profiles"] = [{"profile_id": "SYN-PROFILE-BAD", "attributes": {"email": "person@example.com"}}]
                payload["population_size"] = 1
                with self.assertRaises(LocalApplicationError) as profile:
                    facade.run_survey_virtual(payload)
                self.assertEqual(profile.exception.code, "PROFILE_INVALID")

                payload = llm_payload(questionnaire)
                payload["respondent_profiles"] = [{
                    "profile_id": "SYN-PROFILE-BAD",
                    "attributes": {"contact": {"email": "person@example.com"}},
                }]
                payload["population_size"] = 1
                with self.assertRaises(LocalApplicationError) as nested_profile:
                    facade.run_survey_virtual(payload)
                self.assertEqual(nested_profile.exception.code, "PROFILE_INVALID")

                for field, value in (
                    ("scenario_notes", "contact person@example.com"),
                    ("knowledge_scope", ["employee id EMP-12345"]),
                ):
                    payload = llm_payload(questionnaire)
                    profile_payload = {"profile_id": "SYN-PROFILE-BAD", "attributes": {}}
                    profile_payload[field] = value
                    payload["respondent_profiles"] = [profile_payload]
                    payload["population_size"] = 1
                    with self.assertRaises(LocalApplicationError) as free_text_profile:
                        facade.run_survey_virtual(payload)
                    self.assertEqual(free_text_profile.exception.code, "PROFILE_INVALID")

                payload = llm_payload(questionnaire)
                payload["llm_backend"]["api_key"] = "must-not-be-accepted"
                with self.assertRaises(LocalApplicationError):
                    facade.run_survey_virtual(payload)

                for field, value in (
                    ("credential_env", "AWS_SECRET_ACCESS_KEY"),
                    ("endpoint", "https://example.invalid/v1/responses"),
                ):
                    payload = llm_payload(questionnaire)
                    payload["llm_backend"][field] = value
                    with self.assertRaises(LocalApplicationError) as backend_config:
                        facade.run_survey_virtual(payload)
                    self.assertEqual(backend_config.exception.code, "BACKEND_UNAVAILABLE")

                payload = llm_payload(questionnaire)
                payload["generator_backend"] = []
                with self.assertRaises(LocalApplicationError) as backend_type:
                    facade.run_survey_virtual(payload)
                self.assertEqual(backend_type.exception.code, "APPLICATION-VIRTUAL-PAYLOAD-001")

                payload = llm_payload(questionnaire)
                payload["respondent_profiles"] = [
                    {"profile_id": f"SYN-PROFILE-{index:02d}", "attributes": {"segment": index}}
                    for index in range(9)
                ]
                payload["population_size"] = 9
                with self.assertRaises(LocalApplicationError) as profile_limit:
                    facade.run_survey_virtual(payload)
                self.assertEqual(profile_limit.exception.code, "PROFILE_INVALID")

                for field, value in (
                    ("timeout_seconds", 31),
                    ("max_transport_retries", 2),
                    ("max_repair_attempts", 2),
                ):
                    payload = llm_payload(questionnaire)
                    payload["llm_backend"][field] = value
                    with self.assertRaises(LocalApplicationError) as bounded:
                        facade.run_survey_virtual(payload)
                    self.assertEqual(bounded.exception.code, "APPLICATION-VIRTUAL-PAYLOAD-001")
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
