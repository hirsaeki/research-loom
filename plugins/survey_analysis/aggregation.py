from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import re
from typing import Any, Mapping, Sequence

from .contracts import (
    aggregate_result_content_digest,
    registry_digest,
    stable_identity,
    validate_aggregate_result,
)

AGGREGATION_IMPLEMENTATION = {
    "implementation_id": "survey_shared_aggregation",
    "version": "0.1.0",
}
_DENOMINATORS = {"all_responses", "asked_responses", "valid_responses"}
_STATES = (
    "answered",
    "missing",
    "unknown",
    "not_applicable",
    "prefer_not_to_answer",
    "not_asked",
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def stable_response_key(question: Mapping[str, Any]) -> str:
    value = question.get("response_key") or question.get("question_id")
    if not isinstance(value, str) or not value:
        raise ValueError("Survey Instrument question lacks a stable response variable")
    return value


def _question_map(questionnaire: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    questions = questionnaire.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Survey Instrument must contain questions")
    result: dict[str, Mapping[str, Any]] = {}
    response_keys: set[str] = set()
    for question in questions:
        if not isinstance(question, Mapping):
            raise ValueError("Survey Instrument question must be an object")
        question_id = str(question.get("question_id", ""))
        response_key = stable_response_key(question)
        if not question_id or question_id in result:
            raise ValueError("Survey Instrument question IDs must be unique")
        if response_key in response_keys:
            raise ValueError("Survey Instrument response variables must be unique")
        result[question_id] = question
        response_keys.add(response_key)
    return result


def _regular_options(question: Mapping[str, Any]) -> list[dict[str, Any]]:
    missing = question.get("missing_value_semantics")
    special_ids: set[str] = set()
    if isinstance(missing, Mapping):
        for field in (
            "unknown_option_id",
            "not_applicable_option_id",
            "prefer_not_to_answer_option_id",
        ):
            value = missing.get(field)
            if isinstance(value, str) and value:
                special_ids.add(value)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in question.get("response_options") or []:
        if not isinstance(option, Mapping):
            raise ValueError("Survey Instrument response option must be an object")
        option_id = str(option.get("option_id", ""))
        if option_id in special_ids:
            continue
        value = option.get("value", option_id)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if encoded in seen:
            raise ValueError("Survey Instrument stable choice values must be unique")
        seen.add(encoded)
        result.append({
            "value": deepcopy(value),
            "label": str(option.get("label", value)),
        })
    return result


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a canonical identifier")
    return value


def _denominator(value: Any) -> str:
    if value is None:
        return "valid_responses"
    if value not in _DENOMINATORS:
        raise ValueError("denominator_rule must be all_responses, asked_responses, or valid_responses")
    return str(value)


def default_analysis_items(questionnaire: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_index = 1
    for question in questionnaire.get("questions") or []:
        qid = str(question["question_id"])
        items.append({
            "item_id": f"AN-{next_index:03d}",
            "analysis_type": "missingness",
            "question_id": qid,
        })
        next_index += 1
        question_type = str(question["question_type"])
        if question_type in {"single_choice", "multiple_choice"}:
            items.append({
                "item_id": f"AN-{next_index:03d}",
                "analysis_type": "frequency",
                "question_id": qid,
                "denominator_rule": "valid_responses",
            })
            next_index += 1
        elif question_type == "scale":
            items.append({
                "item_id": f"AN-{next_index:03d}",
                "analysis_type": "scale_summary",
                "question_id": qid,
                "denominator_rule": "valid_responses",
            })
            next_index += 1
        elif question_type == "free_text":
            items.append({
                "item_id": f"AN-{next_index:03d}",
                "analysis_type": "free_text_listing",
                "question_id": qid,
                "max_rows": 25,
            })
            next_index += 1
    return items


def normalize_analysis_items(
    questionnaire: Mapping[str, Any],
    raw_items: Any,
) -> list[dict[str, Any]]:
    questions = _question_map(questionnaire)
    if raw_items is None:
        return default_analysis_items(questionnaire)
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("analysis_items must be a non-empty array when supplied")

    result: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError("analysis item must be an object")
        analysis_type = str(raw.get("analysis_type", ""))
        item_id = _identifier(raw.get("item_id", f"AN-{index:03d}"), "item_id")
        if item_id in item_ids:
            raise ValueError("analysis item IDs must be unique")
        item_ids.add(item_id)

        if analysis_type in {"frequency", "missingness", "scale_summary", "free_text_listing"}:
            qid = _identifier(raw.get("question_id"), "question_id")
            question = questions.get(qid)
            if question is None:
                raise ValueError(f"unknown Survey question ID: {qid}")
            if analysis_type == "frequency":
                allowed = {"analysis_type", "item_id", "question_id", "denominator_rule"}
                if set(raw) - allowed:
                    raise ValueError("frequency analysis item contains unknown fields")
                if question["question_type"] not in {"single_choice", "multiple_choice"}:
                    raise ValueError("frequency requires a categorical Survey question")
                if not _regular_options(question):
                    raise ValueError("frequency requires at least one ordinary stable choice value")
                result.append({
                    "item_id": item_id,
                    "analysis_type": analysis_type,
                    "question_id": qid,
                    "denominator_rule": _denominator(raw.get("denominator_rule")),
                })
            elif analysis_type == "missingness":
                allowed = {"analysis_type", "item_id", "question_id"}
                if set(raw) - allowed:
                    raise ValueError("missingness analysis item contains unknown fields")
                result.append({
                    "item_id": item_id,
                    "analysis_type": analysis_type,
                    "question_id": qid,
                })
            elif analysis_type == "scale_summary":
                allowed = {"analysis_type", "item_id", "question_id", "denominator_rule"}
                if set(raw) - allowed:
                    raise ValueError("scale_summary analysis item contains unknown fields")
                if question["question_type"] != "scale":
                    raise ValueError("scale_summary requires an Instrument scale question")
                result.append({
                    "item_id": item_id,
                    "analysis_type": analysis_type,
                    "question_id": qid,
                    "denominator_rule": _denominator(raw.get("denominator_rule")),
                })
            else:
                allowed = {"analysis_type", "item_id", "question_id", "max_rows"}
                if set(raw) - allowed:
                    raise ValueError("free_text_listing analysis item contains unknown fields")
                if question["question_type"] != "free_text":
                    raise ValueError("free_text_listing requires an Instrument free_text question")
                max_rows = raw.get("max_rows", 25)
                if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 100:
                    raise ValueError("free_text_listing max_rows must be an integer from 1 through 100")
                result.append({
                    "item_id": item_id,
                    "analysis_type": analysis_type,
                    "question_id": qid,
                    "max_rows": max_rows,
                })
            continue

        if analysis_type == "cross_tab":
            allowed = {"analysis_type", "item_id", "row_question_id", "column_question_id"}
            if set(raw) - allowed:
                raise ValueError("cross_tab analysis item contains unknown fields")
            row_id = _identifier(raw.get("row_question_id"), "row_question_id")
            column_id = _identifier(raw.get("column_question_id"), "column_question_id")
            if row_id == column_id:
                raise ValueError("cross_tab row and column questions must be distinct")
            row = questions.get(row_id)
            column = questions.get(column_id)
            if row is None or column is None:
                raise ValueError("cross_tab references an unknown Survey question ID")
            if row["question_type"] != "single_choice" or column["question_type"] != "single_choice":
                raise ValueError("initial cross_tab support is limited to single_choice x single_choice")
            if not _regular_options(row) or not _regular_options(column):
                raise ValueError("cross_tab requires ordinary stable choice values")
            result.append({
                "item_id": item_id,
                "analysis_type": analysis_type,
                "row_question_id": row_id,
                "column_question_id": column_id,
            })
            continue

        raise ValueError(f"unsupported Survey analysis type: {analysis_type or '<missing>'}")
    return result


def _answer_map(questionnaire: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    questions = _question_map(questionnaire)
    answers = response.get("answers")
    if not isinstance(answers, list):
        raise ValueError("canonical Survey response answers must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for answer in answers:
        if not isinstance(answer, Mapping):
            raise ValueError("canonical Survey response answer must be an object")
        qid = str(answer.get("question_id", ""))
        if qid not in questions or qid in result:
            raise ValueError("canonical Survey response answer/question binding is inconsistent")
        if str(answer.get("response_key", "")) != stable_response_key(questions[qid]):
            raise ValueError("canonical Survey response variable does not match the Instrument")
        if answer.get("state") not in _STATES:
            raise ValueError("canonical Survey response contains an unsupported answer state")
        result[qid] = answer
    if set(result) != set(questions):
        raise ValueError("canonical Survey response must preserve one answer state for every Instrument question")
    return result


def _missingness(answer_maps: Sequence[Mapping[str, Mapping[str, Any]]], question_id: str) -> dict[str, int]:
    counts = {state: 0 for state in _STATES}
    for answers in answer_maps:
        counts[str(answers[question_id]["state"])] += 1
    return counts


def _denominator_counts(missingness: Mapping[str, int]) -> dict[str, int]:
    total = sum(int(missingness[state]) for state in _STATES)
    return {
        "all_responses": total,
        "asked_responses": total - int(missingness["not_asked"]),
        "valid_responses": int(missingness["answered"]),
    }


def _percentage(count: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round((100.0 * count) / denominator, 6)


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _frequency(
    item: Mapping[str, Any],
    question: Mapping[str, Any],
    answer_maps: Sequence[Mapping[str, Mapping[str, Any]]],
    dataset_id: str,
) -> dict[str, Any]:
    qid = str(item["question_id"])
    missingness = _missingness(answer_maps, qid)
    denominators = _denominator_counts(missingness)
    denominator_rule = str(item["denominator_rule"])
    denominator_count = denominators[denominator_rule]
    options = _regular_options(question)
    counts = {_encoded(option["value"]): 0 for option in options}
    multiple = question["question_type"] == "multiple_choice"
    selection_total = 0

    for answers in answer_maps:
        answer = answers[qid]
        if answer["state"] != "answered":
            continue
        value = answer.get("value")
        values = value if multiple else [value]
        if multiple and not isinstance(values, list):
            raise ValueError("accepted multiple_choice answer must contain an array")
        encoded_values = [_encoded(selected) for selected in values]
        if multiple and len(encoded_values) != len(set(encoded_values)):
            raise ValueError("accepted multiple_choice answer cannot repeat a stable choice")
        for encoded_value in encoded_values:
            if encoded_value not in counts:
                raise ValueError("accepted categorical answer is not an ordinary stable Instrument choice")
            counts[encoded_value] += 1
            selection_total += 1

    categories = [
        {
            "value": deepcopy(option["value"]),
            "label": option["label"],
            "count": counts[_encoded(option["value"])],
            "percentage": _percentage(counts[_encoded(option["value"])], denominator_count),
        }
        for option in options
    ]
    result: dict[str, Any] = {
        "item_id": str(item["item_id"]),
        "analysis_type": "frequency",
        "question_id": qid,
        "response_key": stable_response_key(question),
        "question_type": str(question["question_type"]),
        "denominator_rule": denominator_rule,
        "denominator_count": denominator_count,
        "denominator_counts": denominators,
        "missingness": missingness,
        "count_semantics": "selection_count" if multiple else "respondent_count",
        "percentage_semantics": (
            "selection_count / respondent denominator; percentages may sum above 100%"
            if multiple
            else "respondent_count / declared denominator"
        ),
        "categories": categories,
        "provenance": {
            "analysis_item_id": str(item["item_id"]),
            "dataset_id": dataset_id,
            "question_ids": [qid],
        },
    }
    if multiple:
        result["selection_count_total"] = selection_total
    return result


def _missingness_result(
    item: Mapping[str, Any],
    question: Mapping[str, Any],
    answer_maps: Sequence[Mapping[str, Mapping[str, Any]]],
    rejected_answer_maps: Sequence[Mapping[str, Mapping[str, Any]]],
    dataset_id: str,
) -> dict[str, Any]:
    qid = str(item["question_id"])
    return {
        "item_id": str(item["item_id"]),
        "analysis_type": "missingness",
        "question_id": qid,
        "response_key": stable_response_key(question),
        "counts": _missingness(answer_maps, qid),
        "excluded_response_count": len(rejected_answer_maps),
        "provenance": {
            "analysis_item_id": str(item["item_id"]),
            "dataset_id": dataset_id,
            "question_ids": [qid],
        },
    }


def _scale_summary(
    item: Mapping[str, Any],
    question: Mapping[str, Any],
    answer_maps: Sequence[Mapping[str, Mapping[str, Any]]],
    dataset_id: str,
) -> dict[str, Any]:
    qid = str(item["question_id"])
    missingness = _missingness(answer_maps, qid)
    denominators = _denominator_counts(missingness)
    denominator_rule = str(item["denominator_rule"])
    denominator_count = denominators[denominator_rule]
    counts: Counter[str] = Counter()
    originals: dict[str, Any] = {}
    for answers in answer_maps:
        answer = answers[qid]
        if answer["state"] != "answered":
            continue
        encoded = _encoded(answer.get("value"))
        counts[encoded] += 1
        originals[encoded] = deepcopy(answer.get("value"))
    keys = sorted(
        counts,
        key=lambda key: (
            0 if isinstance(originals[key], (int, float)) and not isinstance(originals[key], bool) else 1,
            originals[key] if isinstance(originals[key], (int, float)) and not isinstance(originals[key], bool) else key,
        ),
    )
    return {
        "item_id": str(item["item_id"]),
        "analysis_type": "scale_summary",
        "question_id": qid,
        "response_key": stable_response_key(question),
        "denominator_rule": denominator_rule,
        "denominator_count": denominator_count,
        "denominator_counts": denominators,
        "count": denominators["valid_responses"],
        "missingness": missingness,
        "distribution": [
            {
                "value": originals[key],
                "count": counts[key],
                "percentage": _percentage(counts[key], denominator_count),
            }
            for key in keys
        ],
        "provenance": {
            "analysis_item_id": str(item["item_id"]),
            "dataset_id": dataset_id,
            "question_ids": [qid],
        },
    }


def _free_text_listing(
    item: Mapping[str, Any],
    question: Mapping[str, Any],
    responses: Sequence[Mapping[str, Any]],
    answer_maps: Sequence[Mapping[str, Mapping[str, Any]]],
    dataset_id: str,
) -> dict[str, Any]:
    qid = str(item["question_id"])
    rows: list[dict[str, Any]] = []
    for response, answers in zip(responses, answer_maps):
        answer = answers[qid]
        if answer["state"] != "answered":
            continue
        text = answer.get("value")
        if not isinstance(text, str):
            raise ValueError("accepted free_text answer must contain a string")
        if not text.strip():
            continue
        rows.append({
            "question_id": qid,
            "response_id": str(response["response_id"]),
            "participant_id": str(response["participant_id"]),
            "identity_namespace": str(response["identity_namespace"]),
            "text": text,
            "response_origin": str(response["response_origin"]),
        })
    rows.sort(key=lambda row: (row["identity_namespace"], row["response_id"], row["participant_id"]))
    max_rows = int(item["max_rows"])
    returned = rows[:max_rows]
    return {
        "item_id": str(item["item_id"]),
        "analysis_type": "free_text_listing",
        "question_id": qid,
        "response_key": stable_response_key(question),
        "non_empty_count": len(rows),
        "returned_count": len(returned),
        "truncated": len(rows) > len(returned),
        "rows": returned,
        "provenance": {
            "analysis_item_id": str(item["item_id"]),
            "dataset_id": dataset_id,
            "question_ids": [qid],
        },
    }


def _cross_tab(
    item: Mapping[str, Any],
    row_question: Mapping[str, Any],
    column_question: Mapping[str, Any],
    answer_maps: Sequence[Mapping[str, Mapping[str, Any]]],
    dataset_id: str,
) -> dict[str, Any]:
    row_qid = str(item["row_question_id"])
    column_qid = str(item["column_question_id"])
    row_options = _regular_options(row_question)
    column_options = _regular_options(column_question)
    row_keys = [_encoded(option["value"]) for option in row_options]
    column_keys = [_encoded(option["value"]) for option in column_options]
    counts = {(row_key, column_key): 0 for row_key in row_keys for column_key in column_keys}

    for answers in answer_maps:
        row_answer = answers[row_qid]
        column_answer = answers[column_qid]
        if row_answer["state"] != "answered" or column_answer["state"] != "answered":
            continue
        row_key = _encoded(row_answer.get("value"))
        column_key = _encoded(column_answer.get("value"))
        if (row_key, column_key) not in counts:
            raise ValueError("accepted cross_tab answer is not an ordinary stable Instrument choice")
        counts[(row_key, column_key)] += 1

    row_denominators = {
        row_key: sum(counts[(row_key, column_key)] for column_key in column_keys)
        for row_key in row_keys
    }
    column_denominators = {
        column_key: sum(counts[(row_key, column_key)] for row_key in row_keys)
        for column_key in column_keys
    }
    paired = sum(row_denominators.values())
    return {
        "item_id": str(item["item_id"]),
        "analysis_type": "cross_tab",
        "row_question_id": row_qid,
        "column_question_id": column_qid,
        "pair_denominator_rule": "valid_pairs",
        "pair_denominator_count": paired,
        "column_denominators": [
            {"value": deepcopy(option["value"]), "count": column_denominators[_encoded(option["value"])]}
            for option in column_options
        ],
        "rows": [
            {
                "row_value": deepcopy(row_option["value"]),
                "row_count": row_denominators[_encoded(row_option["value"])],
                "cells": [
                    {
                        "column_value": deepcopy(column_option["value"]),
                        "count": counts[(_encoded(row_option["value"]), _encoded(column_option["value"]))],
                        "row_percentage": _percentage(
                            counts[(_encoded(row_option["value"]), _encoded(column_option["value"]))],
                            row_denominators[_encoded(row_option["value"])],
                        ),
                        "column_percentage": _percentage(
                            counts[(_encoded(row_option["value"]), _encoded(column_option["value"]))],
                            column_denominators[_encoded(column_option["value"])],
                        ),
                    }
                    for column_option in column_options
                ],
            }
            for row_option in row_options
        ],
        "provenance": {
            "analysis_item_id": str(item["item_id"]),
            "dataset_id": dataset_id,
            "question_ids": [row_qid, column_qid],
        },
    }


def aggregate_dataset(
    questionnaire: Mapping[str, Any],
    dataset: Mapping[str, Any],
    accepted_responses: Sequence[Mapping[str, Any]],
    rejected_responses: Sequence[Mapping[str, Any]],
    analysis_spec: Mapping[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    questions = _question_map(questionnaire)
    dataset_id = str(dataset["dataset_id"])
    accepted = sorted(
        (deepcopy(dict(response)) for response in accepted_responses),
        key=lambda response: (str(response["identity_namespace"]), str(response["response_id"])),
    )
    rejected = sorted(
        (deepcopy(dict(response)) for response in rejected_responses),
        key=lambda response: (str(response["identity_namespace"]), str(response["response_id"])),
    )
    answer_maps = [_answer_map(questionnaire, response) for response in accepted]
    rejected_answer_maps = [_answer_map(questionnaire, response) for response in rejected]

    result_items: list[dict[str, Any]] = []
    for item in analysis_spec["analysis_items"]:
        analysis_type = str(item["analysis_type"])
        if analysis_type == "frequency":
            question = questions[str(item["question_id"])]
            result_items.append(_frequency(item, question, answer_maps, dataset_id))
        elif analysis_type == "missingness":
            question = questions[str(item["question_id"])]
            result_items.append(
                _missingness_result(item, question, answer_maps, rejected_answer_maps, dataset_id)
            )
        elif analysis_type == "scale_summary":
            question = questions[str(item["question_id"])]
            result_items.append(_scale_summary(item, question, answer_maps, dataset_id))
        elif analysis_type == "free_text_listing":
            question = questions[str(item["question_id"])]
            result_items.append(
                _free_text_listing(item, question, accepted, answer_maps, dataset_id)
            )
        elif analysis_type == "cross_tab":
            result_items.append(
                _cross_tab(
                    item,
                    questions[str(item["row_question_id"])],
                    questions[str(item["column_question_id"])],
                    answer_maps,
                    dataset_id,
                )
            )
        else:
            raise ValueError(f"unsupported Survey analysis type: {analysis_type}")

    rejected_count = int(dataset["rejected_count"])
    rejected_canonical = len(dataset["rejected_response_refs"])
    warnings: list[dict[str, str]] = []
    if dataset["response_origin"] == "synthetic":
        warnings.append({
            "code": "SURVEY_AGGREGATE_SYNTHETIC_NOT_POPULATION_ESTIMATE",
            "message": (
                "Synthetic Survey aggregation is configuration-dependent test output and is not a population estimate."
            ),
        })

    instrument_ref = deepcopy(dict(dataset["instrument_ref"]))
    document: dict[str, Any] = {
        "schema_version": "0.1.0",
        "object_type": "survey_aggregate_result",
        "project_id": str(dataset["project_id"]),
        "analysis_spec_ref": {
            "id": str(analysis_spec["analysis_spec_id"]),
            "content_digest": str(analysis_spec["content_digest"]),
        },
        "dataset_ref": {
            "id": dataset_id,
            "content_digest": str(dataset["content_digest"]),
        },
        "instrument_ref": instrument_ref,
        "response_origin": str(dataset["response_origin"]),
        "epistemic_status": str(dataset["epistemic_status"]),
        "population": {
            "dataset_response_count": int(dataset["response_count"]),
            "accepted_response_count": int(dataset["accepted_count"]),
            "excluded_response_count": rejected_count,
        },
        "exclusions": {
            "rejected_count": rejected_count,
            "rejected_canonical_response_count": rejected_canonical,
            "rejected_raw_input_count": rejected_count - rejected_canonical,
            "issue_code_counts": deepcopy(dict(dataset["validation_summary"]["issue_code_counts"])),
        },
        "aggregation_implementation": deepcopy(AGGREGATION_IMPLEMENTATION),
        "result_items": result_items,
        "warnings": warnings,
        "provenance": {
            "dataset_id": dataset_id,
            "dataset_digest": str(dataset["content_digest"]),
            "analysis_spec_id": str(analysis_spec["analysis_spec_id"]),
            "analysis_spec_digest": str(analysis_spec["content_digest"]),
            "instrument_id": str(instrument_ref["id"]),
            "instrument_version": str(instrument_ref["version"]),
            "instrument_digest": str(instrument_ref["content_digest"]),
            "source_run_ids": sorted(str(value) for value in dataset.get("source_run_ids", [])),
        },
        "generated_at": generated_at,
        "synthetic_population_estimate_claimed": False,
        "research_state_mutation_performed": False,
    }
    document["content_digest"] = aggregate_result_content_digest(document)
    document["aggregate_result_id"] = stable_identity("SAR-", document["content_digest"])
    document["registry_digest"] = registry_digest(document)
    validate_aggregate_result(document)
    return document
