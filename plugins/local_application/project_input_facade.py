from __future__ import annotations

import base64
from copy import deepcopy
import mimetypes
from pathlib import Path
from typing import Any, Mapping

from core.runtime.ports import StaleHeadError
from plugins.local_execution_store import (
    LocalExecutionStoreError,
    bind_controlled_import_root,
    read_controlled_file,
)
from plugins.local_project_input_store import (
    LocalProjectInputStore,
    LocalProjectInputStoreError,
)
from plugins.sqlite_state_store.exhibit_guard import guard_research_state_head

from .facade import LocalApplicationError
from .external_attempt_lifecycle_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ROLES = {"theme", "expectations", "project_brief", "scope", "methodology", "publication_brief", "other"}
_MAX_BYTES = 8 * 1024 * 1024
_MAX_PROJECT_INPUT_IDS = 64
_TEXTUAL_MEDIA_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
}


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Same-workspace immutable project-input registration and Question Review linkage."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._project_input_store = None
        if self._workspace_root is not None:
            bind_controlled_import_root(self._application.execution_store, self._workspace_root)

    def close(self) -> None:
        if self._project_input_store is not None:
            self._project_input_store.close()
            self._project_input_store = None
        super().close()

    def _registry(self) -> LocalProjectInputStore:
        if self._workspace_root is None:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "project input registration requires an opened workspace")
        if self._project_input_store is None:
            self._project_input_store = LocalProjectInputStore(self._workspace_root)
        return self._project_input_store

    def _current_binding(self) -> tuple[str, str, str]:
        repo = self._application.state_repository
        lineage = repo.load_active_lineage_ref(self._project_id)
        state = repo.load_state_view(self._project_id, lineage)
        return str(lineage), str(state.current_snapshot["id"]), str(state.current_snapshot["content_digest"])

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
        lineage, snapshot_id, snapshot_digest = self._current_binding()
        if value.get("expected_snapshot_id") != snapshot_id or value.get("expected_snapshot_digest") != snapshot_digest:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-STALE-001", "project input registration is not bound to the exact current Snapshot")
        try:
            content = read_controlled_file(self._application.execution_store, path, max_bytes=_MAX_BYTES)
        except (OSError, PermissionError, ValueError, LocalExecutionStoreError) as exc:
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-FILE-001", "project input file is not an allowed regular workspace file") from exc
        media_type = value.get("media_type")
        if media_type is None:
            media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if not isinstance(media_type, str) or not media_type.strip():
            raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "media_type must be a non-empty string")
        try:
            with guard_research_state_head(
                self._application.state_repository,
                self._project_id,
                lineage_ref=lineage,
                snapshot_ref=snapshot_id,
                snapshot_digest=snapshot_digest,
            ):
                document = self._registry().register(
                    project_id=self._project_id,
                    role=str(role),
                    media_type=media_type,
                    content=content,
                    source_path=str(Path(path)),
                    provenance=deepcopy(dict(provenance)),
                    lineage_ref=lineage,
                    snapshot_id=snapshot_id,
                    snapshot_digest=snapshot_digest,
                )
        except StaleHeadError as exc:
            raise LocalApplicationError(
                "APPLICATION-PROJECT-INPUT-STALE-001",
                "Research State changed before project input persistence",
            ) from exc
        except LocalProjectInputStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {"status": "REGISTERED", "project_input": document, "research_state_mutation_performed": False}

    def list_project_inputs(
        self, *, limit: int = 100, cursor: str | None = None
    ) -> Mapping[str, Any]:
        try:
            page = self._registry().list_page(self._project_id, limit=limit, cursor=cursor)
        except LocalProjectInputStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {
            "status": "OK",
            "project_id": self._project_id,
            "project_inputs": page["items"],
            "limit": page["limit"],
            "truncated": page["truncated"],
            "next_cursor": page["next_cursor"],
        }

    def show_project_input(self, input_id: str, *, format: str = "metadata") -> Mapping[str, Any]:
        if format not in {"metadata", "text", "base64"}:
            raise LocalApplicationError(
                "APPLICATION-PROJECT-INPUT-FORMAT-001",
                "format must be one of metadata, text, or base64",
            )
        registry = self._registry()
        if format == "metadata":
            item = registry.get(str(input_id), self._project_id)
            if item is None:
                raise LocalApplicationError(
                    "APPLICATION-PROJECT-INPUT-404",
                    "project input does not exist in this project",
                )
            return {
                "status": "OK",
                "project_input": item,
                "content": None,
                "available_content_formats": self._content_formats(str(item["media_type"])),
            }
        try:
            resolved = registry.read_content(str(input_id), self._project_id)
        except LocalProjectInputStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if resolved is None:
            raise LocalApplicationError(
                "APPLICATION-PROJECT-INPUT-404",
                "project input does not exist in this project",
            )
        item, content = resolved
        available = self._content_formats(str(item["media_type"]))
        if format not in available:
            raise LocalApplicationError(
                "APPLICATION-PROJECT-INPUT-FORMAT-001",
                f"{format} retrieval is not supported for media type {item['media_type']}",
            )
        if format == "text":
            try:
                value = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LocalApplicationError(
                    "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                    "stored textual project input is not valid UTF-8",
                ) from exc
            content_projection = {
                "format": "text",
                "encoding": "UTF-8",
                "media_type": item["media_type"],
                "byte_length": item["byte_length"],
                "content_digest": item["content_digest"],
                "value": value,
            }
        else:
            content_projection = {
                "format": "base64",
                "encoding": "base64",
                "media_type": item["media_type"],
                "byte_length": item["byte_length"],
                "content_digest": item["content_digest"],
                "value": base64.b64encode(content).decode("ascii"),
            }
        return {
            "status": "OK",
            "project_input": item,
            "content": content_projection,
            "available_content_formats": available,
        }

    @staticmethod
    def _content_formats(media_type: str) -> list[str]:
        formats = ["metadata", "base64"]
        normalized = media_type.split(";", 1)[0].strip().lower()
        if normalized.startswith("text/") or normalized in _TEXTUAL_MEDIA_TYPES:
            formats.insert(1, "text")
        return formats

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(draft_input, Mapping) and draft_input.get("action_type") == "research_question.review":
            payload = draft_input.get("payload")
            review_inputs = payload.get("review_inputs") if isinstance(payload, Mapping) else None
            ids = review_inputs.get("project_input_ids", []) if isinstance(review_inputs, Mapping) else []
            if ids:
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    raise LocalApplicationError("APPLICATION-PROJECT-INPUT-001", "project_input_ids must be an array of IDs")
                if len(ids) > _MAX_PROJECT_INPUT_IDS:
                    raise LocalApplicationError(
                        "APPLICATION-PROJECT-INPUT-001",
                        f"project_input_ids must contain at most {_MAX_PROJECT_INPUT_IDS} IDs",
                    )
                registry = self._registry()
                resolved = {item: registry.get(item, self._project_id) for item in ids}
                missing = [item for item, value in resolved.items() if value is None]
                if missing:
                    raise LocalApplicationError("APPLICATION-PROJECT-INPUT-404", "Question Review references unknown project inputs: " + ", ".join(missing))
                lineage, snapshot_id, snapshot_digest = self._current_binding()
                stale = [
                    item for item, value in resolved.items()
                    if value is not None and (
                        value["lineage_ref"] != lineage
                        or value["snapshot_id"] != snapshot_id
                        or value["snapshot_digest"] != snapshot_digest
                    )
                ]
                if stale:
                    raise LocalApplicationError(
                        "APPLICATION-PROJECT-INPUT-STALE-001",
                        "Question Review references project inputs that are not bound to the exact current Snapshot: " + ", ".join(stale),
                    )
        return super().submit_action(draft_input)
