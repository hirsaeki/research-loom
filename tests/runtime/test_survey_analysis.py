from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from tests.runtime.survey_analysis_test_support import analysis_questionnaire, analysis_responses, find_item
from tests.runtime.survey_virtual_runner_test_support import SurveyVirtualRunnerTestBase, execution_payload, make_virtual_app
from tests.runtime.test_survey_production import (
    NullResolver, adopt_rq, design_payload, initialize_workspace, instrument_payload,
    profile_provider, run_cli, state_signature,
)
from tests.runtime.test_survey_response_dataset import intake, raw_response


class SurveyAnalysisProductionTests(SurveyVirtualRunnerTestBase):
    def _fixture(self, temp: str):
        app = make_virtual_app(temp)
        facade = LocalApplicationFacade(app, "PRJ-1")
        questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
        dataset = facade.capture_survey_response_dataset(intake(questionnaire, responses=analysis_responses()))
        return app, facade, questionnaire, dataset

    @staticmethod
    def _spec(facade, dataset, items=None):
        payload = {"dataset_id": dataset["dataset_id"], "dataset_digest": dataset["content_digest"]}
        if items is not None:
            payload["analysis_items"] = items
        return facade.capture_survey_analysis_spec(payload)

    @staticmethod
    def _aggregate(facade, dataset, spec):
        return facade.run_survey_aggregation({
            "analysis_spec_id": spec["analysis_spec_id"], "analysis_spec_digest": spec["content_digest"],
            "dataset_id": dataset["dataset_id"], "dataset_digest": dataset["content_digest"],
        })

    def test_default_spec_preserves_missingness_scale_free_text_and_epistemic_status(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, dataset = self._fixture(temp)
            before = state_signature(app)
            spec = self._spec(facade, dataset)
            result = self._aggregate(facade, dataset, spec)
            shown = facade.show_survey_aggregate_result(result["aggregate_result_id"], limit=100)
            self.assertEqual(dataset["accepted_count"], 4)
            self.assertEqual(find_item(shown, "frequency", "Q1")["denominator_count"], 4)
            self.assertEqual(find_item(shown, "scale_summary", "Q2")["count"], 2)
            self.assertEqual(find_item(shown, "missingness", "Q2")["counts"], {
                "answered": 2, "missing": 1, "unknown": 0, "not_applicable": 0,
                "prefer_not_to_answer": 0, "not_asked": 1,
            })
            self.assertEqual(find_item(shown, "missingness", "Q8")["counts"], {
                "answered": 1, "missing": 0, "unknown": 1, "not_applicable": 1,
                "prefer_not_to_answer": 1, "not_asked": 0,
            })
            self.assertEqual(find_item(shown, "free_text_listing", "Q4")["non_empty_count"], 4)
            summary = shown["aggregate_result"]
            self.assertEqual(summary["epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertEqual(summary["warnings"][0]["code"], "SURVEY_AGGREGATE_SYNTHETIC_NOT_POPULATION_ESTIMATE")
            self.assertEqual(state_signature(app), before)
            app.close()

    def test_denominators_are_explicit_and_branch_aware(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, dataset = self._fixture(temp)
            spec = self._spec(facade, dataset, [
                {"item_id": "ALL", "analysis_type": "frequency", "question_id": "Q5", "denominator_rule": "all_responses"},
                {"item_id": "ASKED", "analysis_type": "frequency", "question_id": "Q5", "denominator_rule": "asked_responses"},
                {"item_id": "VALID", "analysis_type": "frequency", "question_id": "Q5", "denominator_rule": "valid_responses"},
                {"item_id": "MISS", "analysis_type": "missingness", "question_id": "Q5"},
            ])
            shown = facade.show_survey_aggregate_result(self._aggregate(facade, dataset, spec)["aggregate_result_id"], limit=100)
            items = {item["item_id"]: item for item in shown["result_items"]}
            self.assertEqual([items[k]["denominator_count"] for k in ("ALL", "ASKED", "VALID")], [4, 3, 2])
            self.assertEqual(items["MISS"]["counts"]["missing"], 1)
            self.assertEqual(items["MISS"]["counts"]["not_asked"], 1)
            app.close()

    def test_multi_select_and_crosstab_keep_selection_and_sparse_cell_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, dataset = self._fixture(temp)
            spec = self._spec(facade, dataset, [
                {"item_id": "MULTI", "analysis_type": "frequency", "question_id": "Q6", "denominator_rule": "valid_responses"},
                {"item_id": "XTAB", "analysis_type": "cross_tab", "row_question_id": "Q1", "column_question_id": "Q7"},
            ])
            shown = facade.show_survey_aggregate_result(self._aggregate(facade, dataset, spec)["aggregate_result_id"], limit=100)
            multi = next(x for x in shown["result_items"] if x["item_id"] == "MULTI")
            self.assertEqual(multi["selection_count_total"], 8)
            self.assertEqual(sum(x["percentage"] for x in multi["categories"]), 200.0)
            xtab = next(x for x in shown["result_items"] if x["item_id"] == "XTAB")
            self.assertEqual(xtab["pair_denominator_count"], 4)
            contributor = next(x for x in xtab["rows"] if x["row_value"] == "contributor")
            self.assertEqual(next(x for x in contributor["cells"] if x["column_value"] == "west")["count"], 0)
            app.close()

    def test_rejected_input_is_excluded_but_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
            responses = analysis_responses() + [raw_response("SYN-BAD", "SYN-P-BAD", answers={"role": "not-a-choice", "segment": "east"})]
            dataset = facade.capture_survey_response_dataset(intake(questionnaire, responses=responses))
            spec = self._spec(facade, dataset, [{"analysis_type": "frequency", "question_id": "Q1"}])
            shown = facade.show_survey_aggregate_result(self._aggregate(facade, dataset, spec)["aggregate_result_id"])
            self.assertEqual(dataset["accepted_count"], 4)
            self.assertEqual(dataset["rejected_count"], 1)
            self.assertEqual(shown["aggregate_result"]["population"]["accepted_response_count"], 4)
            self.assertEqual(shown["aggregate_result"]["exclusions"]["rejected_count"], 1)
            self.assertEqual(shown["result_items"][0]["denominator_count"], 4)
            app.close()

    def test_same_pins_are_deterministic_and_reopenable(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, dataset = self._fixture(temp)
            before = state_signature(app)
            spec = self._spec(facade, dataset)
            first = self._aggregate(facade, dataset, spec)
            second = self._aggregate(facade, dataset, spec)
            self.assertEqual(first["aggregate_result_id"], second["aggregate_result_id"])
            self.assertEqual(first["content_digest"], second["content_digest"])
            self.assertEqual(second["status"], "ALREADY_CAPTURED")
            result_id, spec_id = first["aggregate_result_id"], spec["analysis_spec_id"]
            app.close()
            reopened = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                self.assertEqual(reopened_facade.show_survey_analysis_spec(spec_id)["analysis_spec"]["content_digest"], spec["content_digest"])
                self.assertEqual(reopened_facade.show_survey_aggregate_result(result_id)["aggregate_result"]["content_digest"], first["content_digest"])
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_stale_pins_unknown_question_and_unsupported_crosstab_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _, dataset = self._fixture(temp)
            with self.assertRaises(LocalApplicationError):
                facade.capture_survey_analysis_spec({"dataset_id": dataset["dataset_id"], "dataset_digest": "sha256:" + "0" * 64})
            with self.assertRaises(LocalApplicationError):
                self._spec(facade, dataset, [{"analysis_type": "frequency", "question_id": "NO-SUCH"}])
            with self.assertRaises(LocalApplicationError):
                self._spec(facade, dataset, [{"analysis_type": "cross_tab", "row_question_id": "Q2", "column_question_id": "Q1"}])
            app.close()

    def test_public_actions_round_trip_bounded_result(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = initialize_workspace(Path(temp))
            rq_id = adopt_rq(workspace)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                questionnaire = analysis_questionnaire(rq_id=rq_id)
                facade.capture_survey_design(design_payload(rq_id=rq_id))
                captured = facade.capture_survey_instrument(instrument_payload(rq_id=rq_id, questionnaire=questionnaire))
                questionnaire = facade.show_survey_instrument(captured["instrument_id"], captured["version"])["instrument"]["questionnaire"]
                dataset = facade.capture_survey_response_dataset(intake(questionnaire, responses=analysis_responses()))
            def submit(action_type, payload):
                code, out = run_cli(["action", "submit", "--workspace", str(workspace), "--json", "-"], json.dumps({
                    "action_type": action_type, "payload": payload, "actor_id": "HUMAN-SURVEY",
                    "conversation_id": "CONV-SURVEY-ANALYSIS", "rationale": "PR43 production smoke",
                }))
                self.assertEqual(code, 0)
                self.assertEqual(out["status"], "SUCCEEDED")
                return out["data"]
            spec = submit("survey_analysis_spec.capture", {
                "dataset_id": dataset["dataset_id"], "dataset_digest": dataset["content_digest"],
                "analysis_items": [{"analysis_type": "cross_tab", "row_question_id": "Q1", "column_question_id": "Q7"}],
            })
            result = submit("survey_aggregate.run", {
                "analysis_spec_id": spec["analysis_spec_id"], "analysis_spec_digest": spec["content_digest"],
                "dataset_id": dataset["dataset_id"], "dataset_digest": dataset["content_digest"],
            })
            shown = submit("survey_aggregate.show", {"aggregate_result_id": result["aggregate_result_id"], "limit": 1, "offset": 0})
            self.assertEqual(shown["pagination"]["returned"], 1)
            self.assertEqual(shown["result_items"][0]["analysis_type"], "cross_tab")

    def test_pr41_standard_and_stress_use_shared_aggregator(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            before = state_signature(app)
            standard = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": execution_payload(
                scenario="STANDARD", instrument_version=questionnaire["version"], instrument_digest=questionnaire["content_digest"]), "actor_id": "HUMAN-VR"})
            stress = facade.submit_action({"action_type": "virtual_runner.survey.execute", "payload": execution_payload(
                scenario="STRESS", instrument_version=questionnaire["version"], instrument_digest=questionnaire["content_digest"], prior=(standard["run_id"],)), "actor_id": "HUMAN-VR"})
            for run, expect_rejected in ((standard, False), (stress, True)):
                dataset = run["response_dataset"]
                spec = self._spec(facade, dataset)
                shown = facade.show_survey_aggregate_result(self._aggregate(facade, dataset, spec)["aggregate_result_id"], limit=100)
                self.assertEqual(shown["aggregate_result"]["provenance"]["source_run_ids"], [run["run_id"]])
                self.assertEqual(shown["aggregate_result"]["exclusions"]["rejected_count"] > 0, expect_rejected)
            self.assertEqual(state_signature(app), before)
            app.close()


if __name__ == "__main__":
    unittest.main()
