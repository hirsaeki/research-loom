from tests.runtime.survey_virtual_runner_test_support import *  # noqa: F403


class SurveyVirtualRunnerProductionTestsA2(SurveyVirtualRunnerTestBase):
    def test_fail_closed_on_stale_instrument_and_synthetic_to_empirical_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                stale = execution_payload(scenario="STANDARD", instrument_version=questionnaire["version"], instrument_digest="sha256:" + "0" * 64)
                with self.assertRaises(LocalApplicationError) as error:
                    facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": stale})
                self.assertEqual(error.exception.code, "APPLICATION-VIRTUAL-PIN-001")
                promotion = execution_payload(scenario="STANDARD", instrument_version=questionnaire["version"], instrument_digest=questionnaire["content_digest"])
                promotion["epistemic_mode"] = "empirical"
                with self.assertRaises(LocalApplicationError) as forbidden:
                    facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": promotion})
                self.assertEqual(forbidden.exception.code, "APPLICATION-VIRTUAL-PAYLOAD-001")
                q = extended_questionnaire()
                record = {
                    "schema_version": "0.1.0", "object_type": "survey_response_record", "response_id": "REAL-R1",
                    "raw_data_ref_id": "REAL-DATA-1", "participant_id": "REAL-P1", "identity_namespace": "real:survey",
                    "epistemic_mode": "empirical", "synthetic": False, "response_status": "complete",
                    "eligibility_status": "eligible", "duplicate_disposition": "not_duplicate",
                    "verified_evidence_claimed": False, "dropout": False, "answers": [],
                }
                validation = SurveyResponseValidator().validate(q, [record], expected_epistemic_mode="virtual", expected_identity_namespace="synthetic:survey:test")
                codes = {item["code"] for item in validation["issues"]}
                self.assertIn("SURVEY_RESPONSE_EPISTEMIC_FIREWALL", codes)
                self.assertIn("SURVEY_RESPONSE_IDENTITY_FIREWALL", codes)
            finally:
                app.close()
