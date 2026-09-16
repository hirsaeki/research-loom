from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from itertools import islice
import json
import os
from pathlib import Path
import uuid
from typing import Any, Mapping

from .facade import LocalApplicationError
from .writer_composition_service import (
    SCHEMA_VERSION,
    WriterCompositionService,
    _digest_document,
    _now,
    _require_string,
    _validate_schema,
)

MAX_LIST_COMPOSITIONS = 64
MAX_LIST_DIRECTORY_ENTRIES = 256
MAX_LEGACY_VERSIONS = 64
MAX_SELECTION_HISTORY_READ = 256
MAX_LEGACY_SELECTION_EVENTS = 256


class WriterCompositionHistoryService(WriterCompositionService):
    def _series_index_path(self, composition_id: str) -> Path:
        return self._series_root(composition_id) / "series-index.json"

    def _selection_root(self, composition_id: str) -> Path:
        return self._series_root(composition_id) / "selection"

    def _selection_state_path(self, composition_id: str) -> Path:
        return self._selection_root(composition_id) / "state.json"

    def _selection_event_path(self, composition_id: str, sequence: int) -> Path:
        return self._selection_root(composition_id) / "events" / f"{sequence:08d}.json"

    def _write_json_atomic(self, path: Path, value: Mapping[str, Any], message: str) -> None:
        tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", message) from exc

    @staticmethod
    def _read_mapping_json(path: Path, unreadable_message: str, invalid_message: str) -> Mapping[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", unreadable_message) from exc
        if not isinstance(value, Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", invalid_message)
        return value

    @contextmanager
    def _series_lock(self, composition_id: str):
        safe_id = self._series_root(composition_id).name
        if self._latest_version_info(composition_id) is None:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-404", "composition series does not exist")
        with self._file_lock(self.root / f".{safe_id}.lock", "composition series is being updated"):
            yield

    @contextmanager
    def _capture_lock(self, composition_id: str):
        if self._latest_version_info(composition_id) is not None:
            with self._series_lock(composition_id):
                yield
            return
        with self._creation_lock():
            if self._latest_version_info(composition_id) is not None:
                with self._series_lock(composition_id):
                    yield
            else:
                yield

    def _legacy_latest_version_info(
        self,
        composition_id: str,
        package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any] | None:
        root = self._series_root(composition_id) / "versions"
        if not root.exists():
            return None
        paths = list(islice(root.glob("*.json"), MAX_LEGACY_VERSIONS + 1))
        if len(paths) > MAX_LEGACY_VERSIONS:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                "composition series is missing its bounded latest-version index",
            )
        versions = []
        for path in paths:
            try:
                versions.append(int(path.stem))
            except ValueError:
                continue
        if not versions:
            return None
        latest = max(versions)
        document = self._load_version(composition_id, latest, package_cache)
        return {"version": latest, "digest": document["composition_digest"]}

    def _write_series_index(self, composition_id: str, version: int, digest: str) -> None:
        self._write_json_atomic(
            self._series_index_path(composition_id),
            {"schema_version": SCHEMA_VERSION, "latest_version": version, "latest_digest": digest},
            "composition latest-version index persistence failed",
        )

    def _latest_version_info(
        self,
        composition_id: str,
        *,
        repair: bool = False,
        package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any] | None:
        index_path = self._series_index_path(composition_id)
        if not index_path.exists():
            legacy = self._legacy_latest_version_info(composition_id, package_cache)
            if legacy is not None and repair:
                self._write_series_index(composition_id, int(legacy["version"]), str(legacy["digest"]))
            return legacy
        index = self._read_mapping_json(
            index_path,
            "composition latest-version index is unreadable",
            "composition latest-version index is invalid",
        )
        version = index.get("latest_version")
        digest = index.get("latest_digest")
        if not isinstance(version, int) or version < 1 or not isinstance(digest, str) or not digest:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition latest-version index is invalid")
        document = self._load_version(composition_id, version, package_cache)
        if document["composition_digest"] != digest:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition latest-version index digest mismatch")

        next_path = self._version_path(composition_id, version + 1)
        if next_path.exists():
            if self._version_path(composition_id, version + 2).exists():
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition latest-version index is behind multiple saved versions")
            next_document = self._load_version(composition_id, version + 1, package_cache)
            if next_document.get("base_version") != version or next_document.get("base_digest") != digest:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "unindexed composition version does not extend the indexed latest version")
            version = version + 1
            digest = str(next_document["composition_digest"])
            if repair:
                self._write_series_index(composition_id, version, digest)
        return {"version": version, "digest": digest}

    def _versions(self, composition_id: str) -> list[int]:
        latest = self._latest_version_info(composition_id)
        return [int(latest["version"])] if latest is not None else []

    def _validate_revision_base(self, value: Mapping[str, Any], latest_version: int, latest_digest: str) -> None:
        if value.get("base_version") != latest_version:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-STALE-001", "composition update is based on a stale version; automatic rebase is not supported")
        if value.get("base_digest") != latest_digest:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-STALE-001", "composition update base digest mismatch")

    def capture(self, package_id: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", "composition input must be an object")
        package = self._package(package_id)
        composition_id = value.get("composition_id")
        if composition_id is None:
            composition_id = "COMP-" + uuid.uuid4().hex
        composition_id = _require_string(composition_id, "composition_id")
        self._series_root(composition_id)
        sections, diagnostics = self._validate_sections(value.get("sections"), package)
        with self._capture_lock(composition_id):
            latest_info = self._latest_version_info(composition_id, repair=True)
            base_version = value.get("base_version")
            base_digest = value.get("base_digest")
            if latest_info is not None:
                latest = int(latest_info["version"])
                latest_digest = str(latest_info["digest"])
                self._validate_revision_base(value, latest, latest_digest)
                base = self._load_version(composition_id, latest)
                if base["source"] != self._source_pin(package):
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "a composition series cannot be rebound to another Research Package")
                version = latest + 1
            else:
                if base_version is not None or base_digest is not None:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-STALE-001", "initial composition must not declare a base version")
                version = 1
            source_pin = self._source_pin(package)
            self._validate_source_pin(source_pin, package)
            document = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "writer_composition",
                "composition_id": composition_id,
                "version": version,
                "source": source_pin,
                "purpose": _require_string(value.get("purpose"), "purpose"),
                "audience": [str(x) for x in value.get("audience", package.get("communication_brief", {}).get("audience", [])) if isinstance(x, str) and x],
                "sections": sections,
                "base_version": base_version,
                "base_digest": base_digest,
                "change_reason": str(value.get("change_reason") or ("initial composition" if version == 1 else "unspecified revision")),
                "created_by": deepcopy(dict(value.get("created_by", {"type": "external_or_human"}))) if isinstance(value.get("created_by", {"type": "external_or_human"}), Mapping) else {"type": "external_or_human"},
                "created_at": _now(),
                "validation": {"status": "VALID_WITH_GAPS" if diagnostics else "VALID", "diagnostics": diagnostics},
                "research_state_mutation_performed": False,
                "evidence_verification_performed": False,
                "finding_adoption_performed": False,
                "composition_digest": "",
            }
            document["composition_digest"] = _digest_document(document, "composition_digest")
            _validate_schema(document)
            root = self._series_root(composition_id)
            versions_root = root / "versions"
            versions_root.mkdir(parents=True, exist_ok=True)
            path = self._version_path(composition_id, version)
            if path.exists():
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-IMMUTABLE-001", "composition version already exists")
            tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                os.replace(tmp, path)
                try:
                    self._write_series_index(composition_id, version, str(document["composition_digest"]))
                except LocalApplicationError:
                    path.unlink(missing_ok=True)
                    raise
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", "composition persistence failed") from exc
        return {"status": "CAPTURED", "composition": deepcopy(document), "selection_changed": False}

    def list(self) -> Mapping[str, Any]:
        if not self.root.exists():
            return {"status": "OK", "compositions": [], "truncated": False}
        entries = list(islice(self.root.iterdir(), MAX_LIST_DIRECTORY_ENTRIES + 1))
        roots = [entry for entry in entries[:MAX_LIST_DIRECTORY_ENTRIES] if entry.is_dir()]
        roots.sort(key=lambda path: path.name)
        rows = []
        package_cache: dict[tuple[str, str], Mapping[str, Any]] = {}
        for root in roots[:MAX_LIST_COMPOSITIONS]:
            latest_info = self._latest_version_info(root.name, package_cache=package_cache)
            if latest_info is None:
                continue
            latest_version = int(latest_info["version"])
            latest = self._load_version(root.name, latest_version, package_cache)
            rows.append({"composition_id": root.name, "latest_version": latest_version, "latest_digest": latest["composition_digest"], "source": latest["source"], "selected": self._selected(root.name, package_cache)})
        return {
            "status": "OK",
            "compositions": rows,
            "truncated": len(entries) > MAX_LIST_DIRECTORY_ENTRIES or len(roots) > MAX_LIST_COMPOSITIONS,
        }

    def _legacy_selection(self, composition_id: str) -> Mapping[str, Any] | None:
        path = self._series_root(composition_id) / "selection.json"
        if not path.exists():
            return None
        value = self._read_mapping_json(
            path,
            "composition selection history is unreadable",
            "legacy composition selection history is invalid",
        )
        selected = value.get("selected")
        history = value.get("history")
        if not isinstance(selected, Mapping) or not isinstance(history, list) or not history:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "legacy composition selection history is invalid")
        if len(history) > MAX_LEGACY_SELECTION_EVENTS:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "legacy composition selection history exceeds its former bound")
        if not isinstance(history[-1], Mapping) or dict(history[-1]) != dict(selected):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "legacy composition selection pointer does not match its history")
        return {"selected": deepcopy(dict(selected)), "history": [deepcopy(dict(event)) for event in history]}

    def _selection_event(self, composition_id: str, sequence: int, package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None) -> Mapping[str, Any]:
        path = self._selection_event_path(composition_id, sequence)
        if not path.is_file():
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection event is missing")
        event = self._read_mapping_json(
            path,
            "composition selection event is unreadable",
            "composition selection event is invalid",
        )
        if event.get("sequence") != sequence or _digest_document(event, "event_digest") != event.get("event_digest"):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection event integrity check failed")
        version = event.get("version")
        digest = event.get("digest")
        if not isinstance(version, int) or version < 1 or not isinstance(digest, str) or not isinstance(event.get("selected_at"), str):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection event is invalid")
        document = self._load_version(composition_id, version, package_cache)
        if document["composition_digest"] != digest:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection event digest no longer resolves")
        return event

    def _write_selection_state(self, composition_id: str, event: Mapping[str, Any], legacy_event_count: int) -> None:
        self._write_json_atomic(
            self._selection_state_path(composition_id),
            {
                "schema_version": SCHEMA_VERSION,
                "event_count": int(event["sequence"]),
                "legacy_event_count": legacy_event_count,
                "selected": deepcopy(dict(event)),
            },
            "composition selection state persistence failed",
        )

    def _selection_state(
        self,
        composition_id: str,
        *,
        repair: bool = False,
        package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any] | None:
        state_path = self._selection_state_path(composition_id)
        if not state_path.exists():
            legacy = self._legacy_selection(composition_id)
            legacy_count = len(legacy["history"]) if legacy is not None else 0
            next_sequence = legacy_count + 1
            next_path = self._selection_event_path(composition_id, next_sequence)
            if not next_path.exists():
                if legacy is None:
                    return None
                selected = legacy["selected"]
                document = self._load_version(composition_id, int(selected["version"]), package_cache)
                if document["composition_digest"] != selected.get("digest"):
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "legacy composition selection digest no longer resolves")
                return {"selected": selected, "event_count": legacy_count, "legacy_event_count": legacy_count}
            if self._selection_event_path(composition_id, next_sequence + 1).exists():
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection state is missing behind multiple events")
            event = self._selection_event(composition_id, next_sequence, package_cache)
            if repair:
                self._write_selection_state(composition_id, event, legacy_count)
            return {"selected": event, "event_count": next_sequence, "legacy_event_count": legacy_count}
        state = self._read_mapping_json(
            state_path,
            "composition selection state is unreadable",
            "composition selection state is invalid",
        )
        event_count = state.get("event_count")
        legacy_count = state.get("legacy_event_count")
        selected = state.get("selected")
        if (
            not isinstance(event_count, int)
            or not isinstance(legacy_count, int)
            or legacy_count < 0
            or event_count <= legacy_count
            or not isinstance(selected, Mapping)
        ):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection state is invalid")
        current = self._selection_event(composition_id, event_count, package_cache)
        if dict(current) != dict(selected):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection state does not match its latest event")
        next_path = self._selection_event_path(composition_id, event_count + 1)
        if next_path.exists():
            if self._selection_event_path(composition_id, event_count + 2).exists():
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection state is behind multiple events")
            current = self._selection_event(composition_id, event_count + 1, package_cache)
            event_count += 1
            if repair:
                self._write_selection_state(composition_id, current, legacy_count)
        return {"selected": current, "event_count": event_count, "legacy_event_count": legacy_count}

    def _selected(self, composition_id: str, package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None) -> Mapping[str, Any] | None:
        state = self._selection_state(composition_id, package_cache=package_cache)
        return deepcopy(dict(state["selected"])) if state is not None else None

    def _selection(self, composition_id: str) -> Mapping[str, Any] | None:
        package_cache: dict[tuple[str, str], Mapping[str, Any]] = {}
        state = self._selection_state(composition_id, package_cache=package_cache)
        if state is None:
            return None
        count = int(state["event_count"])
        legacy_count = int(state["legacy_event_count"])
        start = max(1, count - MAX_SELECTION_HISTORY_READ + 1)
        history = []
        if start <= legacy_count:
            legacy = self._legacy_selection(composition_id)
            if legacy is None or len(legacy["history"]) != legacy_count:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "legacy composition selection history no longer matches selection state")
            history.extend(deepcopy(legacy["history"][start - 1 : legacy_count]))
        for sequence in range(max(start, legacy_count + 1), count + 1):
            history.append(deepcopy(dict(self._selection_event(composition_id, sequence, package_cache))))
        return {
            "selected": deepcopy(dict(state["selected"])),
            "history": history,
            "history_total": count,
            "truncated": start > 1,
        }

    def select(self, composition_id: str, version: int, digest: str) -> Mapping[str, Any]:
        if self._latest_version_info(composition_id) is None:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-404", "composition series does not exist")
        with self._series_lock(composition_id):
            document = self._load_version(composition_id, version)
            if digest != document["composition_digest"]:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "selection must name the exact composition digest")
            state = self._selection_state(composition_id, repair=True)
            if state is not None:
                selected = state["selected"]
                if selected.get("version") == version and selected.get("digest") == digest:
                    return {
                        "status": "SELECTED",
                        "composition_id": composition_id,
                        "selection": deepcopy(dict(selected)),
                        "selection_reused": True,
                        "research_state_mutation_performed": False,
                    }
                sequence = int(state["event_count"]) + 1
                legacy_count = int(state["legacy_event_count"])
            else:
                sequence = 1
                legacy_count = 0
            event = {"sequence": sequence, "version": version, "digest": digest, "selected_at": _now(), "event_digest": ""}
            event["event_digest"] = _digest_document(event, "event_digest")
            event_path = self._selection_event_path(composition_id, sequence)
            if event_path.exists():
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-IMMUTABLE-001", "composition selection event already exists")
            self._write_json_atomic(event_path, event, "composition selection event persistence failed")
            try:
                self._write_selection_state(composition_id, event, legacy_count)
            except LocalApplicationError:
                event_path.unlink(missing_ok=True)
                raise
        return {
            "status": "SELECTED",
            "composition_id": composition_id,
            "selection": event,
            "selection_reused": False,
            "research_state_mutation_performed": False,
        }
