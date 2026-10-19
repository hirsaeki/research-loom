"""Characterization tests for ``plugins/local_application/survey/survey_analysis_facade.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They drive ``SurveyAnalysisMixin`` through a real ``LocalApplicationFacade``
built with the Survey Virtual Runner fixtures, and pin the stage hooks, the
lazy action registration, the exact-pin loaders, specification capture,
aggregation and bounded result inspection, including the stable
``LocalApplicationError`` codes callers rely on.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.conversation import ActionDefinition
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.survey import survey_analysis_facade
from plugins.local_application.survey.survey_analysis_actions import (
    _ACTION_VALIDATORS,
    _SURVEY_ANALYSIS_ACTIONS,
)
from plugins.local_application.survey.survey_analysis_facade import (
    SurveyAnalysisMixin,
    list_actions_stage,
    submit_action_stage,
)
from plugins.local_survey_analysis_store import LocalSurveyAnalysisStoreError
from plugins.local_survey_response_store import LocalSurveyResponseStoreError
from tests.runtime.survey_analysis_test_support import analysis_questionnaire, analysis_responses
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    make_virtual_app,
)
from tests.runtime.test_survey_production import state_signature
from tests.runtime.test_survey_response_dataset import intake, raw_response

DATASET = "APPLICATION-SURVEY-ANALYSIS-DATASET-001"
SPEC = "APPLICATION-SURVEY-ANALYSIS-SPEC-001"
INSTRUMENT = "APPLICATION-SURVEY-ANALYSIS-INSTRUMENT-001"
AGGREGATE = "APPLICATION-SURVEY-AGGREGATE-001"
INPUT = "APPLICATION-SURVEY-ANALYSIS-INPUT-001"
SURVEY_INPUT = "APPLICATION-SURVEY-INPUT-001"
MUTATION = "APPLICATION-SURVEY-ANALYSIS-STATE-MUTATION-001"
ZERO = "sha256:" + "0" * 64
ANALYSIS_ACTION_TYPES = {action_type for action_type, _, _ in _SURVEY_ANALYSIS_ACTIONS}


class _StoreProxy:
    """Delegates to a real store; selected methods are overridden per test."""

    def __init__(self, store, **overrides) -> None:
        self._store = store
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._store, name)


def _raise(error):
    def fail(*_args, **_kwargs):
        raise error

    return fail


class StageHookTests(unittest.TestCase):
    def test_list_actions_stage_registers_routes_before_proceeding(self) -> None:
        calls: list[str] = []
        facade = SimpleNamespace(_ensure_survey_analysis_actions=lambda: calls.append("ensure"))

        def proceed():
            calls.append("proceed")
            return {"actions": []}

        self.assertEqual(list_actions_stage(facade, proceed), {"actions": []})
        self.assertEqual(calls, ["ensure", "proceed"])

    def test_submit_action_stage_forwards_only_the_draft_input(self) -> None:
        calls: list[object] = []
        facade = SimpleNamespace(_ensure_survey_analysis_actions=lambda: calls.append("ensure"))
        draft = {"action_type": "survey_aggregate.show"}

        def proceed(*args, **kwargs):
            calls.append((args, kwargs))
            return {"status": "OK"}

        self.assertEqual(
            submit_action_stage(facade, proceed, draft, view="compact"), {"status": "OK"}
        )
        self.assertEqual(calls, ["ensure", ((draft,), {})])

    def test_mixin_declares_both_stage_hooks(self) -> None:
        self.assertIs(SurveyAnalysisMixin._STAGES["list_actions"], list_actions_stage)
        self.assertIs(SurveyAnalysisMixin._STAGES["submit_action"], submit_action_stage)


class StoreLocationTests(unittest.TestCase):
    def test_application_root_is_used_without_a_workspace(self) -> None:
        fake = SimpleNamespace(_workspace_root=None, _application=SimpleNamespace(root="/app"))
        store = SurveyAnalysisMixin._survey_analysis_store(fake)
        self.assertEqual(store.path, Path("/app") / "survey-analysis-registry.sqlite3")

    def test_workspace_root_places_store_under_research_loom(self) -> None:
        fake = SimpleNamespace(_workspace_root=Path("/ws"), _application=SimpleNamespace(root="/x"))
        store = SurveyAnalysisMixin._survey_analysis_store(fake)
        self.assertEqual(
            store.path, Path("/ws") / ".research-loom" / "survey-analysis-registry.sqlite3"
        )

    def test_missing_root_fails_closed(self) -> None:
        fake = SimpleNamespace(_workspace_root=None, _application=SimpleNamespace())
        with self.assertRaises(LocalApplicationError) as caught:
            SurveyAnalysisMixin._survey_analysis_store(fake)
        self.assertEqual(caught.exception.code, "APPLICATION-SURVEY-ANALYSIS-STORE-001")
        self.assertEqual(
            caught.exception.message, "Survey analysis registry requires a local application root"
        )


class _Base(SurveyVirtualRunnerTestBase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = make_virtual_app(temp.name)
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")

    def _dataset(self, responses=None):
        questionnaire = self._capture(self.facade, questionnaire=analysis_questionnaire())
        return self.facade.capture_survey_response_dataset(
            intake(questionnaire, responses=responses or analysis_responses())
        )

    def _spec(self, dataset, items=None):
        payload = {"dataset_id": dataset["dataset_id"], "dataset_digest": dataset["content_digest"]}
        if items is not None:
            payload["analysis_items"] = items
        return self.facade.capture_survey_analysis_spec(payload)

    def _run_payload(self, dataset, spec):
        return {
            "analysis_spec_id": spec["analysis_spec_id"],
            "analysis_spec_digest": spec["content_digest"],
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["content_digest"],
        }

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(LocalApplicationError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class ActionRegistrationTests(_Base):
    def _registered(self):
        return {
            definition.action_type: definition
            for definition in self.app.coordinator.action_definitions()
            if definition.action_type in ANALYSIS_ACTION_TYPES
        }

    def test_actions_are_registered_lazily_as_read_only_harness_services(self) -> None:
        self.assertEqual(self._registered(), {})
        self.facade.list_actions()
        registered = self._registered()
        self.assertEqual(set(registered), ANALYSIS_ACTION_TYPES)
        for action_type, contract, _ in _SURVEY_ANALYSIS_ACTIONS:
            definition = registered[action_type]
            self.assertEqual(definition.payload_contract, contract)
            self.assertEqual(definition.effect, "read_only")
            self.assertEqual(definition.route_kind, "harness_service")
            self.assertFalse(definition.confirmation_required)
            self.assertFalse(definition.human_decision_required)
            self.assertEqual(definition.service_id, action_type)
            self.assertIs(definition.payload_validator, _ACTION_VALIDATORS[action_type])
            self.assertIsNotNone(self.app.coordinator._services.resolve(action_type))

    def test_repeated_registration_is_idempotent(self) -> None:
        self.facade._ensure_survey_analysis_actions()
        first = self._registered()
        handler = self.app.coordinator._services.resolve("survey_aggregate.run")
        self.facade._ensure_survey_analysis_actions()
        self.assertEqual(self._registered(), first)
        self.assertIs(self.app.coordinator._services.resolve("survey_aggregate.run"), handler)

    def test_matching_definition_without_service_gets_a_handler(self) -> None:
        action_type, contract, _ = _SURVEY_ANALYSIS_ACTIONS[0]
        self.app.coordinator._actions.register(
            ActionDefinition(
                action_type,
                contract,
                "read_only",
                "harness_service",
                False,
                service_id=action_type,
            )
        )
        self.facade._ensure_survey_analysis_actions()
        self.assertIsNotNone(self.app.coordinator._services.resolve(action_type))

    def test_conflicting_definition_fails_closed(self) -> None:
        action_type, contract, _ = _SURVEY_ANALYSIS_ACTIONS[3]
        self.app.coordinator._actions.register(
            ActionDefinition(
                action_type,
                contract + "-conflict",
                "read_only",
                "harness_service",
                False,
                service_id=action_type,
            )
        )
        error = self.assertCode("APPLICATION-SURVEY-ANALYSIS-ROUTE-001", self.facade.list_actions)
        self.assertEqual(
            error.message,
            f"registered action conflicts with Survey analysis route: {action_type}",
        )


class SpecCaptureTests(_Base):
    def test_default_spec_is_captured_once_without_state_mutation(self) -> None:
        dataset = self._dataset()
        before = state_signature(self.app)
        first = self._spec(dataset)
        self.assertEqual(first["status"], "CAPTURED")
        self.assertEqual(first["project_id"], "PRJ-1")
        self.assertTrue(first["analysis_spec_id"].startswith("SAS-"))
        self.assertEqual(
            first["analysis_spec_id"],
            "SAS-" + first["content_digest"].removeprefix("sha256:")[:24],
        )
        self.assertEqual(
            first["dataset_ref"],
            {"id": dataset["dataset_id"], "content_digest": dataset["content_digest"]},
        )
        self.assertEqual(first["instrument_ref"], dataset["instrument_ref"])
        self.assertEqual(first["analysis_item_count"], 15)
        self.assertFalse(first["research_state_mutation_performed"])

        second = self._spec(dataset)
        self.assertEqual(second["status"], "ALREADY_CAPTURED")
        self.assertEqual(second["analysis_spec_id"], first["analysis_spec_id"])
        self.assertEqual(state_signature(self.app), before)

    def test_show_returns_the_stored_document(self) -> None:
        dataset = self._dataset()
        spec = self._spec(dataset, [{"analysis_type": "frequency", "question_id": "Q1"}])
        shown = self.facade.show_survey_analysis_spec(spec["analysis_spec_id"])
        self.assertEqual(shown["status"], "OK")
        self.assertEqual(shown["project_id"], "PRJ-1")
        self.assertFalse(shown["research_state_mutation_performed"])
        document = shown["analysis_spec"]
        self.assertEqual(document["object_type"], "survey_analysis_spec")
        self.assertEqual(document["content_digest"], spec["content_digest"])
        self.assertEqual(spec["analysis_item_count"], 1)
        self.assertEqual(len(document["analysis_items"]), 1)

    def test_show_unknown_spec_fails(self) -> None:
        error = self.assertCode(SPEC, self.facade.show_survey_analysis_spec, "SAS-UNKNOWN")
        self.assertEqual(error.message, "SurveyAnalysisSpec was not found")

    def test_input_shape_errors(self) -> None:
        self.assertCode(SURVEY_INPUT, self.facade.capture_survey_analysis_spec, [])
        self.assertCode(
            SURVEY_INPUT,
            self.facade.capture_survey_analysis_spec,
            {"dataset_id": "SRD-1", "dataset_digest": ZERO, "extra": True},
        )
        self.assertCode(
            SURVEY_INPUT,
            self.facade.capture_survey_analysis_spec,
            {"dataset_id": " ", "dataset_digest": ZERO},
        )

    def test_dataset_pin_errors(self) -> None:
        dataset = self._dataset()
        cases = (
            ({"dataset_digest": "md5:abc"}, "dataset_digest must be a sha256 digest"),
            ({"dataset_id": "SRD-UNKNOWN"}, "canonical SurveyResponseDataset was not found"),
            (
                {"dataset_digest": ZERO},
                "SurveyResponseDataset digest does not match the exact stored Dataset",
            ),
        )
        for change, message in cases:
            with self.subTest(message=message):
                payload = {
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["content_digest"],
                    **change,
                }
                error = self.assertCode(DATASET, self.facade.capture_survey_analysis_spec, payload)
                self.assertEqual(error.message, message)

    def test_unsupported_analysis_items_are_spec_errors(self) -> None:
        dataset = self._dataset()
        for items in (
            [{"analysis_type": "frequency", "question_id": "NO-SUCH"}],
            [{"analysis_type": "cross_tab", "row_question_id": "Q2", "column_question_id": "Q1"}],
        ):
            with self.subTest(items=items):
                self.assertCode(SPEC, self._spec, dataset, items)

    def test_response_store_error_is_translated(self) -> None:
        dataset = self._dataset()
        store = self.facade._survey_response_store()
        proxy = _StoreProxy(
            store, load_dataset=_raise(LocalSurveyResponseStoreError("STORE-X", "broken"))
        )
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            error = self.assertCode("STORE-X", self._spec, dataset)
        self.assertEqual(error.message, "broken")

    def test_analysis_store_capture_error_is_translated(self) -> None:
        dataset = self._dataset()
        proxy = _StoreProxy(
            self.facade._survey_analysis_store(),
            capture_spec=_raise(LocalSurveyAnalysisStoreError("ANALYSIS-X", "denied")),
        )
        with patch.object(self.facade, "_survey_analysis_store", return_value=proxy):
            self.assertCode("ANALYSIS-X", self._spec, dataset)

    def test_inconsistent_instrument_binding_fails(self) -> None:
        dataset = self._dataset()
        resolve = self.facade._resolve_instrument

        def drifted(value):
            questionnaire, ref = resolve(value)
            return questionnaire, {**ref, "version": "9.9.9"}

        with patch.object(self.facade, "_resolve_instrument", side_effect=drifted):
            error = self.assertCode(INSTRUMENT, self._spec, dataset)
        self.assertEqual(error.message, "SurveyResponseDataset Instrument binding is inconsistent")

    def test_state_change_during_capture_is_reported(self) -> None:
        # The check runs after the spec is stored (a postcondition by design,
        # #577); the stored spec is immutable and non-authoritative.
        dataset = self._dataset()
        snapshots = iter([{"snapshot_ref": "A"}, {"snapshot_ref": "B"}])
        with patch.object(
            survey_analysis_facade, "_snapshot", side_effect=lambda _state: next(snapshots)
        ):
            self.assertCode(MUTATION, self._spec, dataset)


class AggregationTests(_Base):
    def _fixture(self, items=None):
        dataset = self._dataset()
        spec = self._spec(dataset, items)
        return dataset, spec

    def test_run_captures_then_reuses_result(self) -> None:
        dataset, spec = self._fixture()
        before = state_signature(self.app)
        first = self.facade.run_survey_aggregation(self._run_payload(dataset, spec))
        self.assertEqual(first["status"], "CAPTURED")
        self.assertEqual(first["project_id"], "PRJ-1")
        self.assertTrue(first["aggregate_result_id"].startswith("SAR-"))
        self.assertEqual(
            first["analysis_spec_ref"],
            {"id": spec["analysis_spec_id"], "content_digest": spec["content_digest"]},
        )
        self.assertEqual(first["dataset_ref"], spec["dataset_ref"])
        self.assertEqual(first["instrument_ref"], dataset["instrument_ref"])
        self.assertEqual(first["response_origin"], "synthetic")
        self.assertEqual(first["epistemic_status"], "SYNTHETIC_TEST_ONLY")
        self.assertEqual(
            first["population"],
            {
                "dataset_response_count": 4,
                "accepted_response_count": 4,
                "excluded_response_count": 0,
            },
        )
        self.assertEqual(first["exclusions"]["rejected_count"], 0)
        self.assertEqual(
            [item["code"] for item in first["warnings"]],
            ["SURVEY_AGGREGATE_SYNTHETIC_NOT_POPULATION_ESTIMATE"],
        )
        self.assertFalse(first["research_state_mutation_performed"])

        second = self.facade.run_survey_aggregation(self._run_payload(dataset, spec))
        self.assertEqual(second["status"], "ALREADY_CAPTURED")
        self.assertEqual(second["content_digest"], first["content_digest"])
        self.assertEqual(state_signature(self.app), before)

    def test_rejected_responses_resolve_into_exclusions(self) -> None:
        responses = analysis_responses() + [
            raw_response("SYN-BAD", "SYN-P-BAD", answers={"role": "not-a-choice"})
        ]
        dataset = self._dataset(responses)
        spec = self._spec(dataset, [{"analysis_type": "frequency", "question_id": "Q1"}])
        result = self.facade.run_survey_aggregation(self._run_payload(dataset, spec))
        self.assertEqual(result["population"]["accepted_response_count"], 4)
        self.assertEqual(result["exclusions"]["rejected_count"], 1)

    def test_input_and_pin_errors(self) -> None:
        dataset, spec = self._fixture()
        payload = self._run_payload(dataset, spec)
        self.assertCode(SURVEY_INPUT, self.facade.run_survey_aggregation, {**payload, "x": 1})
        self.assertCode(
            SURVEY_INPUT, self.facade.run_survey_aggregation, {**payload, "dataset_id": ""}
        )
        cases = (
            (
                {"analysis_spec_digest": "nope"},
                SPEC,
                "analysis_spec_digest must be a sha256 digest",
            ),
            ({"analysis_spec_id": "SAS-UNKNOWN"}, SPEC, "SurveyAnalysisSpec was not found"),
            (
                {"analysis_spec_digest": ZERO},
                SPEC,
                "SurveyAnalysisSpec digest does not match the exact stored specification",
            ),
            ({"dataset_digest": ZERO}, DATASET, None),
        )
        for change, code, message in cases:
            with self.subTest(change=change):
                error = self.assertCode(
                    code, self.facade.run_survey_aggregation, {**payload, **change}
                )
                if message is not None:
                    self.assertEqual(error.message, message)

    def test_spec_bound_to_another_dataset_is_stale(self) -> None:
        dataset, spec = self._fixture()
        other = self.facade.capture_survey_response_dataset(
            intake(
                self.facade.show_survey_instrument("QNR-1", "1.0.0")["instrument"]["questionnaire"],
                responses=analysis_responses()[:2],
            )
        )
        error = self.assertCode(
            SPEC,
            self.facade.run_survey_aggregation,
            {
                **self._run_payload(dataset, spec),
                "dataset_id": other["dataset_id"],
                "dataset_digest": other["content_digest"],
            },
        )
        self.assertEqual(
            error.message, "SurveyAnalysisSpec is stale or bound to a different Dataset"
        )

    def _with_stored_spec(self, mutate):
        dataset, spec = self._fixture()
        stored = self.facade._load_spec_exact(spec["analysis_spec_id"], spec["content_digest"])
        mutate(stored)
        return dataset, spec, patch.object(self.facade, "_load_spec_exact", return_value=stored)

    def test_spec_instrument_drift_fails(self) -> None:
        dataset, spec, patched = self._with_stored_spec(
            lambda stored: stored["instrument_ref"].update({"version": "0.0.1"})
        )
        with patched:
            error = self.assertCode(
                INSTRUMENT, self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )
        self.assertEqual(
            error.message,
            "SurveyAnalysisSpec and Dataset are bound to different Instrument revisions",
        )

    def test_spec_items_that_no_longer_normalize_identically_fail(self) -> None:
        dataset, spec, patched = self._with_stored_spec(
            lambda stored: stored["analysis_items"][1].pop("denominator_rule")
        )
        with patched:
            error = self.assertCode(
                SPEC, self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )
        self.assertEqual(
            error.message, "stored SurveyAnalysisSpec no longer matches Instrument semantics"
        )

    def test_spec_items_that_no_longer_normalize_fail(self) -> None:
        dataset, spec, patched = self._with_stored_spec(
            lambda stored: stored["analysis_items"].append(
                {"analysis_type": "frequency", "question_id": "NO-SUCH"}
            )
        )
        with patched:
            self.assertCode(
                SPEC, self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )

    def _population_error(self, **overrides):
        dataset, spec = self._fixture()
        proxy = _StoreProxy(self.facade._survey_response_store(), **overrides)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            return self.assertCode(
                DATASET,
                self.facade.run_survey_aggregation,
                self._run_payload(dataset, spec),
            )

    def test_unresolvable_response_reference_fails(self) -> None:
        error = self._population_error(load_responses=lambda *_args: {})
        self.assertEqual(
            error.message, "SurveyResponseDataset response reference cannot be resolved"
        )

    def test_stale_response_content_fails(self) -> None:
        store = self.facade._survey_response_store()

        def tampered(project_id, keys):
            records = store.load_responses(project_id, keys)
            first = next(iter(records))
            records[first]["response"]["content_digest"] = ZERO
            return records

        error = self._population_error(load_responses=tampered)
        self.assertEqual(
            error.message,
            "SurveyResponseDataset contains stale or mixed canonical response content",
        )

    def test_accepted_count_mismatch_fails(self) -> None:
        store = self.facade._survey_response_store()

        def inflated(project_id, dataset_id):
            dataset = store.load_dataset(project_id, dataset_id)
            dataset["accepted_count"] = int(dataset["accepted_count"]) + 1
            return dataset

        error = self._population_error(load_dataset=inflated)
        self.assertEqual(
            error.message, "SurveyResponseDataset accepted population does not resolve exactly"
        )

    def test_response_loading_store_error_is_translated(self) -> None:
        dataset, spec = self._fixture()
        proxy = _StoreProxy(
            self.facade._survey_response_store(),
            load_responses=_raise(LocalSurveyResponseStoreError("RESP-X", "unreadable")),
        )
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            self.assertCode(
                "RESP-X", self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )

    def test_spec_store_error_is_translated(self) -> None:
        dataset, spec = self._fixture()
        proxy = _StoreProxy(
            self.facade._survey_analysis_store(),
            load_spec=_raise(LocalSurveyAnalysisStoreError("SPEC-X", "unreadable")),
        )
        with patch.object(self.facade, "_survey_analysis_store", return_value=proxy):
            self.assertCode(
                "SPEC-X", self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )
            self.assertCode("SPEC-X", self.facade.show_survey_analysis_spec, "SAS-1")

    def test_aggregator_value_error_becomes_aggregate_error(self) -> None:
        dataset, spec = self._fixture()
        with patch.object(
            survey_analysis_facade, "aggregate_dataset", side_effect=ValueError("bad aggregate")
        ):
            error = self.assertCode(
                AGGREGATE, self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )
        self.assertEqual(error.message, "bad aggregate")

    def test_result_capture_store_error_and_state_change_are_reported(self) -> None:
        dataset, spec = self._fixture()
        proxy = _StoreProxy(
            self.facade._survey_analysis_store(),
            capture_result=_raise(LocalSurveyAnalysisStoreError("RESULT-X", "denied")),
        )
        with patch.object(self.facade, "_survey_analysis_store", return_value=proxy):
            self.assertCode(
                "RESULT-X", self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )
        snapshots = iter([{"snapshot_ref": "A"}, {"snapshot_ref": "B"}])
        with patch.object(
            survey_analysis_facade, "_snapshot", side_effect=lambda _state: next(snapshots)
        ):
            self.assertCode(
                MUTATION, self.facade.run_survey_aggregation, self._run_payload(dataset, spec)
            )


class AggregateResultInspectionTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        dataset = self._dataset()
        spec = self._spec(dataset)
        self.result = self.facade.run_survey_aggregation(self._run_payload(dataset, spec))

    def test_default_page_and_summary_shape(self) -> None:
        shown = self.facade.show_survey_aggregate_result(self.result["aggregate_result_id"])
        self.assertEqual(shown["status"], "OK")
        self.assertEqual(shown["project_id"], "PRJ-1")
        self.assertFalse(shown["research_state_mutation_performed"])
        self.assertNotIn("result_items", shown["aggregate_result"])
        self.assertEqual(shown["aggregate_result"]["content_digest"], self.result["content_digest"])
        self.assertEqual(
            shown["pagination"], {"limit": 25, "offset": 0, "returned": 15, "total": 15}
        )

    def test_bounded_pages(self) -> None:
        result_id = self.result["aggregate_result_id"]
        full = self.facade.show_survey_aggregate_result(result_id, limit=100)["result_items"]
        page = self.facade.show_survey_aggregate_result(result_id, limit=2, offset=1)
        self.assertEqual(page["result_items"], full[1:3])
        self.assertEqual(page["pagination"], {"limit": 2, "offset": 1, "returned": 2, "total": 15})
        beyond = self.facade.show_survey_aggregate_result(result_id, limit=1, offset=99)
        self.assertEqual(beyond["result_items"], [])
        self.assertEqual(beyond["pagination"]["returned"], 0)

    def test_invalid_limit_or_offset(self) -> None:
        result_id = self.result["aggregate_result_id"]
        for limit in (0, 101, True, 1.5, "5"):
            with self.subTest(limit=limit):
                error = self.assertCode(
                    INPUT, self.facade.show_survey_aggregate_result, result_id, limit=limit
                )
                self.assertEqual(error.message, "limit must be an integer from 1 through 100")
        for offset in (-1, False, "0"):
            with self.subTest(offset=offset):
                error = self.assertCode(
                    INPUT, self.facade.show_survey_aggregate_result, result_id, offset=offset
                )
                self.assertEqual(error.message, "offset must be a non-negative integer")

    def test_unknown_result_and_store_error(self) -> None:
        error = self.assertCode(AGGREGATE, self.facade.show_survey_aggregate_result, "SAR-NONE")
        self.assertEqual(error.message, "SurveyAggregateResult was not found")
        proxy = _StoreProxy(
            self.facade._survey_analysis_store(),
            load_result=_raise(LocalSurveyAnalysisStoreError("LOAD-X", "unreadable")),
        )
        with patch.object(self.facade, "_survey_analysis_store", return_value=proxy):
            self.assertCode(
                "LOAD-X",
                self.facade.show_survey_aggregate_result,
                self.result["aggregate_result_id"],
            )


if __name__ == "__main__":
    unittest.main()
