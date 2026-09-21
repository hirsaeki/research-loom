from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_survey_response_store import LocalSurveyResponseStore
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase
from tests.runtime import test_issue221_real_survey_intake as issue221
from tests.runtime.test_survey_production import NullResolver, profile_provider, state_signature


class Issue251RealSurveyBatchTests(SurveyVirtualRunnerTestBase):
    _fixture = issue221.Issue221RealSurveyIntakeTests._fixture

    @staticmethod
    def _append_response(root: Path, payload: dict) -> dict:
        source = root / payload["file"]
        document = json.loads(source.read_text(encoding="utf-8"))
        third = deepcopy(document["responses"][0])
        third.update(response_id="REAL-C", participant_id="P-C")
        document["responses"].append(third)
        source.write_text(json.dumps(document), encoding="utf-8")
        return third

    @staticmethod
    def _batch_id(root: Path, payload: dict) -> str:
        identity = {
            "intake_format": "provider-neutral-json@0.1.0",
            "intake_file": payload["file"],
            "file_digest": "sha256:" + hashlib.sha256((root / payload["file"]).read_bytes()).hexdigest(),
            **{key: payload[key] for key in ("instrument_id", "instrument_version", "instrument_digest")},
        }
        return "SRD-REAL-" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]

    def test_alias_and_cumulative_export_reuse_first_responses_not_population_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                before = state_signature(app)
                first = facade.capture_real_survey_intake(payload)
                first_dataset = facade.show_survey_response_dataset(first["dataset_id"])["dataset"]
                first_response = facade.show_survey_response("REAL-A")
                alias = {**payload, "file": "renamed.json"}
                (root / alias["file"]).write_bytes((root / payload["file"]).read_bytes())
                second = facade.capture_real_survey_intake(alias)
                self.assertNotEqual(second["dataset_id"], first["dataset_id"])
                self.assertEqual(second["accepted_count"], 2)
                self.assertEqual(second["rejected_count"], 1)
                self._append_response(root, payload)
                third = facade.capture_real_survey_intake(payload)
                self.assertEqual(third["accepted_count"], 3)
                self.assertEqual(third["rejected_count"], 1)
                shown = facade.show_real_survey_intake(third["dataset_id"], limit=100)
                self.assertEqual(shown["aggregate_result"]["population"]["accepted_response_count"], 3)
                self.assertEqual({entry["canonical_response"]["response_id"] for entry in shown["responses"] if entry["kind"] == "accepted_response"}, {"REAL-A", "REAL-B", "REAL-C"})
                self.assertEqual(facade.show_survey_response("REAL-A"), first_response)
                self.assertEqual(facade.show_survey_response_dataset(first["dataset_id"])["dataset"], first_dataset)
                self.assertNotEqual(shown["intake_source"]["intake_file_digest"], first["intake_source"]["intake_file_digest"])
                replay = facade.capture_real_survey_intake(payload)
                self.assertEqual(replay["status"], "ALREADY_CAPTURED")
                self.assertEqual(replay["aggregate_result_id"], third["aggregate_result_id"])
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()

    def test_changed_response_or_producer_is_not_reused_or_partially_inserted(self):
        for field in ("answer", "producer"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                app, facade, _, payload = self._fixture(temp)
                try:
                    first = facade.capture_real_survey_intake(payload)
                    original = facade.show_survey_response("REAL-A")
                    self._append_response(root, payload)
                    source = root / payload["file"]
                    doc = json.loads(source.read_text(encoding="utf-8"))
                    if field == "answer":
                        doc["responses"][0]["answers"]["usefulness"] = 5
                    else:
                        doc["responses"][0]["provenance"] = {"provider": "different-provider"}
                    source.write_text(json.dumps(doc), encoding="utf-8")
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.capture_real_survey_intake(payload)
                    self.assertEqual(error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                    self.assertEqual(facade.show_survey_response("REAL-A"), original)
                    self.assertIsNone(facade._survey_response_store().load_response("PRJ-1", "REAL-C"))
                    self.assertEqual(facade.show_real_survey_intake(first["dataset_id"])["accepted_count"], 2)
                finally:
                    app.close()

    def test_legacy_first_batch_metadata_and_producer_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            original_capture = facade._capture_dataset

            def legacy_capture(value, **kwargs):
                kwargs.pop("reuse_real_responses", None)
                return original_capture(value, **kwargs)

            try:
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                document["responses"][0]["provenance"] = {"provider": "original-provider"}
                source.write_text(json.dumps(document), encoding="utf-8")
                with patch.object(facade, "_capture_dataset", side_effect=legacy_capture):
                    first = facade.capture_real_survey_intake(payload)
                original = facade.show_survey_response("REAL-A")
                self.assertEqual(original["response"]["source_provenance"]["intake_file"], payload["file"])
                alias = {**payload, "file": "legacy-alias.json"}
                (root / alias["file"]).write_bytes(source.read_bytes())
                second = facade.capture_real_survey_intake(alias)
                self.assertEqual(second["accepted_count"], 2)
                self.assertEqual(facade.show_survey_response("REAL-A"), original)
                self.assertEqual(facade.capture_real_survey_intake(alias)["status"], "ALREADY_CAPTURED")
                self.assertEqual(facade.capture_real_survey_intake(payload)["dataset_id"], first["dataset_id"])
            finally:
                app.close()

    def test_retry_after_dataset_commit_only_resumes_shared_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                with patch.object(facade, "capture_survey_analysis_spec", side_effect=OSError("aggregation interrupted")):
                    with self.assertRaises(OSError):
                        facade.capture_real_survey_intake(payload)
                dataset_id = self._batch_id(root, payload)
                saved = facade.show_survey_response_dataset(dataset_id)["dataset"]
                with patch.object(facade, "_capture_dataset", side_effect=AssertionError("batch must not be captured again")):
                    resumed = facade.capture_real_survey_intake(payload)
                self.assertEqual(resumed["status"], "ALREADY_CAPTURED")
                self.assertEqual(facade.show_survey_response_dataset(dataset_id)["dataset"], saved)
                self.assertEqual(facade.show_real_survey_intake(dataset_id)["accepted_count"], 2)
            finally:
                app.close()

    def test_partial_batch_write_rolls_back_new_answers_and_reopens_safely(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            original_encoded = LocalSurveyResponseStore._encoded

            def interrupt_dataset(value):
                if isinstance(value, dict) and value.get("object_type") == "survey_response_dataset":
                    raise sqlite3.OperationalError("interrupted after response inserts")
                return original_encoded(value)

            try:
                facade.capture_real_survey_intake(payload)
                original = facade.show_survey_response("REAL-A")
                self._append_response(root, payload)
                with patch.object(LocalSurveyResponseStore, "_encoded", side_effect=interrupt_dataset):
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.capture_real_survey_intake(payload)
                self.assertEqual(error.exception.code, "SURVEY-RESPONSE-STORE-DB-001")
                self.assertIsNone(facade._survey_response_store().load_response("PRJ-1", "REAL-C"))
                self.assertEqual(facade.show_survey_response("REAL-A"), original)
            finally:
                app.close()
            reopened = LocalResearchApplication(root, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                facade = LocalApplicationFacade(reopened, "PRJ-1", workspace_root=root)
                resumed = facade.capture_real_survey_intake(payload)
                self.assertEqual(resumed["accepted_count"], 3)
                self.assertEqual(facade.show_survey_response("REAL-A"), original)
            finally:
                reopened.close()

    def test_concurrent_alias_batches_share_canonical_responses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, _, _, payload = self._fixture(temp)
            app.close()
            alias = {**payload, "file": "parallel.json"}
            (root / alias["file"]).write_bytes((root / payload["file"]).read_bytes())

            def capture(item):
                application = LocalResearchApplication(root, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
                try:
                    return LocalApplicationFacade(application, "PRJ-1", workspace_root=root).capture_real_survey_intake(item)
                finally:
                    application.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(capture, [payload, alias]))
            self.assertEqual([result["accepted_count"] for result in results], [2, 2])
            self.assertEqual(len({result["dataset_id"] for result in results}), 2)
            reopened = LocalResearchApplication(root, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                facade = LocalApplicationFacade(reopened, "PRJ-1", workspace_root=root)
                datasets = [facade.show_survey_response_dataset(result["dataset_id"]) for result in results]
                refs = [[entry["response_ref"] for entry in dataset["entries"] if entry["kind"] == "accepted_response"] for dataset in datasets]
                self.assertEqual(refs[0], refs[1])
                for item in (payload, alias):
                    self.assertEqual(facade.capture_real_survey_intake(item)["status"], "ALREADY_CAPTURED")
            finally:
                reopened.close()

    def test_duplicate_records_within_new_batch_remain_visible_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                facade.capture_real_survey_intake(payload)
                source = root / payload["file"]
                document = json.loads(source.read_text(encoding="utf-8"))
                duplicate = deepcopy(document["responses"][0])
                duplicate["answers"]["usefulness"] = 5
                document["responses"].append(duplicate)
                source.write_text(json.dumps(document), encoding="utf-8")
                result = facade.capture_real_survey_intake(payload)
                self.assertEqual(result["accepted_count"], 2)
                self.assertEqual(result["rejected_count"], 2)
                self.assertIn("SURVEY_RESPONSE_DUPLICATE_RECORD", result["validation_summary"]["issue_code_counts"])
                self.assertEqual(facade.capture_real_survey_intake(payload)["status"], "ALREADY_CAPTURED")
            finally:
                app.close()

    def test_same_batch_concurrent_retry_reuses_one_dataset_and_aggregate(self):
        from threading import Barrier
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, _, _, payload = self._fixture(temp)
            app.close()
            barrier = Barrier(2)

            def capture(_):
                application = LocalResearchApplication(root, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
                try:
                    facade = LocalApplicationFacade(application, "PRJ-1", workspace_root=root)
                    original_capture = facade._capture_dataset
                    def compete(*args, **kwargs):
                        barrier.wait(timeout=10)
                        return original_capture(*args, **kwargs)
                    with patch.object(facade, "_capture_dataset", side_effect=compete):
                        return facade.capture_real_survey_intake(payload)
                finally:
                    application.close()
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(capture, range(2)))
            self.assertEqual({result["status"] for result in results}, {"CAPTURED", "ALREADY_CAPTURED"})
            self.assertEqual(len({result["dataset_id"] for result in results}), 1)
            self.assertEqual(len({result["aggregate_result_id"] for result in results}), 1)

    def test_different_instrument_or_origin_cannot_reuse_an_answer_identity(self):
        from plugins.local_survey_store import canonical_document_digest
        from tests.runtime.test_survey_production import instrument_payload
        from tests.runtime.test_survey_response_dataset import intake
        for mismatch in ("instrument", "origin"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                app, facade, questionnaire, payload = self._fixture(temp)
                try:
                    if mismatch == "instrument":
                        facade.capture_real_survey_intake(payload)
                        changed = deepcopy(questionnaire)
                        changed["version"] = "2.0.0"
                        changed["content_digest"] = canonical_document_digest(changed, "content_digest")
                        instrument = facade.capture_survey_instrument(instrument_payload(questionnaire=changed))
                        payload = {**payload, "instrument_version": instrument["version"], "instrument_digest": instrument["content_digest"]}
                    else:
                        document = json.loads((root / payload["file"]).read_text(encoding="utf-8"))
                        synthetic = deepcopy(document["responses"][0])
                        synthetic["identity_namespace"] = "synthetic:issue251"
                        facade.capture_survey_response_dataset(intake(questionnaire, responses=[synthetic]))
                        stored = facade.show_survey_response("REAL-A", identity_namespace="synthetic:issue251")
                        captured = facade.capture_real_survey_intake(payload)
                        self.assertEqual(captured["accepted_count"], 2)
                        self.assertEqual(facade.show_survey_response("REAL-A", identity_namespace="real:issue221")["response"]["response_origin"], "real")
                        self.assertEqual(facade.show_survey_response("REAL-A", identity_namespace="synthetic:issue251"), stored)
                        continue
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.capture_real_survey_intake(payload)
                    self.assertEqual(error.exception.code, "SURVEY_RESPONSE_DUPLICATE_RECORD")
                finally:
                    app.close()

    def test_schema_is_not_visible_until_initialization_is_committed(self):
        from threading import Event
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            app.close()
            entered, resume = Event(), Event()
            original = LocalSurveyResponseStore._schema_version

            def pause_initialization(connection):
                original(connection)
                path = connection.execute("PRAGMA database_list").fetchone()[2]
                if str(path).endswith(".tmp"):
                    entered.set()
                    if not resume.wait(timeout=10):
                        raise AssertionError("reader did not finish")

            def capture():
                application = LocalResearchApplication(root, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
                try:
                    return LocalApplicationFacade(application, "PRJ-1", workspace_root=root).capture_real_survey_intake(payload)
                finally:
                    application.close()

            with patch.object(LocalSurveyResponseStore, "_schema_version", side_effect=pause_initialization):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    pending = executor.submit(capture)
                    try:
                        self.assertTrue(entered.wait(timeout=10))
                        store = LocalSurveyResponseStore(root / ".research-loom" / "survey-response-registry.sqlite3")
                        self.assertFalse(store.exists)
                        self.assertIsNone(store.load_response("PRJ-1", "REAL-A"))
                    finally:
                        resume.set()
                    self.assertEqual(pending.result(timeout=10)["accepted_count"], 2)

    def test_failed_schema_publication_does_not_create_an_empty_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade, _, payload = self._fixture(temp)
            try:
                with patch("plugins.local_survey_response_store.os.link", side_effect=PermissionError("cannot publish")):
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.capture_real_survey_intake(payload)
                self.assertEqual(error.exception.code, "SURVEY-RESPONSE-STORE-DB-001")
                self.assertFalse(facade._survey_response_store().exists)
                self.assertEqual(facade.capture_real_survey_intake(payload)["accepted_count"], 2)
            finally:
                app.close()
