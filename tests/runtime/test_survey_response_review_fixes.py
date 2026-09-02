from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade
from plugins.local_survey_response_store import LocalSurveyResponseStore
from tests.runtime.test_survey_response_dataset import intake, raw_response
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    make_virtual_app,
)


class SurveyResponseReviewFixTests(SurveyVirtualRunnerTestBase):
    def test_malformed_response_id_reserves_duplicate_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                malformed = {
                    "response_id": "SYN-DUP-MALFORMED",
                    "participant_id": "SYN-P-MALFORMED",
                    "identity_namespace": "synthetic:test",
                    "answers": [],
                }
                later_valid = raw_response(
                    "SYN-DUP-MALFORMED",
                    "SYN-P-LATER",
                    role="Contributor",
                    answers={"role": "contributor"},
                )
                captured = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=[malformed, later_valid])
                )
                self.assertEqual(captured["accepted_count"], 0)
                self.assertEqual(captured["rejected_count"], 2)
                self.assertEqual(
                    captured["validation_summary"]["issue_code_counts"].get(
                        "SURVEY_RESPONSE_DUPLICATE_RECORD"
                    ),
                    1,
                )
            finally:
                app.close()

    def test_noncanonical_raw_number_is_preserved_as_rejected_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                noncanonical = raw_response(
                    "SYN-NAN",
                    "SYN-P-NAN",
                    answers={"role": "manager", "usefulness": math.nan},
                )
                captured = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=[noncanonical])
                )
                self.assertEqual(captured["accepted_count"], 0)
                self.assertEqual(captured["rejected_count"], 1)
                self.assertIn(
                    "SURVEY_RESPONSE_MALFORMED",
                    captured["validation_summary"]["issue_code_counts"],
                )
                shown = facade.show_survey_response_dataset(captured["dataset_id"])
                entry = shown["entries"][0]
                self.assertEqual(entry["kind"], "rejected_raw_input")
                self.assertEqual(
                    entry["raw_input"]["answers"]["usefulness"],
                    {"$noncanonical_number": "NaN"},
                )
            finally:
                app.close()

    def test_dataset_show_uses_storage_page_without_full_dataset_decode(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                records = [
                    raw_response(
                        f"SYN-PAGE-{index}",
                        f"SYN-PART-{index}",
                        role="Contributor",
                        answers={"role": "contributor"},
                    )
                    for index in range(5)
                ]
                captured = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=records)
                )
                with patch.object(
                    LocalSurveyResponseStore,
                    "load_dataset",
                    side_effect=AssertionError("bounded show must not load the full Dataset"),
                ):
                    shown = facade.show_survey_response_dataset(
                        captured["dataset_id"], limit=1, offset=3
                    )
                self.assertEqual(shown["pagination"]["returned"], 1)
                self.assertEqual(shown["pagination"]["total"], 5)
                self.assertTrue(shown["pagination"]["has_more"])
            finally:
                app.close()

    def test_first_store_initialization_is_idempotent_under_concurrency(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "survey-response-registry.sqlite3"

            def initialize(_index: int) -> None:
                connection = LocalSurveyResponseStore(path)._write()
                connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(initialize, range(2)))

            connection = LocalSurveyResponseStore(path)._read()
            self.assertIsNotNone(connection)
            assert connection is not None
            try:
                rows = connection.execute(
                    "SELECT schema_version FROM survey_response_store_meta"
                ).fetchall()
                self.assertEqual(len(rows), 1)
            finally:
                connection.close()

    def test_survey_response_action_preserves_audited_input_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                questionnaire = self._capture(facade)
                result = facade.submit_action(
                    {
                        "action_type": "survey_response_dataset.capture",
                        "payload": intake(
                            questionnaire,
                            responses=[raw_response("SYN-AUDIT", "SYN-P-AUDIT")],
                        ),
                        "actor_id": "HUMAN-AUDIT",
                        "conversation_id": "CONV-SURVEY-AUDIT",
                        "rationale": "Preserve this exact Survey intake audit context.",
                    }
                )
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["data"]["accepted_count"], 1)
                proposal = result["proposal"]
                self.assertEqual(proposal["conversation_id"], "CONV-SURVEY-AUDIT")
                self.assertEqual(
                    proposal["initiating_actor"],
                    {"actor_id": "HUMAN-AUDIT", "actor_type": "human"},
                )
                input_id = proposal["source"]["input_id"]
                stored = app.conversation_store._load_document(
                    "conversation_input", input_id
                )
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored["conversation_id"], "CONV-SURVEY-AUDIT")
                self.assertEqual(stored["actor"]["actor_id"], "HUMAN-AUDIT")
                self.assertEqual(
                    stored["text"],
                    "Preserve this exact Survey intake audit context.",
                )
                self.assertIn("action_receipt", result)
            finally:
                app.close()
