from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.runtime import canonical_digest
from plugins._infra.atomic_write import replace_text
from plugins._infra.clock import utc_now as _now
from plugins._infra.file_lock import lock_byte, unlock_byte, write_sentinel_if_empty
from plugins.application_errors import LocalApplicationError
from plugins.local_durable_store import register_optional_path, require_optional_available

from ..research_package.item_listing import read_mapping
from ..research_package.research_package_format import safe_component
from .writer_composition_support import (
    MAX_COMPOSITIONS,
    MAX_SELECTION_EVENTS,
    MAX_VERSIONS,
    SCHEMA_VERSION,
    _digest_document,
    _require_string,
    _validate_schema,
)
from .writer_composition_validation import WriterCompositionValidationMixin
from .writer_section_input import WriterSectionInputMixin


class WriterCompositionService(WriterCompositionValidationMixin, WriterSectionInputMixin):
    def __init__(self, facade) -> None:
        self.facade = facade
        self.workspace = facade._workspace_root
        if self.workspace is None:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-001", "opened workspace is required"
            )
        self.root = self.workspace / ".research-loom" / "writer-compositions"
        require_optional_available(self.root, LocalApplicationError)

    def _package_service(self):
        return self.facade._research_package_service()

    def _package(self, package_id: str, *, metadata_limit: int | None = None) -> Mapping[str, Any]:
        if metadata_limit is not None:
            package = self._package_service()._load_metadata(package_id, metadata_limit)
            # Only pin fields enter the per-page cache; never retain full package bodies.
            return {
                key: package[key]
                for key in (
                    "package_id",
                    "package_digest",
                    "project",
                    "source_research_snapshot",
                    "effective_profile_set",
                    "package_mode",
                    "source_epistemic_status",
                    "preview_only",
                    "authoritative_research_freeze",
                    "release_eligible",
                )
            }
        return self._package_service().show(package_id)["package"]

    def _series_root(self, composition_id: str) -> Path:
        try:
            safe_component(composition_id, "composition_id")
        except LocalApplicationError as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INPUT-001", "invalid composition_id"
            ) from exc
        if len(composition_id) > 128:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INPUT-001", "invalid composition_id"
            )
        return self.root / composition_id

    @contextmanager
    def _file_lock(self, lock_path: Path, message: str):
        require_optional_available(self.root, LocalApplicationError)
        self.root.mkdir(parents=True, exist_ok=True)
        register_optional_path(self.root)
        handle = lock_path.open("a+b")
        try:
            write_sentinel_if_empty(handle.fileno(), fsync=False)
            try:
                lock_byte(handle.fileno(), blocking=False)
            except (OSError, BlockingIOError) as exc:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-BUSY-001", message
                ) from exc
            try:
                yield
            finally:
                unlock_byte(handle.fileno())
        finally:
            handle.close()

    @contextmanager
    def _series_lock(self, composition_id: str):
        safe_id = self._series_root(composition_id).name
        if not self._versions(composition_id):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-404", "composition series does not exist"
            )
        with self._file_lock(self.root / f".{safe_id}.lock", "composition series is being updated"):
            yield

    @contextmanager
    def _creation_lock(self):
        with self._file_lock(
            self.root / ".creation.lock", "composition series creation is being updated"
        ):
            yield

    @contextmanager
    def _capture_lock(self, composition_id: str):
        if self._versions(composition_id):
            with self._series_lock(composition_id):
                yield
            return
        with self._creation_lock():
            if self._versions(composition_id):
                with self._series_lock(composition_id):
                    yield
            else:
                yield

    def _version_path(self, composition_id: str, version: int) -> Path:
        return self._series_root(composition_id) / "versions" / f"{version:04d}.json"

    def _load_version(
        self,
        composition_id: str,
        version: int,
        package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None,
        *,
        metadata_limit: int | None = None,
    ) -> Mapping[str, Any]:
        path = self._version_path(composition_id, version)
        if not path.is_file():
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-404", "composition version does not exist"
            )
        try:
            value = (
                json.loads(path.read_text(encoding="utf-8"))
                if metadata_limit is None
                else read_mapping(path, metadata_limit)
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                "saved composition version is unreadable",
            ) from exc
        _validate_schema(value)
        if value.get("composition_id") != composition_id or value.get("version") != version:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                "saved composition identity differs from its path",
            )
        if _digest_document(value, "composition_digest") != value.get("composition_digest"):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "saved composition digest mismatch"
            )
        package_id = str(value["source"]["research_package_id"])
        package_digest = str(value["source"]["research_package_digest"])
        key = (package_id, package_digest)
        package = package_cache.get(key) if package_cache is not None else None
        if package is None:
            package = (
                self._package(package_id)
                if metadata_limit is None
                else self._package(package_id, metadata_limit=metadata_limit)
            )
            if package_cache is not None:
                package_cache[key] = package
        if metadata_limit is None:
            self._validate_source_pin(value["source"], package)
        elif value["source"] != self._source_pin(
            package, lineage_ref=value["source"].get("lineage_ref")
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PIN-001",
                "composition source pin differs from package metadata",
            )
        return value

    def _versions(self, composition_id: str) -> list[int]:
        root = self._series_root(composition_id) / "versions"
        if not root.exists():
            return []
        values = []
        for path in root.glob("*.json"):
            try:
                values.append(int(path.stem))
            except ValueError:
                continue
        return sorted(values)

    def capture(self, package_id: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INPUT-001", "composition input must be an object"
            )
        package = self._package(package_id)
        composition_id = value.get("composition_id")
        if composition_id is None:
            composition_id = "COMP-" + uuid.uuid4().hex
        composition_id = _require_string(composition_id, "composition_id")
        self._series_root(composition_id)
        sections, diagnostics = self._validate_sections(value.get("sections"), package)
        with self._capture_lock(composition_id):
            versions = self._versions(composition_id)
            base_version = value.get("base_version")
            base_digest = value.get("base_digest")
            if versions:
                latest = versions[-1]
                if base_version != latest:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-STALE-001",
                        "composition update is based on a stale version; automatic rebase is not supported",
                    )
                base = self._load_version(composition_id, latest)
                if base_digest != base["composition_digest"]:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-STALE-001",
                        "composition update base digest mismatch",
                    )
                if base["source"] != self._source_pin(package):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-PIN-001",
                        "a composition series cannot be rebound to another Research Package",
                    )
                version = latest + 1
            else:
                if base_version is not None or base_digest is not None:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-STALE-001",
                        "initial composition must not declare a base version",
                    )
                if (
                    self.root.exists()
                    and sum(1 for item in self.root.iterdir() if item.is_dir()) >= MAX_COMPOSITIONS
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-BOUND-001",
                        "composition series bound exceeded",
                    )
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
                "audience": [
                    str(x)
                    for x in value.get(
                        "audience", package.get("communication_brief", {}).get("audience", [])
                    )
                    if isinstance(x, str) and x
                ],
                "sections": sections,
                "base_version": base_version,
                "base_digest": base_digest,
                "change_reason": str(
                    value.get("change_reason")
                    or ("initial composition" if version == 1 else "unspecified revision")
                ),
                "created_by": deepcopy(dict(value.get("created_by", {"type": "external_or_human"})))
                if isinstance(value.get("created_by", {"type": "external_or_human"}), Mapping)
                else {"type": "external_or_human"},
                "created_at": _now(),
                "validation": {
                    "status": "VALID_WITH_GAPS" if diagnostics else "VALID",
                    "diagnostics": diagnostics,
                },
                "research_state_mutation_performed": False,
                "evidence_verification_performed": False,
                "finding_adoption_performed": False,
                "composition_digest": "",
            }
            document["composition_digest"] = _digest_document(document, "composition_digest")
            _validate_schema(document)
            root = self._series_root(composition_id)
            versions_root = root / "versions"
            if len(versions) >= MAX_VERSIONS:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-BOUND-001", "composition version bound exceeded"
                )
            versions_root.mkdir(parents=True, exist_ok=True)
            path = self._version_path(composition_id, version)
            if path.exists():
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-IMMUTABLE-001",
                    "composition version already exists",
                )
            try:
                replace_text(
                    path, json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                )
            except OSError as exc:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-WRITE-001", "composition persistence failed"
                ) from exc
        return {"status": "CAPTURED", "composition": deepcopy(document), "selection_changed": False}

    def list(self) -> Mapping[str, Any]:
        if not self.root.exists():
            return {"status": "OK", "compositions": [], "truncated": False}
        roots = [x for x in sorted(self.root.iterdir()) if x.is_dir()][: MAX_COMPOSITIONS + 1]
        rows = []
        package_cache: dict[tuple[str, str], Mapping[str, Any]] = {}
        for root in roots[:MAX_COMPOSITIONS]:
            versions = self._versions(root.name)
            if not versions:
                continue
            latest = self._load_version(root.name, versions[-1], package_cache)
            selection = self._selection(root.name)
            rows.append(
                {
                    "composition_id": root.name,
                    "latest_version": versions[-1],
                    "latest_digest": latest["composition_digest"],
                    "source": latest["source"],
                    "selected": selection.get("selected") if selection else None,
                }
            )
        return {"status": "OK", "compositions": rows, "truncated": len(roots) > MAX_COMPOSITIONS}

    def show(self, composition_id: str, version: int) -> Mapping[str, Any]:
        return {
            "status": "OK",
            "composition": deepcopy(dict(self._load_version(composition_id, version))),
            "selection": self._selection(composition_id),
        }

    def export(self, composition_id: str, version: int, output: str | Path) -> Mapping[str, Any]:
        document = self._load_version(composition_id, version)
        proposal = {
            "composition_id": composition_id,
            "base_version": version,
            "base_digest": document["composition_digest"],
            "purpose": document["purpose"],
            "audience": document["audience"],
            "sections": document["sections"],
            "change_reason": "describe revision",
            "created_by": {"type": "external_or_human"},
        }
        path = Path(output).expanduser()
        managed = (self.workspace / ".research-loom").resolve(strict=False)
        resolved = path.resolve(strict=False)
        if resolved == managed or resolved.is_relative_to(managed):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-EXPORT-001",
                "composition export must not write into managed workspace state",
            )
        if path.exists():
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-EXPORT-001",
                "composition export will not overwrite an existing path",
            )
        if not path.parent.exists():
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-EXPORT-001", "composition export parent must exist"
            )
        payload = (
            json.dumps(proposal, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        created = False
        try:
            with tmp.open("xb") as handle:
                created = True
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError as exc:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-EXPORT-001",
                    "composition export will not overwrite an existing path",
                ) from exc
            tmp.unlink()
        except LocalApplicationError:
            if created:
                tmp.unlink(missing_ok=True)
            raise
        except OSError as exc:
            if created:
                tmp.unlink(missing_ok=True)
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-WRITE-001", "composition export failed"
            ) from exc
        return {
            "status": "EXPORTED",
            "composition_id": composition_id,
            "version": version,
            "output": str(path),
            "content_digest": canonical_digest(proposal),
        }

    def diff(self, composition_id: str, from_version: int, to_version: int) -> Mapping[str, Any]:
        before = self._load_version(composition_id, from_version)
        after = self._load_version(composition_id, to_version)
        b = {x["section_id"]: x for x in before["sections"]}
        a = {x["section_id"]: x for x in after["sections"]}
        changes = []
        for sid in sorted(set(b) | set(a)):
            if sid not in b:
                changes.append({"section_id": sid, "change": "added", "fields": sorted(a[sid])})
                continue
            if sid not in a:
                changes.append({"section_id": sid, "change": "removed", "fields": sorted(b[sid])})
                continue
            fields = sorted(
                key
                for key in set(b[sid]) | set(a[sid])
                if key != "section_digest" and b[sid].get(key) != a[sid].get(key)
            )
            if fields:
                changes.append({"section_id": sid, "change": "modified", "fields": fields})
        return {
            "status": "OK",
            "composition_id": composition_id,
            "from": {"version": from_version, "digest": before["composition_digest"]},
            "to": {"version": to_version, "digest": after["composition_digest"]},
            "change_reason": after.get("change_reason"),
            "section_changes": changes,
        }

    def _selection(self, composition_id: str) -> Mapping[str, Any] | None:
        path = self._series_root(composition_id) / "selection.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                "composition selection history is unreadable",
            ) from exc

    def select(self, composition_id: str, version: int, digest: str) -> Mapping[str, Any]:
        if not self._versions(composition_id):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-404", "composition series does not exist"
            )
        with self._series_lock(composition_id):
            document = self._load_version(composition_id, version)
            if digest != document["composition_digest"]:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-PIN-001",
                    "selection must name the exact composition digest",
                )
            path = self._series_root(composition_id) / "selection.json"
            previous = self._selection(composition_id)
            history = list(previous.get("history", [])) if previous else []
            if len(history) >= MAX_SELECTION_EVENTS:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-BOUND-001",
                    "composition selection history bound exceeded",
                )
            event = {"version": version, "digest": digest, "selected_at": _now()}
            history.append(event)
            value = {"selected": event, "history": history}
            try:
                replace_text(
                    path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                )
            except OSError as exc:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-WRITE-001",
                    "composition selection persistence failed",
                ) from exc
        return {
            "status": "SELECTED",
            "composition_id": composition_id,
            "selection": event,
            "research_state_mutation_performed": False,
        }
