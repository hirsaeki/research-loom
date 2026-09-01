import json

from tests.runtime.survey_virtual_runner_test_support import *  # noqa: F403


class SurveyVirtualRunnerProductionTestsA(SurveyVirtualRunnerTestBase):
    def test_standard_then_stress_is_synthetic_exact_pinned_and_candidate_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade)
                before = state_signature(app)
                standard = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": execution_payload(scenario="STANDARD", instrument_version=questionnaire["version"], instrument_digest=questionnaire["content_digest"]), "actor_id": "HUMAN-VR"})
                self.assertEqual(standard["status"], "SUCCEEDED")
                self.assertEqual(standard["execution_mode"], "virtual")
                self.assertFalse(standard["research_state_mutation_performed"])
                standard_show = facade.show_run(standard["run_id"])
                vr = standard_show["virtual_runner"]
                self.assertEqual(vr["scenario_class"], "STANDARD")
                self.assertEqual(vr["evidence_status"], "SYNTHETIC_TEST_ONLY")
                self.assertEqual(vr["completion_status"], "complete")
                self.assertTrue(vr["synthetic_outputs"])
                self.assertTrue(vr["execution_trace"])
                self.assertEqual(vr["unresolved_ambiguities"], [])
                self.assertEqual(vr["input_pins"]["instrument"]["content_digest"], questionnaire["content_digest"])
                self.assertEqual(vr["readiness_assessment"]["status"], "CANDIDATE_BLOCKED")
                self.assertEqual(vr["validation_failures"], [])
                self.assertTrue(all(item["provenance"].get("evidence_status") == "SYNTHETIC_TEST_ONLY" for item in standard_show["artifacts"]))
                response_meta = next(item for item in app.execution_store.artifacts_for(standard["run_id"]) if item.role == "survey_virtual.synthetic_responses")
                response_batch = json.loads(app.execution_store.load_artifact(response_meta.artifact_id).content.decode("utf-8"))
                self.assertTrue(response_batch["identity_namespace"].startswith("synthetic:"))
                self.assertTrue(all(item["participant_id"].startswith("SYN-PARTICIPANT-") and item["synthetic"] is True and item["epistemic_mode"] == "virtual" for item in response_batch["responses"]))
                proposal = standard["execution_result"]["state_delta_proposal"]
                self.assertTrue(proposal["candidate_only"])
                self.assertEqual({action["payload"]["object"]["kind"] for action in proposal["proposed_actions"]}, {"next_action"})
                self.assertEqual(state_signature(app), before)

                stress = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": execution_payload(scenario="STRESS", instrument_version=questionnaire["version"], instrument_digest=questionnaire["content_digest"], prior=(standard["run_id"],)), "actor_id": "HUMAN-VR"})
                self.assertEqual(stress["status"], "SUCCEEDED")
                stress_show = facade.show_run(stress["run_id"])
                vr = stress_show["virtual_runner"]
                codes = {item["code"] for item in vr["validation_failures"]}
                self.assertTrue({"SURVEY_RESPONSE_REQUIRED_MISSING", "SURVEY_RESPONSE_INVALID_CHOICE", "SURVEY_RESPONSE_OUT_OF_RANGE", "SURVEY_RESPONSE_BRANCH_VIOLATION", "SURVEY_RESPONSE_DUPLICATE_RECORD", "SURVEY_RESPONSE_MALFORMED"}.issubset(codes))
                self.assertTrue(any(item["kind"] == "partial_or_dropout" for item in vr["preservation_events"]))
                self.assertTrue(any(item["kind"] == "optional_missing" for item in vr["preservation_events"]))
                self.assertTrue(any(item["kind"] == "unknown" for item in vr["preservation_events"]))
                self.assertTrue(any("not_applicable" in item for item in vr["warnings"]))
                self.assertTrue(any("prefer_not_to_answer" in item for item in vr["warnings"]))
                self.assertTrue(all(item["disposition"] == "resolved" for item in vr["defects"]))
                self.assertEqual(vr["readiness_assessment"]["status"], "CANDIDATE_READY")
                self.assertFalse(vr["real_execution_started"])
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()

            reopened = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                reopened_show = reopened_facade.show_run(stress["run_id"])
                self.assertEqual(reopened_show["virtual_runner"]["input_pins"]["instrument"]["content_digest"], questionnaire["content_digest"])
                self.assertEqual(reopened_show["virtual_runner"]["readiness_assessment"]["status"], "CANDIDATE_READY")
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()
