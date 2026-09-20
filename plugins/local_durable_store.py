"""Optional Parent children: health is local; reads never initialize lost stores.

Schema expectations come from the owning stores' existing DDL. Payload content is
not guessed or deep-hashed here; its owner verifies the selected object on use.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import errno
import importlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping

OPTIONAL_DURABLE_CHILDREN = {
    "research_attention": {"locator": ".research-loom/attention.sqlite3", "kind": "file"},
    "profile_history": {"locator": ".research-loom/profile-history", "kind": "directory"},
    "research_exhibits": {"locator": ".research-loom/research-exhibits.sqlite3", "kind": "file"},
    "survey_registry": {"locator": ".research-loom/survey-registry.sqlite3", "kind": "file"},
    "survey_response_registry": {"locator": ".research-loom/survey-response-registry.sqlite3", "kind": "file"},
    "survey_analysis_registry": {"locator": ".research-loom/survey-analysis-registry.sqlite3", "kind": "file"},
    "delphi_registry": {"locator": ".research-loom/delphi-registry.sqlite3", "kind": "file"},
    "project_inputs": {"locator": ".research-loom/project-inputs", "kind": "directory"},
    "writer_compositions": {"locator": ".research-loom/writer-compositions", "kind": "directory"},
    "writer_round_trips": {"locator": ".research-loom/writer-round-trips", "kind": "directory"},
    "research_packages": {"locator": ".research-loom/research-packages", "kind": "directory"},
    "publication": {"locator": ".research-loom/publication", "kind": "directory"},
}

# Derived tables absent in supported older stores are not canonical data loss.
_DB_SCHEMAS = {
    "research_attention": ("local_attention_store", "_SCHEMA_SQL", "attention_store_meta", "ATTENTION_STORE_SCHEMA_VERSION", ()),
    "research_exhibits": ("local_research_exhibit_store", "_SCHEMA_SQL", "exhibit_store_meta", "EXHIBIT_STORE_SCHEMA_VERSION", ("research_exhibit_metadata",)),
    "survey_registry": ("local_survey_store", "_SCHEMA_SQL", "survey_store_meta", "SURVEY_STORE_SCHEMA_VERSION", ()),
    "survey_response_registry": ("local_survey_response_store", "_SCHEMA_SQL", "survey_response_store_meta", "SURVEY_RESPONSE_STORE_SCHEMA_VERSION", ("survey_response_dataset_entry_counts",)),
    "survey_analysis_registry": ("local_survey_analysis_store", "_SCHEMA_SQL", "survey_analysis_store_meta", "SURVEY_ANALYSIS_STORE_SCHEMA_VERSION", ()),
    "delphi_registry": ("local_delphi_store", "_SCHEMA", "delphi_store_meta", "SCHEMA_VERSION", ()),
}


class OptionalDurableStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@lru_cache(maxsize=16)
def _expected_columns(script: str) -> dict[str, set[tuple[Any, ...]]]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(script)
        names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            name: {tuple(row[1:]) for row in con.execute(f'PRAGMA table_info("{name}")')}
            for name in names
        }
    finally:
        con.close()


def _database_schema(name: str) -> tuple[str, str | None, str | None, tuple[str, ...]]:
    if name == "project_inputs":
        from plugins.local_project_input_store import LocalProjectInputStore
        return LocalProjectInputStore._create_table_sql(), None, None, ()
    module, ddl, meta, version, optional = _DB_SCHEMAS[name]
    owner = importlib.import_module(f"plugins.{module}")
    return getattr(owner, ddl), meta, str(getattr(owner, version)), optional


def _validate_database(path: Path, name: str, *, quick: bool) -> None:
    con = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
    try:
        if quick and con.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("SQLite quick_check failed")
        script, meta, version, optional = _database_schema(name)
        for table, expected in _expected_columns(script).items():
            actual = {tuple(row[1:]) for row in con.execute(f'PRAGMA table_info("{table}")')}
            if not actual and table in optional:
                continue
            if not expected <= actual:
                raise ValueError(f"SQLite schema is incompatible: {table}")
        if meta is not None:
            versions = con.execute(f'SELECT schema_version FROM "{meta}"').fetchall()
            if versions != [(version,)]:
                raise ValueError("SQLite schema version is incompatible")
        elif con.execute("PRAGMA user_version").fetchone()[0] not in (0, 1, 2):
            raise ValueError("Project Input schema version is incompatible")
    finally:
        con.close()


def inspect_optional_child(
    root: Path, name: str, binding: Mapping[str, Any], *, quick: bool = False,
) -> dict[str, Any]:
    from plugins.local_application.workspace import _safe_locator, LocalWorkspaceError

    spec = OPTIONAL_DURABLE_CHILDREN[name]
    registered = name in binding.get("durable_children", {})
    row: dict[str, Any] = {
        "name": name, "locator": spec["locator"], "registered": registered,
        "status": "OK", "payload_integrity": "UNCHECKED",
        "validation_scope": "presence",
    }
    try:
        path = _safe_locator(root, spec["locator"], require_exists=False)
        if not path.exists():
            if registered:
                raise OptionalDurableStoreError("WORKSPACE-OPTIONAL-CHILD-MISSING-001", "registered child is missing")
            row["status"] = "UNINITIALIZED" if "durable_children" in binding else "LEGACY_AMBIGUOUS"
            return row
        if not (path.is_file() if spec["kind"] == "file" else path.is_dir()):
            raise OptionalDurableStoreError("WORKSPACE-OPTIONAL-CHILD-TYPE-001", "child has the wrong filesystem type")
        if name in _DB_SCHEMAS or name == "project_inputs":
            database = path
            if name == "project_inputs":
                database = _safe_locator(root, spec["locator"] + "/project-inputs.sqlite3", require_exists=False)
                if not database.is_file():
                    raise OptionalDurableStoreError("WORKSPACE-OPTIONAL-METADATA-MISSING-001", "initialized child has no metadata database")
            _validate_database(database, name, quick=quick)
            row["validation_scope"] = "sqlite_quick_check_and_schema" if quick else "sqlite_schema"
        else:
            # Opening the directory detects access errors without traversing payloads.
            with os.scandir(path):
                pass
            row["validation_scope"] = "directory_presence; contents_unchecked"
    except (OSError, sqlite3.Error, ValueError, LocalWorkspaceError, OptionalDurableStoreError) as exc:
        if isinstance(exc, OptionalDurableStoreError):
            code = exc.code
        elif isinstance(exc, LocalWorkspaceError):
            code = "WORKSPACE-OPTIONAL-UNSAFE-PATH-001"
        elif isinstance(exc, OSError):
            code = "WORKSPACE-OPTIONAL-UNREADABLE-001"
        elif isinstance(exc, sqlite3.DatabaseError):
            code = "WORKSPACE-OPTIONAL-DATABASE-001"
        else:
            code = "WORKSPACE-OPTIONAL-SCHEMA-001"
        row.update({
            "status": "UNAVAILABLE", "code": code,
            "message": f"{name}: {exc}",
            "next_action": "restore the exact child from a consistent backup, then run doctor; do not initialize an empty replacement",
        })
    return row


def inspect_optional_children(root: Path, binding: Mapping[str, Any], *, quick: bool = False) -> list[dict[str, Any]]:
    return [inspect_optional_child(root, name, binding, quick=quick) for name in OPTIONAL_DURABLE_CHILDREN]


def _workspace_child(path: Path) -> tuple[Path, str] | None:
    # Lexical ancestors: never resolve away a symlink before the safety check.
    path = path.absolute()
    for internal in path.parents:
        if internal.name != ".research-loom":
            continue
        root = internal.parent
        relative = path.relative_to(root).as_posix()
        for name, spec in OPTIONAL_DURABLE_CHILDREN.items():
            locator = spec["locator"]
            if relative == locator or (spec["kind"] == "directory" and relative.startswith(locator + "/")):
                # Match the lexical child first so its symlink remains visible,
                # then normalize only the workspace root (Windows 8.3 aliases
                # and parent aliases are also normalized by LocalWorkspace.open).
                from plugins.local_application.workspace import _assert_safe_workspace_root
                return _assert_safe_workspace_root(root), name
        break
    return None


def require_optional_available(path: Path, error_type=OptionalDurableStoreError) -> None:
    child = _workspace_child(Path(path))
    if child is None:
        return  # Standalone store; no Parent initialization claim exists.
    root, name = child
    from plugins.local_application.workspace import BINDING_NAME, INTERNAL_DIR, _read_json, _validate_binding_shape
    binding_path = root / INTERNAL_DIR / BINDING_NAME
    if not binding_path.exists():
        return  # LocalResearchApplication bootstrap / standalone fixture.
    binding = _read_json(binding_path, code="WORKSPACE-BINDING-001")
    _validate_binding_shape(binding)
    result = inspect_optional_child(root, name, binding)
    if result["status"] == "UNAVAILABLE":
        raise error_type(result["code"], result["message"] + "; " + result["next_action"])


@contextmanager
def _inventory_lock(root: Path):
    from plugins.local_application.workspace import _safe_locator
    path = _safe_locator(root, ".research-loom/durable-children.lock", require_exists=False)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise OptionalDurableStoreError("WORKSPACE-OPTIONAL-INVENTORY-IO-001", "Parent inventory lock I/O failed") from exc
                if time.monotonic() >= deadline:
                    raise OptionalDurableStoreError("WORKSPACE-OPTIONAL-INVENTORY-BUSY-001", "Parent inventory lock could not be acquired") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def register_optional_path(path: Path) -> None:
    """Record initialization before accepting any domain data, not only on close."""
    child = _workspace_child(Path(path))
    if child is None:
        return
    root, name = child
    from plugins.local_application.workspace import BINDING_NAME, INTERNAL_DIR, _read_json, _validate_binding_shape, _atomic_json_write
    binding_path = root / INTERNAL_DIR / BINDING_NAME
    if not binding_path.is_file():
        return
    with _inventory_lock(root):
        binding = _read_json(binding_path, code="WORKSPACE-BINDING-001")
        _validate_binding_shape(binding)
        children = binding.get("durable_children")
        if children is None or name in children:
            return
        binding["durable_children"][name] = deepcopy(OPTIONAL_DURABLE_CHILDREN[name])
        _atomic_json_write(binding_path, binding)
