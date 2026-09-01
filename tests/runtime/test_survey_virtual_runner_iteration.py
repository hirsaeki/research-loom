from tests.runtime.survey_virtual_runner_test_support import *  # noqa: F403


class SurveyVirtualRunnerProductionTestsB(SurveyVirtualRunnerTestBase):
    def test_instrument_revision_requires_new_run_and_old_run_remains_pinned(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                q1 = self._capture(facade)
                first = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": execution_payload(
                        scenario="STRESS",
                        instrument_version=q1["version"],
                        instrument_digest=q1["content_digest"],
                    ),
                })
                first_show = deepcopy(facade.show_run(first["run_id"]))

                q2 = extended_questionnaire()
                q2["version"] = "1.1.0"
                q2["supersedes_version"] = "1.0.0"
                q2["approval_decision_id"] = "DEC-QNR-1"
                q2["material_revision"] = True
                q2["material_revision_decision_id"] = "DEC-QNR-MAT-2"
                q2["questions"][1]["scale"]["maximum"] = 7
                q2["revision_changes"] = [{
                    "question_id": "Q2",
                    "change_kind": "scale",
                    "material": True,
                }]
                q2["content_digest"] = canonical_document_digest(q2, "content_digest")
                captured = facade.capture_survey_instrument(
                    instrument_payload(questionnaire=q2)
                )
                q2 = facade.show_survey_instrument(
                    captured["instrument_id"],
                    captured["version"],
                )["instrument"]["questionnaire"]

                second = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": execution_payload(
                        scenario="STRESS",
                        instrument_version=q2["version"],
                        instrument_digest=q2["content_digest"],
                    ),
                })
                second_show = facade.show_run(second["run_id"])
                self.assertNotEqual(first["run_id"], second["run_id"])
                self.assertNotEqual(
                    first_show["virtual_runner"]["input_pins"]["instrument"]["content_digest"],
                    second_show["virtual_runner"]["input_pins"]["instrument"]["content_digest"],
                )
                self.assertEqual(facade.show_run(first["run_id"]), first_show)
            finally:
                app.close()

    def test_protocol_authority_and_prior_run_digest_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                q1 = self._capture(facade)

                spoofed = execution_payload(
                    scenario="STANDARD",
                    instrument_version=q1["version"],
                    instrument_digest=q1["content_digest"],
                )
                spoofed["protocol"]["content_digest"] = "sha256:" + "6" * 64
                with self.assertRaises(LocalApplicationError) as spoof_error:
                    facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": spoofed,
                    })
                self.assertEqual(spoof_error.exception.code, "VR-METHOD-BINDING-001")

                missing_decision = execution_payload(
                    scenario="STANDARD",
                    instrument_version=q1["version"],
                    instrument_digest=q1["content_digest"],
                )
                missing_decision["protocol"]["material_revision"] = True
                with self.assertRaises(LocalApplicationError) as error:
                    facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": missing_decision,
                    })
                self.assertEqual(error.exception.code, "APPLICATION-VIRTUAL-PAYLOAD-001")

                material = execution_payload(
                    scenario="STANDARD",
                    instrument_version=q1["version"],
                    instrument_digest=q1["content_digest"],
                )
                material["protocol"]["material_revision"] = True
                material["protocol"]["material_revision_decision_id"] = "DEC-PROTOCOL-MAT-1"
                material_run = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": material,
                })
                self.assertEqual(material_run["status"], "SUCCEEDED")

                first = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": execution_payload(
                        scenario="STANDARD",
                        instrument_version=q1["version"],
                        instrument_digest=q1["content_digest"],
                    ),
                })
                self.assertEqual(first["status"], "SUCCEEDED")

                gap_mismatch = execution_payload(
                    scenario="STRESS",
                    instrument_version=q1["version"],
                    instrument_digest=q1["content_digest"],
                    prior=(first["run_id"],),
                )
                gap_mismatch["evidence_gap_refs"][0]["gap_id"] = "GAP-OTHER"
                gap_result = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": gap_mismatch,
                })
                self.assertEqual(gap_result["status"], "ERROR")
                self.assertIn(
                    "VR-FREEZE-STALE-001",
                    {
                        item["code"]
                        for item in gap_result["execution_result"].get("issues", [])
                    },
                )

                q2 = extended_questionnaire()
                q2["version"] = "1.1.0"
                q2["approval_decision_id"] = "DEC-QNR-1"
                q2["supersedes_version"] = "1.0.0"
                q2["questions"][3]["text"] = "Notes for revised Instrument?"
                q2["revision_changes"] = [{
                    "question_id": "Q4",
                    "change_kind": "wording",
                    "material": False,
                }]
                q2["content_digest"] = canonical_document_digest(q2, "content_digest")
                captured_q2 = facade.capture_survey_instrument(
                    instrument_payload(questionnaire=q2)
                )
                q2 = facade.show_survey_instrument(
                    captured_q2["instrument_id"],
                    captured_q2["version"],
                )["instrument"]["questionnaire"]
                mismatch = execution_payload(
                    scenario="STRESS",
                    instrument_version=q2["version"],
                    instrument_digest=q2["content_digest"],
                    prior=(first["run_id"],),
                )
                result = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": mismatch,
                })
                self.assertEqual(result["status"], "ERROR")
                issue_codes = {
                    item["code"]
                    for item in result["execution_result"].get("issues", [])
                }
                self.assertTrue(
                    "CONTEXT_INVALID" in issue_codes
                    or any(code.startswith("VR-") for code in issue_codes)
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
