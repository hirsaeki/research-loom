"""Conservative initialization diagnosis and exact committed-marker finalization.

No tree deletion or reconstruction is performed. An operator can preserve an
uncommitted directory and use the normal initializer at a new empty location.
"""
from __future__ import annotations

import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping

from core.runtime import canonical_digest
from .workspace import (BINDING_NAME, EFFECTIVE_PROFILE_SET_NAME, INITIALIZING_MARKER,
                        INTERNAL_DIR, PROJECT_CONFIG_NAME, LocalWorkspaceError,
                        _safe_locator)

INTENT_FORMAT = "research-loom-initialization/v1"


# A readable SQLite file can still have no initialized schema. Require the
# existing operational store shape before normal open or init-finish can claim
# it is usable. This checks schema only, not the truth/completeness of all history.
_REQUIRED_STORE_COLUMNS = {
    "WORKSPACE-DECISION-DB-001": {
        "decision_requests": "request_id request_digest project_ref lineage_ref source_candidate_id source_candidate_digest snapshot_ref snapshot_digest payload_json status claimed_response_digest commit_id commit_receipt_json detail",
        "decision_responses": "response_digest request_id response_id disposition actor_id actor_type payload_json outcome detail",
    },
    "WORKSPACE-EXECUTION-DB-001": {
        "schema_migrations": "version name applied_at",
        "runs": "run_id invocation_id invocation_digest capability_id capability_version descriptor_digest implementation_id implementation_version function_id execution_mode context_pack_id context_pack_digest project_ref lineage_ref snapshot_ref snapshot_digest attempt parent_run_id status prepared_at started_at completed_at handoff_ref handoff_digest failure_json provenance_json",
        "run_events": "run_id sequence from_status to_status occurred_at reason",
        "execution_documents": "document_type identity payload_sha256 payload_json run_id",
        "diagnostics": "diagnostic_id run_id kind payload_json",
        "execution_artifacts": "artifact_id run_id role media_type size digest storage_locator execution_mode provenance_json",
        "input_resources": "reference_id media_type size digest storage_locator provenance_json",
    },
    "WORKSPACE-CONTEXT-EXTENSIONS-DB-001": {
        "context_extensions": "capability_id capability_version function_id context_pack_id payload_sha256 payload_json",
    },
    "WORKSPACE-OPERATIONAL-TRACE-DB-001": {
        "operational_events": "run_id sequence event_id event_type occurred_at payload_sha256 payload_json",
    },
}


def validate_required_store_schema(connection: sqlite3.Connection, code: str) -> None:
    for table, columns in _REQUIRED_STORE_COLUMNS.get(code, {}).items():
        row = connection.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
        present = {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if row is None or row[0] != "table" or not set(columns.split()) <= present:
            raise LocalWorkspaceError(code, f"required store schema is missing/incompatible: {table}; preserve the Workspace and restore an exact complete backup")


def initial_intent(root: Path, config: Mapping[str, Any], effective: Mapping[str, Any]) -> dict:
    def digest(value):
        # Match _copy_json/TextIOWrapper native newline bytes, including CRLF.
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + os.linesep).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
    return {"format": INTENT_FORMAT, "phase": "PRE_STATE",
            "root": hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
            "files": {PROJECT_CONFIG_NAME: digest(config), EFFECTIVE_PROFILE_SET_NAME: digest(effective)}}


def _read(path: Path, maximum: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise ValueError("not a bounded regular file")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) != info.st_size or len(raw) > maximum:
        raise ValueError("file changed during diagnosis")
    return raw


def _names(root: Path) -> set[str]:
    # An unfamiliar/non-small tree is never treated as disposable initialization.
    names = list(islice(root.iterdir(), 17))
    if len(names) > 16:
        raise ValueError("not a small initialization staging directory")
    return {path.name for path in names}


def diagnose_initialization(root: Path, integrity: Mapping[str, Any]) -> Mapping[str, Any]:
    classification = "INDETERMINATE"
    binding_digest = None
    next_action = "Stop all processes using this path and preserve the entire directory. Restore an exact complete backup, or initialize a NEW empty Workspace; do not delete the marker to bypass verification."
    try:
        internal = _safe_locator(root, INTERNAL_DIR)
        binding_path = internal / BINDING_NAME
        if integrity.get("status") in {"OK", "DEGRADED"}:
            binding = json.loads(_read(binding_path, 1024 * 1024))
            binding_digest = canonical_digest(binding)
            classification = "COMMITTED_WORKSPACE"
            next_action = "Preserve all research records. Review the full integrity results, then use init-finish with this exact binding_digest. Only the initialization marker will be removed."
        else:
            database = internal / "research-state.sqlite3"
            if database.exists() and stat.S_ISREG(database.lstat().st_mode):
                connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                try:
                    if connection.execute("SELECT 1 FROM project_state LIMIT 1").fetchone():
                        classification = "RESEARCH_RECORDS_PRESENT"
                finally:
                    connection.close()
            # PRE_STATE alone is insufficient: target binding, exact known files
            # and the absence of any State/user/unknown paths must also agree.
            if classification == "INDETERMINATE" and _names(root) == {INTERNAL_DIR}:
                from .workspace_lock import ADVANCEMENT_LOCK
                allowed = {INITIALIZING_MARKER, ADVANCEMENT_LOCK, PROJECT_CONFIG_NAME, EFFECTIVE_PROFILE_SET_NAME}
                names = _names(internal)
                intent = json.loads(_read(internal / INITIALIZING_MARKER, 4096))
                expected_files = {PROJECT_CONFIG_NAME, EFFECTIVE_PROFILE_SET_NAME}
                if (names <= allowed and intent.get("format") == INTENT_FORMAT and intent.get("phase") == "PRE_STATE"
                        and intent.get("root") == hashlib.sha256(str(root).encode("utf-8")).hexdigest()
                        and isinstance(intent.get("files"), dict) and set(intent["files"]) == expected_files
                        and all(isinstance(value, str) and len(value) == 64 for value in intent["files"].values())):
                    if any(not stat.S_ISREG((internal / name).lstat().st_mode) for name in names):
                        raise ValueError("staging contains an unexpected path type")
                    for name in names & expected_files:
                        if hashlib.sha256(_read(internal / name, 1024 * 1024)).hexdigest() != intent["files"][name]:
                            raise ValueError("staging input differs from intent")
                    classification = "PRECOMMIT_STAGING"
                    next_action = "After stopping the initializer and all other processes, retain/quarantine this entire directory without deleting it. Run normal init at a NEW empty path using the explicit original Config/Profile inputs. Do not merge files into this partial directory."
    except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error, LocalWorkspaceError):
        # Unknown bytes are not permission to clean up or silently create a store.
        pass
    return {"status": "ERROR", "checks": integrity.get("checks", []),
            "issues": [{"code": "WORKSPACE-PARTIAL-001", "message": "initialization is incomplete; inspect initialization classification and next_action"}],
            "initialization": {"classification": classification, "binding_digest": binding_digest,
                               "integrity_without_marker": dict(integrity), "next_action": next_action,
                               "cleanup_allowed": False, "live_process_status": "NOT_DETERMINED",
                               "quarantine_after_quiescence": classification == "PRECOMMIT_STAGING"}}


def finish_initialization(workspace: str | Path, expected_binding_digest: str) -> Mapping[str, Any]:
    """Remove only a stale marker after exact, exclusive, full verification."""
    from .workspace import LocalWorkspace, _assert_safe_workspace_root
    from .workspace_lock import workspace_lock
    root = _assert_safe_workspace_root(Path(workspace))
    with workspace_lock(root):
        integrity = LocalWorkspace._doctor_integrity(root)
        if integrity.get("status") not in {"OK", "DEGRADED"}:
            raise LocalWorkspaceError("WORKSPACE-INIT-FINISH-001", "committed Workspace does not fully verify; preserve the directory and inspect doctor")
        binding = json.loads(_read(_safe_locator(root, f"{INTERNAL_DIR}/{BINDING_NAME}"), 1024 * 1024))
        if canonical_digest(binding) != expected_binding_digest:
            raise LocalWorkspaceError("WORKSPACE-INIT-FINISH-001", "expected binding differs; inspect doctor again before finalization")
        marker = _safe_locator(root, f"{INTERNAL_DIR}/{INITIALIZING_MARKER}", require_exists=False)
        try:
            marker_info = marker.lstat()
        except FileNotFoundError:
            marker_info = None
        except OSError as exc:
            raise LocalWorkspaceError("WORKSPACE-INIT-FINISH-001", "cannot inspect initialization marker; resolve access/I/O and retry") from exc
        if marker_info is not None:
            # Marker content is not authority. All canonical stores and current
            # pins above must verify even for a legacy or damaged marker.
            if not stat.S_ISREG(marker_info.st_mode):
                raise LocalWorkspaceError("WORKSPACE-INIT-FINISH-001", "initialization marker is not a regular file")
            try:
                marker.unlink()
            except OSError as exc:
                raise LocalWorkspaceError("WORKSPACE-INIT-FINISH-001", "cannot remove verified initialization marker; preserve records and retry after resolving I/O") from exc
            result = "FINISHED"
        else:
            result = "VERIFIED_REUSE"
        return {"status": integrity["status"], "result": result, "binding_digest": expected_binding_digest,
                "research_state_mutation_performed": False, "integrity": integrity}
