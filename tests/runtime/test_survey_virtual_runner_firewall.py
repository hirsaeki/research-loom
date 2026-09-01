from plugins.survey_virtual_runner.generation import generate_records
from tests.runtime.survey_virtual_runner_test_support import *  # noqa: F403


class SurveyVirtualRunnerProductionTestsA2(SurveyVirtualRunnerTestBase):
    def test_fail_closed_on_stale_instrument_and_synthetic_to_empirical_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)

                stale = execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest="sha256:" + "0" * 64,
                )
                with self.assertRaises(LocalApplicationError) as error:
                    facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": stale,
                    })
                self.assertEqual(error.exception.code, "APPLICATION-VIRTUAL-PIN-001")

                promotion = execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                )
                promotion["epistemic_mode"] = "empirical"
                with self.assertRaises(LocalApplicationError) as forbidden:
                    facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": promotion,
                    })
                self.assertEqual(
                    forbidden.exception.code,
                    "APPLICATION-VIRTUAL-PAYLOAD-001",
                )

                malformed_synth = execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                )
                malformed_synth["synthetic_population"] = {
                    "scenario_dimensions": 1,
                }
                with self.assertRaises(LocalApplicationError) as malformed:
                    facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": malformed_synth,
                    })
                self.assertEqual(
                    malformed.exception.code,
                    "APPLICATION-VIRTUAL-PAYLOAD-001",
                )

                too_many_prior = execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                )
                too_many_prior["prior_virtual_run_ids"] = [
                    f"RUN-PRIOR-{index:02d}" for index in range(17)
                ]
                with self.assertRaises(LocalApplicationError) as bounded:
                    facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": too_many_prior,
                    })
                self.assertEqual(
                    bounded.exception.code,
                    "APPLICATION-VIRTUAL-PAYLOAD-001",
                )

                q = extended_questionnaire()
                record = {
                    "schema_version": "0.1.0",
                    "object_type": "survey_response_record",
                    "response_id": "REAL-R1",
                    "raw_data_ref_id": "REAL-DATA-1",
                    "participant_id": "REAL-P1",
                    "identity_namespace": "real:survey",
                    "epistemic_mode": "empirical",
                    "synthetic": False,
                    "response_status": "complete",
                    "eligibility_status": "eligible",
                    "duplicate_disposition": "not_duplicate",
                    "verified_evidence_claimed": False,
                    "dropout": False,
                    "answers": [],
                }
                validation = SurveyResponseValidator().validate(
                    q,
                    [record],
                    expected_epistemic_mode="virtual",
                    expected_identity_namespace="synthetic:survey:test",
                )
                codes = {item["code"] for item in validation["issues"]}
                self.assertIn("SURVEY_RESPONSE_EPISTEMIC_FIREWALL", codes)
                self.assertIn("SURVEY_RESPONSE_IDENTITY_FIREWALL", codes)
            finally:
                app.close()

    def test_structural_generator_handles_branch_chains_and_null_numeric_minimum(self):
        chained = extended_questionnaire()
        chained["questions"][1]["branching"][0]["value"] = "contributor"
        chained["questions"][2]["branching"] = [{
            "condition_question_id": "Q2",
            "operator": "equals",
            "value": 1,
            "action": "show",
            "target_question_id": "Q3",
        }]
        records, injected = generate_records(
            chained,
            scenario_class="STANDARD",
            population_size=1,
            identity_namespace="synthetic:survey:chain",
            stress_faults=(),
        )
        self.assertEqual(injected, ())
        keys = {item["response_key"] for item in records[0]["answers"]}
        self.assertNotIn("usefulness", keys)
        self.assertNotIn("count", keys)

        restoring = extended_questionnaire()
        restoring["questions"][1]["branching"][0]["value"] = "contributor"
        restoring["questions"][2]["branching"] = [{
            "condition_question_id": "Q2",
            "operator": "missing",
            "action": "show",
            "target_question_id": "Q3",
        }]
        records, _ = generate_records(
            restoring,
            scenario_class="STANDARD",
            population_size=1,
            identity_namespace="synthetic:survey:restore",
            stress_faults=(),
        )
        keys = {item["response_key"] for item in records[0]["answers"]}
        self.assertNotIn("usefulness", keys)
        self.assertIn("count", keys)

        numeric = extended_questionnaire()
        numeric["questions"][2]["numeric_constraints"] = {"minimum": None}
        records, _ = generate_records(
            numeric,
            scenario_class="STANDARD",
            population_size=1,
            identity_namespace="synthetic:survey:numeric",
            stress_faults=(),
        )
        count = next(
            item
            for item in records[0]["answers"]
            if item["response_key"] == "count"
        )
        self.assertEqual(count["value"], 0)
        validation = SurveyResponseValidator().validate(
            numeric,
            records,
            expected_epistemic_mode="virtual",
            expected_identity_namespace="synthetic:survey:numeric",
        )
        self.assertNotIn(
            "SURVEY_RESPONSE_OUT_OF_RANGE",
            {item["code"] for item in validation["issues"]},
        )