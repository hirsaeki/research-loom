from __future__ import annotations

from collections import Counter
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Mapping
import uuid

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

from core.runtime import LineageView, StateView, canonical_digest
from core.runtime.transition_models import with_content_digest
from plugins.local_application.application import LocalResearchApplication, SystemClock, UUIDIdProvider


ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG_SCHEMA = ROOT / "projects/contracts/project-config.schema.json"
EFFECTIVE_PROFILE_SET_SCHEMA = ROOT / "profiles/contracts/effective-profile-set.schema.json"
RESEARCH_OBJECT_SCHEMA = ROOT / "core/models/research-object.schema.json"

WORKSPACE_FORMAT = "research-loom-local-workspace"
WORKSPACE_VERSION = "0.1.0"
BINDING_NAME = "workspace-binding.json"
INTERNAL_DIR = ".research-loom"
INITIALIZING_MARKER = ".initializing"
PROJECT_CONFIG_NAME = "project-config.json"
EFFECTIVE_PROFILE_SET_NAME = "effective-profile-set.json"

_STORAGE = {
    "research_state": f"{INTERNAL_DIR}/research-state.sqlite3",
    "conversation": f"{INTERNAL_DIR}/conversation.db",
    "decision": f"{INTERNAL_DIR}/decision.db",
    "execution_root": f"{INTERNAL_DIR}/execution",
    "execution": f"{INTERNAL_DIR}/execution/execution.db",
    "context_extensions": f"{INTERNAL_DIR}/execution/context-extensions.sqlite3",
    "operational_trace": f"{INTERNAL_DIR}/execution/operational-trace.sqlite3",
}


class LocalWorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class OpenedLocalWorkspace:
    root: Path
    binding: Mapping[str, Any]
    project_config: Mapping[str, Any]
    effective_profile_set: Mapping[str, Any]
    application: LocalResearchApplication

    @property
    def project_id(self) -> str:
        return str(self.binding["project_id"])

    def close(self) -> None:
        self.application.close()

    def __enter__(self) -> "OpenedLocalWorkspace":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class _TypedOnlyResolver:
    """No production LLM resolver is implied by opening a local workspace."""

    def resolve(self, *_args: object, **_kwargs: object):
        return None


def _read_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalWorkspaceError(code, f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise LocalWorkspaceError(code, f"JSON document must be an object: {path}")
    return value


def _schema(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_validate(value: Mapping[str, Any], schema_path: Path, code: str) -> None:
    validator = Draft202012Validator(_schema(schema_path), format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise LocalWorkspaceError(code, f"schema violation at {location}: {error.message}")


def _project_configuration_digest(config: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(config))
    payload.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def _flatten_profile_requests(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for category in ("research", "organization", "narrative", "publication"):
        result.extend(deepcopy(list(config["profile_requests"][category])))
    return result


def _has_duplicates(values) -> bool:
    items = list(values)
    return len(items) != len(set(items))


def _validate_project_semantics(config: Mapping[str, Any]) -> None:
    if config.get("configuration_digest") != _project_configuration_digest(config):
        raise LocalWorkspaceError(
            "PROJECT-CONFIG-DIGEST-001", "Project Config configuration_digest does not match content"
        )

    requests = [
        (item["profile_type"], item["profile_id"])
        for item in _flatten_profile_requests(config)
    ]
    if _has_duplicates(requests):
        raise LocalWorkspaceError(
            "PROJECT-PROFILE-REQUEST-IDENTITY-001", "duplicate direct Profile request identity"
        )

    identities = [
        [item["question_id"] for item in config["research_questions"]["references"]],
        [item["seed_id"] for item in config["research_questions"]["seeds"]],
        [item["attention_id"] for item in config["research_attention"]],
        [item["reference_id"] for item in config["resource_references"]],
        [item["capability_id"] for item in config["capability_hints"]],
        [
            item["guard_id"]
            for category in ("requirements", "prohibitions", "must_not_claim")
            for item in config["project_constraints"][category]
        ],
    ]
    if any(_has_duplicates(items) for items in identities):
        raise LocalWorkspaceError("PROJECT-CONFIG-IDENTITY-001", "duplicate Project Config identity")

    if set(config["scope"]["in_scope"]) & set(config["scope"]["out_of_scope"]):
        raise LocalWorkspaceError("PROJECT-CONFIG-SCOPE-001", "in-scope and out-of-scope entries overlap")

    question_ids = {item["question_id"] for item in config["research_questions"]["references"]}
    seed_ids = {item["seed_id"] for item in config["research_questions"]["seeds"]}
    resource_ids = {item["reference_id"] for item in config["resource_references"]}
    for seed in config["research_questions"]["seeds"]:
        parent = seed.get("parent_seed_id")
        if parent is not None and parent not in seed_ids:
            raise LocalWorkspaceError("PROJECT-CONFIG-REF-001", "RQ seed parent does not resolve")
    for attention in config["research_attention"]:
        if not set(attention.get("source_reference_ids", ())) <= resource_ids:
            raise LocalWorkspaceError("PROJECT-CONFIG-REF-001", "research attention source reference does not resolve")
        if not set(attention.get("related_question_ids", ())) <= question_ids:
            raise LocalWorkspaceError("PROJECT-CONFIG-REF-001", "research attention RQ reference does not resolve")
        if not set(attention.get("related_question_seed_ids", ())) <= seed_ids:
            raise LocalWorkspaceError("PROJECT-CONFIG-REF-001", "research attention RQ seed reference does not resolve")
    if not set(config["provenance"]["source_reference_ids"]) <= resource_ids:
        raise LocalWorkspaceError("PROJECT-CONFIG-REF-001", "Project Config provenance reference does not resolve")


def _validate_profile_binding(config: Mapping[str, Any], effective: Mapping[str, Any]) -> None:
    project_requests = Counter(
        (item["profile_type"], item["profile_id"], item["version"])
        for item in _flatten_profile_requests(config)
    )
    effective_requests = Counter(
        (item["profile_type"], item["profile_id"], item["version"])
        for item in effective["requested_profiles"]
    )
    if project_requests != effective_requests:
        raise LocalWorkspaceError(
            "PROJECT-PROFILE-BINDING-001",
            "Project Config direct Profile requests do not match Effective Profile Set requested_profiles",
        )


def _validate_inputs(config: Mapping[str, Any], effective: Mapping[str, Any]) -> tuple[str, str]:
    _schema_validate(config, PROJECT_CONFIG_SCHEMA, "WORKSPACE-PROJECT-CONFIG-SCHEMA-001")
    _schema_validate(effective, EFFECTIVE_PROFILE_SET_SCHEMA, "WORKSPACE-PROFILE-SET-SCHEMA-001")
    _validate_project_semantics(config)
    _validate_profile_binding(config, effective)
    if config["research_questions"]["references"]:
        raise LocalWorkspaceError(
            "WORKSPACE-BOOTSTRAP-RQ-001",
            "existing Research Question references require an explicit authoritative bootstrap source",
        )
    return str(config["configuration_digest"]), canonical_digest(effective)


def _assert_safe_workspace_root(root: Path) -> Path:
    root = root.expanduser()
    if root.is_symlink():
        raise LocalWorkspaceError("WORKSPACE-PATH-001", "workspace root may not be a symlink")
    return root.resolve(strict=False)


def _safe_locator(root: Path, locator: str, *, require_exists: bool = True) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise LocalWorkspaceError("WORKSPACE-PATH-001", f"unsafe workspace locator: {locator}")
    target = root.joinpath(relative)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LocalWorkspaceError("WORKSPACE-PATH-001", f"workspace locator escapes root: {locator}") from exc
    if target.is_symlink():
        raise LocalWorkspaceError("WORKSPACE-PATH-001", f"workspace locator may not be a symlink: {locator}")
    if require_exists and not target.exists():
        raise LocalWorkspaceError("WORKSPACE-MISSING-001", f"required workspace path is missing: {locator}")
    return target


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _copy_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _runtime_profile_provider(project_id: str, digest: str, effective: Mapping[str, Any]):
    runtime_view = deepcopy(dict(effective))
    runtime_view["content_digest"] = digest

    def provider(requested_project_id: str, requested_digest: str):
        if str(requested_project_id) != project_id or str(requested_digest) != digest:
            raise KeyError("Effective Profile Set binding mismatch")
        return deepcopy(runtime_view)

    return provider


def _bootstrap_state(
    config: Mapping[str, Any],
    effective: Mapping[str, Any],
    *,
    config_digest: str,
    profile_digest: str,
    clock,
    ids,
) -> StateView:
    project = config["project"]
    project_id = str(project["project_id"])
    core_project: dict[str, Any] = {
        "schema_version": "0.1.0",
        "id": project_id,
        "kind": "project",
        "revision": 0,
        "title": str(project["title"]),
    }
    if "objective" in project:
        core_project["objective"] = str(project["objective"])
    scope = config.get("scope", {})
    if scope.get("in_scope"):
        core_project["scope"] = list(scope["in_scope"])
    if scope.get("out_of_scope"):
        core_project["out_of_scope"] = list(scope["out_of_scope"])

    _schema_validate(core_project, RESEARCH_OBJECT_SCHEMA, "WORKSPACE-BOOTSTRAP-CORE-001")
    snapshot = with_content_digest({
        "schema_version": "0.1.0",
        "id": ids.new("SNP-"),
        "kind": "snapshot",
        "revision": 0,
        "project_id": project_id,
        "snapshot_type": "research",
        "created_at": clock.now(),
        "mode": "real",
        "members": [{
            "kind": "project",
            "id": project_id,
            "revision": 0,
            "digest": canonical_digest(core_project),
        }],
    })
    _schema_validate(snapshot, RESEARCH_OBJECT_SCHEMA, "WORKSPACE-BOOTSTRAP-CORE-001")

    lineage_id = ids.new("LIN-")
    lineage = LineageView(
        lineage_id=lineage_id,
        lineage_kind="primary",
        head_snapshot_ref=str(snapshot["id"]),
        head_snapshot_digest=str(snapshot["content_digest"]),
        head_snapshot_revision=0,
        execution_mode="real",
        status="active",
        project_config_ref=PROJECT_CONFIG_NAME,
        project_config_digest=config_digest,
        effective_profile_set_ref=EFFECTIVE_PROFILE_SET_NAME,
        effective_profile_set_digest=profile_digest,
    )
    return StateView(
        project_ref=project_id,
        lineage_ref=lineage_id,
        current_snapshot=snapshot,
        objects=(core_project, snapshot),
        decisions=(),
        used_decision_ids=(),
        lineages=(lineage,),
        active_lineage_ref=lineage_id,
        project_config_ref=PROJECT_CONFIG_NAME,
        project_config_digest=config_digest,
        effective_profile_set_ref=EFFECTIVE_PROFILE_SET_NAME,
        effective_profile_set_digest=profile_digest,
        project_config=deepcopy(dict(config)),
        effective_constraints={
            str(item["path"]): deepcopy(dict(item))
            for item in effective.get("effective_constraints", ())
        },
    )


def _binding(project_id: str, config_digest: str, profile_digest: str, *, initialized_at: str) -> dict[str, Any]:
    return {
        "workspace_format": WORKSPACE_FORMAT,
        "workspace_version": WORKSPACE_VERSION,
        "project_id": project_id,
        "project_config": {"locator": PROJECT_CONFIG_NAME, "digest": config_digest},
        "effective_profile_set": {"locator": EFFECTIVE_PROFILE_SET_NAME, "digest": profile_digest},
        "storage": deepcopy(_STORAGE),
        "initialized_at": initialized_at,
    }


def _validate_binding_shape(binding: Mapping[str, Any]) -> None:
    expected_keys = {
        "workspace_format", "workspace_version", "project_id", "project_config",
        "effective_profile_set", "storage", "initialized_at",
    }
    if set(binding) != expected_keys:
        raise LocalWorkspaceError("WORKSPACE-BINDING-001", "workspace binding has unexpected or missing fields")
    if binding.get("workspace_format") != WORKSPACE_FORMAT or binding.get("workspace_version") != WORKSPACE_VERSION:
        raise LocalWorkspaceError("WORKSPACE-FORMAT-001", "workspace format/version is incompatible")
    for key in ("project_config", "effective_profile_set"):
        value = binding.get(key)
        if not isinstance(value, Mapping) or set(value) != {"locator", "digest"}:
            raise LocalWorkspaceError("WORKSPACE-BINDING-001", f"malformed {key} binding")
    storage = binding.get("storage")
    if not isinstance(storage, Mapping) or dict(storage) != _STORAGE:
        raise LocalWorkspaceError("WORKSPACE-BINDING-001", "runtime storage layout does not match this workspace version")


def _sqlite_quick_check(path: Path, *, code: str) -> None:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
            if row is None or str(row[0]).lower() != "ok":
                raise LocalWorkspaceError(code, f"SQLite quick_check failed: {path}")
        finally:
            connection.close()
    except LocalWorkspaceError:
        raise
    except sqlite3.Error as exc:
        raise LocalWorkspaceError(code, f"SQLite database is not readable: {path}") from exc


def _validate_state_database(path: Path, binding: Mapping[str, Any]) -> None:
    project_id = str(binding["project_id"])
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            project = connection.execute(
                "SELECT * FROM project_state WHERE project_ref=?", (project_id,)
            ).fetchone()
            if project is None:
                raise LocalWorkspaceError("WORKSPACE-STATE-PROJECT-001", "Research State belongs to another or missing project")
            if (
                str(project["project_config_ref"]) != str(binding["project_config"]["locator"])
                or str(project["project_config_digest"]) != str(binding["project_config"]["digest"])
                or str(project["effective_profile_set_ref"]) != str(binding["effective_profile_set"]["locator"])
                or str(project["effective_profile_set_digest"]) != str(binding["effective_profile_set"]["digest"])
            ):
                raise LocalWorkspaceError("WORKSPACE-STATE-PIN-001", "Research State Config/Profile pins do not match workspace binding")
            active = connection.execute(
                "SELECT active_lineage_ref FROM project_active_lineage WHERE project_ref=?", (project_id,)
            ).fetchone()
            if active is None:
                raise LocalWorkspaceError("WORKSPACE-STATE-HEAD-001", "active Research Lineage is missing")
            lineage = connection.execute(
                "SELECT * FROM lineages WHERE lineage_id=? AND project_ref=?",
                (str(active["active_lineage_ref"]), project_id),
            ).fetchone()
            if lineage is None:
                raise LocalWorkspaceError("WORKSPACE-STATE-HEAD-001", "active Research Lineage does not resolve")
            if (
                str(lineage["project_config_ref"]) != str(binding["project_config"]["locator"])
                or str(lineage["project_config_digest"]) != str(binding["project_config"]["digest"])
                or str(lineage["effective_profile_set_ref"]) != str(binding["effective_profile_set"]["locator"])
                or str(lineage["effective_profile_set_digest"]) != str(binding["effective_profile_set"]["digest"])
            ):
                raise LocalWorkspaceError("WORKSPACE-STATE-PIN-001", "active Lineage Config/Profile pins do not match workspace binding")
            snapshot = connection.execute(
                "SELECT snapshot_ref,content_digest FROM snapshots WHERE snapshot_ref=?",
                (str(lineage["head_snapshot_ref"]),),
            ).fetchone()
            if snapshot is None or str(snapshot["content_digest"]) != str(lineage["head_snapshot_digest"]):
                raise LocalWorkspaceError("WORKSPACE-STATE-HEAD-001", "active Lineage HEAD snapshot does not resolve exactly")
        finally:
            connection.close()
    except LocalWorkspaceError:
        raise
    except sqlite3.Error as exc:
        raise LocalWorkspaceError("WORKSPACE-STATE-DB-001", "Research State DB is unreadable or incompatible") from exc


def _validated_documents(root: Path, binding: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    config_path = _safe_locator(root, str(binding["project_config"]["locator"]))
    profile_path = _safe_locator(root, str(binding["effective_profile_set"]["locator"]))
    config = _read_json(config_path, code="WORKSPACE-PROJECT-CONFIG-001")
    effective = _read_json(profile_path, code="WORKSPACE-PROFILE-SET-001")
    config_digest, profile_digest = _validate_inputs(config, effective)
    if str(config["project"]["project_id"]) != str(binding["project_id"]):
        raise LocalWorkspaceError("WORKSPACE-PROJECT-ID-001", "Project Config project identity does not match workspace binding")
    if config_digest != str(binding["project_config"]["digest"]):
        raise LocalWorkspaceError("WORKSPACE-CONFIG-DIGEST-001", "Project Config digest does not match workspace binding")
    if profile_digest != str(binding["effective_profile_set"]["digest"]):
        raise LocalWorkspaceError("WORKSPACE-PROFILE-DIGEST-001", "Effective Profile Set digest does not match workspace binding")
    return config, effective


class LocalWorkspace:
    @classmethod
    def init(
        cls,
        workspace: str | Path,
        project_config_file: str | Path,
        effective_profile_set_file: str | Path,
        *,
        clock=None,
        id_provider=None,
    ) -> OpenedLocalWorkspace:
        root = _assert_safe_workspace_root(Path(workspace))
        root_preexisting = root.exists()
        if root_preexisting and not root.is_dir():
            raise LocalWorkspaceError("WORKSPACE-PATH-001", "workspace path is not a directory")
        if root_preexisting and any(root.iterdir()):
            raise LocalWorkspaceError("WORKSPACE-INIT-EXISTS-001", "workspace directory must be absent or empty")

        # Validate all explicit inputs before creating any workspace-owned path.
        config = _read_json(Path(project_config_file), code="WORKSPACE-PROJECT-CONFIG-001")
        effective = _read_json(Path(effective_profile_set_file), code="WORKSPACE-PROFILE-SET-001")
        config_digest, profile_digest = _validate_inputs(config, effective)
        project_id = str(config["project"]["project_id"])
        clock = clock or SystemClock()
        ids = id_provider or UUIDIdProvider()
        seed = _bootstrap_state(
            config,
            effective,
            config_digest=config_digest,
            profile_digest=profile_digest,
            clock=clock,
            ids=ids,
        )

        root.mkdir(parents=True, exist_ok=True)
        internal = root / INTERNAL_DIR
        marker = internal / INITIALIZING_MARKER
        config_path = root / PROJECT_CONFIG_NAME
        profile_path = root / EFFECTIVE_PROFILE_SET_NAME
        internal_created = False
        config_written = False
        profile_written = False
        app: LocalResearchApplication | None = None
        try:
            internal.mkdir(parents=False, exist_ok=False)
            internal_created = True
            marker.write_text("initializing\n", encoding="utf-8")
            config_written = True
            _copy_json(config_path, config)
            profile_written = True
            _copy_json(profile_path, effective)

            app = LocalResearchApplication(
                internal,
                resolver=_TypedOnlyResolver(),
                effective_profile_set_provider=_runtime_profile_provider(project_id, profile_digest, effective),
                seed_state=seed,
                clock=clock,
                id_provider=ids,
            )
            binding = _binding(project_id, config_digest, profile_digest, initialized_at=clock.now())
            app.close()
            app = None
            _atomic_json_write(internal / BINDING_NAME, binding)
            marker.unlink()
            return cls.open(root)
        except Exception:
            if app is not None:
                with suppress(Exception):
                    app.close()
            if internal_created and internal.exists():
                with suppress(OSError):
                    shutil.rmtree(internal)
            if config_written and config_path.exists() and config_path.is_file():
                with suppress(OSError):
                    config_path.unlink()
            if profile_written and profile_path.exists() and profile_path.is_file():
                with suppress(OSError):
                    profile_path.unlink()
            if not root_preexisting and root.exists():
                with suppress(OSError):
                    if not any(root.iterdir()):
                        root.rmdir()
            raise

    @classmethod
    def open(cls, workspace: str | Path) -> OpenedLocalWorkspace:
        root = _assert_safe_workspace_root(Path(workspace))
        if not root.is_dir():
            raise LocalWorkspaceError("WORKSPACE-MISSING-001", "workspace directory does not exist")
        internal = _safe_locator(root, INTERNAL_DIR)
        if (internal / INITIALIZING_MARKER).exists():
            raise LocalWorkspaceError("WORKSPACE-PARTIAL-001", "workspace initialization is incomplete")
        binding_path = _safe_locator(root, f"{INTERNAL_DIR}/{BINDING_NAME}")
        binding = _read_json(binding_path, code="WORKSPACE-BINDING-001")
        _validate_binding_shape(binding)
        config, effective = _validated_documents(root, binding)
        for key, locator in binding["storage"].items():
            path = _safe_locator(root, str(locator))
            if key != "execution_root" and not path.is_file():
                raise LocalWorkspaceError("WORKSPACE-MISSING-001", f"required storage is missing: {locator}")
            if key == "execution_root" and not path.is_dir():
                raise LocalWorkspaceError("WORKSPACE-MISSING-001", "execution root is missing")
        state_path = _safe_locator(root, str(binding["storage"]["research_state"]))
        _sqlite_quick_check(state_path, code="WORKSPACE-STATE-DB-001")
        _validate_state_database(state_path, binding)
        for key in ("conversation", "decision", "execution", "context_extensions", "operational_trace"):
            _sqlite_quick_check(
                _safe_locator(root, str(binding["storage"][key])),
                code=f"WORKSPACE-{key.upper().replace('_', '-')}-DB-001",
            )
        project_id = str(binding["project_id"])
        profile_digest = str(binding["effective_profile_set"]["digest"])
        application = LocalResearchApplication(
            internal,
            resolver=_TypedOnlyResolver(),
            effective_profile_set_provider=_runtime_profile_provider(project_id, profile_digest, effective),
        )
        try:
            lineage = application.state_repository.load_active_lineage_ref(project_id)
            state = application.state_repository.load_state_view(project_id, lineage)
            if (
                state.project_ref != project_id
                or state.project_config_digest != str(binding["project_config"]["digest"])
                or state.effective_profile_set_digest != profile_digest
            ):
                raise LocalWorkspaceError("WORKSPACE-STATE-PIN-001", "opened Research State does not match workspace binding")
        except Exception:
            application.close()
            raise
        return OpenedLocalWorkspace(root, binding, config, effective, application)

    @classmethod
    def doctor(cls, workspace: str | Path) -> Mapping[str, Any]:
        """Read-only integrity checks. Never migrate, repair, or reopen stores read/write."""
        checks: list[dict[str, Any]] = []
        try:
            root = _assert_safe_workspace_root(Path(workspace))
            if not root.is_dir():
                raise LocalWorkspaceError("WORKSPACE-MISSING-001", "workspace directory does not exist")
            internal = _safe_locator(root, INTERNAL_DIR)
            if (internal / INITIALIZING_MARKER).exists():
                raise LocalWorkspaceError("WORKSPACE-PARTIAL-001", "workspace initialization is incomplete")
            binding_path = _safe_locator(root, f"{INTERNAL_DIR}/{BINDING_NAME}")
            binding = _read_json(binding_path, code="WORKSPACE-BINDING-001")
            _validate_binding_shape(binding)
            checks.append({"check": "workspace_binding", "status": "OK"})

            config, effective = _validated_documents(root, binding)
            checks.append({"check": "project_config", "status": "OK"})
            checks.append({"check": "effective_profile_set", "status": "OK"})

            for key, locator in binding["storage"].items():
                path = _safe_locator(root, str(locator))
                if key == "execution_root":
                    if not path.is_dir():
                        raise LocalWorkspaceError("WORKSPACE-MISSING-001", "execution root is missing")
                elif not path.is_file():
                    raise LocalWorkspaceError("WORKSPACE-MISSING-001", f"required storage is missing: {locator}")

            state_path = _safe_locator(root, str(binding["storage"]["research_state"]))
            _sqlite_quick_check(state_path, code="WORKSPACE-STATE-DB-001")
            _validate_state_database(state_path, binding)
            try:
                connection = sqlite3.connect(f"file:{state_path}?mode=ro", uri=True)
                try:
                    connection.row_factory = sqlite3.Row
                    active = connection.execute(
                        "SELECT active_lineage_ref FROM project_active_lineage WHERE project_ref=?",
                        (str(binding["project_id"]),),
                    ).fetchone()
                    if active is None:
                        raise LocalWorkspaceError(
                            "WORKSPACE-STATE-HEAD-001", "active Research Lineage is missing"
                        )
                    lineage = connection.execute(
                        "SELECT head_snapshot_ref FROM lineages WHERE lineage_id=?",
                        (str(active["active_lineage_ref"]),),
                    ).fetchone()
                    if lineage is None:
                        raise LocalWorkspaceError(
                            "WORKSPACE-STATE-HEAD-001", "active Research Lineage does not resolve"
                        )
                    active_lineage = str(active["active_lineage_ref"])
                    snapshot_id = str(lineage["head_snapshot_ref"])
                finally:
                    connection.close()
            except LocalWorkspaceError:
                raise
            except sqlite3.Error as exc:
                raise LocalWorkspaceError(
                    "WORKSPACE-STATE-DB-001", "Research State DB is unreadable or incompatible"
                ) from exc
            checks.append({
                "check": "research_state", "status": "OK",
                "active_lineage": active_lineage, "snapshot_id": snapshot_id,
            })

            for key, label in (
                ("conversation", "conversation_store"),
                ("decision", "decision_store"),
                ("execution", "execution_store"),
                ("context_extensions", "context_extension_store"),
                ("operational_trace", "operational_trace_store"),
            ):
                _sqlite_quick_check(
                    _safe_locator(root, str(binding["storage"][key])),
                    code=f"WORKSPACE-{key.upper().replace('_', '-')}-DB-001",
                )
                checks.append({"check": label, "status": "OK"})

            return {
                "status": "OK",
                "project_id": str(config["project"]["project_id"]),
                "checks": checks,
                "issues": [],
            }
        except LocalWorkspaceError as exc:
            return {
                "status": "ERROR",
                "checks": checks,
                "issues": [{"code": exc.code, "message": exc.message}],
            }
