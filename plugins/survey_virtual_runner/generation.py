from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .response_validation import reachable_questions, stable_response_key

DEFAULT_STRESS_FAULTS = (
    "required_missing",
    "optional_missing",
    "unknown",
    "not_applicable",
    "prefer_not_to_answer",
    "invalid_choice",
    "out_of_range_scale",
    "branch_violation",
    "duplicate_record",
    "duplicate_identity",
    "partial_completion",
    "malformed_response",
    "extreme_valid",
)


def _value(question: Mapping[str, Any], *, extreme: bool = False) -> Any:
    qtype = str(question["question_type"])
    if qtype in {"single_choice", "multiple_choice"}:
        values = [str(item.get("value") or item["option_id"]) for item in question.get("response_options", ())]
        if not values:
            return None
        chosen = values[-1] if extreme else values[0]
        return [chosen] if qtype == "multiple_choice" else chosen
    if qtype == "scale":
        scale = question.get("scale") or {}
        return scale.get("maximum") if extreme else scale.get("minimum")
    if qtype == "numeric":
        limits = question.get("numeric_constraints") or {}
        if extreme and limits.get("maximum") is not None:
            return limits["maximum"]
        return limits.get("minimum", 0)
    return "SYNTHETIC_TEXT_001"


def _record(questionnaire: Mapping[str, Any], *, index: int, namespace: str) -> dict[str, Any]:
    answers = [
        {"response_key": stable_response_key(question), "state": "answered", "value": _value(question)}
        for question in questionnaire.get("questions", ())
    ]
    by_key = {str(item["response_key"]): item for item in answers}
    reachable = reachable_questions(questionnaire, by_key)
    answers = [
        answer for question, answer in zip(questionnaire.get("questions", ()), answers)
        if str(question["question_id"]) in reachable
    ]
    return {
        "schema_version": "0.1.0",
        "object_type": "survey_response_record",
        "response_id": f"SYN-RESP-{index + 1:04d}",
        "raw_data_ref_id": f"SYN-DATA-{index + 1:04d}",
        "participant_id": f"SYN-PARTICIPANT-{index + 1:04d}",
        "identity_namespace": namespace,
        "epistemic_mode": "virtual",
        "synthetic": True,
        "response_status": "complete",
        "eligibility_status": "eligible",
        "duplicate_disposition": "not_duplicate",
        "verified_evidence_claimed": False,
        "dropout": False,
        "answers": answers,
    }


def _question(questionnaire, predicate):
    for question in questionnaire.get("questions", ()):
        if predicate(question):
            return question
    return None


def _answer(record: Mapping[str, Any], key: str):
    for answer in record.get("answers", ()):
        if isinstance(answer, Mapping) and answer.get("response_key") == key:
            return answer
    return None


def _set_state(record: dict[str, Any], question: Mapping[str, Any], state: str) -> None:
    key = stable_response_key(question)
    answer = _answer(record, key)
    if answer is None:
        answer = {"response_key": key, "state": state}
        record["answers"].append(answer)
    else:
        answer.clear()
        answer.update({"response_key": key, "state": state})


def _set_value(record: dict[str, Any], question: Mapping[str, Any], value: Any) -> None:
    key = stable_response_key(question)
    answer = _answer(record, key)
    if answer is None:
        record["answers"].append({"response_key": key, "state": "answered", "value": value})
    else:
        answer.clear()
        answer.update({"response_key": key, "state": "answered", "value": value})


def _inject_branch_violation(questionnaire: Mapping[str, Any], record: dict[str, Any]) -> None:
    for owner in questionnaire.get("questions", ()):
        for rule in owner.get("branching", ()):
            target_id = rule.get("target_question_id")
            if not target_id or rule.get("action") not in {"show", "skip"}:
                continue
            condition = _question(questionnaire, lambda q: q.get("question_id") == rule.get("condition_question_id"))
            target = _question(questionnaire, lambda q: q.get("question_id") == target_id)
            if condition is None or target is None:
                continue
            if rule.get("operator") == "equals" and condition.get("response_options"):
                values = [str(item.get("value") or item["option_id"]) for item in condition["response_options"]]
                expected = str(rule.get("value"))
                alternate = next((item for item in values if item != expected), "__NON_MATCHING__")
                _set_value(record, condition, alternate if rule.get("action") == "show" else expected)
            _set_value(record, target, _value(target))
            return


def _inject_fault(questionnaire: Mapping[str, Any], records: list[Any], fault: str) -> None:
    if not records:
        return
    slots = {
        "required_missing": 0, "invalid_choice": 1, "branch_violation": 1,
        "out_of_range_scale": 2, "duplicate_record": 3, "duplicate_identity": 3,
        "partial_completion": 4, "optional_missing": 0, "unknown": 4,
        "not_applicable": 4, "prefer_not_to_answer": 4, "malformed_response": 5,
        "extreme_valid": 0,
    }
    index = min(slots.get(fault, 0), len(records) - 1)
    record = records[index]
    if not isinstance(record, dict):
        return
    required = _question(questionnaire, lambda q: bool(q.get("required")))
    optional = _question(questionnaire, lambda q: not bool(q.get("required")))
    choice = _questionhquestionnaire, lambda q: q.get("question_type") in {"single_choice", "multiple_choice"})
    ranged = _question(questionnaire, lambda q: q.get("question_type") in {"scale", "numeric"})
    questions = list(questionnaire.get("questions", ()))

    if fault == "required_missing" and required is not None:
        _set_state(record, required, "missing")
    elif fault == "optional_missing" and optional is not None:
        _set_state(record, optional, "missing")
    elif fault in {"unknown", "not_applicable", "prefer_not_to_answer"} and questions:
        target_index = {"unknown": 0, "not_applicable": 2, "prefer_not_to_answer": 3}[fault]
        _set_state(record, questions[min(target_index, len(questions) - 1)], fault)
    elif fault == "invalid_choice" and choice is not None:
        _set_value(record, choice, "__INVALID_CHOICE__")
    elif fault == "out_of_range_scale" and ranged is not None:
        if ranged["question_type"] == "scale":
            maximum = (ranged.get("scale") or {}).get("maximum", 0)
        else:
            maximum = (ranged.get("numeric_constraints") or {}).get("maximum")
        _set_value(record, ranged, (maximum + 1) if isinstance(maximum, (int, float)) else -1)
    elif fault == "branch_violation":
        _inject_branch_violation(questionnaire, record)
    elif fault == "duplicate_record" and len(records) > 1:
        record["response_id"] = records[max(0, index - 1)]["response_id"]
    elif fault == "duplicate_identity" and len(records) > 1:
        prior = records[max(0, index - 1)]
        record["participant_id"] = prior["participant_id"]
        record["identity_namespace"] = prior["identity_namespace"]
    elif fault == "partial_completion":
        record["response_status"] = "partial"
        record["dropout"] = True
    elif fault == "malformed_response":
        records[index] = {"malformed": True}
    elif fault == "extreme_valid" and ranged is not None:
        _set_value(record, ranged, _value(ranged, extreme=True))


def generate_records(
    questionnaire: Mapping[str, Any],
    *,
    scenario_class: str,
    population_size: int,
    identity_namespace: str,
    stress_faults: Sequence[str],
) -> tuple[list[Any], tuple[str, ...]]:
    count = max(1, int(population_size))
    records: list[Any] = [
        _record(questionnaire, index=index, namespace=identity_namespace)
        for index in range(count)
    ]
    injected: tuple[str, ...] = ()
    if scenario_class == "STANDARD":
        optional = _questionhquestionnaire, lambda q: not bool(q.get("required")))
        if optional is not None and len(records) > 1:
            _set_state(records[1], optional, "missing")
        return records, injected

    configured = tuple(stress_faults) or DEFAULT_STRESS_FAULTS
    for fault in configured:
        _inject_fault(questionnaire, records, str(fault))
    return records, configured
