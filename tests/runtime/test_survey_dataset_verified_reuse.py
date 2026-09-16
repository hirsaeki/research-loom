from __future__ import annotations

import tempfile
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.survey_virtual_runner.llm_backend import DeterministicFakeVirtualRespondentBackend
from tests.runtime.survey_analysis_test_support import analysis_questionnaire
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, make_virtual_app
from tests.runtime.test_survey_llm_virtual_respondent import ANSWERS, llm_payload
from tests.runtime.test_survey_production import state_signature


class SurveyDatasetVerifiedReuseTests(SurveyVirtualRunnerTestBase):
    def _completed_llm_run(self, facade: LocalApplicationFacade):
        questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
        facade._virtual_respondent_backend = lambda _payload: DeterministicFakeVirtualRespondentBackend(
            ANSWERS,
            backend_id="openai_responses",
        )
        result = facade.submit_action(
            {
                "action_type": "virtual_runner.survey.execute",
                "payload": llm_payload(questionnaire),
                "actor_id": "HUMAN-SDR-REUSE",
            }
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        return questionnaire, result

    @staticmethod
    def _instrument_ref(questionnaire):
        return {
            "id": questionnaire["questionnaire_id"],
            "version": questionnaire["version"],
            "content_digest": questionnaire["content_digest"],
        }

    def test_verified_reuse_preserves_metadata_rejects_wrong_bindings_and_survives_race(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                before_state = state_signature(app)
                questionnaire, first = self._completed_llm_run(facade)
                run_id = first["run_id"]
                dataset_id = first["response_dataset"]["dataset_id"]
                instrument_ref = self._instrument_ref(questionnaire)
                store = facade._survey_response_store()
                first_dataset = store.load_dataset("PRJ-1", dataset_id)
                self.assertIsNotNone(first_dataset)
                first_ref = first_dataset["accepted_response_refs"][0]
                first_response = facade.show_survey_response(
                    first_ref["response_id"],
                    identity_namespace=first_ref["identity_namespace"],
                )["response"]

                time.sleep(0.002)
                reused = facade.capture_virtual_run_response_dataset(
                    run_id,
                    instrument_ref=instrument_ref,
                )
                self.assertEqual(reused["status"], "ALREADY_CAPTURED")
                self.assertEqual(reused["dataset_id"], dataset_id)
                self.assertEqual(reused["content_digest"], first_dataset["content_digest"])
                self.assertEqual(reused["registry_digest"], first_dataset["registry_digest"])
                self.assertEqual(reused["created_at"], first_dataset["created_at"])
                self.assertEqual(reused["captured_against"], first_dataset["captured_against"])
                self.assertEqual(reused["source_provenance"], first_dataset["source_provenance"])

                # Simulate check-then-act concurrency: this caller observes absence,
                # another caller wins the immutable insert, then this caller collides.
                with patch.object(store, "load_dataset", side_effect=[None, first_dataset]):
                    with patch.object(facade, "_survey_response_store", return_value=store):
                        raced = facade.capture_virtual_run_response_dataset(
                            run_id,
                            instrument_ref=instrument_ref,
                        )
                self.assertEqual(raced["status"], "ALREADY_CAPTURED")
                self.assertEqual(raced["registry_digest"], first_dataset["registry_digest"])
                self.assertEqual(raced["created_at"], first_dataset["created_at"])

                stored_again = store.load_dataset("PRJ-1", dataset_id)
                response_again = facade.show_survey_response(
                    first_ref["response_id"],
                    identity_namespace=first_ref["identity_namespace"],
                )["response"]
                self.assertEqual(stored_again, first_dataset)
                self.assertEqual(response_again["ingested_at"], first_response["ingested_at"])
                self.assertEqual(response_again["registry_digest"], first_response["registry_digest"])

                # Ablation: without verified reuse, the old recreate path still conflicts.
                with patch.object(store, "load_dataset", return_value=None):
                    with patch.object(facade, "_survey_response_store", return_value=store):
                        with self.assertRaises(LocalApplicationError) as immutable:
                            facade.capture_virtual_run_response_dataset(run_id, instrument_ref=instrument_ref)
                self.assertEqual(immutable.exception.code, "SURVEY-RESPONSE-DATASET-IMMUTABLE-001")

                wrong_instrument = dict(instrument_ref)
                wrong_instrument["id"] = "QNR-WRONG"
                with self.assertRaises(LocalApplicationError) as instrument_error:
                    facade.capture_virtual_run_response_dataset(run_id, instrument_ref=wrong_instrument)
                self.assertEqual(instrument_error.exception.code, "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001")

                self_outer = self

                class ResponseStoreProxy:
                    def __init__(self, dataset):
                        self.dataset = dataset

                    def load_dataset(self, project_id, requested_dataset_id):
                        self_outer.assertEqual(project_id, "PRJ-1")
                        self_outer.assertEqual(requested_dataset_id, dataset_id)
                        return deepcopy(self.dataset)

                    def load_responses(self, project_id, response_keys):
                        return store.load_responses(project_id, response_keys)

                wrong_artifact = deepcopy(first_dataset)
                wrong_artifact["source_provenance"]["response_artifact_digest"] = "sha256:" + "0" * 64
                wrong_origin = deepcopy(first_dataset)
                wrong_origin["response_origin"] = "real"
                wrong_producer = deepcopy(first_dataset)
                wrong_producer["source_run_ids"] = ["RUN-FOREIGN"]

                for mutated in (wrong_artifact, wrong_origin, wrong_producer):
                    with self.subTest(
                        origin=mutated["response_origin"],
                        source_run_ids=mutated["source_run_ids"],
                    ):
                        with patch.object(
                            facade,
                            "_survey_response_store",
                            return_value=ResponseStoreProxy(mutated),
                        ):
                            with self.assertRaises(LocalApplicationError) as caught:
                                facade.capture_virtual_run_response_dataset(
                                    run_id,
                                    instrument_ref=instrument_ref,
                                )
                        self.assertEqual(caught.exception.code, "APPLICATION-SURVEY-RESPONSE-REUSE-001")

                class RawMismatchProxy(ResponseStoreProxy):
                    def load_responses(self, project_id, response_keys):
                        values = store.load_responses(project_id, response_keys)
                        first_key = next(iter(values))
                        values[first_key]["raw_input"]["answers"]["role"] = "tampered-answer"
                        return values

                with patch.object(
                    facade,
                    "_survey_response_store",
                    return_value=RawMismatchProxy(first_dataset),
                ):
                    with self.assertRaises(LocalApplicationError) as answer_error:
                        facade.capture_virtual_run_response_dataset(
                            run_id,
                            instrument_ref=instrument_ref,
                        )
                self.assertEqual(answer_error.exception.code, "APPLICATION-SURVEY-RESPONSE-REUSE-001")

                # Guard ablation: bypassing producer/artifact verification would
                # accept the deliberately wrong immutable Dataset binding.
                with patch.object(
                    facade,
                    "_survey_response_store",
                    return_value=ResponseStoreProxy(wrong_artifact),
                ):
                    with patch.object(
                        facade,
                        "_verified_virtual_dataset_reuse",
                        side_effect=lambda dataset, **_kwargs: facade._dataset_capture_result(
                            dataset,
                            status="ALREADY_CAPTURED",
                        ),
                    ):
                        accepted = facade.capture_virtual_run_response_dataset(
                            run_id,
                            instrument_ref=instrument_ref,
                        )
                self.assertEqual(accepted["status"], "ALREADY_CAPTURED")
                self.assertEqual(
                    accepted["source_provenance"]["response_artifact_digest"],
                    "sha256:" + "0" * 64,
                )

                # Downstream aggregation can retry from the immutable Dataset
                # without re-running Virtual Respondents.
                spec = facade.capture_survey_analysis_spec(
                    {
                        "dataset_id": reused["dataset_id"],
                        "dataset_digest": reused["content_digest"],
                        "analysis_items": llm_payload(questionnaire)["analysis_items"],
                    }
                )
                aggregate = facade.run_survey_aggregation(
                    {
                        "analysis_spec_id": spec["analysis_spec_id"],
                        "analysis_spec_digest": spec["content_digest"],
                        "dataset_id": reused["dataset_id"],
                        "dataset_digest": reused["content_digest"],
                    }
                )
                self.assertEqual(aggregate["dataset_ref"]["id"], dataset_id)
                self.assertEqual(aggregate["epistemic_status"], "SYNTHETIC_TEST_ONLY")
                self.assertEqual(state_signature(app), before_state)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
