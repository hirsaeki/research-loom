from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_SPEC_SCHEMA_PATH = ROOT / "core/packages/survey/survey-analysis-spec.schema.json"
AGGREGATE_RESULT_SCHEMA_PATH = ROOT / "core/packages/survey/survey-aggregate-result.schema.json"


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


ANALYSIS_SPEC_VALIDATOR = _validator(ANALYSIS_SPEC_SCHEMA_PATH)
AGGREGATE_RESULT_VALIDATOR = _validator(AGGREGATE_RESULT_SCHEMA_PATH)


def canonical_digest(value: Any) -> str:
    try:
        encoded = rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Survey analysis value is not canonicalizable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def analysis_spec_content_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    for field in ("analysis_spec_id", "created_at", "content_digest", "registry_digest"):
        payload.pop(field, None)
    return canonical_digest(payload)


def aggregate_result_content_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    for field in ("aggregate_result_id", "generated_at", "content_digest", "registry_digest"):
        payload.pop(field, None)
    return canonical_digest(payload)


def registry_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    payload.pop("registry_digest", None)
    return canonical_digest(payload)


def stable_identity(prefix: str, content_digest: str) -> str:
    if not content_digest.startswith("sha256:") or len(content_digest) != 71:
        raise ValueError("content_digest must be a sha256 digest")
    return prefix + content_digest.removeprefix("sha256:")[:24]


def _schema_errors(validator: Draft202012Validator, value: Any) -> list[str]:
    errors = sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]


def validate_analysis_spec(document: Mapping[str, Any]) -> None:
    errors = _schema_errors(ANALYSIS_SPEC_VALIDATOR, document)
    if errors:
        raise ValueError(errors[0])
    if document["content_digest"] != analysis_spec_content_digest(document):
        raise ValueError("SurveyAnalysisSpec content_digest does not match canonical content")
    if document["analysis_spec_id"] != stable_identity("SAS-", document["content_digest"]):
        raise ValueError("SurveyAnalysisSpec identity does not match its canonical content")
    if document["registry_digest"] != registry_digest(document):
        raise ValueError("SurveyAnalysisSpec registry_digest does not match persisted content")
    item_ids = [str(item["item_id"]) for item in document["analysis_items"]]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("SurveyAnalysisSpec analysis item IDs must be unique")


def validate_aggregate_result(document: Mapping[str, Any]) -> None:
    errors = _schema_errors(AGGREGATE_RESULT_VALIDATOR, document)
    if errors:
        raise ValueError(errors[0])
    population = document["population"]
    if (
        int(population["dataset_response_count"])
        != int(population["accepted_response_count"]) + int(population["excluded_response_count"])
    ):
        raise ValueError("SurveyAggregateResult population counters are inconsistent")
    if document["content_digest"] != aggregate_result_content_digest(document):
        raise ValueError("SurveyAggregateResult content_digest does not match canonical content")
    if document["aggregate_result_id"] != stable_identity("SAR-", document["content_digest"]):
        raise ValueError("SurveyAggregateResult identity does not match its canonical content")
    if document["registry_digest"] != registry_digest(document):
        raise ValueError("SurveyAggregateResult registry_digest does not match persisted content")
    item_ids = [str(item["item_id"]) for item in document["result_items"]]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("SurveyAggregateResult item IDs must be unique")
