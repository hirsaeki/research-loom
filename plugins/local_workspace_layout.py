"""Workspace layout: locators, binding shape and safe path resolution.

These are the pieces of the local workspace format that the durable stores
need. They live below both ``plugins.local_durable_store`` and
``plugins.local_application`` so neither has to import the other for them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from plugins._infra.atomic_write import replace_text

WORKSPACE_FORMAT = "research-loom-local-workspace"
WORKSPACE_VERSION = "0.1.0"
BINDING_NAME = "workspace-binding.json"
INTERNAL_DIR = ".research-loom"
PROJECT_CONFIG_NAME = "project-config.json"
EFFECTIVE_PROFILE_SET_NAME = "effective-profile-set.json"
PROJECT_CONFIG_LOCATOR = f"{INTERNAL_DIR}/{PROJECT_CONFIG_NAME}"
EFFECTIVE_PROFILE_SET_LOCATOR = f"{INTERNAL_DIR}/{EFFECTIVE_PROFILE_SET_NAME}"

STORAGE = {
    "research_state": f"{INTERNAL_DIR}/research-state.sqlite3",
    "conversation": f"{INTERNAL_DIR}/conversation.db",
    "decision": f"{INTERNAL_DIR}/decision.db",
    "execution_root": f"{INTERNAL_DIR}/execution",
    "execution": f"{INTERNAL_DIR}/execution/execution.db",
    "context_extensions": f"{INTERNAL_DIR}/execution/context-extensions.sqlite3",
    "operational_trace": f"{INTERNAL_DIR}/execution/operational-trace.sqlite3",
}

BASE_DURABLE_CHILDREN = {
    "project_config": {"locator": PROJECT_CONFIG_LOCATOR, "kind": "file"},
    "effective_profile_set": {"locator": EFFECTIVE_PROFILE_SET_LOCATOR, "kind": "file"},
    "research_state": {"locator": STORAGE["research_state"], "kind": "file"},
    "conversation": {"locator": STORAGE["conversation"], "kind": "file"},
    "decision": {"locator": STORAGE["decision"], "kind": "file"},
    "execution_material": {"locator": STORAGE["execution_root"], "kind": "directory"},
}

OPTIONAL_DURABLE_CHILDREN = {
    "research_attention": {"locator": ".research-loom/attention.sqlite3", "kind": "file"},
    "profile_history": {"locator": ".research-loom/profile-history", "kind": "directory"},
    "research_exhibits": {"locator": ".research-loom/research-exhibits.sqlite3", "kind": "file"},
    "survey_registry": {"locator": ".research-loom/survey-registry.sqlite3", "kind": "file"},
    "survey_response_registry": {
        "locator": ".research-loom/survey-response-registry.sqlite3",
        "kind": "file",
    },
    "survey_analysis_registry": {
        "locator": ".research-loom/survey-analysis-registry.sqlite3",
        "kind": "file",
    },
    "delphi_registry": {"locator": ".research-loom/delphi-registry.sqlite3", "kind": "file"},
    "project_inputs": {"locator": ".research-loom/project-inputs", "kind": "directory"},
    "writer_compositions": {"locator": ".research-loom/writer-compositions", "kind": "directory"},
    "writer_round_trips": {"locator": ".research-loom/writer-round-trips", "kind": "directory"},
    "research_packages": {"locator": ".research-loom/research-packages", "kind": "directory"},
    "publication": {"locator": ".research-loom/publication", "kind": "directory"},
}


class LocalWorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def read_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalWorkspaceError(code, f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise LocalWorkspaceError(code, f"JSON document must be an object: {path}")
    return value


def assert_safe_workspace_root(root: Path) -> Path:
    root = root.expanduser()
    if root.is_symlink():
        raise LocalWorkspaceError("WORKSPACE-PATH-001", "workspace root may not be a symlink")
    return root.resolve(strict=False)


def safe_locator(root: Path, locator: str, *, require_exists: bool = True) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise LocalWorkspaceError("WORKSPACE-PATH-001", f"unsafe workspace locator: {locator}")
    normalized_root = assert_safe_workspace_root(root)
    target = root.joinpath(relative)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(normalized_root)
    except ValueError as exc:
        raise LocalWorkspaceError(
            "WORKSPACE-PATH-001", f"workspace locator escapes root: {locator}"
        ) from exc
    if target.is_symlink():
        raise LocalWorkspaceError(
            "WORKSPACE-PATH-001", f"workspace locator may not be a symlink: {locator}"
        )
    if require_exists and not target.exists():
        raise LocalWorkspaceError(
            "WORKSPACE-MISSING-001", f"required workspace path is missing: {locator}"
        )
    return target


def atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    replace_text(
        path, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )


def validate_binding_shape(binding: Mapping[str, Any]) -> None:
    required_keys = {
        "workspace_format",
        "workspace_version",
        "project_id",
        "project_config",
        "effective_profile_set",
        "storage",
        "initialized_at",
    }
    if not required_keys <= set(binding) or set(binding) - required_keys - {"durable_children"}:
        raise LocalWorkspaceError(
            "WORKSPACE-BINDING-001", "workspace binding has unexpected or missing fields"
        )
    if (
        binding.get("workspace_format") != WORKSPACE_FORMAT
        or binding.get("workspace_version") != WORKSPACE_VERSION
    ):
        raise LocalWorkspaceError(
            "WORKSPACE-FORMAT-001", "workspace format/version is incompatible"
        )
    for key in ("project_config", "effective_profile_set"):
        value = binding.get(key)
        if not isinstance(value, Mapping) or set(value) not in (
            {"locator", "digest"},
            {"locator", "ref", "digest"},
        ):
            raise LocalWorkspaceError("WORKSPACE-BINDING-001", f"malformed {key} binding")
    storage = binding.get("storage")
    if not isinstance(storage, Mapping) or dict(storage) != STORAGE:
        raise LocalWorkspaceError(
            "WORKSPACE-BINDING-001", "runtime storage layout does not match this workspace version"
        )
    children = binding.get("durable_children")
    if children is not None:
        if not isinstance(children, Mapping):
            raise LocalWorkspaceError("WORKSPACE-BINDING-001", "durable_children must be an object")
        for name, spec in children.items():
            if (
                not isinstance(name, str)
                or not isinstance(spec, Mapping)
                or set(spec) != {"locator", "kind"}
            ):
                raise LocalWorkspaceError(
                    "WORKSPACE-BINDING-001", "durable child entry is malformed"
                )
            if spec.get("kind") not in {"file", "directory"}:
                raise LocalWorkspaceError("WORKSPACE-BINDING-001", "durable child kind is invalid")
            locator = Path(str(spec.get("locator", "")))
            if (
                locator.is_absolute()
                or ".." in locator.parts
                or not locator.parts
                or locator.parts[0] != INTERNAL_DIR
            ):
                raise LocalWorkspaceError(
                    "WORKSPACE-BINDING-001",
                    "durable child locator must stay under Parent Durable Store Root",
                )
        for name, spec in BASE_DURABLE_CHILDREN.items():
            if children.get(name) != spec:
                raise LocalWorkspaceError(
                    "WORKSPACE-BINDING-001",
                    f"required durable child binding is missing or changed: {name}",
                )
        for name, spec in children.items():
            if name not in BASE_DURABLE_CHILDREN and OPTIONAL_DURABLE_CHILDREN.get(name) != spec:
                raise LocalWorkspaceError(
                    "WORKSPACE-BINDING-001", f"unknown durable child binding: {name}"
                )
