from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from plugins.local_survey_store import canonical_document_digest
from .facade import LocalApplicationError

HARNESS_OWNED_FIELDS = {
    "project_id", "captured_against", "project_config_digest",
    "effective_profile_set_digest", "captured_at", "registry_digest",
}


def schema_validate(value: Mapping[str, Any], path: Path, code: str) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise LocalApplicationError(code, f"schema violation at {location}: {error.message}")


def input_object(value: Mapping[str, Any], allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalApplicationError(
            "APPLICATION-SURVEY-INPUT-001", f"{label} input must be an object"
        )
    unknown = set(value) - allowed
    if unknown:
        owned = sorted(str(item) for item in unknown if item in HARNESS_OWNED_FIELDS)
        if owned:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-AUTHORITY-001",
                "caller may not supply Harness-owned Survey fields: " + ", ".join(owned),
            )
        raise LocalApplicationError(
            "APPLICATION-SURVEY-INPUT-001",
            f"{label} input contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown)),
        )
    return deepcopy(dict(value))


def required_string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise LocalApplicationError(
            "APPLICATION-SURVEY-INPUT-001", f"{field} must be a non-empty string"
        )
    return item


def capture_origin(value: Mapping[str, Any]) -> str:
    origin = value.get("capture_origin", "operator_conversation")
    if not isinstance(origin, str) or not origin.strip():
        raise LocalApplicationError(
            "APPLICATION-SURVEY-INPUT-001", "capture_origin must be a non-empty string"
        )
    return origin


def string_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001", f"{field} is required"
            )
        return []
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
        or (required and not value)
    ):
        raise LocalApplicationError(
            "APPLICATION-SURVEY-INPUT-001",
            f"{field} must be an array of unique non-empty strings",
        )
    return list(value)


def validate_digest(document: Mapping[str, Any], field: str, code: str) -> None:
    try:
        expected = canonical_document_digest(document, field)
    except Exception as exc:
        raise LocalApplicationError(code, f"{field} content is not canonicalizable") from exc
    if document.get(field) != expected:
        raise LocalApplicationError(code, f"{field} does not match canonical content")


def validate_rqs(rq_ids: list[str], state) -> None:
    authoritative = {
        str(obj["id"])
        for obj in state.effective_objects()
        if obj.get("kind") == "research_question"
        and str(obj.get("project_id", state.project_ref)) == state.project_ref
        and obj.get("adoption_state") == "approved"
    }
    missing = sorted(set(rq_ids) - authoritative)
    if missing:
        raise LocalApplicationError(
            "APPLICATION-SURVEY-RQ-001",
            "Survey RQ binding is not current authoritative Research State: "
            + ", ".join(missing),
        )


def validate_questionnaire(
    questionnaire: Mapping[str, Any],
    design_record: Mapping[str, Any],
    state,
) -> None:
    questions = list(questionnaire.get("questions", []))
    ids = [str(question.get("question_id")) for question in questions]
    variables = [
        str(question.get("response_key", question.get("question_id")))
        for question in questions
    ]
    if len(ids) != len(set(ids)) or len(variables) != len(set(variables)):
        raise LocalApplicationError(
            "APPLICATION-SURVEY-QUESTIONNAIRE-001",
            "question_id and response variable identities must be unique",
        )
    id_set = set(ids)
    question_by_id = {
        str(question["question_id"]): question for question in questions
    }
    sections = list(questionnaire.get("sections") or [])
    section_ids = [str(item.get("section_id")) for item in sections]
    if len(section_ids) != len(set(section_ids)):
        raise LocalApplicationError(
            "APPLICATION-SURVEY-QUESTIONNAIRE-001", "section_id must be unique"
        )
    section_set = set(section_ids)
    design_rqs = set(str(item) for item in design_record["rq_ids"])
    traced: set[str] = set()

    for question in questions:
        question_id = str(question.get("question_id"))
        q_rqs = {
            str(item)
            for item in (question.get("traceability") or {}).get(
                "research_question_ids", []
            )
        }
        traced.update(q_rqs)
        if not q_rqs <= design_rqs:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RQ-001",
                "Questionnaire RQ traceability must stay within the bound Survey Design RQs",
            )
        if sections and question.get("section_id") not in section_set:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                f"question section_id does not resolve: {question_id}",
            )

        options = list(question.get("response_options", []))
        option_ids = [str(item.get("option_id")) for item in options]
        option_values = [
            str(item.get("value", item.get("option_id"))) for item in options
        ]
        if (
            len(option_ids) != len(set(option_ids))
            or len(option_values) != len(set(option_values))
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                f"response option identity/value must be unique for {question_id}",
            )
        option_id_set = set(option_ids)
        missing = question.get("missing_value_semantics")
        if isinstance(missing, Mapping):
            semantic_option_ids = []
            for field in (
                "unknown_option_id",
                "not_applicable_option_id",
                "prefer_not_to_answer_option_id",
            ):
                option_id = missing.get(field)
                if option_id is not None:
                    semantic_option_ids.append(str(option_id))
                    if str(option_id) not in option_id_set:
                        raise LocalApplicationError(
                            "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                            f"{field} does not resolve to a response option for {question_id}",
                        )
            if len(semantic_option_ids) != len(set(semantic_option_ids)):
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                    f"explicit missing-value categories must use distinct response options for {question_id}",
                )

        for branch in question.get("branching", []):
            condition = str(branch.get("condition_question_id"))
            target = branch.get("target_question_id")
            if condition not in id_set or (
                target is not None and str(target) not in id_set
            ):
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-BRANCH-001",
                    "branch question reference does not resolve",
                )
            if branch.get("action") in {"show", "skip"} and target is None:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-BRANCH-001",
                    "show/skip branching requires target_question_id",
                )
            condition_options = list(
                question_by_id[condition].get("response_options", [])
            )
            if (
                condition_options
                and branch.get("operator") in {"equals", "not_equals", "contains"}
                and "value" in branch
            ):
                stable_values = {
                    str(option.get("value", option["option_id"]))
                    for option in condition_options
                }
                if str(branch["value"]) not in stable_values:
                    raise LocalApplicationError(
                        "APPLICATION-SURVEY-BRANCH-001",
                        "branch choice condition must use the condition question's stable response value",
                    )

    validate_rqs(sorted(traced), state)
