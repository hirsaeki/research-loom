from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from plugins.survey_virtual_runner.response_support import reachable_questions, stable_response_key
from plugins.survey_virtual_runner.response_validation import SurveyResponseValidator

from .contracts import (
    RAW_RESPONSE_VALIDATOR,
    preserve_raw_input,
    registry_digest,
    response_content_digest,
    schema_issues,
    validate_canonical_response,
)

_CANONICAL_STATES = {
    "answered",
    "missing",
    "unknown",
    "not_applicable",
    "prefer_not_to_answer",
    "not_asked",
}


def _issue(
    code: str,
    message: str,
    *,
    response_id: str | None = None,
    response_key: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if response_id:
        value["response_id"] = response_id
    if response_key:
        value["response_key"] = response_key
    return value


def _normalization_event(code: str, detail: str, *, response_key: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "detail": detail}
    if response_key:
        value["response_key"] = response_key
    return value


def _stable_option_value(option: Mapping[str, Any]) -> str:
    value = option.get("value")
    return str(value) if isinstance(value, str) and value else str(option["option_id"])


def _alias_map(questionnaire: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = {}
    for question in questionnaire.get("questions", ()):
        for alias in {str(question["question_id"]), stable_response_key(question)}:
            result.setdefault(alias, []).append(question)
    return result


def _choice_value(
    question: Mapping[str, Any],
    value: Any,
    *,
    response_key: str,
    events: list[dict[str, Any]],
) -> Any:
    qtype = str(question["question_type"])
    if qtype not in {"single_choice", "multiple_choice"}:
        return value
    options = list(question.get("response_options", ()))
    stable = {_stable_option_value(option) for option in options}
    labels: dict[str, list[str]] = {}
    for option in options:
        labels.setdefault(str(option.get("label", "")), []).append(_stable_option_value(option))

    def one(item: Any) -> Any:
        if not isinstance(item, str) or item in stable:
            return item
        matches = labels.get(item, [])
        if len(matches) == 1:
            events.append(
                _normalization_event(
                    "SURVEY_RESPONSE_LABEL_MAPPED",
                    f"display label was mapped to the Instrument stable value {matches[0]}",
                    response_key=response_key,
                )
            )
            return matches[0]
        return item

    if qtype == "multiple_choice" and isinstance(value, list):
        return [one(item) for item in value]
    return one(value)


def _normalize_raw_answer(
    question: Mapping[str, Any],
    raw_answer: Any,
    *,
    response_id: str,
    events: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    key = stable_response_key(question)
    if isinstance(raw_answer, Mapping) and "state" in raw_answer:
        state = str(raw_answer.get("state"))
        if state not in _CANONICAL_STATES:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_INVALID_MISSING_STATE",
                    f"response state {state!r} is not canonical",
                    response_id=response_id,
                    response_key=key,
                )
            )
            return {"question_id": str(question["question_id"]), "response_key": key, "state": "missing"}
        answer = {"question_id": str(question["question_id"]), "response_key": key, "state": state}
        if state == "answered":
            answer["value"] = _choice_value(
                question,
                raw_answer.get("value"),
                response_key=key,
                events=events,
            )
        return answer
    if raw_answer is None:
        issues.append(
            _issue(
                "SURVEY_RESPONSE_INVALID_MISSING_STATE",
                "null is ambiguous at the provider-neutral boundary; missing state must be explicit",
                response_id=response_id,
                response_key=key,
            )
        )
        return {"question_id": str(question["question_id"]), "response_key": key, "state": "missing"}
    return {
        "question_id": str(question["question_id"]),
        "response_key": key,
        "state": "answered",
        "value": _choice_value(question, raw_answer, response_key=key, events=events),
    }


def _compatibility_record(response: Mapping[str, Any]) -> dict[str, Any]:
    answers = []
    for answer in response["answers"]:
        if answer["state"] == "not_asked":
            continue
        item = {"response_key": answer["response_key"], "state": answer["state"]}
        if "value" in answer:
            item["value"] = deepcopy(answer["value"])
        answers.append(item)
    raw_digest = str(response["raw_input_digest"]).split(":", 1)[-1]
    return {
        "schema_version": "0.1.0",
        "object_type": "survey_response_record",
        "response_id": response["response_id"],
        "raw_data_ref_id": f"RAW-{raw_digest[:32]}",
        "participant_id": response["participant_id"],
        "identity_namespace": response["identity_namespace"],
        "epistemic_mode": "virtual" if response["response_origin"] == "synthetic" else "empirical",
        "synthetic": response["response_origin"] == "synthetic",
        "response_status": response["response_status"],
        "eligibility_status": "eligible",
        "duplicate_disposition": "not_duplicate",
        "verified_evidence_claimed": False,
        "dropout": response["dropout"],
        "answers": answers,
        **({"response_timestamp": response["completed_at"]} if response.get("completed_at") else {}),
    }


def normalize_response(
    questionnaire: Mapping[str, Any],
    raw: Any,
    *,
    project_id: str,
    instrument_ref: Mapping[str, Any],
    response_origin: str,
    epistemic_status: str,
    ingested_at: str,
    source_run_id: str | None = None,
    source_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    malformed = schema_issues(RAW_RESPONSE_VALIDATOR, raw)
    preserved_raw, raw_digest, canonicalization_issue = preserve_raw_input(raw)
    if canonicalization_issue is not None:
        malformed.append(canonicalization_issue)
    if malformed:
        return {
            "raw_input_digest": raw_digest,
            "raw_input": preserved_raw,
            "canonical_response": None,
            "issues": malformed,
        }

    raw = deepcopy(dict(raw))
    response_id = str(raw["response_id"])
    participant_id = str(raw["participant_id"])
    identity_namespace = str(raw["identity_namespace"])
    issues: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    if response_origin == "synthetic":
        if epistemic_status != "SYNTHETIC_TEST_ONLY" or not identity_namespace.startswith("synthetic:"):
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                    "synthetic responses require a synthetic:* identity namespace and SYNTHETIC_TEST_ONLY epistemic status",
                    response_id=response_id,
                )
            )
    elif response_origin == "real":
        if epistemic_status != "EMPIRICAL" or not identity_namespace.startswith("real:"):
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                    "real responses require a real:* identity namespace and EMPIRICAL epistemic status",
                    response_id=response_id,
                )
            )
    else:
        issues.append(_issue("SURVEY_RESPONSE_ORIGIN_MISMATCH", "response_origin must be synthetic or real", response_id=response_id))

    aliases = _alias_map(questionnaire)
    provided: dict[str, dict[str, Any]] = {}
    for raw_key in sorted(raw["answers"]):
        matches = aliases.get(str(raw_key), [])
        if not matches:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_UNKNOWN_VARIABLE",
                    f"response variable {raw_key} is not present in the pinned Instrument",
                    response_id=response_id,
                    response_key=str(raw_key),
                )
            )
            continue
        unique = {str(item["question_id"]): item for item in matches}
        if len(unique) != 1:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_AMBIGUOUS_VARIABLE",
                    f"response variable {raw_key} ambiguously resolves in the pinned Instrument",
                    response_id=response_id,
                    response_key=str(raw_key),
                )
            )
            continue
        question = next(iter(unique.values()))
        qid = str(question["question_id"])
        if qid in provided:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_DUPLICATE_VARIABLE",
                    f"multiple raw keys resolve to response variable {stable_response_key(question)}",
                    response_id=response_id,
                    response_key=stable_response_key(question),
                )
            )
            continue
        provided[qid] = _normalize_raw_answer(
            question,
            raw["answers"][raw_key],
            response_id=response_id,
            events=events,
            issues=issues,
        )

    compatibility_answers = {
        item["response_key"]: {
            "response_key": item["response_key"],
            "state": item["state"],
            **({"value": deepcopy(item["value"])} if "value" in item else {}),
        }
        for item in provided.values()
        if item["state"] != "not_asked"
    }
    reachable = reachable_questions(questionnaire, compatibility_answers)
    answers: list[dict[str, Any]] = []
    for question in questionnaire.get("questions", ()):
        qid = str(question["question_id"])
        key = stable_response_key(question)
        answer = provided.get(qid)
        if answer is None:
            answer = {
                "question_id": qid,
                "response_key": key,
                "state": "missing" if qid in reachable else "not_asked",
            }
        elif answer["state"] == "not_asked" and qid in reachable:
            issues.append(
                _issue(
                    "SURVEY_RESPONSE_BRANCH_VIOLATION",
                    f"reachable response variable {key} cannot be marked not_asked",
                    response_id=response_id,
                    response_key=key,
                )
            )
        answers.append(answer)

    source = deepcopy(dict(source_provenance or {}))
    record_provenance = raw.get("provenance")
    if isinstance(record_provenance, Mapping):
        source["producer"] = deepcopy(dict(record_provenance))

    response: dict[str, Any] = {
        "schema_version": "0.1.0",
        "object_type": "survey_response",
        "project_id": project_id,
        "response_id": response_id,
        "instrument_ref": deepcopy(dict(instrument_ref)),
        "participant_id": participant_id,
        "identity_namespace": identity_namespace,
        "response_origin": response_origin,
        "epistemic_status": epistemic_status,
        "response_status": str(raw.get("response_status", "complete")),
        "dropout": bool(raw.get("dropout", False)),
        "answers": answers,
        "ingested_at": ingested_at,
        "source_provenance": source,
        "raw_input_digest": raw_digest,
        "normalization_events": events,
        "validation": {"status": "accepted", "issues": [], "preservation_events": []},
        "verified_evidence_claimed": False,
        "research_state_mutation_performed": False,
    }
    if raw.get("started_at"):
        response["started_at"] = raw["started_at"]
    if raw.get("completed_at"):
        response["completed_at"] = raw["completed_at"]
    if source_run_id:
        response["source_run_id"] = source_run_id

    compat = _compatibility_record(response)
    validation = SurveyResponseValidator().validate(
        questionnaire,
        [compat],
        expected_epistemic_mode="virtual" if response_origin == "synthetic" else "empirical",
        expected_identity_namespace=identity_namespace,
    )
    combined = list(issues) + list(validation["issues"])
    response["validation"] = {
        "status": "rejected" if any(item.get("severity") == "error" for item in combined) else "accepted",
        "issues": combined,
        "preservation_events": deepcopy(list(validation["preservation_events"])),
    }
    response["content_digest"] = response_content_digest(response)
    response["registry_digest"] = registry_digest(response)

    try:
        validate_canonical_response(response)
    except ValueError as exc:
        schema_issue = _issue(
            "SURVEY_RESPONSE_MALFORMED",
            f"canonical response could not be formed: {exc}",
            response_id=response_id,
        )
        return {
            "raw_input_digest": raw_digest,
            "raw_input": deepcopy(raw),
            "canonical_response": None,
            "issues": combined + [schema_issue],
        }
    return {
        "raw_input_digest": raw_digest,
        "raw_input": deepcopy(raw),
        "canonical_response": response,
        "issues": combined,
    }


def append_rejection_issue(response: Mapping[str, Any], issue: Mapping[str, Any]) -> dict[str, Any]:
    value = deepcopy(dict(response))
    validation = deepcopy(dict(value["validation"]))
    validation["issues"] = list(validation["issues"]) + [deepcopy(dict(issue))]
    validation["status"] = "rejected"
    value["validation"] = validation
    value["content_digest"] = response_content_digest(value)
    value["registry_digest"] = registry_digest(value)
    validate_canonical_response(value)
    return value


def virtual_record_to_raw(record: Any) -> Any:
    if not isinstance(record, Mapping):
        return deepcopy(record)
    required = {"response_id", "participant_id", "identity_namespace", "answers"}
    if not required <= set(record):
        return deepcopy(record)
    answers: dict[str, Any] = {}
    for answer in record.get("answers", ()):
        if not isinstance(answer, Mapping) or not answer.get("response_key") or not answer.get("state"):
            return deepcopy(record)
        state = str(answer["state"])
        if state == "answered":
            answers[str(answer["response_key"])] = deepcopy(answer.get("value"))
        else:
            answers[str(answer["response_key"])] = {"state": state}
    result: dict[str, Any] = {
        "response_id": str(record["response_id"]),
        "participant_id": str(record["participant_id"]),
        "identity_namespace": str(record["identity_namespace"]),
        "response_status": str(record.get("response_status", "complete")),
        "dropout": bool(record.get("dropout", False)),
        "answers": answers,
        "provenance": {
            "producer_shape": "survey_response_record@0.1.0",
            **(
                deepcopy(dict(record["producer_provenance"]))
                if isinstance(record.get("producer_provenance"), Mapping)
                else {}
            ),
        },
    }
    if record.get("response_timestamp"):
        result["completed_at"] = str(record["response_timestamp"])
    return result
