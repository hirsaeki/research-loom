from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

from core.conversation.validation import canonical_digest

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

    def test_joined_pretest_inspection_preserves_explicit_profile_response_lineage(self):
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
                shown = facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(shown["profile_response_binding"], "explicit")
                self.assertEqual(shown["synthetic_firewall"], {
                    "response_origin": "synthetic",
                    "epistemic_status": "SYNTHETIC_TEST_ONLY",
                    "population_estimate": False,
                    "empirical_evidence": False,
                    "validity_certification": False,
                })
                self.assertEqual(len(shown["respondents"]), len(PROFILES))
                by_profile = {item["profile"]["profile_id"]: item for item in shown["respondents"]}
                for profile in PROFILES:
                    row = by_profile[profile["profile_id"]]
                    self.assertEqual(row["profile"]["profile_digest"], canonical_digest(profile))
                    self.assertEqual(row["generation_status"], "generated")
                    self.assertEqual(row["response"]["validation_status"], "accepted")
                manager_b = by_profile["SYN-PROFILE-MANAGER-B"]
                readiness = next(item for item in manager_b["response"]["answers"] if item["response_key"] == "readiness")
                self.assertEqual(readiness["response_state"], "unknown")
                notes = next(item for item in manager_b["response"]["answers"] if item["response_key"] == "notes")
                self.assertEqual(notes["stable_value"], "synthetic engineering note")
                self.assertEqual(shown["dataset_ref"]["id"], run["response_dataset"]["dataset_id"])
                self.assertEqual(shown["aggregate_result_ref"]["id"], run["aggregate_result"]["aggregate_result_id"])
                self.assertEqual(
                    {item["analysis_type"] for item in shown["aggregate_inspection"]["result_items"]},
                    {"frequency", "missingness", "scale_summary", "cross_tab", "free_text_listing"},
                )
                routed = facade.submit_action({
                    "action_type": "survey_virtual_pretest.show",
                    "payload": {"run_id": run["run_id"]},
                    "actor_id": "HUMAN-LLM-VR",
                })
                self.assertEqual(routed["data"]["profile_response_binding"], "explicit")
                self.assertEqual(state_signature(app), before)
                run_id = run["run_id"]
            finally:
                app.close()

            reopened = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                shown = reopened_facade.show_survey_virtual_pretest(run_id)
                self.assertEqual(shown["profile_response_binding"], "explicit")
                self.assertEqual(
                    {row["profile"]["profile_id"] for row in shown["respondents"]},
                    {profile["profile_id"] for profile in PROFILES},
                )
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_joined_pretest_partial_failure_uses_explicit_binding_not_response_order(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                profiles = [
                    {"profile_id": "SYN-PROFILE-001", "attributes": {"slot": "A"}, "knowledge_scope": ["own work"]},
                    {"profile_id": "SYN-PROFILE-002", "attributes": {"slot": "B"}, "knowledge_scope": ["own work"]},
                    {"profile_id": "SYN-PROFILE-003", "attributes": {"slot": "C"}, "knowledge_scope": ["own work"]},
                ]
                answers = {
                    "SYN-PROFILE-001": ANSWERS["SYN-PROFILE-MANAGER-A"],
                    "SYN-PROFILE-003": ANSWERS["SYN-PROFILE-MANAGER-C"],
                }
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(answers, backend_id="openai_responses")
                payload = llm_payload(questionnaire)
                payload["respondent_profiles"] = profiles
                payload["population_size"] = 3
                payload["minimum_valid_response_count"] = 2
                run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": payload, "actor_id": "HUMAN-LLM-VR"})
                shown = facade.show_survey_virtual_pretest(run["run_id"])
                rows = {item["profile"]["profile_id"]: item for item in shown["respondents"]}
                self.assertEqual(rows["SYN-PROFILE-001"]["response"]["response_id"], "SYN-RESP-0001")
                self.assertEqual(rows["SYN-PROFILE-002"]["generation_status"], "failed")
                self.assertIsNone(rows["SYN-PROFILE-002"]["response"])
                self.assertEqual(rows["SYN-PROFILE-003"]["response"]["response_id"], "SYN-RESP-0002")
            finally:
                app.close()

    def test_joined_pretest_rejected_response_keeps_profile_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                invalid_answers = dict(ANSWERS)
                invalid_answers["SYN-PROFILE-MANAGER-B"] = {**ANSWERS["SYN-PROFILE-MANAGER-B"], "role": "not-a-stable-choice"}
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(invalid_answers, backend_id="openai_responses")
                run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": llm_payload(questionnaire), "actor_id": "HUMAN-LLM-VR"})
                shown = facade.show_survey_virtual_pretest(run["run_id"])
                row = next(item for item in shown["respondents"] if item["profile"]["profile_id"] == "SYN-PROFILE-MANAGER-B")
                self.assertEqual(row["generation_status"], "generated")
                self.assertEqual(row["response"]["validation_status"], "rejected")
                self.assertTrue(any(item["code"] == "SURVEY_RESPONSE_INVALID_CHOICE" for item in row["response"]["validation_issues"]))
                stored = facade.show_survey_response(row["response"]["response_id"], identity_namespace=row["response"]["identity_namespace"])
                self.assertEqual(stored["response"]["source_provenance"]["producer"]["respondent_profile_ref"]["profile_id"], "SYN-PROFILE-MANAGER-B")
                self.assertEqual(stored["raw_input"]["provenance"]["respondent_profile_ref"]["profile_id"], "SYN-PROFILE-MANAGER-B")
            finally:
                app.close()

    def test_legacy_llm_run_does_not_retrofit_profile_binding_from_ordinals(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(ANSWERS, backend_id="openai_responses")
                from plugins.survey_virtual_runner import output_builder
                original = output_builder.build_output

                def legacy_output(request, extension, **kwargs):
                    records = deepcopy(list(kwargs["records"]))
                    for record in records:
                        record.pop("producer_provenance", None)
                    attempts = deepcopy(list(kwargs["generation_attempts"]))
                    for attempt in attempts:
                        attempt.pop("generation_attempt_id", None)
                        attempt.pop("respondent_profile_digest", None)
                        attempt.pop("response_ref", None)
                    kwargs["records"] = records
                    kwargs["generation_attempts"] = attempts
                    return original(request, extension, **kwargs)

                with patch("plugins.survey_virtual_runner.llm_adapter.build_output", legacy_output):
                    run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": llm_payload(questionnaire), "actor_id": "HUMAN-LLM-VR"})
                shown = facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(shown["profile_response_binding"], "unavailable")
                self.assertEqual(len(shown["unbound_responses"]), 4)
                self.assertTrue(all(item["response"] is None for item in shown["respondents"]))
            finally:
                app.close()

    def test_joined_pretest_fails_closed_on_profile_lineage_tampering(self):
        from plugins.survey_virtual_runner import output_builder
        original = output_builder.build_output
        cases = (
            ("unknown_profile", lambda records: records[0]["producer_provenance"]["respondent_profile_ref"].update({"profile_id": "SYN-PROFILE-999"})),
            ("digest_mismatch", lambda records: records[0]["producer_provenance"]["respondent_profile_ref"].update({"profile_digest": "sha256:" + "0" * 64})),
            ("duplicate_binding", lambda records: records[1]["producer_provenance"]["respondent_profile_ref"].update(deepcopy(records[0]["producer_provenance"]["respondent_profile_ref"]))),
        )
        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                app = make_virtual_app(temp)
                facade = LocalApplicationFacade(app, "PRJ-1")
                try:
                    questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                    facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(ANSWERS, backend_id="openai_responses")

                    def tampered_output(request, extension, **kwargs):
                        records = deepcopy(list(kwargs["records"]))
                        mutate(records)
                        kwargs["records"] = records
                        return original(request, extension, **kwargs)

                    with patch("plugins.survey_virtual_runner.llm_adapter.build_output", tampered_output):
                        run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": llm_payload(questionnaire), "actor_id": "HUMAN-LLM-VR"})
                    with self.assertRaises(LocalApplicationError) as mismatch:
                        facade.show_survey_virtual_pretest(run["run_id"])
                    self.assertEqual(mismatch.exception.code, "APPLICATION-SURVEY-VIRTUAL-PRETEST-001")
                finally:
                    app.close()

    def test_joined_pretest_fails_closed_on_dataset_and_aggregate_binding_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(ANSWERS, backend_id="openai_responses")
                run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": llm_payload(questionnaire), "actor_id": "HUMAN-LLM-VR"})

                response_store = facade._survey_response_store()

                class ResponseStoreProxy:
                    def load_dataset(self, project_id, dataset_id):
                        value = deepcopy(response_store.load_dataset(project_id, dataset_id))
                        value["source_run_ids"] = ["RUN-NOT-THE-SOURCE"]
                        return value

                    def __getattr__(self, name):
                        return getattr(response_store, name)

                with patch.object(facade, "_survey_response_store", return_value=ResponseStoreProxy()):
                    with self.assertRaises(LocalApplicationError) as mismatch:
                        facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(mismatch.exception.code, "APPLICATION-SURVEY-VIRTUAL-PRETEST-001")

                analysis_store = facade._survey_analysis_store()

                class AnalysisStoreProxy:
                    def find_results_by_dataset(self, project_id, dataset_id):
                        values = deepcopy(analysis_store.find_results_by_dataset(project_id, dataset_id))
                        values[0]["dataset_ref"] = {"id": "SRD-WRONG", "content_digest": "sha256:" + "0" * 64}
                        return values

                    def __getattr__(self, name):
                        return getattr(analysis_store, name)

                with patch.object(facade, "_survey_analysis_store", return_value=AnalysisStoreProxy()):
                    with self.assertRaises(LocalApplicationError) as mismatch:
                        facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(mismatch.exception.code, "APPLICATION-SURVEY-VIRTUAL-PRETEST-001")
            finally:
                app.close()

    def test_joined_pretest_requires_exact_aggregate_when_dataset_has_multiple_results(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(ANSWERS, backend_id="openai_responses")
                run = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": llm_payload(questionnaire), "actor_id": "HUMAN-LLM-VR"})
                second_spec = facade.capture_survey_analysis_spec({
                    "dataset_id": run["response_dataset"]["dataset_id"],
                    "dataset_digest": run["response_dataset"]["content_digest"],
                    "analysis_items": [{"item_id": "MISS-ONLY", "analysis_type": "missingness", "question_id": "Q8"}],
                })
                second_result = facade.run_survey_aggregation({
                    "analysis_spec_id": second_spec["analysis_spec_id"],
                    "analysis_spec_digest": second_spec["content_digest"],
                    "dataset_id": run["response_dataset"]["dataset_id"],
                    "dataset_digest": run["response_dataset"]["content_digest"],
                })
                self.assertNotEqual(second_result["aggregate_result_id"], run["aggregate_result"]["aggregate_result_id"])
                with self.assertRaises(LocalApplicationError) as ambiguous:
                    facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(ambiguous.exception.code, "APPLICATION-SURVEY-VIRTUAL-PRETEST-001")
                shown = facade.show_survey_virtual_pretest(
                    run["run_id"], aggregate_result_id=run["aggregate_result"]["aggregate_result_id"]
                )
                self.assertEqual(shown["aggregate_result_ref"]["id"], run["aggregate_result"]["aggregate_result_id"])
            finally:
                app.close()

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
