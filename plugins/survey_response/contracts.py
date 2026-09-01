from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

ROOT = Path(__file__).resolve().parents[2]
RAW_SCHEMA_PATH = ROOT / "core/packages/survey/survey-raw-response.schema.json"
CANONICAL_RESPONSE_SCHEMA_PATH = ROOT / "core/packages/survey/survey-response-canonical.schema.json"
DATASET_SCHEMA_PATH = ROOT / "core/packages/survey/survey-response-dataset.schema.json"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )


RAW_RESPONSE_VALIDATOR = _validator(RAW_SCHEMA_PATH)
CANONICAL_RESPONSE_VALIDATOR = _validator(CANONICAL_RESPONSE_SCHEMA_PATH)
DATASET_VALIDATOR = _validator(DATASET_SCHEMA_PATH)


def canonical_digest(value: Any) -> str:
    try:
        encoded = rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Survey response value is not canonicalizable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def raw_input_digest(value: Any) -> str:
    return canonical_digest(value)


def _diagnostic_projection(value: Any) -> Any:
    """Project malformed non-JSON/RFC8785 input into a durable diagnostic value."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER:
            return value
        return {"$noncanonical_integer": str(value)}
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            label = "NaN"
        elif value > 0:
            label = "Infinity"
        else:
            label = "-Infinity"
        return {"$noncanonical_number": label}
    if isinstance(value, Mapping):
        if all(isinstance(key, str) for key in value):
            return {
                str(key): _diagnostic_projection(item)
                for key, item in value.items()
            }
        return {
            "$mapping_entries": [
                [_diagnostic_projection(key), _diagnostic_projection(item)]
                for key, item in value.items()
            ]
        }
    if isinstance(value, (list, tuple)):
        return [_diagnostic_projection(item) for item in value]
    if isinstance(value, (set, frozenset)):
        projected = [_diagnostic_projection(item) for item in value]
        return {
            "$set_items": sorted(
                projected,
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
        }
    return {
        "$unsupported_type": f"{type(value).__module__}.{type(value).__qualname__}",
        "$repr": repr(value),
    }


def preserve_raw_input(value: Any) -> tuple[Any, str, dict[str, Any] | None]:
    """Return a persistable raw value and digest without hiding malformed input."""
    try:
        return deepcopy(value), raw_input_digest(value), None
    except ValueError:
        projected = _diagnostic_projection(value)
        digest = canonical_digest({"noncanonical_raw_input": projected})
        return projected, digest, {
            "code": "SURVEY_RESPONSE_MALFORMED",
            "severity": "error",
            "message": (
                "raw input is not RFC8785-canonicalizable; "
                "a diagnostic projection was preserved"
            ),
        }


def response_content_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    for field in ("ingested_at", "content_digest", "registry_digest"):
        payload.pop(field, None)
    return canonical_digest(payload)


def dataset_content_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    for field in (
        "dataset_id",
        "created_at",
        "captured_against",
        "project_config_digest",
        "effective_profile_set_digest",
        "capture_origin",
        "content_digest",
        "registry_digest",
    ):
        payload.pop(field, None)
    for field in ("accepted_response_refs", "rejected_response_refs"):
        if isinstance(payload.get(field), list):
            payload[field] = sorted(
                payload[field],
                key=lambda item: (
                    str(item.get("identity_namespace", "")),
                    str(item.get("response_id", "")),
                    str(item.get("content_digest", "")),
                ),
            )
    if isinstance(payload.get("rejected_inputs"), list):
        payload["rejected_inputs"] = sorted(
            payload["rejected_inputs"],
            key=lambda item: str(item.get("raw_input_digest", "")),
        )
    if isinstance(payload.get("source_run_ids"), list):
        payload["source_run_ids"] = sorted(payload["source_run_ids"])
    return canonical_digest(payload)


def registry_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    payload.pop("registry_digest", None)
    return canonical_digest(payload)


def schema_issues(validator: Draft202012Validator, value: Any) -> list[dict[str, Any]]:
    errors = sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    issues: list[dict[str, Any]] = []
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        issues.append(
            {
                "code": "SURVEY_RESPONSE_MALFORMED",
                "severity": "error",
                "message": f"{path}: {error.message}",
            }
        )
    return issues


def validate_canonical_response(document: Mapping[str, Any]) -> None:
    issues = schema_issues(CANONICAL_RESPONSE_VALIDATOR, document)
    if issues:
        raise ValueError(issues[0]["message"])
    if document["content_digest"] != response_content_digest(document):
        raise ValueError("SurveyResponse content_digest does not match canonical content")
    if document["registry_digest"] != registry_digest(document):
        raise ValueError("SurveyResponse registry_digest does not match persisted content")


def validate_dataset(document: Mapping[str, Any]) -> None:
    issues = schema_issues(DATASET_VALIDATOR, document)
    if issues:
        raise ValueError(issues[0]["message"])
    if document["response_count"] != document["accepted_count"] + document["rejected_count"]:
        raise ValueError("SurveyResponseDataset response counters are inconsistent")
    if document["accepted_count"] != len(document["accepted_response_refs"]):
        raise ValueError("SurveyResponseDataset accepted_count is inconsistent")
    if document["rejected_count"] != len(document["rejected_inputs"]):
        raise ValueError("SurveyResponseDataset rejected_count is inconsistent")
    accepted_ids = [
        (str(item["identity_namespace"]), str(item["response_id"]))
        for item in document["accepted_response_refs"]
    ]
    rejected_ids = [
        (str(item["identity_namespace"]), str(item["response_id"]))
        for item in document["rejected_response_refs"]
    ]
    if len(accepted_ids) != len(set(accepted_ids)) or len(rejected_ids) != len(set(rejected_ids)):
        raise ValueError("SurveyResponseDataset response references must be unique")
    if set(accepted_ids) & set(rejected_ids):
        raise ValueError("SurveyResponseDataset cannot accept and reject the same response")
    if document["content_digest"] != dataset_content_digest(document):
        raise ValueError("SurveyResponseDataset content_digest does not match canonical content")
    if document["registry_digest"] != registry_digest(document):
        raise ValueError("SurveyResponseDataset registry_digest does not match persisted content")
