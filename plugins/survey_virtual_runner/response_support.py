from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
_RESPONSE_SCHEMA = json.loads(
    (ROOT / "core/packages/survey/survey-response.schema.json").read_text(encoding="utf-8")
)
_RESPONSE_VALIDATOR = Draft202012Validator(
    _RESPONSE_SCHEMA,
    format_checker=FormatChecker(),
)


def _issue(
    code: str,
    message: str,
    *,
    response_id: str | None = None,
    response_key: str | None = None,
    severity: str = "error",
) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if response_id:
        value["response_id"] = response_id
    if response_key:
        value["response_key"] = response_key
    return value


def _preservation(
    kind: str,
    *,
    response_id: str,
    response_key: str | None = None,
    detail: str,
) -> dict[str, Any]:
    value = {"kind": kind, "response_id": response_id, "detail": detail}
    if response_key:
        value["response_key"] = response_key
    return value


def stable_response_key(question: Mapping[str, Any]) -> str:
    value = question.get("response_key")
    return str(value) if isinstance(value, str) and value else str(question["question_id"])


def _stable_option_value(option: Mapping[str, Any]) -> str:
    value = option.get("value")
    return str(value) if isinstance(value, str) and value else str(option["option_id"])


def _answers_by_key(
    record: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, Any]]]:
    result: dict[str, Mapping[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    response_id = str(record.get("response_id") or "")
    answers = record.get("answers")
    if not isinstance(answers, list):
        return result, issues
    for item in answers:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("response_key") or "")
        if not key:
            continue
        if key in result:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_DUPLICATE_VARIABLE",
                    f"response variable {key} occurs more than once in one response",
                    response_id=response_id,
                    response_key=key,
                )
            )
            continue
        result[key] = item
    return result, issues


def _condition_matches(
    rule: Mapping[str, Any],
    answers: Mapping[str, Mapping[str, Any]],
    key_by_question: Mapping[str, str],
) -> bool:
    source_key = key_by_question.get(str(rule["condition_question_id"]))
    if source_key is None:
        return False
    answer = answers.get(source_key)
    operator = str(rule["operator"])
    if answer is None:
        return operator == "missing"
    state = str(answer.get("state"))
    if operator == "missing":
        return state == "missing"
    if operator == "answered":
        return state == "answered"
    if state != "answered":
        return False
    value = answer.get("value")
    expected = rule.get("value")
    if operator == "equals":
        return value == expected
    if operator == "not_equals":
        return value != expected
    if operator == "contains":
        return isinstance(value, list) and expected in value
    return False


def reachable_questions(
    questionnaire: Mapping[str, Any],
    answers: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    questions = list(questionnaire.get("questions", ()))
    key_by_question = {
        str(question["question_id"]): stable_response_key(question)
        for question in questions
    }
    index_by_question = {
        str(question["question_id"]): index
        for index, question in enumerate(questions)
    }
    rules_by_target: dict[str, list[Mapping[str, Any]]] = {}
    end_after_index: int | None = None

    for owner in questions:
        owner_index = index_by_question[str(owner["question_id"])]
        for rule in owner.get("branching", ()):
            if not isinstance(rule, Mapping):
                continue
            target = str(rule.get("target_question_id") or "")
            if target:
                rules_by_target.setdefault(target, []).append(rule)
            if (
                rule.get("action") == "end"
                and _condition_matches(rule, answers, key_by_question)
            ):
                condition_index = index_by_question.get(
                    str(rule["condition_question_id"]),
                    owner_index,
                )
                end_after_index = (
                    condition_index
                    if end_after_index is None
                    else min(end_after_index, condition_index)
                )

    reachable: set[str] = set()
    for index, question in enumerate(questions):
        qid = str(question["question_id"])
        if end_after_index is not None and index > end_after_index:
            continue
        rules = rules_by_target.get(qid, ())
        show_rules = [rule for rule in rules if rule.get("action") == "show"]
        skip_rules = [rule for rule in rules if rule.get("action") == "skip"]
        visible = True
        if show_rules:
            visible = any(
                _condition_matches(rule, answers, key_by_question)
                for rule in show_rules
            )
        if visible and any(
            _condition_matches(rule, answers, key_by_question)
            for rule in skip_rules
        ):
            visible = False
        if visible:
            reachable.add(qid)
    return reachable


def _validate_answer_value(
    question: Mapping[str, Any],
    answer: Mapping[str, Any],
    *,
    response_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    key = stable_response_key(question)
    state = str(answer.get("state"))
    missing = question.get("missing_value_semantics") or {}

    if state != "answered":
        supported = {
            "missing": True,
            "unknown": bool(missing.get("unknown_option_id")),
            "not_applicable": bool(missing.get("not_applicable_option_id")),
            "prefer_not_to_answer": bool(missing.get("prefer_not_to_answer_option_id")),
        }
        if not supported.get(state, False):
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_MISSING_SEMANTICS",
                    f"{state} is not declared for response variable {key}",
                    response_id=response_id,
                    response_key=key,
                )
            )
        return issues

    value = answer.get("value")
    qtype = str(question["question_type"])
    if qtype in {"single_choice", "multiple_choice"}:
        allowed = {
            _stable_option_value(option)
            for option in question.get("response_options", ())
        }
        values = value if qtype == "multiple_choice" else [value]
        if (
            not isinstance(values, list)
            or (
                qtype == "multiple_choice"
                and len(values) != len(set(map(str, values)))
            )
            or any(not isinstance(item, str) or item not in allowed for item in values)
        ):
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_INVALID_CHOICE",
                    f"response variable {key} contains a value outside the stable choice vocabulary",
                    response_id=response_id,
                    response_key=key,
                )
            )
    elif qtype == "scale":
        scale = question.get("scale") or {}
        invalid = (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < scale.get("minimum")
            or value > scale.get("maximum")
        )
        if invalid:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_OUT_OF_RANGE",
                    f"response variable {key} is outside its declared scale range",
                    response_id=response_id,
                    response_key=key,
                )
            )
    elif qtype == "numeric":
        limits = question.get("numeric_constraints") or {}
        invalid = isinstance(value, bool) or not isinstance(value, (int, float))
        if not invalid and limits.get("minimum") is not None:
            invalid = value < limits["minimum"]
        if not invalid and limits.get("maximum") is not None:
            invalid = value > limits["maximum"]
        if invalid:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_OUT_OF_RANGE",
                    f"response variable {key} violates declared numeric constraints",
                    response_id=response_id,
                    response_key=key,
                )
            )
    elif qtype == "free_text" and (not isinstance(value, str) or not value):
        issues.append(
            _issue(
                "SURVEY_RESPONSE_INVALID_TEXT",
                f"response variable {key} requires non-empty text when answered",
                response_id=response_id,
                response_key=key,
            )
        )
    return issues
