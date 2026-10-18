"""Module-level helpers of the writer round trip service (#494)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from core.resources import resource_path
from plugins.application_errors import LocalApplicationError

SCHEMA_VERSION = "0.1.0"
MAX_SECTIONS = 64
MAX_FEEDBACK_ISSUES = 128
MAX_INSPECT_ANCESTRY = 64
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ROUND_TRIP_INPUT_BYTES = 16 * 1024 * 1024
SCHEMA = resource_path("core/packages/writer-publication/writer-round-trip.schema.json")


def _validate_schema(value: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
            "canonical Writer round-trip schema is unavailable",
        ) from exc
    if errors:
        first = errors[0]
        path = ".".join(map(str, first.absolute_path)) or "$"
        raise LocalApplicationError(
            "APPLICATION-WRITER-ROUND-TRIP-SCHEMA-001",
            f"Writer round-trip contract violation at {path}: {first.message}",
        )


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
