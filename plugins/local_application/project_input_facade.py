from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from plugins.local_execution_store import bind_controlled_import_root, read_controlled_file
from .facade import LocalApplicationError
from .external_attempt_lifecycle_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ROLES = {"theme", "expectations", "project_brief", "scope", "methodology", "publication_brief", "other"}
_MAX_BYTES = 8 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _ProjectInputRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root / ".research-loom" / "project-inputs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "project-inputs.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS project_inputs(
                input_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                media_type TEXT NOT NULL,
                byte_length INTEGER NOT NULL,
                content_digest TEXT NOT NULL,
                source_path TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                lineage_ref TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                snapshot_digest TEXT NOT NULL,
                UNIQUE(project_id, role, content_digest)
            )
            """
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def register(self, *, project_id: str, role: str, media_type: str, content: bytes,
                 source_path: str, provenance: Mapping[str, Any], lineage_ref: str,
                 snapshot_id: str, snapshot_digest: str) -> dict[str, Any]:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        identity_seed = f"{project_id}\0{role}\0{digest}".encode("utf-8")
        input_id = "PIN-" + hashlib.sha256(identity_seed).hexdigest()[:24]
        registered_at = _now()
        row = self.db.execute(
            "SELECT * FROM project_inputs WHERE project_id=? AND role=? AND content_digest=?",
            (project_id, role, digest),
        ).fetchone()
        if row is None:
            hex_digest = digest.split(":", 1)[1]
            target = self.blobs / hex_digest[:2] / hex_digest
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(content)
            self.db.execute(
                """INSERT INTO project_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (input_id, project_id, role, media_type, len(content), digest, source_path,
                 json.dumps(dict(provenance), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                 registered_at, lineage_ref, snapshot_id, snapshot_digest),
            )
            self.db.commit()
            row = self.db.execute("SELECT * FROM project_inputs WHERE input_id=?", (input_id,)).fetchone()
        return self._project(row)

    def get(self, input_id: str, project_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM project_inputs WHERE input_id=? AND project_id=?", (input_id, project_id)
        ).fetchone()
        return None if row is None else self._project(row)

    def list(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM project_inputs WHERE project_id=? ORDER BY registered_at,input_id LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [self._project(row) for row in rows]

    @staticmethod
    def _project(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "input_id": row["input_id"], "project_id": row["project_id"], "role": row["role"],
            "media_type": row["media_type"], "byte_length": row["byte_length"],
            "content_digest": row["content_digest"], "source_path": row["source_path"],
            "provenance": json.loads(row["provenance_json"]), "registered_at": row["registered_at"],
            "lineage_ref": row["lineage_ref"], "snapshot_id": row["snapshot_id"],
            "snapshot_digest": row["snapshot_digest"],
        }


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Same-workspace immutable project-input registration and Question Review linkage."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._project_input_registry = None
        if self._workspace_root is not None:
            bind_controlled_import_root(self._application.execution_store, self._workspace_root)

    def close(self) -> None:
        if self._project_input_registry is not None:
            self._project_input_registry.close()
            self._project_input_registry = None
        super().close()

    def _registry(self) -> _ProjectInputRegistry:
        if self._workspace_root is None:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "project input registration requires an opened workspace")
        if self._project_input_registry is None:
            self._project_input_registry = _ProjectInputRegistry(self._workspace_root)
        return self._project_input_registry

    def _current_binding(self) -> tuple[Any, str, str, str]:
        repo = self._application.state_repository
        lineage = repo.load_active_lineage_ref(self._project_id)
        state = repo.load_state_view(self._project_id, lineage)
        return state, str(lineage), str(state.current_snapshot["id"]), str(state.current_snapshot["content_digest"])

    def register_project_input(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = {"file", "role", "media_type", "provenance", "expected_snapshot_id", "expected_snapshot_digest"}
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "project input registration contains unknown fields")
        path = value.get("file")
        role = value.get("role")
        if not isinstance(path, str) or not path.strip():
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "file is required")
        if role not in _ROLES:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "role is not an allowed project-input role")
        provenance = value.get("provenance", {})
        if not isinstance(provenance, Mapping):
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "provenance must be an object")
        state, lineage, snapshot_id, snapshot_digest = self._current_binding()
        if value.get("expected_snapshot_id") != snapshot_id or value.get("expected_snapshot_digest") != snapshot_digest:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-STALE-001", "project input registration is not bound to the exact current Snapshot")
        try:
            content = read_controlled_file(self._application.execution_store, path, max_bytes=_MAX_BYTES)
        except (OSError, PermissionError, ValueError) as exc:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-FILE-001", "project input file is not an allowed regular workspace file") from exc
        media_type = value.get("media_type")
        if media_type is None:
            media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if not isinstance(media_type, str) or not media_type.strip():
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "media_type must be a non-empty string")
        document = self._registry().register(
            project_id=self._project_id, role=str(role), media_type=media_type, content=content,
            source_path=str(Path(path)), provenance=deepcopy(dict(provenance)), lineage_ref=lineage,
            snapshot_id=snapshot_id, snapshot_digest=snapshot_digest,
        )
        return {"status": "REGISTERED", "project_input": document, "research_state_mutation_performed": False}

    def list_project_inputs(self) -> Mapping[str, Any]:
        return {"status": "OK", "project_id": self._project_id, "project_inputs": self._registry().list(self._project_id)}

    def show_project_input(self, input_id: str) -> Mapping[str, Any]:
        item = self._registry().get(str(input_id), self._project_id)
        if item is None:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-404", "project input does not exist in this project")
        return {"status": "OK", "project_input": item}

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(draft_input, Mapping) and draft_input.get("action_type") == "research_question.review":
            payload = draft_input.get("payload")
            review_inputs = payload.get("review_inputs") if isinstance(payload, Mapping) else None
            ids = review_inputs.get("project_input_ids", []) if isinstance(review_inputs, Mapping) else []
            if ids:
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "project_input_ids must be an array of IDs")
                registry = self._registry()
                missing = [item for item in ids if registry.get(item, self._project_id) is None]
                if missing:
                    raise LocalApplicationError("APPLICATION-PROJECT-INPUT-404", "Question Review references unknown project inputs: " + ", ".join(missing))
        return super().submit_action(draft_input)
