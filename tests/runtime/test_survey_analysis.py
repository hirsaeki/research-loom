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
    # Preserve a reached-but-unanswered response as canonical missing rather than
    # rejecting it so denominator behavior can be tested explicitly.
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
        {
            "question_id": "Q8",
            "response_key": "readiness",
            "section_id": "SEC-CORE",
            "item_revision": 1,
            "text": "Readiness?",
            "question_type": "single_choice",
            "required": False,
            "response_options": [
                {"option_id": "READY", "value": "ready", "label": "Ready"},
                {"option_id": "U", "value": "unknown", "label": "Unknown"},
                {"option_id": "NA", "value": "not_applicable", "label": "Not applicable"},
                {"option_id": "P", "value": "prefer_not", "label": "Prefer not to answer"},
            ],
            "missing_value_semantics": {
                "missing": "no_response",
                "unknown_option_id": "U",
                "not_applicable_option_id": "NA",
                "prefer_not_to_answer_option_id": "P",
            },
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
                "readiness": "ready",
            },
        ),
        raw_response(
            "SYN-B",
            "SYN-P-B",
            answers={
                "role": "manager",
                "usefulness": {"state": "missing"},
                "notes": "beta",
                "actions": ["assist", "execute"],
                "segment": "west",
                "readiness": {"state": "unknown"},
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
                "readiness": {"state": "not_applicable"},
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
                "readiness": {"state": "prefer_not_to_answer"},
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
        return ²È="24             })
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
