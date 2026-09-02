from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

from core.conversation.validation import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.survey_virtual_runner.llm_backend import DeterministicFakeVirtualRespondentBackend
from tests.runtime.survey_analysis_test_support import analysis_questionnaire
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, make_virtual_app
from tests.runtime.test_survey_llm_virtual_respondent import ANSWERS, llm_payload


class SurveyLlmLineageReviewFixTests(SurveyVirtualRunnerTestBase):
    def test_adapter_computes_missing_parsed_payload_digest_for_explicit_lineage(self):
        class MissingParsedDigestBackend(DeterministicFakeVirtualRespondentBackend):
            def generate_response(self, **kwargs):
                result = dict(super().generate_response(**kwargs))
                result.pop("parsed_answer_payload_digest", None)
                return result

        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                facade._virtual_respondent_backend = lambda _payload: MissingParsedDigestBackend(
                    ANSWERS, backend_id="openai_responses"
                )
                run = facade.submit_action({
                    "action_type": "virtual_runner.survey.execute",
                    "payload": llm_payload(questionnaire),
                    "actor_id": "HUMAN-LLM-VR",
                })
                shown = facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(shown["profile_response_binding"], "explicit")
                first = shown["respondents"][0]["response"]
                stored = facade.show_survey_response(
                    first["response_id"], identity_namespace=first["identity_namespace"]
                )
                self.assertEqual(
                    stored["response"]["source_provenance"]["producer"]["parsed_answer_payload_digest"],
                    canonical_digest({"answers": ANSWERS["SYN-PROFILE-MANAGER-A"]}),
                )
            finally:
                app.close()

    def test_joined_pretest_rejects_non_virtual_producer_on_canonical_response(self):
        from plugins.survey_virtual_runner import output_builder
        original = output_builder.build_output

        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(
                    ANSWERS, backend_id="openai_responses"
                )

                def tampered_output(request, extension, **kwargs):
                    records = deepcopy(list(kwargs["records"]))
                    records[0]["producer_provenance"]["producer_type"] = "real_import"
                    kwargs["records"] = records
                    return original(request, extension, **kwargs)

                with patch("plugins.survey_virtual_runner.llm_adapter.build_output", tampered_output):
                    run = facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": llm_payload(questionnaire),
                        "actor_id": "HUMAN-LLM-VR",
                    })
                with self.assertRaises(LocalApplicationError) as mismatch:
                    facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(mismatch.exception.code, "APPLICATION-SURVEY-VIRTUAL-PRETEST-001")
            finally:
                app.close()

    def test_joined_pretest_rejects_non_virtual_producer_on_rejected_raw_input(self):
        from plugins.survey_virtual_runner import output_builder
        original = output_builder.build_output

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

                def tampered_output(request, extension, **kwargs):
                    records = deepcopy(list(kwargs["records"]))
                    target = next(
                        record for record in records
                        if record["producer_provenance"]["respondent_profile_ref"]["profile_id"]
                        == "SYN-PROFILE-MANAGER-B"
                    )
                    target["producer_provenance"]["producer_type"] = "real_import"
                    kwargs["records"] = records
                    return original(request, extension, **kwargs)

                with patch("plugins.survey_virtual_runner.llm_adapter.build_output", tampered_output):
                    run = facade.submit_action({
                        "action_type": "virtual_runner.survey.execute",
                        "payload": llm_payload(questionnaire),
                        "actor_id": "HUMAN-LLM-VR",
                    })
                with self.assertRaises(LocalApplicationError) as mismatch:
                    facade.show_survey_virtual_pretest(run["run_id"])
                self.assertEqual(mismatch.exception.code, "APPLICATION-SURVEY-VIRTUAL-PRETEST-001")
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
