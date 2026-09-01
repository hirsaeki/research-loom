from __future__ import annotations

from typing import Any, Mapping, Sequence

from .response_support import (
    _RESPONSE_VALIDATOR,
    _answers_by_key,
    _issue,
    _preservation,
    _validate_answer_value,
    reachable_questions,
    stable_response_key,
)

class SurveyResponseValidator:
    """Canonical Survey response validation shared by VIRTUAL and future REAL intake."""

    def validate(
        self,
        questionnaire: Mapping[str, Any],
        records: Sequence[Any],
        *,
        expected_epistemic_mode: str | None = None,
        expected_identity_namespace: str | None = None,
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        preservation: list[dict[str, Any]] = []
        seen_response_ids: set[str] = set()
        seen_participants: set[tuple[str, str]] = set()

        questions = list(questionnaire.get("questions", ()))
        by_key = {stable_response_key(question): question for question in questions}
        by_id = {str(question["question_id"]): question for question in questions}

        for raw in records:
            if not isinstance(raw, Mapping):
                issues.append(_issue("SURVEY_RESPONSE_MALFORMED", "response input is not an object"))
                continue
            response_id = str(raw.get("response_id") or "")
            errors = sorted(
                _RESPONSE_VALIDATOR.iter_errors(raw),
                key=lambda item: tuple(str(part) for part in item.absolute_path),
            )
            if errors:
                error = errors[0]
                path = ".".join(str(part) for part in error.absolute_path) or "$"
                issues.append(
                    _issue(
                        "SURVEY_RESPONSE_MALFORMED",
                        f"{path}: {error.message}",
                        response_id=response_id or None,
                    )
                )
                continue

            if response_id in seen_response_ids:
                issues.append(_issue("SURVEY_RESPONSE_DUPLICATE_RECORD", "response_id is duplicated", response_id=response_id))
            seen_response_ids.add(response_id)

            participant = (str(raw["identity_namespace"]), str(raw["participant_id"]))
            if participant in seen_participants:
                issues.append(
                    _issue(
                        "SURVEY_RESPONSE_DUPLICATE_IDENTITY",
                        "participant identity is duplicated within the same identity namespace",
                        response_id=response_id,
                    )
                )
            seen_participants.add(participant)

            if expected_epistemic_mode is not None and raw["epistemic_mode"] != expected_epistemic_mode:
                issues.append(
                    _issue(
                        "SURVEY_RESPONSE_EPISTEMIC_FIREWALL",
                        "response epistemic mode does not match the execution boundary",
                        response_id=response_id,
                    )
                )
            if expected_identity_namespace is not None and raw["identity_namespace"] != expected_identity_namespace:
                issues.append(
                    _issue(
                        "SURVEY_RESPONSE_IDENTITY_FIREWALL",
                        "response identity namespace does not match the pinned synthetic namespace",
                        response_id=response_id,
                    )
                )

            answers, duplicate_issues = _answers_by_key(raw)
            issues.extend(duplicate_issues)
            for key in sorted(set(answers) - set(by_key)):
                issues.append(
                    _issue(
                        "SURVEY_RESPONSE_UNKNOWN_VARIABLE",
                        f"response variable {key} is not present in the pinned Instrument",
                        response_id=response_id,
                        response_key=key,
                    )
                )

            reachable = reachable_questions(questionnaire, answers)
            for qid, question in by_id.items():
                key = stable_response_key(question)
                answer = answers.get(key)
                if qid not in reachable:
                    if answer is not None:
                        issues.append(
                            _issue(
                                "SURVEY_RESPONSE_BRANCH_VIOLATION",
                                f"response contains an answer for unreachable question {qid}",
                                response_id=response_id,
                                response_key=key,
                            )
                        )
                    continue
                if answer is None or str(answer.get("state")) == "missing":
                    if bool(question.get("required")):
                        issues.append(
                            _issue(
                                "SURVEY_RESPONSE_REQUIRED_MISSING",
                                f"required reachable response variable {key} is missing",
                                response_id=response_id,
                                response_key=key,
                            )
                        )
                    else:
                        preservation.append(
                            _preservation(
                                "optional_missing",
                                response_id=response_id,
                                response_key=key,
                                detail="optional no-response preserved",
                            )
                        )
                    continue
                state = str(answer.get("state"))
                if state in {"unknown", "not_applicable", "prefer_not_to_answer"}:
                    preservation.append(
                        _preservation(
                            state,
                            response_id=response_id,
                            response_key=key,
                            detail=f"explicit {state} state preserved",
                        )
                    )
                issues.extend(_validate_answer_value(question, answer, response_id=response_id))

            status = str(raw["response_status"])
            if status != "complete" or bool(raw["dropout"]):
                preservation.append(
                    _preservation(
                        "partial_or_dropout",
                        response_id=response_id,
                        detail=f"response_status={status}, dropout={bool(raw['dropout'])}",
                    )
                )

        return {
            "schema_version": "0.1.0",
            "validator_id": "survey-response-validation",
            "validator_version": "0.1.0",
            "valid": not any(item["severity"] == "error" for item in issues),
            "issues": issues,
            "preservation_events": preservation,
            "record_count": len(records),
        }
