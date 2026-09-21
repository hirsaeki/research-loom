from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from plugins.local_survey_response_store import LocalSurveyResponseStore
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from tests.runtime import test_issue251_real_survey_batches as batches
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase
from tests.runtime.test_survey_production import NullResolver, profile_provider, state_signature


class Issue251MalformedResponseConflictTests(SurveyVirtualRunnerTestBase):
    _fixture = batches.Issue251RealSurveyBatchTests._fixture

    def test_malformed_existing_answer_conflicts_atomically_and_resumes_after_correction(self):
        for malformed in ("answers", "participant", "unknown_field"):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                app, facade, _, payload = self._fixture(temp)
                try:
                    before = state_signature(app)
                    first = facade.capture_real_survey_intake(payload)
                    first_result = facade.show_real_survey_intake(first["dataset_id"])
                    original = facade.show_survey_response("REAL-A")
                    batches.Issue251RealSurveyBatchTests._append_response(root, payload)
                    source = root / payload["file"]
                    corrected = source.read_bytes()
                    document = json.loads(corrected)
                    bad = document["responses"][0]
                    if malformed == "answers":
                        bad["answers"] = []
                    elif malformed == "participant":
                        bad.pop("participant_id")
                    else:
                        bad["unknown_field"] = True
                    # A new answer before the conflict must not be partially saved.
                    document["responses"].insert(0, document["responses"].pop())
                    source.write_text(json.dumps(document), encoding="utf-8")
                    rejected_dataset_id = batches.Issue251RealSurveyBatchTests._batch_id(root, payload)
                    with patch.object(facade, "capture_survey_analysis_spec", wraps=facade.capture_survey_analysis_spec) as analysis:
                        with self.assertRaises(LocalApplicationError) as error:
                            facade.capture_real_survey_intake(payload)
                    self.assertEqual(error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                    analysis.assert_not_called()
                    store = facade._survey_response_store()
                    self.assertIsNone(store.load_dataset("PRJ-1", rejected_dataset_id))
                    self.assertIsNone(store.load_response("PRJ-1", "REAL-C"))
                    self.assertEqual(facade.show_survey_response("REAL-A"), original)
                    self.assertEqual(facade.show_real_survey_intake(first["dataset_id"]), first_result)
                    self.assertEqual(state_signature(app), before)
                finally:
                    app.close()

                reopened = LocalResearchApplication(root, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
                try:
                    facade = LocalApplicationFacade(reopened, "PRJ-1", workspace_root=root)
                    with self.assertRaises(LocalApplicationError) as retry_error:
                        facade.capture_real_survey_intake(payload)
                    self.assertEqual(retry_error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                    source.write_bytes(corrected)
                    resumed = facade.capture_real_survey_intake(payload)
                    self.assertEqual(resumed["accepted_count"], 3)
                    self.assertEqual(facade.show_survey_response("REAL-A"), original)
                    self.assertEqual(state_signature(reopened), before)
                finally:
                    reopened.close()

    def test_new_malformed_and_unidentifiable_records_remain_visible_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                facade.capture_real_survey_intake(payload)
                original = facade.show_survey_response("REAL-A")
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                malformed = deepcopy(document["responses"][0])
                malformed.update(response_id="NEW-MALFORMED", answers=[])
                foreign_namespace = deepcopy(malformed)
                foreign_namespace.update(response_id="REAL-A", identity_namespace="real:other-provider")
                incomplete = [
                    {"response_id": "REAL-A", "answers": []},
                    {"identity_namespace": "real:issue221", "response_id": 42, "answers": []},
                    None,
                ]
                new_inputs = [malformed, foreign_namespace, *incomplete]
                document["responses"].extend(new_inputs)
                source.write_text(json.dumps(document), encoding="utf-8")
                captured = facade.capture_real_survey_intake(payload)
                self.assertEqual(captured["accepted_count"], 2)
                self.assertEqual(captured["rejected_count"], 1 + len(new_inputs))
                shown = facade.show_real_survey_intake(captured["dataset_id"], limit=100)
                rejected = [row["raw_input"] for row in shown["responses"] if row["kind"] == "rejected_raw_input"]
                for raw in new_inputs:
                    self.assertIn(raw, rejected)
                self.assertEqual(facade.show_survey_response("REAL-A"), original)
                replay = facade.capture_real_survey_intake(payload)
                self.assertEqual(replay["status"], "ALREADY_CAPTURED")
                self.assertEqual(replay["aggregate_result_id"], captured["aggregate_result_id"])
            finally:
                app.close()

    def test_malformed_later_duplicate_does_not_remove_the_valid_first_response(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                facade.capture_real_survey_intake(payload)
                original = facade.show_survey_response("REAL-A")
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                duplicate = deepcopy(document["responses"][0])
                duplicate["answers"] = []
                document["responses"].append(duplicate)
                source.write_text(json.dumps(document), encoding="utf-8")
                captured = facade.capture_real_survey_intake(payload)
                self.assertEqual(captured["accepted_count"], 2)
                self.assertEqual(captured["rejected_count"], 2)
                self.assertIn("SURVEY_RESPONSE_DUPLICATE_RECORD", captured["validation_summary"]["issue_code_counts"])
                shown = facade.show_real_survey_intake(captured["dataset_id"], limit=100)
                self.assertEqual(shown["aggregate_result"]["population"]["accepted_response_count"], 2)
                self.assertEqual(facade.show_survey_response("REAL-A"), original)
                self.assertEqual(facade.capture_real_survey_intake(payload)["status"], "ALREADY_CAPTURED")
            finally:
                app.close()

    def test_malformed_first_duplicate_cannot_suppress_an_existing_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                first = facade.capture_real_survey_intake(payload)
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                malformed = deepcopy(document["responses"][0])
                malformed["answers"] = []
                document["responses"].insert(0, malformed)
                source.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(LocalApplicationError) as error:
                    facade.capture_real_survey_intake(payload)
                self.assertEqual(error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                self.assertEqual(facade.show_real_survey_intake(first["dataset_id"])["accepted_count"], 2)
            finally:
                app.close()

    def test_interleaved_valid_capture_is_checked_inside_the_write_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                document = json.loads((root / payload["file"]).read_text(encoding="utf-8"))
                document["responses"][0]["answers"] = []
                malformed = {**payload, "file": "malformed-first.json"}
                (root / malformed["file"]).write_text(json.dumps(document), encoding="utf-8")
                original_capture = facade._capture
                interleaved = []

                def capture_after_valid_commit(state, operation):
                    # Commit another capture after the outer normalizer's empty
                    # read, before the Research State guard/write transaction.
                    with patch.object(facade, "_capture", original_capture):
                        interleaved.append(facade.capture_real_survey_intake(payload))
                    return original_capture(state, operation)

                with patch.object(facade, "_capture", capture_after_valid_commit):
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.capture_real_survey_intake(malformed)
                self.assertEqual(error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                self.assertEqual(len(interleaved), 1)
                self.assertEqual(interleaved[0]["accepted_count"], 2)
                rejected_id = batches.Issue251RealSurveyBatchTests._batch_id(root, malformed)
                self.assertIsNone(facade._survey_response_store().load_dataset("PRJ-1", rejected_id))
                self.assertEqual(facade.capture_real_survey_intake(payload)["status"], "ALREADY_CAPTURED")
            finally:
                app.close()

    def test_old_rejection_batch_replays_without_rewriting_later_valid_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                document = json.loads((root / payload["file"]).read_text(encoding="utf-8"))
                document["responses"][0]["answers"] = []
                malformed = {**payload, "file": "earlier-malformed.json"}
                (root / malformed["file"]).write_text(json.dumps(document), encoding="utf-8")
                earlier = facade.capture_real_survey_intake(malformed)
                earlier_result = facade.show_real_survey_intake(earlier["dataset_id"])
                self.assertEqual(earlier["accepted_count"], 1)
                later = facade.capture_real_survey_intake(payload)
                original = facade.show_survey_response("REAL-A")
                self.assertEqual(later["accepted_count"], 2)
                replay = facade.capture_real_survey_intake(malformed)
                self.assertEqual(replay["status"], "ALREADY_CAPTURED")
                self.assertEqual(replay["aggregate_result_id"], earlier["aggregate_result_id"])
                self.assertEqual(facade.show_real_survey_intake(earlier["dataset_id"]), earlier_result)
                self.assertEqual(facade.show_survey_response("REAL-A"), original)
            finally:
                app.close()

    def test_many_malformed_rejections_use_bounded_write_transaction_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                first = facade.capture_real_survey_intake(payload)
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                new_inputs = [
                    {"identity_namespace": "real:issue221", "response_id": f"NEW-{i}", "answers": []}
                    for i in range(801)
                ]
                document["responses"].extend(new_inputs + [new_inputs[-1]])
                source.write_text(json.dumps(document), encoding="utf-8")
                statements = []
                original_write = LocalSurveyResponseStore._write

                def traced_write(store):
                    con = original_write(store)
                    con.set_trace_callback(statements.append)
                    return con

                with patch.object(LocalSurveyResponseStore, "_write", traced_write):
                    captured = facade.capture_real_survey_intake(payload)
                queries = [q for q in statements if q.startswith("SELECT response_id FROM survey_responses")]
                self.assertEqual(len(queries), 3)
                self.assertFalse(any(q.startswith("SELECT 1 FROM survey_responses") for q in statements))
                begin = statements.index("BEGIN IMMEDIATE")
                commit = statements.index("COMMIT")
                self.assertTrue(all(begin < statements.index(q) < commit for q in queries))
                self.assertEqual(captured["accepted_count"], first["accepted_count"])
                self.assertEqual(captured["rejected_count"], first["rejected_count"] + 802)
                self.assertEqual(facade.capture_real_survey_intake(payload)["status"], "ALREADY_CAPTURED")
            finally:
                app.close()
