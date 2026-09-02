from __future__ import annotations

from copy import deepcopy

from plugins.local_survey_store import canonical_document_digest
from tests.runtime.test_survey_production import extended_questionnaire
from tests.runtime.test_survey_response_dataset import raw_response


def analysis_questionnaire(*, rq_id: str = "RQ-1") -> dict:
    q = extended_questionnaire(rq_id=rq_id)
    q["questions"][1]["required"] = False
    trace = {"construct_ids": ["ANALYSIS"], "research_question_ids": [rq_id], "evidence_gap_ids": ["GAP-1"]}
    q["questions"].extend([
        {
            "question_id": "Q5", "response_key": "approval", "section_id": "SEC-CORE",
            "item_revision": 1, "text": "Approval mode?", "question_type": "single_choice", "required": False,
            "response_options": [
                {"option_id": "Y", "value": "yes", "label": "Yes"},
                {"option_id": "N", "value": "no", "label": "No"},
            ],
            "scale": None, "numeric_constraints": None,
            "branching": [{"condition_question_id": "Q1", "operator": "equals", "value": "manager", "action": "show", "target_question_id": "Q5"}],
            "randomization_group_id": None, "traceability": deepcopy(trace),
        },
        {
            "question_id": "Q6", "response_key": "actions", "section_id": "SEC-CORE",
            "item_revision": 1, "text": "Allowed actions?", "question_type": "multiple_choice", "required": False,
            "response_options": [
                {"option_id": "A", "value": "assist", "label": "Assist"},
                {"option_id": "R", "value": "recommend", "label": "Recommend"},
                {"option_id": "E", "value": "execute", "label": "Execute"},
            ],
            "scale": None, "numeric_constraints": None, "branching": [],
            "randomization_group_id": None, "traceability": deepcopy(trace),
        },
        {
            "question_id": "Q7", "response_key": "segment", "section_id": "SEC-CORE",
            "item_revision": 1, "text": "Segment?", "question_type": "single_choice", "required": False,
            "response_options": [
                {"option_id": "EAST", "value": "east", "label": "East"},
                {"option_id": "WEST", "value": "west", "label": "West"},
            ],
            "scale": None, "numeric_constraints": None, "branching": [],
            "randomization_group_id": None, "traceability": deepcopy(trace),
        },
        {
            "question_id": "Q8", "response_key": "readiness", "section_id": "SEC-CORE",
            "item_revision": 1, "text": "Readiness?", "question_type": "single_choice", "required": False,
            "response_options": [
                {"option_id": "READY", "value": "ready", "label": "Ready"},
                {"option_id": "U", "value": "unknown", "label": "Unknown"},
                {"option_id": "NA", "value": "not_applicable", "label": "Not applicable"},
                {"option_id": "P", "value": "prefer_not", "label": "Prefer not to answer"},
            ],
            "missing_value_semantics": {
                "missing": "no_response", "unknown_option_id": "U",
                "not_applicable_option_id": "NA", "prefer_not_to_answer_option_id": "P",
            },
            "scale": None, "numeric_constraints": None, "branching": [],
            "randomization_group_id": None, "traceability": deepcopy(trace),
        },
    ])
    q["content_digest"] = canonical_document_digest(q, "content_digest")
    return q


def analysis_responses() -> list[dict]:
    return [
        raw_response("SYN-A", "SYN-P-A", answers={
            "role": "manager", "usefulness": 4, "notes": "alpha", "approval": "yes",
            "actions": ["assist", "recommend"], "segment": "east", "readiness": "ready",
        }),
        raw_response("SYN-B", "SYN-P-B", answers={
            "role": "manager", "usefulness": {"state": "missing"}, "notes": "beta",
            "actions": ["assist", "execute"], "segment": "west", "readiness": {"state": "unknown"},
        }),
        raw_response("SYN-C", "SYN-P-C", answers={
            "role": "contributor", "notes": "gamma", "actions": ["recommend"], "segment": "east",
            "readiness": {"state": "not_applicable"},
        }),
        raw_response("SYN-D", "SYN-P-D", answers={
            "role": "manager", "usefulness": 2, "notes": "delta", "approval": "no",
            "actions": ["assist", "recommend", "execute"], "segment": "west",
            "readiness": {"state": "prefer_not_to_answer"},
        }),
    ]


def find_item(shown: dict, analysis_type: str, question_id: str | None = None) -> dict:
    for item in shown["result_items"]:
        if item["analysis_type"] == analysis_type and (question_id is None or item.get("question_id") == question_id):
            return item
    raise AssertionError((analysis_type, question_id))
