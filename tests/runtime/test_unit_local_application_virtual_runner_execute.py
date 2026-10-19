"""Characterization tests for ``plugins.local_application.virtual_runner.virtual_runner_execute`` (#507).

They pin ``VirtualRunnerExecuteMixin.run_survey_virtual`` on a real local
application: the Instrument/Design lookups and their error mapping, the
structural and LLM result envelopes, the minimum-valid-response rule, the
optional Survey analysis hand-off, the failed-run envelope, and the epistemic
firewall that rejects a Research State change during execution.
"""

from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace

from plugins.application_errors import LocalApplicationError
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.virtual_runner.virtual_runner_execute import (
    DESCRIPTOR_PATH,
    VirtualRunnerExecuteMixin,
)
from plugins.local_survey_store import LocalSurveyStoreError
from plugins.survey_virtual_runner.llm_backend import (
    DeterministicFakeVirtualRespondentBackend,
    OpenAIResponsesVirtualRespondentBackend,
)
from tests.runtime.survey_analysis_test_support import analysis_questionnaire
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    execution_payload,
    make_virtual_app,
)
from tests.runtime.test_survey_llm_virtual_respondent import ANSWERS, llm_payload


class StoreProxy:
    """Delegates to the real Survey store but lets a test override one lookup."""

    def __init__(self, store, **overrides) -> None:
        self._store = store
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._store, name)


def raise_store_error(*_args, **_kwargs):
    raise LocalSurveyStoreError("SURVEY-STORE-TEST-001", "store refused the lookup")


class CrashingBackend(DeterministicFakeVirtualRespondentBackend):
    """A backend failure outside the respondent error contract fails the managed Run."""

    def generate_response(self, **_kwargs):
        raise RuntimeError("transport exploded")


class ExecuteCase(SurveyVirtualRunnerTestBase):
    questionnaire_factory = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.app = make_virtual_app(self.tempdir.name)
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")
        factory = type(self).questionnaire_factory
        self.questionnaire = self._capture(
            self.facade, questionnaire=factory() if factory is not None else None
        )

    def structural_payload(self, **overrides) -> dict:
        payload = execution_payload(
            scenario="STANDARD",
            instrument_version=self.questionnaire["version"],
            instrument_digest=self.questionnaire["content_digest"],
        )
        payload.update(overrides)
        return payload

    def override_store(self, **overrides) -> None:
        real = type(self.facade)._survey_store.__get__(self.facade)
        self.facade._survey_store = lambda: StoreProxy(real(), **overrides)

    def assert_rejected(self, payload, code, message):
        with self.assertRaises(LocalApplicationError) as caught:
            self.facade.run_survey_virtual(payload)
        self.assertEqual((caught.exception.code, caught.exception.message), (code, message))


class StructuralExecuteTests(ExecuteCase):
    def test_structural_run_envelope(self):
        result = self.facade.run_survey_virtual(self.structural_payload())
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["project_id"], "PRJ-1")
        self.assertTrue(result["run_id"].startswith("RUN-"))
        self.assertEqual(result["execution_mode"], "virtual")
        self.assertEqual(result["scenario_class"], "STANDARD")
        self.assertEqual(result["generator_backend"], "structural")
        self.assertEqual(
            result["instrument_pin"],
            {
                "id": self.questionnaire["questionnaire_id"],
                "version": self.questionnaire["version"],
                "content_digest": self.questionnaire["content_digest"],
            },
        )
        self.assertEqual(result["execution_result"]["run"]["status"], "COMPLETED")
        self.assertIsNotNone(result["response_dataset"])
        self.assertIsNone(result["analysis_spec"])
        self.assertIsNone(result["aggregate_result"])
        self.assertFalse(result["research_state_mutation_performed"])
        self.assertFalse(result["real_execution_started"])

    def test_payload_is_validated_first(self):
        self.assert_rejected(
            self.structural_payload(scenario_class="REAL"),
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "scenario_class must be STANDARD or STRESS",
        )

    def test_unknown_instrument_revision(self):
        self.assert_rejected(
            self.structural_payload(instrument_version="9.9.9"),
            "APPLICATION-SURVEY-INSTRUMENT-NOT-FOUND-001",
            "Survey Instrument revision was not found",
        )

    def test_stale_instrument_digest(self):
        self.assert_rejected(
            self.structural_payload(instrument_digest="sha256:" + "0" * 64),
            "APPLICATION-VIRTUAL-PIN-001",
            "Instrument digest is stale or does not match the exact PR40 registry revision",
        )

    def test_survey_store_errors_are_mapped(self):
        for method in ("load_instrument", "load_design"):
            with self.subTest(method=method):
                self.override_store(**{method: raise_store_error})
                self.assert_rejected(
                    self.structural_payload(), "SURVEY-STORE-TEST-001", "store refused the lookup"
                )

    def test_missing_design_revision(self):
        self.override_store(load_design=lambda *_args: None)
        self.assert_rejected(
            self.structural_payload(),
            "APPLICATION-VIRTUAL-PIN-001",
            "pinned Survey Design revision is missing",
        )

    def test_research_state_change_trips_the_firewall(self):
        real_state = self.facade._state
        calls = []

        def state():
            current = real_state()
            calls.append(current)
            if len(calls) == 1:
                return current
            return SimpleNamespace(
                current_snapshot={**current.current_snapshot, "content_digest": "sha256:moved"}
            )

        self.facade._state = state
        self.assert_rejected(
            self.structural_payload(),
            "VR-EPISTEMIC-FIREWALL-001",
            "Virtual Runner execution mutated authoritative Research State",
        )

    def test_default_backend_and_descriptor(self):
        backend = VirtualRunnerExecuteMixin()._virtual_respondent_backend({"ignored": True})
        self.assertIsInstance(backend, OpenAIResponsesVirtualRespondentBackend)
        self.assertTrue(DESCRIPTOR_PATH.is_file())


class LlmExecuteTests(ExecuteCase):
    questionnaire_factory = staticmethod(analysis_questionnaire)

    def use_answers(self, answers) -> None:
        self.facade._virtual_respondent_backend = lambda _payload: (
            DeterministicFakeVirtualRespondentBackend(answers, backend_id="openai_responses")
        )

    def test_llm_run_hands_off_to_analysis(self):
        self.use_answers(ANSWERS)
        result = self.facade.run_survey_virtual(llm_payload(self.questionnaire))
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["generator_backend"], "llm")
        self.assertEqual(result["response_dataset"]["accepted_count"], 4)
        spec = result["analysis_spec"]
        dataset_ref = {
            "id": result["response_dataset"]["dataset_id"],
            "content_digest": result["response_dataset"]["content_digest"],
        }
        self.assertEqual(result["response_dataset"]["dataset_id"], f"SRD-{result['run_id']}")
        self.assertEqual(spec["analysis_item_count"], 6)
        self.assertEqual(spec["dataset_ref"], dataset_ref)
        self.assertEqual(
            result["aggregate_result"]["analysis_spec_ref"],
            {"id": spec["analysis_spec_id"], "content_digest": spec["content_digest"]},
        )
        self.assertEqual(result["aggregate_result"]["dataset_ref"], dataset_ref)

    def test_llm_run_without_analysis_items(self):
        self.use_answers(ANSWERS)
        payload = llm_payload(self.questionnaire)
        del payload["analysis_items"]
        result = self.facade.run_survey_virtual(payload)
        self.assertEqual(result["status"], "SUCCEEDED")
        # Without analysis_items the analysis spec derives its own default items.
        self.assertGreater(result["analysis_spec"]["analysis_item_count"], 0)
        self.assertIsNotNone(result["aggregate_result"])

    def test_minimum_valid_shortfall_is_error_without_analysis(self):
        answers = dict(ANSWERS)
        answers.pop("SYN-PROFILE-MANAGER-C")
        self.use_answers(answers)
        payload = llm_payload(self.questionnaire)
        payload["minimum_valid_response_count"] = 4
        result = self.facade.run_survey_virtual(payload)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["response_dataset"]["accepted_count"], 3)
        self.assertIsNone(result["analysis_spec"])
        self.assertIsNone(result["aggregate_result"])

    def test_failed_run_has_no_response_dataset(self):
        self.facade._virtual_respondent_backend = lambda _payload: CrashingBackend(
            {}, backend_id="openai_responses"
        )
        result = self.facade.run_survey_virtual(llm_payload(self.questionnaire))
        self.assertEqual(result["status"], "ERROR")
        self.assertNotEqual(result["execution_result"]["run"]["status"], "COMPLETED")
        self.assertIsNone(result["response_dataset"])
        self.assertIsNone(result["analysis_spec"])
        self.assertIsNone(result["aggregate_result"])


if __name__ == "__main__":
    unittest.main()
