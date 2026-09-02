from __future__ import annotations

import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, make_virtual_app
from tests.runtime.test_survey_response_dataset import intake, raw_response


class SurveyAnalysisOriginNeutralTests(SurveyVirtualRunnerTestBase):
    def test_synthetic_and_real_datasets_use_the_same_frequency_formula(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)

            synthetic = facade.capture_survey_response_dataset(intake(
                questionnaire,
                responses=[raw_response("SYN-1", "SYN-P-1", answers={"role": "contributor"})],
            ))
            real = facade.capture_survey_response_dataset(intake(
                questionnaire,
                origin="real",
                responses=[raw_response(
                    "REAL-1", "REAL-P-1", namespace="real:test", answers={"role": "contributor"}
                )],
            ))

            def aggregate(dataset):
                spec = facade.capture_survey_analysis_spec({
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["content_digest"],
                    "analysis_items": [{
                        "analysis_type": "frequency",
                        "question_id": "Q1",
                        "denominator_rule": "valid_responses",
                    }],
                })
                result = facade.run_survey_aggregation({
                    "analysis_spec_id": spec["analysis_spec_id"],
                    "analysis_spec_digest": spec["content_digest"],
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["content_digest"],
                })
                return facade.show_survey_aggregate_result(result["aggregate_result_id"])

            synthetic_result = aggregate(synthetic)
            real_result = aggregate(real)
            self.assertEqual(
                synthetic_result["result_items"][0]["categories"],
                real_result["result_items"][0]["categories"],
            )
            self.assertEqual(
                synthetic_result["result_items"][0]["denominator_counts"],
                real_result["result_items"][0]["denominator_counts"],
            )
            self.assertEqual(
                synthetic_result["aggregate_result"]["epistemic_status"],
                "SYNTHETIC_TEST_ONLY",
            )
            self.assertEqual(real_result["aggregate_result"]["epistemic_status"], "EMPIRICAL")
            app.close()


if __name__ == "__main__":
    unittest.main()
