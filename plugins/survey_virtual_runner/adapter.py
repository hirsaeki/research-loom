from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from core.conversation.validation import canonical_digest
from core.execution import CapabilityExecutionOutput, ExecutionStyle
from core.execution.models import CapabilityExecutionError, ExecutionFailureCode

from .contracts import document_digest, validate_virtual_document
from .digest import file_digest, text_digest
from .response_validation import SurveyResponseValidator, reachable_questions, stable_response_key


ROOT = Path(__file__).resolve().parents[2]
RUNNER_VERSION = "0.1.0"
IMPLEMENTATION_ID = "plugin.survey-virtual-runner.structural"
IMPLEMENTATION_VERSION = "0.1.0"
STRUCTURAL_TEMPLATE_VERSION = "1.0.0"
STRUCTURAL_TEMPLATE = (
    "Structural Survey generator v1: use only declared stable choice values, declared "
    "numeric/scale bounds, explicit missing-value states, and synthetic text placeholders; "
    "inject only explicitly configured structural STRESS faults."
)
RESPONSE_SCHEMA_PATH = ROOT / "core/packages/survey/survey-response.schema.json"
SURVEY_SCHEMA_PATH = ROOT / "core/packages/survey/survey-contract.schema.json"
VR_SCHEMA_PATH = ROOT / "core/packages/virtual-runner/virtual-runner-contract.schema.json"

FAULT_TO_CODES = {
    "required_missing": {"SURVEY_RESPONSE_REQUIRED_MISSING"},
    "optional_missing": set(),
    "invalid_choice": {"SURVEY_RESPONSE_INVALID_CHOICE", "SURVEY_RESPONSE_BRANCH_VIOLATION"},
    "out_of_range_scale": {"SURVEY_RESPONSE_OUT_OF_RANGE"},
    "branch_violation": {"SURVEY_RESPONSE_BRANCH_VIOLATION"},
    "duplicate_record": {"SURVEY_RESPONSE_DUPLICATE_RECORD", "SURVEY_RESPONSE_DUPLICATE_IDENTITY"},
    "duplicate_identity": {"SURVEY_RESPONSE_DUPLICATE_IDENTITY"},
    "partial_completion": set(),
    "malformed_response": {"SURVEY_RESPONSE_MALFORMED"},
    "extreme_valid": set(),
    "unknown": set(),
    "not_applicable": set(),
    "prefer_not_to_answer": set(),
}
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
    "partial_completion",
    "malformed_response",
    "extreme_valid",
)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "-" for character in value)[:120]


def _answer_value(question: Mapping[str, Any], *, extreme: bool = False) -> Any:
    qtype = str(question["question_type"])
    if qtype in {"single_choice", "multiple_choice"}:
        options = list(question.get("response_options", ()))
        if not options:
            return None
        stable = [
            str(option.get("value") or option["option_id"])
            for option in options
        ]
        return [stable[-1] if extreme else stable[0]] if qtype == "multiple_choice" else (stable[-1] if extreme else stable[0])
    if qtype == "scale":
        scale = question.get("scale") or {}
        return scale.get("maximum") if extreme else scale.get("minimum")
    if qtype == "numeric":
        limits = question.get("numeric_constraints") or {}
        if extreme and limits.get("maximum") is not None:
            return limits["maximum"]
        return limits["minimum"] if limits.get("minimum") is not None else 0
    return "SYNTHETIC_TEXT_001"


def _base_record(
    questionnaire: Mapping[str, Any],
    *,
    response_id: str,
    raw_data_ref_id: str,
    participant_id: str,
    identity_namespace: str,
    variant: int,
    extreme: bool = False,
) -> dict[str, Any]:
    answers: list[dict[str, Any]] = []
    partial_map: dict[str, Mapping[str, Any]] = {}
    questions = list(questionnaire.get("questions", ()))
    for index, question in enumerate(questions):
        key = stable_response_key(question)
        qtype = str(question["question_type"])
        missing = question.get("missing_value_semantics") or {}

        # Explicit missing categories are exercised only when declared. Keep the first
        # respondent on the normal stable path so branches have a deterministic baseline.
        if variant > 0 and index == 0:
            for state, field in (
                ("unknown", "unknown_option_id"),
                ("not_applicable", "not_applicable_option_id"),
                ("prefer_not_to_answer", "prefer_not_to_answer_option_id"),
            ):
                if missing.get(field) and variant % 4 == {"unknown": 1, "not_applicable": 2, "prefer_not_to_answer": 3}[state]:
                    answer = {"response_key": key, "state": state}
                    answers.append(answer)
                    partial_map[key] = answer
                    break
            else:
                answer = {"response_key": key, "state": "answered", "value": _answer_value(question, extreme=extreme)}
                answers.append(answer)
                partial_map[key] = answer
        else:
            answer = {"response_key": key, "state": "answered", "value": _answer_value(question, extreme=extreme)}
            answers.append(answer)
            partial_map[key] = answer

        reachable = reachable_questions(questionnaire, partial_map)
        if str(question["question_id"]) not in reachable:
            answers.pop()
            partial_map.pop(key, None)

    # Standard optional missingness: preserve one optional no-response without
    # collapsing it into any explicit unknown/not-applicable category.
    optional = [
        question for question in questions
        if not bool(question.get("required"))
        and str(question["question_id"]) in reachable_questions(
            questionnaire, {str(answer["response_key"]): answer for answer in answers}
        )
    ]
    if optional and variant % 2 == 1 and not extreme:
        target = stable_response_key(optional[-1])
        answers = [answer for answer in answers if answer["response_key"] != target]
        answers.append({"response_key": target, "state": "missing"})

    return {
        "schema_version": "0.1.0",
        "object_type": "survey_response_record",
        "response_id": response_id,
        "raw_data_ref_id": raw_data_ref_id,
        "participant_id": participant_id,
        "identity_namespace": identity_namespace,
        "epistemic_mode": "virtual",
        "synthetic": True,
        "response_status": "complete",
        "eligibility_status": "eligible",
        "duplicate_disposition": "not_duplicate",
        "verified_evidence_claimed": False,
        "dropout": False,
        "answers": answers,
    }


def _find_question(questionnaire, predicate):
    for question in questionnaire.get("questions", ()):
        if predicate(question):
            return question
    return None


def _answer(record: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    for item in record.get("answers", ()):
        if isinstance(item, Mapping) and item.get("response_key") == key:
            return item
    return None


def _replace_answer(record: dict[str, Any], key: str, answer: Mapping[str, Any] | None) -> None:
    record["answers"] = [
        item for item in record.get("answers", ())
        if not isinstance(item, Mapping) or item.get("response_key") != key
    ]
  ²È="24€€€€€€€€€€™½È¥Ñ•´¥¸É•ÅÕ•ÍÐ¹½¹Ñ•áÑ}Á…­l‰ÁÉ½©•Ñ}½¹ÍÑÉ…¥¹ÑÌ‰umÉ½ÕÁt(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€€€€€€‰•™™•Ñ¥Ù•}½¹ÍÑÉ…¥¹Ñ}Á…Ñ¡Ìˆèl(€€€€€€€€€€€€€€€€€€€ÍÑÈ¡¥Ñ•µl‰Á…Ñ ‰t¤™½È¥Ñ•´¥¸É•ÅÕ•ÍÐ¹½¹Ñ•áÑ}Á…­l‰•™™•Ñ¥Ù•}½¹ÍÑÉ…¥¹ÑÌ‰t(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰Ù…±¥‘…Ñ¥½¸ˆèì‰ÍÑ…ÑÕÌˆè€‰Ù…±¥ˆ°€‰¥ÍÍÕ•Ìˆèmuô°(€€€€€€€€€€€€‰½ÕÑÁÕÑÌˆèì(€€€€€€€€€€€€€€€€‰½‰Í•ÉÙ…Ñ¥½¹Ìˆèmt°(€€€€€€€€€€€€€€€€‰Í½ÕÉ•}…ÁÑÕÉ•Ìˆèmt°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}…¹‘¥‘…Ñ•Ìˆèmt°(€€€€€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}™¥¹‘¥¹Ìˆèmt°(€€€€€€€€€€€€€€€€‰½Õ¹Ñ•É•Ù¥‘•¹”ˆèmt°(€€€€€€€€€€€€€€€€‰½¹™±¥ÑÌˆèmt°(€€€€€€€€€€€€€€€€‰Õ¹­¹½Ý¹Ìˆèmt°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}…ÁÌˆèmt°(€€€€€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}¹•áÑ}…Ñ¥½¹Ìˆèm¹•áÑ}…Ñ¥½¹t°(€€€€€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}¹•áÑ}µ•Ñ¡½‘Ìˆèmt°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰ÁÉ½Ù•¹…¹”ˆèì(€€€€€€€€€€€€€€€€‰ÑÉ…•}¥ˆèÍÑÈ¡É•ÅÕ•ÍÐ¹¥¹Ù½…Ñ¥½¹l‰ÑÉ…”‰ul‰ÑÉ…•}¥‰t¤°(€€€€€€€€€€€€€€€€‰ÁÉ½‘Õ•‘}…ÐˆèÍ•±˜¹}±½¬¹¹½Ü ¤°(€€€€€€€€€€€€€€€€‰¥µÁ±•µ•¹Ñ…Ñ¥½¹}¥ˆè%5A159QQ%=9}%°(€€€€€€€€€€€€€€€€‰¥µÁ±•µ•¹Ñ…Ñ¥½¹}Ù•ÉÍ¥½¸ˆè%5A159QQ%=9}YIM%=8°(€€€€€€€€€€€€€€€€‰¥¹ÁÕÑ}½¹Ñ•¹Ñ}‘¥•ÍÑÌˆèl(€€€€€€€€€€€€€€€€€€€É•ÅÕ•ÍÐ¹ÉÕ¸¹¥¹Ù½…Ñ¥½¹}‘¥•ÍÐ°(€€€€€€€€€€€€€€€€€€€É•ÅÕ•ÍÐ¹ÉÕ¸¹½¹Ñ•áÑ}Á…­}‘¥•ÍÐ°(€€€€€€€€€€€€€€€€€€€ÍÑÈ¡•áÑ•¹Í¥½¹l‰¥¹ÍÑÉÕµ•¹Ñ}É•˜‰ul‰½¹Ñ•¹Ñ}‘¥•ÍÐ‰t¤°(€€€€€€€€€€€€€€€€€€€ÍÑÈ¡•áÑ•¹Í¥½¹l‰‘•Í¥¹}É•˜‰ul‰½¹Ñ•¹Ñ}‘¥•ÍÐ‰t¤°(€€€€€€€€€€€€€€€€€€€ÍÑÈ¡•áÑ•¹Í¥½¹l‰ÉÕ¹}ÍÁ•Œ‰ul‰½¹Ñ•¹Ñ}‘¥•ÍÐ‰t¤°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰…‘½ÁÑ¥½¹}‰½Õ¹‘…Éäˆèì(€€€€€€€€€€€€€€€€‰É•Í•…É¡}ÍÑ…Ñ•}µÕÑ…Ñ¥½¹}Á•É™½Éµ•ˆè…±Í”°(€€€€€€€€€€€€€€€€‰½ÕÑÁÕÑÍ}…É•}…¹‘¥‘…Ñ•ÌˆèQÉÕ”°(€€€€€€€€€€€€€€€€‰¡Õµ…¹}‘•¥Í¥½¹}É•ÅÕ¥É•‘}™½É}…ÕÑ¡½É¥Ñ…Ñ¥Ù•}ÑÉ…¹Í¥Ñ¥½¸ˆèQÉÕ”°(€€€€€€€€€€€ô°(€€€€€€€ô(€€€€€€€¡…¹‘½™™l‰¡…¹‘½™™}‘¥•ÍÐ‰t€ô‘½Õµ•¹Ñ}‘¥•ÍÐ¡¡…¹‘½™˜°€‰¡…¹‘½™™}‘¥•ÍÐˆ¤((€€€€€€€ÙÉ}É•ÍÕ±Ð€ôì(€€€€€€€€€€€€‰Í¡•µ…}Ù•ÉÍ¥½¸ˆè€ˆÀ¸Ä¸Àˆ°(€€€€€€€€€€€€‰½‰©•Ñ}ÑåÁ”ˆè€‰Ù¥ÉÑÕ…±}ÉÕ¹¹•É}É•ÍÕ±Ðˆ°(€€€€€€€€€€€€‰¡…¹‘½™™}‰¥¹‘¥¹œˆèì(€€€€€€€€€€€€€€€€‰¡…¹‘½™™}¥ˆè¡…¹‘½™™l‰¡…¹‘½™™}¥‰t°(€€€€€€€€€€€€€€€€‰¡…¹‘½™™}‘¥•ÍÐˆè¡…¹‘½™™l‰¡…¹‘½™™}‘¥•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰¥¹Ù½…Ñ¥½¹}¥ˆèÉ•ÅÕ•ÍÐ¹ÉÕ¸¹¥¹Ù½…Ñ¥½¹}¥°(€€€€€€€€€€€€€€€€‰ÉÕ¹}¥ˆèÉ•ÅÕ•ÍÐ¹ÉÕ¸¹ÉÕ¹}¥°(€€€€€€€€€€€€€€€€‰½¹Ñ•áÑ}Á…­}¥ˆèÉ•ÅÕ•ÍÐ¹ÉÕ¸¹½¹Ñ•áÑ}Á…­}¥°(€€€€€€€€€€€€€€€€‰½¹Ñ•áÑ}Á…­}‘¥•ÍÐˆèÉ•ÅÕ•ÍÐ¹ÉÕ¸¹½¹Ñ•áÑ}Á…­}‘¥•ÍÐ°(€€€€€€€€€€€€€€€€‰…Á…‰¥±¥Ñå}¥ˆè€‰Ù¥ÉÑÕ…°µÉÕ¹¹•Èˆ°(€€€€€€€€€€€€€€€€‰™Õ¹Ñ¥½¹}¥ˆè€‰•á•ÕÑ”ˆ°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰Í•¹…É¥½}±…ÍÌˆèÍ•¹…É¥¼°(€€€€€€€€€€€€‰•Ù¥‘•¹•}ÍÑ…ÑÕÌˆè€‰Me9Q!Q%}QMQ}=91dˆ°(€€€€€€€€€€€€‰½µÁ±•Ñ¥½¹}ÍÑ…ÑÕÌˆè€‰½µÁ±•Ñ”ˆ°(€€€€€€€€€€€€‰Íå¹Ñ¡•Ñ¥}½ÕÑÁÕÑÌˆèmì(€€€€€€€€€€€€€€€€‰½ÕÑÁÕÑ}¥ˆèÉ•ÍÁ½¹Í•}…ÉÑ¥™…Ð¹…ÉÑ¥™…Ñ}¥°(€€€€€€€€€€€€€€€€‰­¥¹ˆè€‰É…Ý}‘…Ñ„ˆ°(€€€€€€€€€€€€€€€€‰¥‘•¹Ñ¥Ñå}¹…µ•ÍÁ…”ˆè¥‘•¹Ñ¥Ñå}¹…µ•ÍÁ…”°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹Ñ}‘¥•ÍÐˆèÉ•ÍÁ½¹Í•}…ÉÑ¥™…Ð¹‘¥•ÍÐ°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}ÍÑ…ÑÕÌˆè€‰Me9Q!Q%}QMQ}=91dˆ°(€€€€€€€€€€€€€€€€‰•µÁ¥É¥…±}…‘½ÁÑ¥½¹}Á•É™½Éµ•ˆè…±Í”°(€€€€€€€€€€€õt°(€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}…¹…±åÍ•Ìˆèmt°(€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}™¥¹‘¥¹Ìˆèmt°(€€€€€€€€€€€€‰‘•™•ÑÌˆè‘•™•ÑÌ°(€€€€€€€€€€€€‰Ý…É¹¥¹ÌˆèÝ…É¹¥¹Ì°(€€€€€€€€€€€€‰Õ¹É•Í½±Ù•‘}…µ‰¥Õ¥Ñ¥•Ìˆèmt°(€€€€€€€€€€€€‰¡Õµ…¹}…Ñ•}É•ÅÕ¥É•µ•¹ÑÌˆèl(€€€€€€€€€€€€€€€€‰É•…‘¥¹•ÍÌ¥Ì…¹‘¥‘…Ñ”µ½¹±ä…¹‘½•Ì¹½Ð…ÕÑ¡½É¥é”½ÈÍÑ…ÉÐI0MÕÉÙ•ä•á•ÕÑ¥½¸ˆ(€€€€€€€€€€€t°(€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}¡…¹•}É•ÅÕ•ÍÑÌˆèl(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰¡…¹•}É•ÅÕ•ÍÑ}¥ˆè˜‰YI!µí}Í…™•}¥¡É•ÅÕ•ÍÐ¹ÉÕ¸¹ÉÕ¹}¥¥ôµí¥¹‘•àèÀÍ‘ôˆ°(€€€€€€€€€€€€€€€€€€€€‰Ñ…É•Ñ}É•˜ˆè‘•™•Ñl‰…™™•Ñ•‘}É•˜‰t°(€€€€€€€€€€€€€€€€€€€€‰ÁÉ½Á½Í…°ˆè‘•™•Ñl‰ÁÉ½Á½Í•‘}½ÉÉ•Ñ¥½¸‰t°(€€€€€€€€€€€€€€€€€€€€‰…ÕÑ¡½É¥Ñ…Ñ¥Ù•}¡…¹•}…ÁÁ±¥•ˆè…±Í”°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€™½È¥¹‘•à°‘•™•Ð¥¸•¹Õµ•É…Ñ”¡½Á•¹}‘•™•ÑÌ°ÍÑ…ÉÐôÄ¤(€€€€€€€€€€€t°(€€€€€€€€€€€€‰É•…‘¥¹•ÍÍ}…ÍÍ•ÍÍµ•¹ÐˆèÉ•…‘¥¹•ÍÌ°(€€€€€€€€€€€€‰•á•ÕÑ¥½¹}ÑÉ…”ˆèl(€€€€€€€€€€€€€€€€‰•á…ÐMÕÉÙ•ä•Í¥¸½%¹ÍÑÉÕµ•¹Ð…¹I•Í•…É 5•Ñ¡½•á•ÕÑ”¥¹ÁÕÑÌÙ…±¥‘…Ñ•ˆ°(€€€€€€€€€€€€€€€˜‰ÍÑÉÕÑÕÉ…°Íå¹Ñ¡•Ñ¥Œ•¹•É…Ñ¥½¸€¡íÍ•¹…É¥½ô¤ˆ°(€€€€€€€€€€€€€€€€‰…¹½¹¥…°MÕÉÙ•äÉ•ÍÁ½¹Í”Ù…±¥‘…Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€€‰‘•™•Ð½Ý…É¹¥¹œÁÉ•Í•ÉÙ…Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€€‰…¹‘¥‘…Ñ”ÁÉ”µI0É•…‘¥¹•ÍÌ…ÍÍ•ÍÍµ•¹Ðˆ°(€€€€€€€€€€€t°(€€€€€€€ô(€€€€€€€ÙÉ}É•ÍÕ±Ñl‰•áÑ•¹Í¥½¹}‘¥•ÍÐ‰t€ô‘½Õµ•¹Ñ}‘¥•ÍÐ¡ÙÉ}É•ÍÕ±Ð°€‰•áÑ•¹Í¥½¹}‘¥•ÍÐˆ¤(€€€€€€€É•ÍÕ±Ñ}•ÉÉ½È€ôÙ…±¥‘…Ñ•}Ù¥ÉÑÕ…±}‘½Õµ•¹Ð¡ÙÉ}É•ÍÕ±Ð¤(€€€€€€€¥˜É•ÍÕ±Ñ}•ÉÉ½Èè(€€€€€€€€€€€É…¥Í”…Á…‰¥±¥Ñåá•ÕÑ¥½¹ÉÉ½È (€€€€€€€€€€€€€€€€‰YHµIMU1Pµ	%9%9´ÀÀÄˆ°(€€€€€€€€€€€€€€€˜‰…¹½¹¥…°Y¥ÉÑÕ…°IÕ¹¹•ÈI•ÍÕ±ÐÉ•©•Ñ•ÁÉ½‘ÕÑ¥½¸½ÕÑÁÕÐèíÉ•ÍÕ±Ñ}•ÉÉ½Éôˆ°(€€€€€€€€€€€€¤((€€€€€€€É•ÍÕ±Ñ}•áÑ•¹Í¥½¸€ôì(€€€€€€€€€€€€‰Í¡•µ…}Ù•ÉÍ¥½¸ˆè€ˆÀ¸Ä¸Àˆ°(€€€€€€€€€€€€‰•áÑ•¹Í¥½¹}ÑåÁ”ˆè€‰ÍÕÉÙ•å}Ù¥ÉÑÕ…±}ÉÕ¹¹•É}É•ÍÕ±Ðˆ°(€€€€€€€€€€€€‰¡…¹‘½™™}‰¥¹‘¥¹œˆè‘••Á½Áä¡ÙÉ}É•ÍÕ±Ñl‰¡…¹‘½™™}‰¥¹‘¥¹œ‰t¤°(€€€€€€€€€€€€‰•Ù¥‘•¹•}ÍÑ…ÑÕÌˆè€‰Me9Q!Q%}QMQ}=91dˆ°(€€€€€€€€€€€€‰¥¹ÁÕÑ}Á¥¹Ìˆèì(€€€€€€€€€€€€€€€€‰‘•Í¥¸ˆè‘••Á½Áä¡‘¥Ð¡•áÑ•¹Í¥½¹l‰‘•Í¥¹}É•˜‰t¤¤°(€€€€€€€€€€€€€€€€‰¥¹ÍÑÉÕµ•¹Ðˆè‘••Á½Áä¡‘¥Ð¡•áÑ•¹Í¥½¹l‰¥¹ÍÑÉÕµ•¹Ñ}É•˜‰t¤¤°(€€€€€€€€€€€€€€€€‰ÉÅ}¥‘Ìˆè±¥ÍÐ¡É•ÅÕ•ÍÐ¹½¹Ñ•áÑ}Á…­l‰ÅÕ•ÍÑ¥½¹}¥‘Ì‰t¤°(€€€€€€€€€€€€€€€€‰½É•}µ•Ñ¡½ˆè‘••Á½Áä¡‘¥Ð¡•áÑ•¹Í¥½¹l‰½É•}µ•Ñ¡½‘}É•˜‰t¤¤°(€€€€€€€€€€€€€€€€‰ÁÉ½Ñ½½°ˆè‘••Á½Áä¡‘¥Ð¡•áÑ•¹Í¥½¹l‰ÁÉ½Ñ½½±}É•˜‰t¤¤°(€€€€€€€€€€€€€€€€‰ÉÕ¹}ÍÁ•Œˆè‘••Á½Áä¡‘¥Ð¡•áÑ•¹Í¥½¹l‰ÉÕ¹}ÍÁ•Œ‰t¤¤°(€€€€€€€€€€€€€€€€‰É•Í•…É¡}Í¹…ÁÍ¡½Ðˆè‘••Á½Áä¡É•ÅÕ•ÍÐ¹½¹Ñ•áÑ}Á…­l‰Á¥¹Ì‰ul‰É•Í•…É¡}Í¹…ÁÍ¡½Ð‰t¤°(€€€€€€€€€€€€€€€€‰ÁÉ½©•Ñ}½¹™¥}‘¥•ÍÐˆèÉ•ÅÕ•ÍÐ¹½¹Ñ•áÑ}Á…­l‰Á¥¹Ì‰ul‰ÁÉ½©•Ñ}½¹™¥œ‰ul‰½¹™¥ÕÉ…Ñ¥½¹}‘¥•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰•™™•Ñ¥Ù•}ÁÉ½™¥±•}Í•Ñ}‘¥•ÍÐˆèÉ•ÅÕ•ÍÐ¹½¹Ñ•áÑ}Á…­l‰Á¥¹Ì‰ul‰•™™•Ñ¥Ù•}ÁÉ½™¥±•}Í•Ð‰ul‰½¹Ñ•¹Ñ}‘¥•ÍÐ‰t°(€€€€€€€€€€€€€€€€‰Ù¥ÉÑÕ…±}ÉÕ¹¹•É}‘•ÍÉ¥ÁÑ½Èˆèì(€€€€€€€€€€€€€€€€€€€€‰…Á…‰¥±¥Ñå}¥ˆèÉ•ÅÕ•ÍÐ¹‘•ÍÉ¥ÁÑ½Él‰…Á…‰¥±¥Ñå}¥‰t°(€€€€€€€€€€€€€€€€€€€€‰Ù•ÉÍ¥½¸ˆèÉ•ÅÕ•ÍÐ¹‘•ÍÉ¥ÁÑ½Él‰…Á…‰¥±¥Ñå}Ù•ÉÍ¥½¸‰t°(€€€€€€€€€€€€€€€€€€€€‰‘•ÍÉ¥ÁÑ½É}‘¥•ÍÐˆèÉ•ÅÕ•ÍÐ¹‘•ÍÉ¥ÁÑ½Él‰‘•ÍÉ¥ÁÑ½É}‘¥•ÍÐ‰t°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€‰Íå¹Ñ¡•Ñ¥}Á½ÁÕ±…Ñ¥½¹}‘¥•ÍÐˆè…¹½¹¥…±}‘¥•ÍÐ¡Á½ÁÕ±…Ñ¥½¸¤°(€€€€€€€€€€€€€€€€‰ÉÕ¹¹•É}½¹™¥ÕÉ…Ñ¥½¹}‘¥•ÍÐˆè•¹•É…Ñ¥½¹}½¹™¥ÕÉ…Ñ¥½¹}‘¥•ÍÐ°(€€€€€€€€€€€€€€€€‰ÉÕ¹¹•É}‘¥•ÍÐˆèÉÕ¹¹•É}‘¥•ÍÐ°(€€€€€€€€€€€€€€€€‰ÍÕÉÙ•å}‰¥¹‘¥¹}Ù•ÉÍ¥½¸ˆè€ˆÀ¸Ä¸Àˆ°(€€€€€€€€€€€€€€€€‰ÍÕÉÙ•å}‰¥¹‘¥¹}‘¥•ÍÐˆèÍÕÉÙ•å}‰¥¹‘¥¹}‘¥•ÍÐ°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰Íå¹Ñ¡•Ñ¥}Á½ÁÕ±…Ñ¥½¸ˆèÁ½ÁÕ±…Ñ¥½¸°(€€€€€€€€€€€€‰•¹•É…Ñ¥½¹}ÁÉ½Ù•¹…¹”ˆè•¹•É…Ñ¥½¹}ÁÉ½Ù•¹…¹”°(€€€€€€€€€€€€‰Ù…±¥‘…Ñ¥½¹}™…¥±ÕÉ•Ìˆè‘••Á½Áä¡É•Á½ÉÑl‰¥ÍÍÕ•Ì‰t¤°(€€€€€€€€€€€€‰ÁÉ•Í•ÉÙ…Ñ¥½¹}•Ù•¹ÑÌˆè‘••Á½Áä¡É•Á½ÉÑl‰ÁÉ•Í•ÉÙ…Ñ¥½¹}•Ù•¹ÑÌ‰t¤°(€€€€€€€€€€€€‰‘•™•ÑÌˆè‘•™•ÑÌ°(€€€€€€€€€€€€‰Ý…É¹¥¹ÌˆèÝ…É¹¥¹Ì°(€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}¡…¹•}É•ÅÕ•ÍÑÌˆè‘••Á½Áä¡ÙÉ}É•ÍÕ±Ñl‰…¹‘¥‘…Ñ•}¡…¹•}É•ÅÕ•ÍÑÌ‰t¤°(€€€€€€€€€€€€‰É•…‘¥¹•ÍÍ}…ÍÍ•ÍÍµ•¹ÐˆèÉ•…‘¥¹•ÍÌ°(€€€€€€€€€€€€‰Ù¥ÉÑÕ…±}ÉÕ¹¹•É}É•ÍÕ±ÐˆèÙÉ}É•ÍÕ±Ð°(€€€€€€€€€€€€‰É•Í•…É¡}ÍÑ…Ñ•}µÕÑ…Ñ¥½¹}Á•É™½Éµ•ˆè…±Í”°(€€€€€€€€€€€€‰É•…±}•á•ÕÑ¥½¹}ÍÑ…ÉÑ•ˆè…±Í”°(€€€€€€€ô(€€€€€€€É•ÍÕ±Ñ}•áÑ•¹Í¥½¹l‰•áÑ•¹Í¥½¹}‘¥•ÍÐ‰t€ô‘½Õµ•¹Ñ}‘¥•ÍÐ¡É•ÍÕ±Ñ}•áÑ•¹Í¥½¸°€‰•áÑ•¹Í¥½¹}‘¥•ÍÐˆ¤(€€€€€€€É•ÍÕ±Ñ}…ÉÑ¥™…Ð€ô}…ÉÑ¥™…Ð (€€€€€€€€€€€É•ÅÕ•ÍÐ°(€€€€€€€€€€€É½±”ô‰ÍÕÉÙ•å}Ù¥ÉÑÕ…°¹Ù¥ÉÑÕ…±}ÉÕ¹¹•É}É•ÍÕ±Ðˆ°(€€€€€€€€€€€…ÉÑ¥™…Ñ}¥õ˜‰IPµYHµIMU1Pµí}Í…™•}¥¡É•ÅÕ•ÍÐ¹ÉÕ¸¹ÉÕ¹}¥¥ôˆ°(€€€€€€€€€€€Ù…±Õ”õÉ•ÍÕ±Ñ}•áÑ•¹Í¥½¸°(€€€€€€€€€€€ÁÉ½Ù•¹…¹”õ…ÉÑ¥™…Ñ}ÁÉ½Ù•¹…¹”°(€€€€€€€€¤((€€€€€€€…ÉÑ¥™…ÑÌ€ô€ (€€€€€€€€€€€É•ÍÁ½¹Í•}…ÉÑ¥™…Ð°(€€€€€€€€€€€•¹•É…Ñ¥½¹}…ÉÑ¥™…Ð°(€€€€€€€€€€€Ù…±¥‘…Ñ¥½¹}…ÉÑ¥™…Ð°(€€€€€€€€€€€‘•™•Ñ}…ÉÑ¥™…Ð°(€€€€€€€€€€€É•…‘¥¹•ÍÍ}…ÉÑ¥™…Ð°(€€€€€€€€€€€É•ÍÕ±Ñ}…ÉÑ¥™…Ð°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸…Á…‰¥±¥Ñåá•ÕÑ¥½¹=ÕÑÁÕÐ (€€€€€€€€€€€¡…¹‘½™˜õ¡…¹‘½™˜°(€€€€€€€€€€€•áÑ•¹Í¥½¸õÉ•ÍÕ±Ñ}•áÑ•¹Í¥½¸°(€€€€€€€€€€€…ÉÑ¥™…ÑÌõ…ÉÑ¥™…ÑÌ°(€€€€€€€€¤(