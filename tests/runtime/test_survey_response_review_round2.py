from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade
from plugins.local_survey_response_store import LocalSurveyResponseStore
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    make_virtual_app,
)
from tests.runtime.test_survey_response_dataset import intake, raw_response


class SurveyResponseReviewRound2Tests(SurveyVirtualRunnerTestBase):
    def test_malformed_duplicate_reservation_is_scoped_by_identity_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                malformed = {
                    "response_id": "SHARED-ID",
                    "participant_id": "SYN-P-MALFORMED",
                    "identity_namespace": "synthetic:source-a",
                    "answers": [],
                }
                valid_other_namespace = raw_response(
                    "SHARED-ID",
                    "SYN-P-VALID",
                    namespace="synthetic:source-b",
                    role="Contributor",
                    answers={"role": "contributor"},
                )
                captured = facade.capture_survey_response_dataset(
                    intake(
                        questionnaire,
                        responses=[malformed, valid_other_namespace],
                    )
                )
                self.assertEqual(captured["accepted_count"], 1)
                self.assertEqual(captured["rejected_count"], 1)
                self.assertNotIn(
                    "SURVEY_RESPONSE_DUPLICATE_RECORD",
                    captured["validation_summary"]["issue_code_counts"],
                )
                shown = facade.show_survey_response(
                    "SHARED-ID",
                    identity_namespace="synthetic:source-b",
                )
                self.assertEqual(
                    shown["response"]["identity_namespace"],
                    "synthetic:source-b",
                )
            finally:
                app.close()

    def test_lazy_action_registration_is_atomic_under_concurrent_first_use(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facades = [LocalApplicationFacade(app, "PRJ-1") for _ in range(8)]

                def discover(facade: LocalApplicationFacade):
                    return facade.list_actions()["actions"]

                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(discover, facades))

                expected = {
                    "survey_response.normalize",
                    "survey_response.capture",
                    "survey_response.show",
                    "survey_response_dataset.capture",
                    "survey_response_dataset.show",
                }
                for actions in results:
                    action_types = [str(item["action_type"]) for item in actions]
                    self.assertTrue(expected <= set(action_types))
                    for action_type in expected:
                        self.assertEqual(action_types.count(action_type), 1)
            finally:
                app.close()

    def test_bounded_dataset_page_uses_summary_total_without_full_count_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                records = [
                    raw_response(
                        f"SYN-PAGE2-{index}",
                        f"SYN-PART2-{index}",
                        role="Contributor",
                        answers={"role": "contributor"},
                    )
                    for index in range(5)
                ]
                captured = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=records)
                )

                queries: list[str] = []

                class TracedStore(LocalSurveyResponseStore):
                    def _read(self):
                        connection = super()._read()
                        if connection is not None:
                            connection.set_trace_callback(queries.append)
                        return connection

                store_path = Path(temp) / "survey-response-registry.sqlite3"
                page = TracedStore(store_path).load_dataset_entries(
                    "PRJ-1",
                    captured["dataset_id"],
                    limit=1,
                    offset=3,
                )
                self.assertIsNotNone(page)
                assert page is not None
                self.assertEqual(page["total"], 5)
                self.assertEqual(len(page["entries"]), 1)
                normalized_queries = [query.upper() for query in queries]
                self.assertFalse(any("COUNT(" in query for query in normalized_queries))
                self.assertFalse(any("SUM(" in query for query in normalized_queries))
                self.assertTrue(any("ENTRY_INDEX>=3" in query.replace(" ", "") for query in normalized_queries))
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
