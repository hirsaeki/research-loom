from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade
from plugins.local_survey_response_store import LocalSurveyResponseStore
from tests.runtime.survey_analysis_test_support import analysis_questionnaire, analysis_responses, find_item
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, make_virtual_app
from tests.runtime.test_survey_response_dataset import intake, raw_response


class SurveyAnalysisReviewFixTests(SurveyVirtualRunnerTestBase):
    @staticmethod
    def _spec(facade, dataset, items):
        return facade.capture_survey_analysis_spec({
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["content_digest"],
            "analysis_items": items,
        })

    @staticmethod
    def _aggregate(facade, dataset, spec):
        return facade.run_survey_aggregation({
            "analysis_spec_id": spec["analysis_spec_id"],
            "analysis_spec_digest": spec["content_digest"],
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["content_digest"],
        })

    def test_aggregation_uses_batch_response_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                responses = analysis_responses() + [
                    raw_response(
                        "SYN-BAD-BATCH",
                        "SYN-P-BAD-BATCH",
                        answers={"role": "not-a-choice", "segment": "east"},
                    )
                ]
                dataset = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=responses)
                )
                spec = self._spec(
                    facade,
                    dataset,
                    [{"analysis_type": "frequency", "question_id": "Q1"}],
                )
                with patch.object(
                    LocalSurveyResponseStore,
                    "load_response",
                    side_effect=AssertionError("aggregation must batch-load Dataset responses"),
                ):
                    result = self._aggregate(facade, dataset, spec)
                shown = facade.show_survey_aggregate_result(result["aggregate_result_id"])
                self.assertEqual(
                    shown["aggregate_result"]["population"]["accepted_response_count"],
                    4,
                )
                self.assertEqual(shown["aggregate_result"]["exclusions"]["rejected_count"], 1)
            finally:
                app.close()

    def test_free_text_listing_keeps_only_max_rows_while_counting_all_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
                responses = [
                    raw_response(
                        f"SYN-TEXT-{index:03d}",
                        f"SYN-P-TEXT-{index:03d}",
                        answers={
                            "role": "manager",
                            "usefulness": 4,
                            "notes": f"note-{index:03d}",
                            "segment": "east",
                        },
                    )
                    for index in range(120)
                ]
                dataset = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=responses)
                )
                spec = self._spec(
                    facade,
                    dataset,
                    [{"analysis_type": "free_text_listing", "question_id": "Q4", "max_rows": 3}],
                )
                shown = facade.show_survey_aggregate_result(
                    self._aggregate(facade, dataset, spec)["aggregate_result_id"],
                    limit=100,
                )
                listing = find_item(shown, "free_text_listing", "Q4")
                self.assertEqual(listing["non_empty_count"], 120)
                self.assertEqual(listing["returned_count"], 3)
                self.assertTrue(listing["truncated"])
                self.assertEqual(
                    [row["response_id"] for row in listing["rows"]],
                    ["SYN-TEXT-000", "SYN-TEXT-001", "SYN-TEXT-002"],
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
