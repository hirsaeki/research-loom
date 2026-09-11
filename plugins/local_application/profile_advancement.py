from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Mapping
import uuid

from plugins.local_application.profile_resolution import (
    effective_profile_digest,
    exact_manifest_identity_map,
    resolve_effective_profile_set,
    target_project_config,
)
from plugins.local_application.workspace import (
    BINDING_NAME,
    EFFECTIVE_PROFILE_SET_NAME,
    INTERNAL_DIR,
    PROJECT_CONFIG_NAME,
    LocalWorkspace,
    LocalWorkspaceError,
    _assert_safe_workspace_root,
    _binding,
    _read_json,
    _safe_locator,
    _schema_validate,
    _validate_profile_binding,
    _validate_project_semantics,
    _validate_binding_shape,
    PROJECT_CONFIG_SCHEMA,
    EFFECTIVE_PROFILE_SET_SCHEMA,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository

HISTORY_DIR = "profile-history"
GENERATIONS_DIR = "generations"
EVENTS_DIR = "events"
PENDING_MARKER = "profile-advancement.pending.json"
ADVANCEMENT_LOCK = "profile-advancement.lock"
_LOCK_STATE = threading.local()
_ADVANCEMENT_NOTE = "Profile generation advancement: direct Profile requests changed mechanically; other project semantics are unchanged."




@contextmanager
def _workspace_advancement_lock(root: Path):
    if not root.is_dir():
        raise LocalWorkspaceError("WORKSPACE-MISSING-001", "workspace directory does not exist")
    key = str(root.resolve(strict=True))
    leases = getattr(_LOCK_STATE, "leases", None)
    if leases is None:
        leases = {}
        _LOCK_STATE.leases = leases
    lease = leases.get(key)
    if lease is None:
        internal = _safe_locator(root, INTERNAL_DIR)
        if not internal.is_dir():
            raise LocalWorkspaceError("WORKSPACE-MISSING-001", "workspace internal directory is missing")
        lock_path = _safe_locator(root, f"{INTERNAL_DIR}/{ADVANCEMENT_LOCK}", require_exists=False)
        handle = lock_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            handle.close()
            raise
        lease = {"handle": handle, "count": 0}
        leases[key] = lease

    lease["count"] += 1
    try:
        yield
    finally:
        lease["count"] -= 1
        if lease["count"] == 0:
            leases.pop(key, None)
            handle = lease["handle"]
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _generation_key(config_digest: str, profile_digest: str) -> str:
    return f"cfg-{config_digest.removeprefix('sha256:')}__eps-{profile_digest.removeprefix('sha256:')}"


def _generation_dir(root: Path, config_digest: str, profile_digest: str) -> Path:
    return root / INTERNAL_DIR / HISTORY_DIR / GENERATIONS_DIR / _generation_key(config_digest, profile_digest)


def _flatten_constraints(effective: Mapping[str, Any]) -> dict[str, Any]:
    return {str(item["path"]): deepcopy(dict(item)) for item in effective.get("effective_constraints", [])}


def _validate_target_project_delta(current: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    if str(current["project"]["project_id"]) != str(target["project"]["project_id"]):
        raise LocalWorkspaceError("PROFILE-ADVANCE-PROJECT-001", "Profile advancement cannot change project identity")
    current_rest = deepcopy(dict(current))
    target_rest = deepcopy(dict(target))
    for value in (current_rest, target_rest):
        value.pop("configuration_digest", None)
        value.pop("profile_requests", None)
        value.pop("provenance", None)
    if current_rest != target_rest:
        raise LocalWorkspaceError(
            "PROFILE-ADVANCE-PROJECT-SEMANTICS-001",
            "Profile advancement may not change Project Config semantics outside profile_requests/provenance",
        )
    old_prov = current["provenance"]
    new_prov = target["provenance"]
    if list(new_prov.get("source_reference_ids", [])) != list(old_prov.get("source_reference_ids", [])):
        raise LocalWorkspaceError("PROFILE-ADVANCE-PROJECT-SEMANTICS-001", "Profile advancement may not change provenance source references")
    old_derived = list(old_prov.get("derived_from_configuration_digests", []))
    new_derived = list(new_prov.get("derived_from_configuration_digests", []))
    old_notes = list(old_prov.get("notes", []))
    new_notes = list(new_prov.get("notes", []))
    requests_changed = current["profile_requests"] != target["profile_requests"]
    if requests_changed:
        expected_derived = old_derived + ([] if current["configuration_digest"] in old_derived else [current["configuration_digest"]])
        expected_notes = old_notes + ([] if _ADVANCEMENT_NOTE in old_notes else [_ADVANCEMENT_NOTE])
        if new_derived != expected_derived or new_notes != expected_notes:
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-PROJECT-PROVENANCE-001",
                "Profile request evolution must carry only the canonical mechanical provenance update",
            )
    elif new_prov != old_prov:
        raise LocalWorkspaceError(
            "PROFILE-ADVANCE-PROJECT-PROVENANCE-001",
            "EPS-only advancement may not rewrite Project Config provenance",
        )


def _reject_same_identity_content_swap(current_eps: Mapping[str, Any], target_eps: Mapping[str, Any]) -> None:
    current = {
        (str(item["profile_type"]), str(item["profile_id"]), str(item["profile_version"])): str(item["manifest_sha256"])
        for item in current_eps.get("effective_profiles", [])
    }
    for item in target_eps.get("effective_profiles", []):
        identity = (str(item["profile_type"]), str(item["profile_id"]), str(item["profile_version"]))
        old_digest = current.get(identity)
        if old_digest is not None and old_digest != str(item["manifest_sha256"]):
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-IDENTITY-001",
                "same Profile id/version cannot change manifest content during generation advancement",
            )


def _strengthening_bindings(invariant: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for source in invariant.get("provenance", []):
        binding = source.get("validator_binding") if isinstance(source, Mapping) else None
        if not isinstance(binding, Mapping):
            continue
        result.add((str(binding.get("validator_id")), str(binding.get("validator_version")), str(binding.get("form_id"))))
    return result


def _reject_core_weakening(current_eps: Mapping[str, Any], target_eps: Mapping[str, Any]) -> None:
    target = {str(item["invariant_id"]): item for item in target_eps.get("core_invariants", [])}
    for old in current_eps.get("core_invariants", []):
        if old.get("status") != "strengthened":
            continue
        new = target.get(str(old["invariant_id"]))
        old_bindings = _strengthening_bindings(old)
        new_bindings = _strengthening_bindings(new or {})
        if new is None or new.get("status") != "strengthened" or not old_bindings <= new_bindings:
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-CORE-WEAKENING-001",
                f"target Profile generation weakens Core invariant {old['invariant_id']}",
            )


def _validate_authoritative_state(state, target_eps: Mapping[str, Any]) -> None:
    constraints = _flatten_constraints(target_eps)
    required = constraints.get("evidence.capture.required_fields")
    if required is None:
        return
    fields = required.get("value")
    if not isinstance(fields, list) or any(not isinstance(item, str) or not item for item in fields):
        raise LocalWorkspaceError(
            "PROFILE-ADVANCE-STATE-COMPAT-001",
            "target executable evidence.capture.required_fields constraint is malformed",
        )
    for obj in state.objects:
        if str(obj.get("kind")) != "evidence":
            continue
        missing = [field for field in fields if field not in obj]
        if missing:
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-STATE-COMPAT-001",
                f"authoritative Evidence {obj.get('id')} is incompatible with target Profile constraints: missing {', '.join(missing)}",
            )


def _archive_generation(root: Path, *, config_text: str, effective_text: str, config_digest: str, profile_digest: str) -> list[str]:
    directory = _generation_dir(root, config_digest, profile_digest)
    config_path = directory / PROJECT_CONFIG_NAME
    profile_path = directory / EFFECTIVE_PROFILE_SET_NAME
    created: list[str] = []
    if directory.exists():
        if not config_path.is_file() or not profile_path.is_file():
            raise LocalWorkspaceError("PROFILE-HISTORY-001", "historical Profile generation is incomplete")
        if config_path.read_text(encoding="utf-8") != config_text or profile_path.read_text(encoding="utf-8") != effective_text:
            raise LocalWorkspaceError("PROFILE-HISTORY-001", "historical Profile generation content is not immutable")
        return created
    directory.mkdir(parents=True, exist_ok=False)
    _write_text(config_path, config_text)
    _write_text(profile_path, effective_text)
    created.append(str(directory.relative_to(root)))
    return created


def _remove_created(root: Path, paths: list[str]) -> None:
    for locator in reversed(paths):
        target = _safe_locator(root, locator, require_exists=False)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            try:
                target.unlink()
            except OSError:
                pass


def _state_rebind(root: Path, binding: Mapping[str, Any], *, expected_config: str, expected_profile: str, config: Mapping[str, Any], effective: Mapping[str, Any]) -> None:
    state_path = root / str(binding["storage"]["research_state"])
    with SQLiteResearchStateRepository(state_path) as repository:
        repository.rebind_current_configuration(
            str(binding["project_id"]),
            expected_project_config_digest=expected_config,
            expected_effective_profile_set_digest=expected_profile,
            project_config_ref=PROJECT_CONFIG_NAME,
            project_config_digest=str(config["configuration_digest"]),
            project_config=config,
            effective_profile_set_ref=EFFECTIVE_PROFILE_SET_NAME,
            effective_profile_set_digest=effective_profile_digest(effective),
            effective_constraints=_flatten_constraints(effective),
        )


def _recover_incomplete_profile_advancement_locked(root: Path) -> None:
    marker_path = _safe_locator(root, f"{INTERNAL_DIR}/{PENDING_MARKER}", require_exists=False)
    if not marker_path.exists():
        return
    marker = _read_json(marker_path, code="PROFILE-ADVANCE-RECOVERY-001")
    old_binding = marker.get("old_binding")
    new_binding = marker.get("new_binding")
    if not isinstance(old_binding, Mapping) or not isinstance(new_binding, Mapping):
        raise LocalWorkspaceError("PROFILE-ADVANCE-RECOVERY-001", "Profile advancement recovery marker is malformed")
    _validate_binding_shape(old_binding)
    _validate_binding_shape(new_binding)
    old_config = marker.get("old_project_config")
    old_effective = marker.get("old_effective_profile_set")
    if not isinstance(old_config, Mapping) or not isinstance(old_effective, Mapping):
        raise LocalWorkspaceError("PROFILE-ADVANCE-RECOVERY-001", "Profile advancement recovery marker lacks old generation")
    event_locator = marker.get("event_locator")
    if event_locator is not None and not isinstance(event_locator, str):
        raise LocalWorkspaceError("PROFILE-ADVANCE-RECOVERY-001", "Profile advancement recovery event locator is malformed")
    event_path = (
        _safe_locator(root, event_locator, require_exists=False)
        if isinstance(event_locator, str)
        else None
    )
    created_history_paths = marker.get("created_history_paths", [])
    if not isinstance(created_history_paths, list) or not all(isinstance(locator, str) for locator in created_history_paths):
        raise LocalWorkspaceError("PROFILE-ADVANCE-RECOVERY-001", "Profile advancement recovery history locators are malformed")
    for locator in created_history_paths:
        _safe_locator(root, locator, require_exists=False)

    # Restore DB only when it reached the target binding. If it is already old, no DB write is needed.
    state_path = _safe_locator(root, str(old_binding["storage"]["research_state"]))
    with SQLiteResearchStateRepository(state_path) as repository:
        lineage = repository.load_active_lineage_ref(str(old_binding["project_id"]))
        state = repository.load_state_view(str(old_binding["project_id"]), lineage)
        if (
            state.project_config_digest == str(new_binding["project_config"]["digest"])
            and state.effective_profile_set_digest == str(new_binding["effective_profile_set"]["digest"])
        ):
            repository.rebind_current_configuration(
                str(old_binding["project_id"]),
                expected_project_config_digest=str(new_binding["project_config"]["digest"]),
                expected_effective_profile_set_digest=str(new_binding["effective_profile_set"]["digest"]),
                project_config_ref=str(old_binding["project_config"]["locator"]),
                project_config_digest=str(old_binding["project_config"]["digest"]),
                project_config=old_config,
                effective_profile_set_ref=str(old_binding["effective_profile_set"]["locator"]),
                effective_profile_set_digest=str(old_binding["effective_profile_set"]["digest"]),
                effective_constraints=_flatten_constraints(old_effective),
            )
        elif not (
            state.project_config_digest == str(old_binding["project_config"]["digest"])
            and state.effective_profile_set_digest == str(old_binding["effective_profile_set"]["digest"])
        ):
            raise LocalWorkspaceError("PROFILE-ADVANCE-RECOVERY-001", "Research State is neither the old nor target Profile binding")
    _write_text(root / PROJECT_CONFIG_NAME, str(marker["old_project_config_text"]))
    _write_text(root / EFFECTIVE_PROFILE_SET_NAME, str(marker["old_effective_profile_set_text"]))
    _write_json(root / INTERNAL_DIR / BINDING_NAME, old_binding)
    if event_path is not None and event_path.exists():
        event_path.unlink()
    _remove_created(root, created_history_paths)
    marker_path.unlink()


def recover_incomplete_profile_advancement(root: Path) -> None:
    root = _assert_safe_workspace_root(Path(root))
    with _workspace_advancement_lock(root):
        _recover_incomplete_profile_advancement_locked(root)


def prepare_profile_generation(workspace: str | Path, request: Mapping[str, Any], output: str | Path) -> Mapping[str, Any]:
    root = _assert_safe_workspace_root(Path(workspace))
    manifest_files = request.get("profile_manifest_files")
    replacements = request.get("request_replacements", [])
    if not isinstance(manifest_files, list) or not all(isinstance(item, str) for item in manifest_files):
        raise LocalWorkspaceError("PROFILE-RESOLVE-INPUT-001", "profile_manifest_files must be a list of file paths")
    if not isinstance(replacements, list) or not all(isinstance(item, Mapping) for item in replacements):
        raise LocalWorkspaceError("PROFILE-RESOLVE-INPUT-001", "request_replacements must be a list")
    with LocalWorkspace.open(root) as opened:
        current = deepcopy(dict(opened.project_config))
    target_config = target_project_config(current, replacements)
    _schema_validate(target_config, PROJECT_CONFIG_SCHEMA, "WORKSPACE-PROJECT-CONFIG-SCHEMA-001")
    _validate_project_semantics(target_config)
    _validate_target_project_delta(current, target_config)
    target_eps = resolve_effective_profile_set(target_config, manifest_files)
    _validate_profile_binding(target_config, target_eps)

    out = Path(output).expanduser().resolve(strict=False)
    if out.exists():
        raise LocalWorkspaceError("PROFILE-RESOLVE-OUTPUT-001", "profile resolve output path already exists")
    out.mkdir(parents=True)
    _write_json(out / PROJECT_CONFIG_NAME, target_config)
    _write_json(out / EFFECTIVE_PROFILE_SET_NAME, target_eps)
    manifest_pins = exact_manifest_identity_map(manifest_files)
    resolution = {
        "schema_version": "0.1.0",
        "source_project_config_digest": current["configuration_digest"],
        "target_project_config_digest": target_config["configuration_digest"],
        "target_effective_profile_set_digest": effective_profile_digest(target_eps),
        "profile_request_changed": current["profile_requests"] != target_config["profile_requests"],
        "profile_manifest_files": [str(Path(item).expanduser().resolve(strict=True)) for item in manifest_files],
        "manifest_pins": [
            {"profile_type": key[0], "profile_id": key[1], "profile_version": key[2], "manifest_sha256": digest}
            for key, digest in sorted(manifest_pins.items())
        ],
    }
    _write_json(out / "resolution.json", resolution)
    return {"status": "OK", "output": str(out), **resolution}


def advance_profile_generation(workspace: str | Path, request: Mapping[str, Any]) -> Mapping[str, Any]:
    root = _assert_safe_workspace_root(Path(workspace))
    with _workspace_advancement_lock(root):
        return _advance_profile_generation_locked(root, request)


def _advance_profile_generation_locked(root: Path, request: Mapping[str, Any]) -> Mapping[str, Any]:
    target_config_file = request.get("project_config_file")
    target_eps_file = request.get("effective_profile_set_file")
    manifest_files = request.get("profile_manifest_files")
    origin = request.get("origin", "operator")
    if not isinstance(target_config_file, str) or not isinstance(target_eps_file, str):
        raise LocalWorkspaceError("PROFILE-ADVANCE-INPUT-001", "project_config_file and effective_profile_set_file are required")
    if not isinstance(manifest_files, list) or not all(isinstance(item, str) for item in manifest_files):
        raise LocalWorkspaceError("PROFILE-ADVANCE-INPUT-001", "profile_manifest_files must be a list of file paths")
    if not isinstance(origin, str) or not origin.strip():
        raise LocalWorkspaceError("PROFILE-ADVANCE-INPUT-001", "origin must be a non-empty string")

    recover_incomplete_profile_advancement(root)
    with LocalWorkspace.open(root) as opened:
        old_binding = deepcopy(dict(opened.binding))
        old_config = deepcopy(dict(opened.project_config))
        old_eps = deepcopy(dict(opened.effective_profile_set))
        state = opened.application.state_repository.load_state_view(opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id))
        lineage_id = state.lineage_ref
        snapshot = deepcopy(dict(state.current_snapshot))

    target_config_path = Path(target_config_file).expanduser().resolve(strict=True)
    target_eps_path = Path(target_eps_file).expanduser().resolve(strict=True)
    target_config = _read_json(target_config_path, code="WORKSPACE-PROJECT-CONFIG-001")
    target_eps = _read_json(target_eps_path, code="WORKSPACE-PROFILE-SET-001")
    _schema_validate(target_config, PROJECT_CONFIG_SCHEMA, "WORKSPACE-PROJECT-CONFIG-SCHEMA-001")
    _schema_validate(target_eps, EFFECTIVE_PROFILE_SET_SCHEMA, "WORKSPACE-PROFILE-SET-SCHEMA-001")
    _validate_project_semantics(target_config)
    _validate_profile_binding(target_config, target_eps)
    _validate_target_project_delta(old_config, target_config)
    resolved = resolve_effective_profile_set(target_config, manifest_files)
    if resolved != target_eps:
        raise LocalWorkspaceError(
            "PROFILE-ADVANCE-PROVENANCE-001",
            "target Effective Profile Set does not exactly match production resolution from supplied manifests",
        )
    _reject_same_identity_content_swap(old_eps, target_eps)
    _reject_core_weakening(old_eps, target_eps)
    _validate_authoritative_state(state, target_eps)

    new_config_digest = str(target_config["configuration_digest"])
    new_profile_digest = effective_profile_digest(target_eps)
    old_config_digest = str(old_binding["project_config"]["digest"])
    old_profile_digest = str(old_binding["effective_profile_set"]["digest"])
    if old_config_digest == new_config_digest and old_profile_digest == new_profile_digest:
        return {
            "status": "OK",
            "result": "NOOP",
            "project_id": str(old_binding["project_id"]),
            "lineage_id": lineage_id,
            "project_config_digest": old_config_digest,
            "effective_profile_set_digest": old_profile_digest,
        }

    target_binding = _binding(str(old_binding["project_id"]), new_config_digest, new_profile_digest, initialized_at=str(old_binding["initialized_at"]))
    event_id = "PGA-" + uuid.uuid4().hex
    event_locator = f"{INTERNAL_DIR}/{HISTORY_DIR}/{EVENTS_DIR}/{event_id}.json"
    old_config_text = (root / PROJECT_CONFIG_NAME).read_text(encoding="utf-8")
    old_eps_text = (root / EFFECTIVE_PROFILE_SET_NAME).read_text(encoding="utf-8")
    target_config_text = target_config_path.read_text(encoding="utf-8")
    target_eps_text = target_eps_path.read_text(encoding="utf-8")
    event = {
        "schema_version": "0.1.0",
        "event_id": event_id,
        "event_type": "project_profile_generation_advanced",
        "project_id": str(old_binding["project_id"]),
        "lineage_id": lineage_id,
        "applied_at": _now(),
        "origin": origin,
        "old_binding": {
            "project_config_digest": old_config_digest,
            "effective_profile_set_digest": old_profile_digest,
            "generation_locator": str(_generation_dir(root, old_config_digest, old_profile_digest).relative_to(root)),
        },
        "new_binding": {
            "project_config_digest": new_config_digest,
            "effective_profile_set_digest": new_profile_digest,
            "generation_locator": str(_generation_dir(root, new_config_digest, new_profile_digest).relative_to(root)),
        },
        "research_snapshot": {
            "snapshot_id": snapshot["id"],
            "revision": snapshot.get("revision", 0),
            "content_digest": snapshot["content_digest"],
        },
        "research_state_mutation_performed": False,
    }
    marker_path = root / INTERNAL_DIR / PENDING_MARKER
    old_generation_dir = _generation_dir(root, old_config_digest, old_profile_digest)
    new_generation_dir = _generation_dir(root, new_config_digest, new_profile_digest)
    prospective_history_paths = [
        str(path.relative_to(root))
        for path in (old_generation_dir, new_generation_dir)
        if not path.exists()
    ]
    marker = {
        "schema_version": "0.1.0",
        "event_locator": event_locator,
        "created_history_paths": prospective_history_paths,
        "old_binding": old_binding,
        "new_binding": target_binding,
        "old_project_config": old_config,
        "old_effective_profile_set": old_eps,
        "old_project_config_text": old_config_text,
        "old_effective_profile_set_text": old_eps_text,
        "new_project_config": target_config,
        "new_effective_profile_set": target_eps,
    }
    _write_json(marker_path, marker)
    try:
        _archive_generation(root, config_text=old_config_text, effective_text=old_eps_text, config_digest=old_config_digest, profile_digest=old_profile_digest)
        _archive_generation(root, config_text=target_config_text, effective_text=target_eps_text, config_digest=new_config_digest, profile_digest=new_profile_digest)
        _write_text(root / PROJECT_CONFIG_NAME, target_config_text)
        _write_text(root / EFFECTIVE_PROFILE_SET_NAME, target_eps_text)
        _write_json(root / INTERNAL_DIR / BINDING_NAME, target_binding)
        _state_rebind(
            root,
            old_binding,
            expected_config=old_config_digest,
            expected_profile=old_profile_digest,
            config=target_config,
            effective=target_eps,
        )
        _write_json(root / event_locator, event)
        marker_path.unlink()
    except Exception:
        # A later reopen also has the same deterministic recovery path if rollback here is interrupted.
        try:
            recover_incomplete_profile_advancement(root)
        except Exception:
            pass
        raise

    with LocalWorkspace.open(root) as reopened:
        new_state = reopened.application.state_repository.load_state_view(reopened.project_id, reopened.application.state_repository.load_active_lineage_ref(reopened.project_id))
        if (
            new_state.project_config_digest != new_config_digest
            or new_state.effective_profile_set_digest != new_profile_digest
            or new_state.current_snapshot.get("id") != snapshot.get("id")
            or new_state.current_snapshot.get("content_digest") != snapshot.get("content_digest")
        ):
            raise LocalWorkspaceError("PROFILE-ADVANCE-VERIFY-001", "reopened Workspace did not expose the exact advanced binding")
    return {
        "status": "OK",
        "result": "ADVANCED",
        "event_id": event_id,
        "project_id": str(old_binding["project_id"]),
        "lineage_id": lineage_id,
        "old_project_config_digest": old_config_digest,
        "old_effective_profile_set_digest": old_profile_digest,
        "new_project_config_digest": new_config_digest,
        "new_effective_profile_set_digest": new_profile_digest,
        "research_snapshot": event["research_snapshot"],
    }


def profile_history(workspace: str | Path) -> Mapping[str, Any]:
    root = _assert_safe_workspace_root(Path(workspace))
    recover_incomplete_profile_advancement(root)
    with LocalWorkspace.open(root) as opened:
        current = {
            "project_config_digest": opened.binding["project_config"]["digest"],
            "effective_profile_set_digest": opened.binding["effective_profile_set"]["digest"],
        }
    history_root = root / INTERNAL_DIR / HISTORY_DIR
    generations = []
    generation_root = history_root / GENERATIONS_DIR
    if generation_root.exists():
        for directory in sorted(path for path in generation_root.iterdir() if path.is_dir()):
            config = _read_json(directory / PROJECT_CONFIG_NAME, code="PROFILE-HISTORY-001")
            eps = _read_json(directory / EFFECTIVE_PROFILE_SET_NAME, code="PROFILE-HISTORY-001")
            _schema_validate(config, PROJECT_CONFIG_SCHEMA, "PROFILE-HISTORY-001")
            _schema_validate(eps, EFFECTIVE_PROFILE_SET_SCHEMA, "PROFILE-HISTORY-001")
            _validate_project_semantics(config)
            _validate_profile_binding(config, eps)
            config_digest = str(config["configuration_digest"])
            profile_digest = effective_profile_digest(eps)
            if directory.name != _generation_key(config_digest, profile_digest):
                raise LocalWorkspaceError("PROFILE-HISTORY-001", "historical Profile generation locator does not match its exact digests")
            generations.append({
                "locator": str(directory.relative_to(root)),
                "project_config_digest": config_digest,
                "effective_profile_set_digest": profile_digest,
                "project_config": config,
                "effective_profile_set": eps,
            })
    events = []
    events_root = history_root / EVENTS_DIR
    if events_root.exists():
        for path in sorted(events_root.glob("*.json")):
            events.append(_read_json(path, code="PROFILE-HISTORY-001"))
    return {"status": "OK", "current": current, "generations": generations, "events": events}
