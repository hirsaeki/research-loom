from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    make_virtual_app,
)
from tests.runtime.test_survey_response_dataset import intake, raw_response


class SurveyResponseReviewRound3Tests(SurveyVirtualRunnerTestBase):
    def test_bounded_page_detects_entry_loss_outside_requested_page(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                records = [
                    raw_response(
                        f"SYN-CORRUPT-{index}",
                        f"SYN-CORRUPT-P-{index}",
                        role="Contributor",
                        answers={"role": "contributor"},
                    )
                    for index in range(5)
                ]
                captured = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=records)
                )

                path = Path(temp) / "survey-response-registry.sqlite3"
                connection = sqlite3.connect(path)
                try:
                    connection.execute(
                        """
                        DELETE FROM survey_response_dataset_entries
                        WHERE project_id=? AND dataset_id=? AND entry_index=?
                        """,
                        ("PRJ-1", captured["dataset_id"], 4),
                    )
                    connection.commit()
                finally:
                    connection.close()

                with self.assertRaises(LocalApplicationError) as caught:
                    facade.show_survey_response_dataset(
                        captured["dataset_id"], limit=1, offset=0
                    )
                self.assertEqual(
                    caught.exception.code,
                    "SURVEY-RESPONSE-STORE-INTEGRITY-001",
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
