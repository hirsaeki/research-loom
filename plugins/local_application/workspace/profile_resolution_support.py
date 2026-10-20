"""Profile resolution constants and small loading/version helpers (#494)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from core.resources import resource_path
from plugins.local_application.workspace.workspace import LocalWorkspaceError

PROFILE_MANIFEST_SCHEMA = resource_path("profiles/contracts/profile-manifest.schema.json")
EPS_SCHEMA = resource_path("profiles/contracts/effective-profile-set.schema.json")
CORE_INVARIANTS = resource_path("core/validators/non-overridable-invariants.yaml")
STRENGTHENING_REGISTRY = resource_path("profiles/contracts/invariant-strengthening-validators.yaml")
NARRATIVE_SEMANTICS = resource_path("profiles/contracts/narrative-semantics.yaml")
RESEARCH_QUALITY_POLICY = resource_path("profiles/contracts/research-quality-policy.yaml")
CORE_CONTRACTS = {"research_contract": "0.1.0", "invariant_contract": "0.1.0"}
TYPE_RANK = {
    name: i for i, name in enumerate(("research", "organization", "narrative", "publication"))
}
MAX_PROFILE_RESOLUTION_STATES = 10_000
MAX_PROFILE_RESOURCE_BYTES = 1_048_576
MAX_EFFECTIVE_RESOURCE_BYTES = 8_388_608
_COMPARATOR = re.compile(r"^(>=|>|<=|<|=)(\d+\.\d+\.\d+)$")


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalWorkspaceError(code, f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise LocalWorkspaceError(code, f"JSON document must be an object: {path}")
    return value


def _validate_schema(value: Mapping[str, Any], schema_path: Path, code: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise LocalWorkspaceError(code, f"schema violation at {location}: {error.message}")


def _sha256(path: Path) -> str:
    # Git may materialize canonical JSON manifests with CRLF on Windows.
    # Profile identity pins describe repository content, not checkout line-ending policy.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _semver(text: str) -> tuple[int, int, int]:
    return tuple(int(item) for item in text.split("."))  # type: ignore[return-value]


def _satisfies(version: str, requirement: str) -> bool:
    value = _semver(version)
    if re.fullmatch(r"\d+\.\d+\.\d+", requirement):
        return value == _semver(requirement)
    for token in requirement.split():
        match = _COMPARATOR.fullmatch(token)
        if match is None:
            raise LocalWorkspaceError(
                "PROFILE-VERSION-001", f"unsupported version requirement {requirement!r}"
            )
        op, rhs_text = match.groups()
        rhs = _semver(rhs_text)
        if op == ">=" and not value >= rhs:
            return False
        if op == ">" and not value > rhs:
            return False
        if op == "<=" and not value <= rhs:
            return False
        if op == "<" and not value < rhs:
            return False
        if op == "=" and not value == rhs:
            return False
    return True


def _key(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value["profile_type"]), str(value["profile_id"])


def _keyver(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(value["profile_type"]), str(value["profile_id"]), str(value["profile_version"])


def _pin(candidate: Mapping[str, Any]) -> dict[str, Any]:
    manifest = candidate["manifest"]
    return {
        "profile_id": manifest["profile_id"],
        "profile_type": manifest["profile_type"],
        "profile_version": manifest["profile_version"],
        "manifest_sha256": candidate["manifest_sha256"],
    }


def _flatten_requests(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for profile_type in ("research", "organization", "narrative", "publication"):
        requests.extend(deepcopy(list(config["profile_requests"][profile_type])))
    return requests
