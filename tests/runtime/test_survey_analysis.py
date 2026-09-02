from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_survey_store import canonical_document_digest
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    execution_payload,
    make_virtual_app,
)
from tests.runtime.test_survey_production import (
    NullResolver,
    adopt_rq,
    design_payload,
    extended_questionnaire,
    initialize_workspace,
    instrument_payload,
    profile_provider,
    run_cli,
    state_signature,
)
from tests.runtime.test_survey_response_dataset import intake, raw_response


def analysis_questionnaire(*, rq_id: str = "RQ-1") -> dict:
    questionnaire = extended_questionnaire(rq_id=rq_id)
    questionnaire["questions"][1]["required"] = False
    trace = {
        "construct_ids": ["ANALYSIS"],
        "research_question_ids": [rq_id],
        "evidence_gap_ids": ["GAP-1"],
    }
    questionnaire["questions"].extend([
        {
            "question_id": "Q5",
            "response_key": "approval",
            "section_id": "SEC-CORE",
            "item_revision": 1,
            "text": "Approval mode?",
            "question_type": "single_choice",
            "required": False,
            "response_options": [
                {"option_id": "Y", "value": "yes", "label": "Yes"},
                {"option_id": "N", "value": "no", "label": "No"},
            ],
            "scale": None,
            "numeric_constraints": None,
            "branching": [{
                "condition_question_id": "Q1",
                "operator": "equals",
                "value": "manager",
                "action": "show",
                "target_question_id": "Q5",
            }],
            "randomization_group_id": None,
            "traceability": deepcopy(trace),
        },
        {
            "question_id": "Q6",
            "response_key": "actions",
            "section_id": "SEC-CORE",
            "item_revision": 1,
            "text": "Allowed actions?",
            "question_type": "multiple_choice",
            "required": False,
            "response_options": [
                {"option_id": "A", "value": "assist", "label": "Assist"},
                {"option_id": "R", "value": "recommend", "label": "Recommend"},
                {"option_id": "E", "value": "execute", "label": "Execute"},
            ],
            "scale": None,
            "numeric_constraints": None,
            "branching": [],
            "randomization_group_id": None,
            "traceability": deepcopy(trace),
        },
        {
            "question_id": "Q7",
            "response_key": "segment",
            "section_id": "SEC-CORE",
            "item_revision": 1,
            "text": "Segment?",
            "question_type": "single_choice",
            "required": False,
            "response_options": [
                {"option_id": "EAST", "value": "east", "label": "East"},
                {"option_id": "WEST", "value": "west", "label": "West"},
            ],
            "scale": None,
            "numeric_constraints": None,
            "branching": [],
            "randomization_group_id": None,
            "traceability": deepcopy(trace),
        },
    ])
    questionnaire["content_digest"] = canonical_document_digest(
        questionnaire, "content_digest"
    )
    return questionnaire


def analysis_responses() -> list[dict]:
    return [
        raw_response(
            "SYN-A",
            "SYN-P-A",
            answers={
                "role": "manager",
                "usefulness": 4,
                "notes": "alpha",
                "approval": "yes",
                "actions": ["assist", "recommend"],
                "segment": "east",
            },
        ),
        raw_response(
            "SYN-B",
            "SYN-P-B",
            answers={
                "role": "manager",
                "usefulness": {"state": "unknown"},
                "notes": "beta",
                "actions": ["assist", "execute"],
                "segment": "west",
            },
        ),
        raw_response(
            "SYN-C",
            "SYN-P-C",
            answers={
                "role": "contributor",
                "notes": "gamma",
                "actions": ["recommend"],
                "segment": "east",
            },
        ),
        raw_response(
            "SYN-D",
            "SYN-P-D",
            answers={
                "role": "manager",
                "usefulness": 2,
                "notes": "delta",
                "approval": "no",
                "actions": ["assist", "recommend", "execute"],
                "segment": "west",
            },
        ),
    ]


def find_item(shown: dict, analysis_type: str, *, question_id: str | None = None) -> dict:
    for item in shown["result_items"]:
        if item["analysis_type"] != analysis_type:
            continue
        if question_id is not None and item.get("question_id") != question_id:
            continue
        return item
    raise AssertionError(f"result item not found: {analysis_type} {question_id}")


class SurveyAnalysisProductionTests(SurveyVirtualRunnerTestBase):
    def _analysis_fixture(self, temp: str):
        app = make_virtual_app(temp)
        facade = LocalApplicationFacade(app, "PRJ-1")
        questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
        captured = facade.capture_survey_response_dataset(
            intake(questionnaire, responses=analysis_responses())
        )
        return app, facade, questionnaire, captured

    def _capture_spec(self, facade, dataset, analysis_items=None):
        payload = {
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["content_digest"],
        }
        if analysis_items is not None:
            payload["analysis_items"] = analysis_items
        return facade.capture_survey_analysis_spec(payload)

    def _aggregate(self, facade, dataset, spec):
        return facade.run_survey_aggregation({
            "analysis_spec_id": spec["analysis_spec_id"],
            "analysis_spec_digest": spec["content_digest"],
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["content_digest"],
        })

    def test_default_spec_frequency_missingness_scale_free_text_and_epistemic_firewall(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _questionnaire, dataset = self._analysis_fixture(temp)
            before = state_signature(app)
            spec = self._capture_spec(facade, dataset)
            result = self._aggregate(facade, dataset, spec)
            shown = facade.show_survey_aggregate_result(result["aggregate_result_id"], limit=100)

            q1 = find_item(shown, "frequency", question_id="Q1")
            self.assertEqual(q1["denominator_rule"], "valid_responses")
            self.assertEqual(q1["denominator_count"], 4)
            self.assertEqual(
                [(row["value"], row["count"]) for row in q1["categories"]],
                [("manager", 3), ("contributor", 1)],
            )
            self.assertNotIn("unknown", [row["value"] for row in q1["categories"]])

            q2_missing = find_item(shown, "missingness", question_id="Q2")
            self.assertEqual(q2_missing["counts"]["answered"], 2)
            self.assertEqual(q2_missing["counts"]["unknown"], 1)
            self.assertEqual(q2_missing["counts"]["not_asked"], 1)
            q2_scale = find_item(shown, "scale_summary", question_id="Q2")
            self.assertEqual(q2_scale["count"], 2)
            self.assertEqual(
                [(row["value"], row["count"]) for row in q2_scale["distribution"]],
                [(2, 1), (4, 1)],
            )
            notes = find_item(shown, "free_text_listing", question_id="Q4")
            self.assertEqual(notes["non_empty_count"], 4)
            self.assertEqual(notes["returned_count"], 4)
            self.assertFalse(notes["truncated"])

            summary = shown["aggregate_result"]
            self.assertEqual(summary["response_origin"], "synthetic")
            self.assertEqual(summary["epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertFalse(summary["synthetic_population_estimate_claimed"])
            self.assertEqual(
                summary["warnings"][0]["code"],
                "SURVEY_AGGREGATE_SYNTHETIC_NOT_POPULATION_ESTIMATE",
            )
            self.assertEqual(state_signature(app), before)
            app.close()

    def test_denominator_rules_are_explicit_and_branch_aware(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _questionnaire, dataset = self._analysis_fixture(temp)
            spec = self._capture_spec(
                facade,
                dataset,
                [
                    {"item_id": "ALL", "analysis_type": "frequency", "question_id": "Q5", "denominator_rule": "all_responses"},
                    {"item_id": "ASKED", "analysis_type": "frequency", "question_id": "Q5", "denominator_rule": "asked_responses"},
                    {"item_id": "VALID", "analysis_type": "frequency", "question_id": "Q5", "denominator_rule": "valid_responses"},
                    {"item_id": "MISS", "analysis_type": "missingness", "question_id": "Q5"},
                ],
            )
            result = self._aggregate(facade, dataset, spec)
            shown = facade.show_survey_aggregate_result(result["aggregate_result_id"], limit=100)
            by_id = {item["item_id"]: item for item in shown["result_items"]}
            self.assertEqual(by_id["ALL"]["denominator_count"], 4)
            self.assertEqual(by_id["ASKED"]["denominator_count"], 3)
            self.assertEqual(by_id["VALID"]["denominator_count"], 2)
            self.assertEqual(by_id["MISS"]["counts"]["missing"], 1)
            self.assertEqual(by_id["MISS"]["counts"]["not_asked"], 1)
            yes = lambda item: next(row for row in item["categories"] if row["value"] == "yes")
            self.assertEqual(yes(by_id["ALL"])["percentage"], 25.0)
            self.assertAlmostEqual(yes(by_id["ASKED"])["percentage"], 33.333333)
            self.assertEqual(yes(by_id["VALID"])["percentage"], 50.0)
            app.close()

    def test_multi_select_and_cross_tab_preserve_selection_and_sparse_cell_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _questionnaire, dataset = self._analysis_fixture(temp)
            spec = self._capture_spec(
                facade,
                dataset,
                [
                    {"item_id": "MULTI", "analysis_type": "frequency", "question_id": "Q6", "denominator_rule": "valid_responses"},
                    {"item_id": "XTAB", "analysis_type": "cross_tab", "row_question_id": "Q1", "column_question_id": "Q7"},
                ],
            )
            shown = facade.show_survey_aggregate_result(
                self._aggregate(facade, dataset, spec)["aggregate_result_id"],
                limit=100,
            )
            multi = next(item for item in shown["result_items"] if item["item_id"] == "MULTI")
            self.assertEqual(multi["count_semantics"], "selection_count")
            self.assertEqual(multi["denominator_count"], 4)
            self.assertEqual(multi["selection_count_total"], 8)
            self.assertEqual(sum(row["percentage"] for row in multi["categories"]), 200.0)

            xtab = next(item for item in shown["result_items"] if item["item_id"] == "XTAB")
            self.assertEqual(xtab["pair_denominator_rule"], "valid_pairs")
            self.assertEqual(xtab["pair_denominator_count"], 4)
            manager = next(row for row in xtab["rows"] if row["row_value"] == "manager")
            contributor = next(row for row in xtab["rows"] if row["row_value"] == "contributor")
            self.assertEqual(manager["row_count"], 3)
            self.assertEqual(contributor["row_count"], 1)
            contributor_west = next(cell for cell in contributor["cells"] if cell["column_value"] == "west")
            self.assertEqual(contributor_west["count"], 0)
            self.assertEqual(contributor_west["row_percentage"], 0.0)
            app.close()

    def test_rejected_responses_are_excluded_but_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade, questionnaire=analysis_questionnaire())
            responses = analysis_responses() + [
                raw_response(
                    "SYN-BAD",
                    "SYN-P-BAD",
                    answers={"role": "not-a-choice", "segment": "east"},
                )
            ]
            dataset = facade.capture_survey_response_dataset(
                intake(questionnaire, responses=responses)
            )
            self.assertEqual(dataset["accepted_count"], 4)
            self.assertEqual(dataset["rejected_count"], 1)
            spec = self._capture_spec(
                facade,
                dataset,
                [{"analysis_type": "frequency", "question_id": "Q1"}, {"analysis_type": "missingness", "question_id": "Q1"}],
            )
            shown = facade.show_survey_aggregate_result(
                self._aggregate(facade, dataset, spec)["aggregate_result_id"], limit=100
            )
            summary = shown["aggregate_result"]
            self.assertEqual(summary["population"]["accepted_response_count"], 4)
            self.assertEqual(summary["population"]["excluded_response_count"], 1)
            self.assertEqual(summary["exclusions"]["rejected_count"], 1)
            self.assertIn("SURVEY_RESPONSE_INVALID_CHOICE", summary["exclusions"]["issue_code_counts"])
            frequency = find_item(shown, "frequency", question_id="Q1")
            self.assertEqual(frequency["denominator_count"], 4)
            missingness = find_item(shown, "missingness", question_id="Q1")
            self.assertEqual(missingness["excluded_response_count"], 1)
            app.close()

    def test_origin_neutral_frequency_uses_same_formula(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            synthetic = facade.capture_survey_response_dataset(
                intake(
                    questionnaire,
                    responses=[raw_response("SYN-1", "SYN-P-1", role="Contributor", answers={"role": "contributor"})],
                )
            )
            real = facade.capture_survey_response_dataset(
                intake(
                    questionnaire,
                    origin="real",
                    responses=[raw_response("REAL-1", "REAL-P-1", namespace="real:test", role="Contributor", answers={"role": "contributor"})],
                )
            )
            item = [{"analysis_type": "frequency", "question_id": "Q1", "denominator_rule": "valid_responses"}]
            syn_spec = self._capture_spec(facade, synthetic, item)
            real_spec = self._capture_spec(facade, real, item)
            syn = facade.show_survey_aggregate_result(self._aggregate(facade, synthetic, syn_spec)["aggregate_result_id"])
            empirical = facade.show_survey_aggregate_result(self._aggregate(facade, real, real_spec)["aggregate_result_id"])
            self.assertEqual(syn["result_items"][0]["categories"], empirical["result_items"][0]["categories"])
            self.assertEqual(syn["result_items"][0]["denominator_counts"], empirical["result_items"][0]["denominator_counts"])
            self.assertEqual(empirical["aggregate_result"]["epistemic_status"], "EMPIRICAL")
            self.assertEqual(empirical["aggregate_result"]["warnings"], [])
            app.close()

    def test_same_pins_are_deterministic_immutable_and_reopenable(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _questionnaire, dataset = self._analysis_fixture(temp)
            before = state_signature(app)
            spec = self._capture_spec(facade, dataset)
            first = self._aggregate(facade, dataset, spec)
            second = self._aggregate(facade, dataset, spec)
            self.assertEqual(first["aggregate_result_id"], second["aggregate_result_id"])
            self.assertEqual(first["content_digest"], second["content_digest"])
            self.assertEqual(second["status"], "ALREADY_CAPTURED")
            result_id = first["aggregate_result_id"]
            spec_id = spec["analysis_spec_id"]
            self.assertEqual(state_signature(app), before)
            app.close()

            reopened = LocalResearchApplication(
                temp,
                resolver=NullResolver(),
                effective_profile_set_provider=profile_provider,
            )
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                shown_spec = reopened_facade.show_survey_analysis_spec(spec_id)["analysis_spec"]
                shown_result = reopened_facade.show_survey_aggregate_result(result_id, limit=100)
                self.assertEqual(shown_spec["content_digest"], spec["content_digest"])
                self.assertEqual(shown_result["aggregate_result"]["content_digest"], first["content_digest"])
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_fail_closed_on_stale_pins_unknown_question_and_unsupported_cross_tab(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _questionnaire, dataset = self._analysis_fixture(temp)
            with self.assertRaises(LocalApplicationError):
                facade.capture_survey_analysis_spec({
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": "sha256:" + "0" * 64,
                })
            with self.assertRaises(LocalApplicationError):
                self._capture_spec(
                    facade,
                    dataset,
                    [{"analysis_type": "frequency", "question_id": "NO-SUCH-QUESTION"}],
                )
            with self.assertRaises(LocalApplicationError):
                self._capture_spec(
                    facade,
                    dataset,
                    [{"analysis_type": "cross_tab", "row_question_id": "Q2", "column_question_id": "Q1"}],
                )
            spec = self._capture_spec(facade, dataset)
            with self.assertRaises(LocalApplicationError):
                facade.run_survey_aggregation({
                    "analysis_spec_id": spec["analysis_spec_id"],
                    "analysis_spec_digest": "sha256:" + "0" * 64,
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["content_digest"],
                })
            app.close()

    def test_action_submit_exposes_spec_aggregate_and_bounded_result_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = initialize_workspace(root)
            rq_id = adopt_rq(workspace)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                questionnaire = analysis_questionnaire(rq_id=rq_id)
                facade.capture_survey_design(design_payload(rq_id=rq_id))
                captured_instrument = facade.capture_survey_instrument(
                    instrument_payload(rq_id=rq_id, questionnaire=questionnaire)
                )
                questionnaire = facade.show_survey_instrument(
                    captured_instrument["instrument_id"], captured_instrument["version"]
                )["instrument"]["questionnaire"]
                dataset = facade.capture_survey_response_dataset(
                    intake(questionnaire, responses=analysis_responses())
                )

            capture_action = {
                "action_type": "survey_analysis_spec.capture",
                "payload": {
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["content_digest"],
                    "analysis_items": [{"analysis_type": "cross_tab", "row_question_id": "Q1", "column_question_id": "Q7"}],
                },
                "actor_id": "HUMAN-SURVEY",
                "conversation_id": "CONV-SURVEY-ANALYSIS",
                "rationale": "Capture a pinned descriptive Survey analysis specification.",
            }
            code, captured = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps(capture_action),
            )
            self.assertEqual(code, 0)
            self.assertEqual(captured["status"], "SUCCEEDED")
            spec = captured["data"]

            aggregate_action = {
                "action_type": "survey_aggregate.run",
                "payload": {
                    "analysis_spec_id": spec["analysis_spec_id"],
                    "analysis_spec_digest": spec["content_digest"],
                    "dataset_id": dataset["dataset_id"],
                    "dataset_digest": dataset["content_digest"],
                },
                "actor_id": "HUMAN-SURVEY",
                "conversation_id": "CONV-SURVEY-ANALYSIS",
                "rationale": "Run shared descriptive aggregation over the exact canonical Dataset.",
            }
            code, aggregated = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps(aggregate_action),
            )
            self.assertEqual(code, 0)
            self.assertEqual(aggregated["status"], "SUCCEEDED")
            result = aggregated["data"]

            show_action = {
                "action_type": "survey_aggregate.show",
                "payload": {
                    "aggregate_result_id": result["aggregate_result_id"],
                    "limit": 1,
                    "offset": 0,
                },
                "actor_id": "HUMAN-SURVEY",
                "conversation_id": "CONV-SURVEY-ANALYSIS",
                "rationale": "Inspect the persisted aggregate result through the public bounded surface.",
            }
            code, shown = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps(show_action),
            )
            self.assertEqual(code, 0)
            self.assertEqual(shown["status"], "SUCCEEDED")
            self.assertEqual(shown["data"]["pagination"]["returned"], 1)
            self.assertEqual(shown["data"]["result_items"][0]["analysis_type"], "cross_tab")

    def test_pr41_standard_and_stress_flow_through_same_aggregator(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            before = state_signature(app)

            standard = facade.submit_action({
                "action_type": "virtual_runner.survey.execute",
                "payload": execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                ),
                "actor_id": "HUMAN-VR",
            })
            standard_dataset = standard["response_dataset"]
            standard_spec = self._capture_spec(facade, standard_dataset)
            standard_result = facade.show_survey_aggregate_result(
                self._aggregate(facade, standard_dataset, standard_spec)["aggregate_result_id"],
                limit=100,
            )
            self.assertEqual(standard_result["aggregate_result"]["exclusions"]["rejected_count"], 0)
            self.assertEqual(
                standard_result["aggregate_result"]["provenance"]["source_run_ids"],
                [standard["run_id"]],
            )

            stress = facade.submit_action({
                "action_type": "virtual_runner.survey.execute",
                "payload": execution_payload(
                    scenario="STRESS",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                    prior=(standard["run_id"],),
                ),
                "actor_id": "HUMAN-VR",
            })
            stress_dataset = stress["response_dataset"]
            stress_spec = self._capture_spec(facade, stress_dataset)
            stress_result = facade.show_survey_aggregate_result(
                self._aggregate(facade, stress_dataset, stress_spec)["aggregate_result_id"],
                limit=100,
            )
            self.assertGreater(stress_result["aggregate_result"]["exclusions"]["rejected_count"], 0)
            self.assertEqual(
                stress_result["aggregate_result"]["population"]["accepted_response_count"],
                stress_dataset["accepted_count"],
            )
            self.assertEqual(
                stress_result["aggregate_result"]["provenance"]["source_run_ids"],
                [stress["run_id"]],
            )
            self.assertEqual(state_signature(app), before)
            app.close()


if __name__ == "__main__":
    unittest.main()
