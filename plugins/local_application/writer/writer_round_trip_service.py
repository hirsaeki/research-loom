from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.runtime import canonical_digest
from plugins._infra.atomic_write import write_durable
from plugins.application_errors import LocalApplicationError
from plugins.local_durable_store import register_optional_path, require_optional_available

from ..research_package.research_package_format import safe_component
from .writer_composition_support import _digest_document
from .writer_input_bundle import compact_input, expand_input
from .writer_round_trip_import import WriterRoundTripImportMixin
from .writer_round_trip_review import WriterRoundTripReviewMixin
from .writer_round_trip_support import (
    MAX_EXPORT_OPERATION_BYTES,
    MAX_SECTIONS,
    SCHEMA_VERSION,
    _json_bytes,
    _sha256_text,
    _validate_schema,
)


class WriterRoundTripService(WriterRoundTripReviewMixin, WriterRoundTripImportMixin):
    def __init__(self, facade) -> None:
        self.facade = facade
        self.workspace = facade._workspace_root
        if self.workspace is None:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-001", "opened workspace is required"
            )
        self.root = self.workspace / ".research-loom" / "writer-round-trips"
        require_optional_available(self.root, LocalApplicationError)
        self.inputs_root = self.root / "inputs"
        self.series_root = self.root / "series"

    def _composition_service(self):
        return self.facade._writer_composition_service()

    def _input_path(self, input_id: str) -> Path:
        return self.inputs_root / f"{safe_component(input_id, 'input_id')}.json"

    def _revision_root(self, composition_id: str) -> Path:
        return self.series_root / safe_component(composition_id, "composition_id")

    def _revision_path(self, composition_id: str, revision_id: str) -> Path:
        # The response key permits direct retry lookup; the full nonce ID stays in the
        # immutable document, so losing every retained fact cannot resurrect an old ID.
        match = re.fullmatch(r"(WMR-[0-9a-f]{24})(?:-[0-9a-f]{32})?", revision_id)
        key = match.group(1) if match else safe_component(revision_id, "revision_id")
        return self._revision_root(composition_id) / "revisions" / f"{key}.json"

    def _checkpoint_path(self, composition_id: str) -> Path:
        return self.root / f".{safe_component(composition_id, 'composition_id')}.latest.json"

    def _head_path(self, composition_id: str) -> Path:
        return self._revision_root(composition_id) / "head.json"

    def _read_json(self, path: Path, *, message: str) -> Mapping[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", message
            ) from exc
        if not isinstance(value, Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", message)
        return value

    def _write_immutable(self, path: Path, value: Mapping[str, Any]) -> bool:
        return self._write_record(path, value, replace=False)

    def _write_head(self, composition_id: str, value: Mapping[str, Any]) -> None:
        self._write_pointer(self._head_path(composition_id), value)

    def _write_pointer(self, path: Path, value: Mapping[str, Any]) -> None:
        self._write_record(path, value, replace=True)

    def _write_record(self, path: Path, value: Mapping[str, Any], *, replace: bool) -> bool:
        from plugins.local_workspace_layout import safe_locator as _safe_locator

        require_optional_available(self.root, LocalApplicationError)
        path = _safe_locator(
            self.workspace, path.relative_to(self.workspace).as_posix(), require_exists=False
        )
        try:
            if not replace and path.exists():
                existing = self._read_json(
                    path, message="immutable Writer round-trip record is unreadable"
                )
                if dict(existing) != dict(value):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001",
                        "immutable Writer identity contains different content; restore its exact backup",
                    )
                return True
            path.parent.mkdir(parents=True, exist_ok=True)
            register_optional_path(self.root)
            if not write_durable(
                path, _json_bytes(value), prefix=".writer-", suffix=".tmp", replace=replace
            ):
                existing = self._read_json(
                    path, message="immutable Writer round-trip record is unreadable"
                )
                if dict(existing) != dict(value):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001",
                        "immutable Writer identity contains different content; restore its exact backup",
                    )
                return True
            return False
        except OSError as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-WRITE-001",
                "Writer persistence failed; resolve the I/O error and retry the exact response",
            ) from exc

    def _load_input(self, input_id: str) -> Mapping[str, Any]:
        path = self._input_path(input_id)
        if not path.is_file():
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-404", "Writer input does not exist"
            )
        value = self._read_json(path, message="Writer input receipt is unreadable")
        _validate_schema(value)
        if _digest_document(value, "input_digest") != value.get("input_digest"):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "Writer input digest mismatch"
            )
        expanded = expand_input(value)
        self._validate_input_context(expanded)
        self._validate_input_origins(expanded)
        return expanded

    def _validate_input_origins(self, value: Mapping[str, Any]) -> None:
        rows = value["sections"]
        if not any("origin_input_ref" in row for row in rows):
            return
        if any("origin_input_ref" not in row for row in rows):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "assembled Writer input has incomplete section origins",
            )
        origins: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            ref = row["origin_input_ref"]
            if ref["input_id"] == value["input_id"]:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "assembled Writer input cannot reference itself",
                )
            origin_id = str(ref["input_id"])
            if origin_id not in origins:
                raw_origin = self._read_json(
                    self._input_path(origin_id), message="batch Writer input is unreadable"
                )
                if any("origin_input_ref" in item for item in raw_origin.get("sections", [])):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                        "assembled Writer input must reference original exported batches",
                    )
                origins[origin_id] = self._load_input(origin_id)
            origin = origins[origin_id]
            if (
                ref["input_digest"] != origin["input_digest"]
                or origin["source"] != value["source"]
                or not any(
                    item["section_id"] == row["section_id"]
                    and item["section_input_digest"] == row["section_input_digest"]
                    for item in origin["sections"]
                )
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                    "assembled section does not resolve to its exact batch Writer input",
                )

    def _load_revision(self, composition_id: str, revision_id: str) -> Mapping[str, Any]:
        path = self._revision_path(composition_id, revision_id)
        if not path.is_file():
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-404", "manuscript revision does not exist"
            )
        value = self._read_json(path, message="manuscript revision is unreadable")
        self._validate_revision(value, composition_id, revision_id)
        return value

    @staticmethod
    def _validate_revision(value: Mapping[str, Any], composition_id: str, revision_id: str) -> None:
        _validate_schema(value)
        if _digest_document(value, "revision_digest") != value.get("revision_digest"):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript revision digest mismatch"
            )
        if value.get("revision_id") != revision_id:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "manuscript revision identity does not match its storage path",
            )
        source = value.get("source")
        if not isinstance(source, Mapping) or source.get("composition_id") != composition_id:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "manuscript revision source composition does not match its storage series",
            )

    def _validate_revision_scope(
        self, revision: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> None:
        if revision.get("schema_version") != SCHEMA_VERSION:
            return
        expected_source = {
            "input_id": receipt["input_id"],
            "input_digest": receipt["input_digest"],
            **receipt["source"],
        }
        if revision["source"] != expected_source:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "manuscript source does not match its effective Writer input",
            )
        response_ref = self._response_input_ref(revision)
        response = self._load_input(str(response_ref["input_id"]))
        if (
            response_ref["input_digest"] != response["input_digest"]
            or response["source"] != receipt["source"]
            or any("origin_input_ref" in row for row in response["sections"])
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "manuscript response batch does not match its effective input",
            )
        rows = revision["sections"]
        if [row["section_id"] for row in rows] != [
            row["section_id"] for row in receipt["sections"]
        ]:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "manuscript sections do not cover its effective Writer input in order",
            )
        for section, scope in zip(rows, receipt["sections"], strict=True):
            origin_ref = scope.get("origin_input_ref", response_ref)
            if section["origin_input_ref"] != origin_ref or section[
                "content_digest"
            ] != _sha256_text(section["content"]):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript section content or origin does not match its pinned input",
                )

    def _load_latest_revision(self, composition_id: str) -> Mapping[str, Any] | None:
        # Only used when the continuity record is absent, never on healthy imports.
        root = self._revision_root(composition_id) / "revisions"
        if not root.exists():
            return None
        by_number: dict[int, Mapping[str, Any]] = {}
        for path in root.glob("*.json"):
            if not path.is_file():
                continue
            stored = self._read_json(path, message="manuscript revision is unreadable")
            revision_id = str(stored.get("revision_id", ""))
            if self._revision_path(composition_id, revision_id) != path:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript revision path mismatch",
                )
            revision = self._load_revision(composition_id, revision_id)
            number = int(revision["revision_number"])
            if number in by_number:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "ambiguous manuscript history: multiple successors; restore a consistent exact backup",
                )
            by_number[number] = revision
        previous = None
        for number, revision in sorted(by_number.items()):
            expected_parent = (
                {key: previous[key] for key in ("revision_id", "revision_digest")}
                if previous
                else None
            )
            if (
                number != (int(previous["revision_number"]) + 1 if previous else 1)
                or revision["parent_revision_ref"] != expected_parent
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript history has missing or conflicting ancestry; restore a consistent exact backup",
                )
            previous = revision
        return previous

    def _head(self, composition_id: str) -> Mapping[str, Any] | None:
        path = self._head_path(composition_id)
        if not path.exists():
            return None
        value = self._read_json(path, message="manuscript revision head is unreadable")
        revision_id = value.get("revision_id")
        revision_digest = value.get("revision_digest")
        if not isinstance(revision_id, str) or not isinstance(revision_digest, str):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript revision head is invalid"
            )
        revision = self._load_revision(composition_id, revision_id)
        if revision.get("revision_digest") != revision_digest:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "manuscript revision head digest does not resolve",
            )
        if value.get("revision_number") != revision.get("revision_number"):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "manuscript revision head number does not resolve",
            )
        return value

    @staticmethod
    def _revision_ref(revision: Mapping[str, Any]) -> dict[str, Any]:
        return {key: revision[key] for key in ("revision_id", "revision_digest", "revision_number")}

    @staticmethod
    def _response_input_ref(revision: Mapping[str, Any]) -> dict[str, Any]:
        source = revision.get("response_input_ref", revision["source"])
        return {key: source[key] for key in ("input_id", "input_digest")}

    def _effective_input(
        self,
        receipt: Mapping[str, Any],
        base: Mapping[str, Any] | None,
        drafts: Mapping[str, Mapping[str, Any]],
        composition: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, Mapping[str, Any]]:
        """Assemble the exact scope of a batched response before any new write."""
        batch = {str(row["section_id"]): row for row in receipt["sections"]}
        if any("origin_input_ref" in row for row in receipt["sections"]):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                "Writer response must name an exported batch input, not an assembled manuscript view",
            )
        if not set(drafts) <= set(batch):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer response names a section outside its exported batch",
            )
        if base is None:
            if set(drafts) != set(batch):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                    "initial manuscript response must provide every section in the exported input",
                )
            return None, receipt
        if {key: base["source"][key] for key in receipt["source"]} != dict(receipt["source"]):
            if set(batch) != {str(row["section_id"]) for row in composition["sections"]} or set(
                drafts
            ) != set(batch):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                    "changed composition or Package pins require a complete new Writer input and response",
                )
            return None, receipt
        previous_batch = self._response_input_ref(base)
        if previous_batch["input_id"] != receipt["input_id"] and set(drafts) != set(batch):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                "a changed Writer input requires every section of the new batch",
            )
        base_receipt = self._load_input(str(base["source"]["input_id"]))
        previous = {str(row["section_id"]): row for row in base_receipt["sections"]}
        selected = set(previous) | set(batch)
        ordered = [
            str(row["section_id"])
            for row in sorted(
                composition["sections"], key=lambda row: (row["order"], row["section_id"])
            )
            if str(row["section_id"]) in selected
        ]
        if set(ordered) != selected:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "manuscript contains a section outside the pinned composition",
            )
        current_ref = {key: receipt[key] for key in ("input_id", "input_digest")}
        rows: list[dict[str, Any]] = []
        for section_id in ordered:
            if section_id in drafts:
                row = deepcopy(dict(batch[section_id]))
                origin_ref = current_ref
            else:
                if section_id not in previous:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                        f"Writer response omits section without a reusable base: {section_id}",
                    )
                row = deepcopy(dict(previous[section_id]))
                origin_ref = row.get("origin_input_ref", previous_batch)
            row["origin_input_ref"] = deepcopy(dict(origin_ref))
            rows.append(row)
        document = compact_input(receipt["source"], rows)
        _validate_schema(document)
        expanded = expand_input(document)
        self._validate_input_context(expanded)
        self._validate_input_origins(expanded)
        return document, expanded

    def _reconcile_head(self, composition_id: str) -> tuple[Mapping[str, Any] | None, list[str]]:
        checkpoint = self._checkpoint_path(composition_id)
        new_checkpoint = not checkpoint.exists()
        if new_checkpoint:
            latest = self._load_latest_revision(composition_id)
            if latest is None:
                if self._revision_root(composition_id).exists():
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-RECOVERY-REQUIRED-001",
                        "Original manuscript facts are missing. Restore an exact backup or start a new composition series; do not recreate old identities.",
                    )
                return None, []
        else:
            latest = self._read_json(
                checkpoint,
                message="Writer continuity record is unreadable; preserve it and restore an exact backup",
            )
        self._validate_revision(latest, composition_id, str(latest.get("revision_id", "")))
        receipt = self._load_input(str(latest["source"]["input_id"]))
        if latest["source"] != {
            "input_id": receipt["input_id"],
            "input_digest": receipt["input_digest"],
            **receipt["source"],
        }:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer continuity record does not match its exact input",
            )
        self._validate_revision_scope(latest, receipt)
        expected = self._revision_ref(latest)
        parent_ref = latest.get("parent_revision_ref")
        if int(latest["revision_number"]) == 1:
            if parent_ref is not None:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "initial manuscript has a parent"
                )
        else:
            if not isinstance(parent_ref, Mapping):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript predecessor is missing",
                )
            parent = self._load_revision(composition_id, str(parent_ref["revision_id"]))
            if parent["revision_digest"] != parent_ref["revision_digest"] or int(
                parent["revision_number"]
            ) + 1 != int(latest["revision_number"]):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript predecessor binding differs",
                )
        head_path = self._head_path(composition_id)
        head = (
            self._read_json(
                head_path,
                message="manuscript head is corrupt; restore its exact backup or remove only this derived pointer before retry",
            )
            if head_path.exists()
            else None
        )
        # A lagging pointer is accepted only when it is an exact ancestor. Healthy
        # imports do not traverse ancestry; interrupted imports normally check one edge.
        ancestor = latest
        while head is not None and head != self._revision_ref(ancestor):
            parent_ref = ancestor.get("parent_revision_ref")
            if not isinstance(parent_ref, Mapping):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript head conflicts with retained history; preserve it and restore an exact backup",
                )
            parent = self._load_revision(composition_id, str(parent_ref["revision_id"]))
            if parent["revision_digest"] != parent_ref["revision_digest"] or int(
                parent["revision_number"]
            ) + 1 != int(ancestor["revision_number"]):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript ancestry does not verify",
                )
            ancestor = parent
        restored = []
        if new_checkpoint:
            self._write_pointer(checkpoint, latest)
            restored.append("continuity_record")
        if not self._write_immutable(
            self._revision_path(composition_id, str(latest["revision_id"])), latest
        ):
            restored.append("manuscript_revision")
        if head != expected:
            self._write_head(composition_id, expected)
            restored.append("head")
        return expected, restored

    def _export_lock_path(self, output: Path) -> Path:
        resolved = os.path.normcase(str(output.resolve(strict=False)))
        token = hashlib.sha256(resolved.encode("utf-8")).hexdigest()
        return self._composition_service().root / f".writer-round-trip-export-{token}.lock"

    @staticmethod
    def _section_scope(section_input: Mapping[str, Any]) -> Mapping[str, Any]:
        contract = section_input["section_contract"]
        locators: dict[str, set[str]] = {
            str(source): set() for source in contract.get("source_refs", [])
        }
        for citation in contract.get("citation_requirements", []):
            if not isinstance(citation, Mapping):
                continue
            source = citation.get("source_ref")
            locator = citation.get("locator_ref")
            if isinstance(source, str) and isinstance(locator, str):
                locators.setdefault(source, set()).add(locator)
        for obj in section_input.get("resolved_research_objects", []):
            if not isinstance(obj, Mapping):
                continue
            if (
                obj.get("kind") == "source"
                and isinstance(obj.get("id"), str)
                and isinstance(obj.get("canonical_locator"), str)
            ):
                locators.setdefault(str(obj["id"]), set()).add(str(obj["canonical_locator"]))
            if (
                obj.get("kind") == "evidence"
                and isinstance(obj.get("source_id"), str)
                and isinstance(obj.get("locator"), str)
            ):
                locators.setdefault(str(obj["source_id"]), set()).add(str(obj["locator"]))
        for material in section_input.get("resolved_materials", []):
            if not isinstance(material, Mapping) or not isinstance(material.get("source_id"), str):
                continue
            capture = material.get("capture")
            if isinstance(capture, Mapping):
                for key in ("source_locator", "exact_locator"):
                    locator = capture.get(key)
                    if isinstance(locator, str) and locator:
                        locators.setdefault(str(material["source_id"]), set()).add(locator)
        return {
            "section_id": contract["section_id"],
            "section_digest": contract["section_digest"],
            "section_input_digest": section_input["section_input_digest"],
            "source_refs": list(contract.get("source_refs", [])),
            "citation_scope": [
                {"source_ref": source, "locators": sorted(values)}
                for source, values in sorted(locators.items())
            ],
            "exhibit_refs": list(contract.get("exhibit_refs", [])),
        }

    def _validate_input_context(
        self, value: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        source = value["source"]
        composer = self._composition_service()
        composition = composer._load_version(
            str(source["composition_id"]), int(source["composition_version"])
        )
        if composition.get("composition_digest") != source.get("composition_digest"):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer input composition pin no longer resolves",
            )
        package = composer._package(str(source["research_package_id"]))
        composer._validate_source_pin(composition["source"], package)
        expected_source = {
            "composition_id": composition["composition_id"],
            "composition_version": composition["version"],
            "composition_digest": composition["composition_digest"],
            **composition["source"],
        }
        if dict(source) != expected_source:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer input pins do not match the immutable composition and Research Package",
            )

        for row in value["sections"]:
            section_id = str(row["section_id"])
            embedded = row.get("section_input")
            if not isinstance(embedded, Mapping):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                    "Writer input receipt is missing its canonical section input",
                )
            expected = composer._build_section_input_document(
                composition["composition_id"],
                section_id,
                version=int(composition["version"]),
                digest=str(composition["composition_digest"]),
            )
            if dict(embedded) != dict(expected):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                    "embedded section Writer input differs from the canonical pinned payload",
                )
            expected_scope = dict(self._section_scope(expected))
            for key in (
                "section_id",
                "section_digest",
                "section_input_digest",
                "source_refs",
                "citation_scope",
                "exhibit_refs",
            ):
                if row.get(key) != expected_scope.get(key):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                        "Writer input receipt summary does not match its canonical section input",
                    )

        if value.get("schema_version") == "0.1.0" and value.get("input_id") != (
            "WRI-"
            + canonical_digest({"source": source, "sections": value["sections"]}).split(":", 1)[1][
                :24
            ]
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "Writer input identity does not match its canonical pinned content",
            )
        return composition, package

    def export_input(
        self, composition_id: str, section_ids: list[str], output_dir: str | Path
    ) -> Mapping[str, Any]:
        if not isinstance(section_ids, list) or not section_ids or len(section_ids) > MAX_SECTIONS:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                "section_ids must be a bounded non-empty array",
            )
        if any(
            not isinstance(section_id, str) or not section_id for section_id in section_ids
        ) or len(set(section_ids)) != len(section_ids):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                "section_ids must contain unique non-empty IDs",
            )
        out = Path(output_dir).expanduser()
        managed = (self.workspace / ".research-loom").resolve(strict=False)
        resolved = out.resolve(strict=False)
        if resolved == managed or resolved.is_relative_to(managed):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001",
                "Writer input export must not write into managed workspace state",
            )
        if out.exists():
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001",
                "Writer input export will not overwrite an existing path",
            )
        parent = out.parent
        if not parent.exists():
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001", "Writer input export parent must exist"
            )
        composer = self._composition_service()
        selection = composer._selection(composition_id)
        if not selection or not isinstance(selection.get("selected"), Mapping):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-SELECTION-001",
                "a composition version must be explicitly selected before Writer export",
            )
        selected = selection["selected"]
        composition = composer._load_version(composition_id, int(selected["version"]))
        if composition["composition_digest"] != selected["digest"]:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                "selected composition digest no longer resolves",
            )
        package = composer._package(composition["source"]["research_package_id"])
        composer._validate_source_pin(composition["source"], package)
        section_map = {str(row["section_id"]): row for row in composition["sections"]}
        missing = [section_id for section_id in section_ids if section_id not in section_map]
        if missing:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-404",
                "selected Writer sections do not exist: " + ", ".join(missing),
            )

        tmp: Path | None = None
        try:
            with composer._file_lock(
                self._export_lock_path(out),
                "Writer round-trip output destination is being exported",
            ):
                if out.exists():
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001",
                        "Writer input export will not overwrite an existing path",
                    )
                tmp = Path(tempfile.mkdtemp(prefix=".writer-input-", dir=parent))
                staging = tmp / "payload"
                staging.mkdir()
                section_records: list[dict[str, Any]] = []
                operation_bytes = 0
                sections_root = staging / "sections"
                sections_root.mkdir()
                for section_id in section_ids:
                    section_out = sections_root / safe_component(section_id, "section_id")
                    composer.export_section_input(composition_id, section_id, section_out)
                    payload_path = section_out / "section-writer-input.json"
                    operation_bytes += payload_path.stat().st_size
                    operation_bytes += (section_out / "manifest.json").stat().st_size
                    if operation_bytes > MAX_EXPORT_OPERATION_BYTES:
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-ROUND-TRIP-BOUND-001",
                            f"Writer export generated {operation_bytes} bytes, above its {MAX_EXPORT_OPERATION_BYTES}-byte operation budget; retry with fewer section_ids, or narrow the section in a new composition version",
                        )
                    section_bytes = payload_path.read_bytes()
                    section_input = json.loads(section_bytes.decode("utf-8"))
                    record = {
                        **dict(self._section_scope(section_input)),
                        "relative_path": f"sections/{safe_component(section_id, 'section_id')}/section-writer-input.json",
                        "section_input": deepcopy(section_input),
                    }
                    section_records.append(record)

                source = {
                    "composition_id": composition["composition_id"],
                    "composition_version": composition["version"],
                    "composition_digest": composition["composition_digest"],
                    **composition["source"],
                }
                document = compact_input(source, section_records)
                _validate_schema(document)
                self._validate_input_context(expand_input(document))
                receipt_bytes = _json_bytes(document)
                operation_bytes += len(receipt_bytes)
                if operation_bytes > MAX_EXPORT_OPERATION_BYTES:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-BOUND-001",
                        f"Writer export generated {operation_bytes} bytes, above its {MAX_EXPORT_OPERATION_BYTES}-byte operation budget; retry with fewer section_ids",
                    )
                reused = self._write_immutable(self._input_path(document["input_id"]), document)
                (staging / "writer-input.json").write_bytes(receipt_bytes)
                if out.exists():
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001",
                        "Writer input export will not overwrite an existing path",
                    )
                os.rename(staging, out)
        except LocalApplicationError as exc:
            if exc.code == "APPLICATION-WRITER-COMPOSITION-BUSY-001":
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001",
                    "Writer input export destination is busy",
                ) from exc
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-WRITE-001", "Writer input export failed"
            ) from exc
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
        return {
            "status": "EXPORTED",
            "input_id": document["input_id"],
            "input_digest": document["input_digest"],
            "input_reused": reused,
            "composition_id": composition_id,
            "composition_version": composition["version"],
            "section_ids": list(section_ids),
            "output": str(out),
            "research_state_mutation_performed": False,
        }
