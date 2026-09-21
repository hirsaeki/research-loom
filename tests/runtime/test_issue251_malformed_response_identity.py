from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from plugins.local_application import LocalApplicationError
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase
from tests.runtime import test_issue251_real_survey_batches as batches
from tests.runtime.test_survey_production import state_signature


class Issue251MalformedResponseIdentityTests(SurveyVirtualRunnerTestBase):
    _fixture = batches.Issue251RealSurveyBatchTests._fixture

    def test_changed_existing_identity_cannot_hide_as_structurally_rejected_input(self):
        for change in ("missing_answers", "invalid_answers", "missing_participant", "extra_field"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                app, facade, _, payload = self._fixture(temp)
                try:
                    first = facade.capture_real_survey_intake(payload)
                    original = facade.show_survey_response("REAL-A")
                    before = state_signature(app)
                    source = root / payload["file"]
                    document = json.loads(source.read_text(encoding="utf-8"))
                    new = deepcopy(document["responses"][0])
                    new.update(response_id="REAL-C", participant_id="P-C")
                    changed = document["responses"][0]
                    if change == "missing_answers":
                        changed.pop("answers")
                    elif change == "invalid_answers":
                        changed["answers"] = "not an answers object"
                    elif change == "missing_participant":
                        changed.pop("participant_id")
                    else:
                        changed["unexpected_field"] = True
                    # A valid new answer preceding the conflict must not leak.
                    document["responses"].insert(0, new)
                    source.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.capture_real_survey_intake(payload)
                    self.assertEqual(error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                    self.assertEqual(facade.show_survey_response("REAL-A"), original)
                    self.assertIsNone(facade._survey_response_store().load_response("PRJ-1", "REAL-C"))
                    self.assertEqual(facade.show_real_survey_intake(first["dataset_id"])["accepted_count"], 2)
                    self.assertEqual(state_signature(app), before)
                finally:
                    app.close()

    def test_new_malformed_identity_stays_visible_without_blocking_valid_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                facade.capture_real_survey_intake(payload)
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                malformed = deepcopy(document["responses"][0])
                malformed.update(response_id="NEW-MALFORMED", participant_id="P-NEW")
                malformed.pop("answers")
                document["responses"].append(malformed)
                source.write_text(json.dumps(document), encoding="utf-8")
                result = facade.capture_real_survey_intake(payload)
                self.assertEqual(result["accepted_count"], 2)
                self.assertEqual(result["rejected_count"], 2)
                shown = facade.show_real_survey_intake(result["dataset_id"], limit=100)
                self.assertIn(malformed, [entry["raw_input"] for entry in shown["responses"]])
                self.assertEqual(facade.capture_real_survey_intake(payload)["status"], "ALREADY_CAPTURED")
            finally:
                app.close()

    def test_malformed_duplicate_within_batch_remains_a_visible_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                facade.capture_real_survey_intake(payload)
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                malformed = deepcopy(document["responses"][0])
                malformed.pop("answers")
                document["responses"].append(malformed)
                source.write_text(json.dumps(document), encoding="utf-8")
                result = facade.capture_real_survey_intake(payload)
                self.assertEqual(result["accepted_count"], 2)
                self.assertEqual(result["rejected_count"], 2)
                self.assertIn("SURVEY_RESPONSE_DUPLICATE_RECORD", result["validation_summary"]["issue_code_counts"])
                self.assertEqual(facade.capture_real_survey_intake(payload)["status"], "ALREADY_CAPTURED")
            finally:
                app.close()
