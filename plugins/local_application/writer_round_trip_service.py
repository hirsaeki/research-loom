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
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from core.resources import resource_path
from core.runtime import canonical_digest
from plugins._infra.atomic_write import write_durable
from plugins._infra.clock import utc_now as _now
from plugins.local_durable_store import register_optional_path, require_optional_available

from .facade import LocalApplicationError
from .research_package_format import safe_component
from .writer_composition_service import _digest_document, _object_index, _package_ref_sets

SCHEMA_VERSION = "0.1.0"
MAX_SECTIONS = 64
MAX_FEEDBACK_ISSUES = 128
MAX_INSPECT_ANCESTRY = 64
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ROUND_TRIP_INPUT_BYTES = 16 * 1024 * 1024
SCHEMA = resource_path("core/packages/writer-publication/writer-round-trip.schema.json")


def _validate_schema(value: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalApplicationError(
            "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
            "canonical Writer round-trip schema is unavailable",
        ) from exc
    if errors:
        first = errors[0]
        path = ".".join(map(str, first.absolute_path)) or "$"
        raise LocalApplicationError(
            "APPLICATION-WRITER-ROUND-TRIP-SCHEMA-001",
            f"Writer round-trip contract violation at {path}: {first.message}",
        )


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


class WriterRoundTripService:
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
        from .workspace import _safe_locator

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
        self._validate_input_context(value)
        return value

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

        fingerprint = canonical_digest({"source": source, "sections": value["sections"]})
        expected_input_id = "WRI-" + fingerprint.split(":", 1)[1][:24]
        if value.get("input_id") != expected_input_id:
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
                total_input_bytes = 0
                sections_root = staging / "sections"
                sections_root.mkdir()
                for section_id in section_ids:
                    section_out = sections_root / safe_component(section_id, "section_id")
                    composer.export_section_input(composition_id, section_id, section_out)
                    payload_path = section_out / "section-writer-input.json"
                    section_bytes = payload_path.read_bytes()
                    total_input_bytes += len(section_bytes)
                    if total_input_bytes > MAX_ROUND_TRIP_INPUT_BYTES:
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-ROUND-TRIP-BOUND-001",
                            "Writer round-trip section inputs exceed supported aggregate size",
                        )
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
                fingerprint = canonical_digest({"source": source, "sections": section_records})
                document: dict[str, Any] = {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "writer_round_trip_input",
                    "input_id": "WRI-" + fingerprint.split(":", 1)[1][:24],
                    "source": source,
                    "sections": section_records,
                    "authority_boundary": {
                        "research_state_mutation_performed": False,
                        "evidence_verification_performed": False,
                        "finding_adoption_performed": False,
                        "recommendation_adoption_performed": False,
                    },
                    "input_digest": "",
                }
                document["input_digest"] = _digest_document(document, "input_digest")
                _validate_schema(document)
                self._validate_input_context(document)
                receipt_bytes = _json_bytes(document)
                if len(receipt_bytes) > MAX_ROUND_TRIP_INPUT_BYTES:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-BOUND-001",
                        "Writer round-trip receipt exceeds supported aggregate size",
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

    @staticmethod
    def _known_package_refs(package: Mapping[str, Any]) -> set[str]:
        refs = set(_object_index(package))
        ref_sets = _package_ref_sets(package)
        for values in ref_sets.values():
            refs.update(values)
        refs.add(str(package["package_id"]))
        return refs

    @staticmethod
    def _writer_review_plan(scope: Mapping[str, Any]) -> dict[str, set[str]]:
        section_input = scope.get("section_input")
        if not isinstance(section_input, Mapping):
            return {}
        delivery = section_input.get("writer_profile")
        if delivery is None:
            return {}
        if not isinstance(delivery, Mapping) or not isinstance(delivery.get("review_plan"), list):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                "Writer Profile review plan is malformed",
            )
        result: dict[str, set[str]] = {}
        for row in delivery["review_plan"]:
            if (
                not isinstance(row, Mapping)
                or not isinstance(row.get("review_id"), str)
                or not isinstance(row.get("rule_ids"), list)
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile review plan is malformed",
                )
            review_id = str(row["review_id"])
            rule_ids = {
                str(rule_id) for rule_id in row["rule_ids"] if isinstance(rule_id, str) and rule_id
            }
            if not review_id or not rule_ids or review_id in result:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile review plan contains an invalid group",
                )
            result[review_id] = rule_ids
        return result

    @staticmethod
    def _validate_profile_review(draft: Mapping[str, Any], scope: Mapping[str, Any]) -> set[str]:
        plan = WriterRoundTripService._writer_review_plan(scope)
        metadata = WriterRoundTripService._writer_rule_metadata(scope)
        reviews = draft.get("profile_review", [])
        if not plan:
            if reviews:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer response reports Profile review without delivered Writer rules",
                )
            return set()
        if not isinstance(reviews, list):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                "Writer response must report the delivered Profile review plan",
            )
        by_id: dict[str, Mapping[str, Any]] = {}
        for row in reviews:
            if not isinstance(row, Mapping) or not isinstance(row.get("review_id"), str):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile review entry is malformed",
                )
            review_id = str(row["review_id"])
            if review_id in by_id:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"duplicate Writer Profile review group: {review_id}",
                )
            by_id[review_id] = row
        if set(by_id) != set(plan):
            missing = sorted(set(plan) - set(by_id))
            extra = sorted(set(by_id) - set(plan))
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                f"Writer Profile review groups do not match delivered plan; missing={missing}, extra={extra}",
            )
        violations: set[str] = set()
        for review_id, expected_rule_ids in plan.items():
            row = by_id[review_id]
            actual_rule_ids = {str(x) for x in row.get("rule_ids", []) if isinstance(x, str)}
            violated_rule_ids = {
                str(x) for x in row.get("violated_rule_ids", []) if isinstance(x, str)
            }
            if actual_rule_ids != expected_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"Writer Profile review does not cover exact rules for {review_id}",
                )
            if not violated_rule_ids <= expected_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"Writer Profile review names unavailable rules for {review_id}",
                )
            outcome = str(row.get("outcome"))
            if metadata:
                WriterRoundTripService._validate_rule_results(row, expected_rule_ids, metadata)
            if outcome in {"violation", "mixed"}:
                if not violated_rule_ids:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        f"Writer Profile review {review_id} reports a violation without rule IDs",
                    )
                violations.update(violated_rule_ids)
            elif violated_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"Writer Profile review {review_id} lists violated rules for non-violation outcome",
                )
        return violations

    @staticmethod
    def _writer_rule_metadata(scope: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        delivery = scope.get("section_input", {}).get("writer_profile", {})
        result = {}
        for resource in delivery.get("resources", []):
            if resource.get("role") != "WRITER_RULES":
                continue
            body = json.loads(resource["content"])
            if body.get("review_contract_version") != "1.0.0":
                continue
            for item in body["items"]:
                result[item["id"]] = item["review"]
        return result

    @staticmethod
    def _validate_rule_results(
        row: Mapping[str, Any],
        expected_rule_ids: set[str],
        metadata: Mapping[str, Mapping[str, Any]],
        *,
        scope: str = "section",
    ) -> None:
        def refuse(message: str) -> None:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001", message)

        results = row.get("rule_results", [])
        by_id = {item["rule_id"]: item for item in results}
        if len(by_id) != len(results) or set(by_id) != expected_rule_ids:
            refuse("Writer rule results must cover exact delivered IDs once")
        violations = set()
        outcomes = set()
        for rule_id, item in by_id.items():
            review = metadata.get(rule_id)
            outcome = item["outcome"]
            outcomes.add(outcome)
            if not item["rationale"].strip():
                refuse("Writer rule result needs a content-based rationale")
            if outcome == "violation":
                violations.add(rule_id)
            if review is None:
                continue
            if outcome == "not_applicable":
                if (
                    item["applicability"] != "not_applicable"
                    or item["method"] != review["check_kind"]
                ):
                    refuse(
                        "Writer N/A needs evaluated non-applicability and the rule's review method"
                    )
            elif outcome != "unevaluated":
                if item["applicability"] != "applicable" or item["method"] != review["check_kind"]:
                    refuse(
                        "Writer result cannot replace semantic/editorial review with structural presence"
                    )
            elif item["method"] != "unevaluated":
                refuse("Unevaluated Writer result must identify its unperformed review")
            if (
                scope == "section"
                and review["scope"] == "document"
                and outcome not in {"unevaluated", "not_applicable"}
            ):
                refuse("Section review cannot establish a document-scoped result")
        if violations != set(row.get("violated_rule_ids", [])):
            refuse("Group violations must match rule results")
        group = row["outcome"]
        if group == "not_applicable" and outcomes != {"not_applicable"}:
            refuse("Group N/A requires every rule to be non-applicable")
        if group == "conformant" and not outcomes <= {"conformant", "not_applicable"}:
            refuse("Unevaluated or violated rules cannot become group conformance")
        if group == "conformant" and outcomes == {"not_applicable"}:
            refuse("All-N/A review cannot become conformance")
        if group in {"violation", "mixed"} and not violations:
            refuse("Group violation requires a violated rule result")
        if group == "mixed" and not outcomes.intersection({"conformant", "not_applicable"}):
            refuse("Mixed group requires both violated and conformant or non-applicable rules")
        if group == "unevaluated" and violations:
            refuse("Group unevaluated cannot conceal declared violations")

    def _validate_response_semantics(
        self, response: Mapping[str, Any], receipt: Mapping[str, Any], package: Mapping[str, Any]
    ) -> None:
        section_scope = {str(row["section_id"]): row for row in receipt["sections"]}
        response_ids: set[str] = set()
        violations_by_section: dict[str, set[str]] = {}
        for draft in response["sections"]:
            section_id = str(draft["section_id"])
            if section_id in response_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                    f"duplicate Writer response section: {section_id}",
                )
            response_ids.add(section_id)
            scope = section_scope.get(section_id)
            if scope is None:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                    f"Writer response section was not exported by the pinned input: {section_id}",
                )
            allowed_exhibits = set(map(str, scope.get("exhibit_refs", [])))
            if not set(map(str, draft.get("exhibit_refs", []))) <= allowed_exhibits:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    f"Writer response introduces an unavailable Exhibit in {section_id}",
                )
            citation_scope = {
                str(row["source_ref"]): set(map(str, row.get("locators", [])))
                for row in scope.get("citation_scope", [])
                if isinstance(row, Mapping)
            }
            for citation in draft.get("citations", []):
                source = str(citation["source_ref"])
                locator = citation.get("locator_ref")
                if source not in citation_scope:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                        f"Writer response citation Source is unavailable: {source}",
                    )
                if locator is not None and str(locator) not in citation_scope[source]:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                        f"Writer response citation locator is unavailable: {locator}",
                    )
            if self._writer_rule_metadata(scope):
                citations = draft.get("citations", [])
                for required in scope["section_input"]["section_contract"].get(
                    "citation_requirements", []
                ):
                    if not any(
                        item["source_ref"] == required["source_ref"]
                        and (
                            required.get("locator_ref") is None
                            or item.get("locator_ref") == required["locator_ref"]
                        )
                        for item in citations
                    ):
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                            "Writer response omits an explicitly required citation: "
                            + str(required["source_ref"]),
                        )
            violations_by_section[section_id] = self._validate_profile_review(draft, scope)
        known_refs = self._known_package_refs(package)
        document_violations = {
            rule_id
            for row in response.get("document_review", {}).get("profile_review", [])
            for rule_id in row.get("violated_rule_ids", [])
        }
        feedback_rule_ids_by_section: dict[str, set[str]] = {}
        for issue in response.get("feedback", []):
            target_type = issue["target_type"]
            target_id = str(issue["target_id"])
            if target_type == "section" and target_id not in section_scope:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    f"Writer feedback targets an unavailable section: {target_id}",
                )
            if target_type == "package" and target_id != package["package_id"]:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    "Writer feedback targets the wrong Research Package",
                )
            if target_type in {"research_object", "argument"} and target_id not in known_refs:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    f"Writer feedback target is not in the pinned Research Package: {target_id}",
                )
            unknown_support = sorted(
                set(map(str, issue.get("supporting_package_refs", []))) - known_refs
            )
            if unknown_support:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    "Writer feedback references material outside the pinned Research Package: "
                    + ", ".join(unknown_support),
                )
            profile_rule_ids = {
                str(x) for x in issue.get("profile_rule_ids", []) if isinstance(x, str)
            }
            if profile_rule_ids:
                section_rule_ids = profile_rule_ids - document_violations
                if section_rule_ids and target_type != "section":
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        "Profile rule feedback must target a section",
                    )
                allowed = violations_by_section.get(target_id, set())
                if not section_rule_ids <= allowed:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        "Writing Feedback names Profile rules not reported as violated for the section",
                    )
                feedback_rule_ids_by_section.setdefault(target_id, set()).update(section_rule_ids)
        for section_id, violated_rule_ids in violations_by_section.items():
            missing = sorted(
                violated_rule_ids - feedback_rule_ids_by_section.get(section_id, set())
            )
            if missing:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile violations require Writing Feedback for exact rule IDs: "
                    + ", ".join(missing),
                )

    @staticmethod
    def _document_target(
        receipt: Mapping[str, Any], sections: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        # input_digest already includes the exact package, composition (roles/order)
        # and Profile pins. Review metadata and revision identity are not content.
        projection = {
            "projection_version": "1.0.0",
            "input_digest": receipt["input_digest"],
            "sections": [
                {
                    key: deepcopy(row[key])
                    for key in ("section_id", "content", "citations", "exhibit_refs")
                }
                for row in sections
            ],
        }
        return {"target_digest": canonical_digest(projection), "material": projection}

    @classmethod
    def _document_plan(
        cls, receipt: Mapping[str, Any]
    ) -> tuple[dict[str, set[str]], dict[str, Mapping[str, Any]]]:
        plan: dict[str, set[str]] = {}
        metadata: dict[str, Mapping[str, Any]] = {}
        for section in receipt["sections"]:
            rules = cls._writer_rule_metadata(section)
            for rule_id, review in rules.items():
                if rule_id in metadata and metadata[rule_id] != review:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        "conflicting document rule metadata",
                    )
                metadata[rule_id] = review
            for review_id, rule_ids in cls._writer_review_plan(section).items():
                selected = {
                    rule_id
                    for rule_id in rule_ids
                    if rules.get(rule_id, {}).get("scope") == "document"
                }
                if selected:
                    plan.setdefault(review_id, set()).update(selected)
        return plan, metadata

    @classmethod
    def _validate_document_review(
        cls,
        response: Mapping[str, Any],
        receipt: Mapping[str, Any],
        sections: list[Mapping[str, Any]],
    ) -> None:
        review = response.get("document_review")
        if review is None:
            return

        def refuse(message: str) -> None:
            raise LocalApplicationError("APPLICATION-WRITER-DOCUMENT-REVIEW-001", message)

        if not review["reviewer"]["reviewer_id"].strip():
            refuse("Document review needs an identified reviewer")
        target = cls._document_target(receipt, sections)
        if review["target_digest"] != target["target_digest"]:
            refuse(
                "Document review does not match the assembled manuscript target; remove or review it again"
            )
        target_ids = [row["section_id"] for row in sections]
        covered = review["section_ids"]
        if not set(covered) <= set(target_ids) or covered != [
            sid for sid in target_ids if sid in covered
        ]:
            refuse("Document review must name existing sections in target order")
        if review["coverage"] == "full" and covered != target_ids:
            refuse("Full review must cover every section in the exported manuscript scope")
        plan, metadata = cls._document_plan(receipt)
        rows = review["profile_review"]
        by_id = {row["review_id"]: row for row in rows}
        if len(by_id) != len(rows) or set(by_id) != set(plan):
            refuse("Document review groups must match the delivered document-scoped plan")
        violations: set[str] = set()
        for review_id, expected in plan.items():
            row = by_id[review_id]
            if not row["rationale"].strip():
                refuse("Document review group needs a content-based rationale")
            if set(row["rule_ids"]) != expected:
                refuse("Document review must cover the exact document-scoped rule IDs")
            cls._validate_rule_results(row, expected, metadata, scope="document")
            if review["coverage"] == "partial" and any(
                item["outcome"] in {"conformant", "not_applicable"} for item in row["rule_results"]
            ):
                refuse("Partial review cannot establish document conformance or document N/A")
            violations.update(row["violated_rule_ids"])
        feedback_ids = {
            rule_id
            for issue in response.get("feedback", [])
            for rule_id in issue.get("profile_rule_ids", [])
        }
        if not violations <= feedback_ids:
            refuse("Document violations require Writing Feedback for the exact rule IDs")
        for issue in response.get("feedback", []):
            if (
                set(issue.get("profile_rule_ids", [])) & violations
                and issue["target_type"] == "section"
                and issue["target_id"] not in covered
            ):
                refuse(
                    "Document rule feedback must target a reviewed section or a pinned research/package target"
                )

    @classmethod
    def _document_review_status(
        cls, revision: Mapping[str, Any], composition: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        review = revision.get("document_review", {})
        results = [
            item for group in review.get("profile_review", []) for item in group["rule_results"]
        ]
        _, metadata = cls._document_plan(receipt)
        evaluated = bool(results) and all(item["outcome"] != "unevaluated" for item in results)
        return {
            "status": "partial"
            if review.get("coverage") == "partial"
            else "reviewed"
            if evaluated
            else "unevaluated",
            "coverage": review.get("coverage", "unevaluated"),
            "scope_section_ids": [row["section_id"] for row in revision["sections"]],
            "reviewed_section_ids": list(review.get("section_ids", [])),
            "covers_composition": [row["section_id"] for row in revision["sections"]]
            == [row["section_id"] for row in composition["sections"]],
            "rule_outcomes": {item["rule_id"]: item["outcome"] for item in results},
            "results_by_check_kind": {
                kind: [
                    deepcopy(item)
                    for item in results
                    if metadata[item["rule_id"]]["check_kind"] == kind
                ]
                for kind in ("structural", "semantic", "editorial")
            },
            "semantic_quality_guaranteed": False,
            "reader_effect_validated": False,
        }

    def prepare_document_review(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        """Materialize a proposed response plus its exact base without saving a draft."""
        if (
            not isinstance(value, Mapping)
            or len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-BOUND-001",
                "Writer response exceeds supported size or is not an object",
            )
        _validate_schema(value)
        receipt = self._load_input(str(value["input_ref"]["input_id"]))
        if value["input_ref"]["input_digest"] != receipt["input_digest"]:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer response does not name the exact exported input digest",
            )
        composition, package = self._validate_input_context(receipt)
        self._validate_response_semantics(value, receipt, package)
        composition_id = str(composition["composition_id"])
        with self._composition_service()._series_lock(composition_id):
            head = self._head(composition_id)
            if head is not None:
                # Read-only continuity check; an interrupted import must be recovered
                # through the existing exact-response retry before preparing a review.
                inspected = self.inspect(composition_id)
                base = inspected["revision"]
                exact_base = {key: base[key] for key in ("revision_id", "revision_digest")}
                if value["base_revision_ref"] != exact_base:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "review preparation requires the exact current base",
                    )
            else:
                if self._checkpoint_path(composition_id).exists():
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-RECOVERY-REQUIRED-001",
                        "restore the manuscript head by retrying the exact response",
                    )
                base = None
                if value["base_revision_ref"] is not None:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "initial review target must not name a base",
                    )
            drafts = {row["section_id"]: row for row in value["sections"]}
            required_ids = [row["section_id"] for row in receipt["sections"]]
            if base is None or base["source"]["input_id"] != receipt["input_id"]:
                if set(drafts) != set(required_ids):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                        "initial or changed-input review target requires all exported sections",
                    )
            previous = {row["section_id"]: row for row in base["sections"]} if base else {}
            sections = [
                deepcopy(drafts[sid] if sid in drafts else previous[sid]) for sid in required_ids
            ]
            target = self._document_target(receipt, sections)
            plan, metadata = self._document_plan(receipt)
            return {
                "status": "PREPARED",
                **target,
                "input_ref": deepcopy(value["input_ref"]),
                "base_revision_ref": deepcopy(value["base_revision_ref"]),
                "writer_input": deepcopy(receipt),
                "review_plan": [
                    {"review_id": key, "rule_ids": sorted(ids)} for key, ids in plan.items()
                ],
                "rule_metadata": {
                    key: metadata[key] for ids in plan.values() for key in sorted(ids)
                },
                "scope_section_ids": required_ids,
                "composition_section_ids": [row["section_id"] for row in composition["sections"]],
                "research_state_mutation_performed": False,
            }

    def import_response(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "Writer response must be an object"
            )
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-BOUND-001", "Writer response exceeds supported size"
            )
        _validate_schema(value)
        input_ref = value["input_ref"]
        receipt = self._load_input(str(input_ref["input_id"]))
        if input_ref["input_digest"] != receipt["input_digest"]:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer response does not name the exact exported input digest",
            )
        composition, package = self._validate_input_context(receipt)
        self._validate_response_semantics(value, receipt, package)
        composition_id = str(composition["composition_id"])
        composer = self._composition_service()

        response_digest = canonical_digest(value)
        revision_id = "WMR-" + response_digest.split(":", 1)[1][:24]
        response_section_ids = {str(row["section_id"]) for row in value["sections"]}
        receipt_section_ids = {str(row["section_id"]) for row in receipt["sections"]}
        with composer._series_lock(composition_id):
            head, restored = self._reconcile_head(composition_id)
            existing_path = self._revision_path(composition_id, revision_id)
            if existing_path.is_file():
                stored = self._read_json(existing_path, message="manuscript revision is unreadable")
                revision_id = str(stored.get("revision_id", ""))
                existing = self._load_revision(composition_id, revision_id)
                if (
                    existing.get("response_digest") != response_digest
                    or existing.get("source", {}).get("input_digest") != receipt["input_digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001",
                        "existing manuscript revision identity conflicts with this response",
                    )
                if head is None or int(existing["revision_number"]) > int(head["revision_number"]):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                        "stored response is ahead of the retained continuity record; restore a consistent exact backup",
                    )
                if int(head["revision_number"]) == int(existing["revision_number"]) and (
                    head["revision_id"] != existing["revision_id"]
                    or head["revision_digest"] != existing["revision_digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                        "manuscript head conflicts with an existing revision at the same revision number",
                    )
                return {
                    "status": "RESTORED" if "manuscript_revision" in restored else "VERIFIED_REUSE",
                    **(
                        {"restored_components": restored, "recovered_at": _now()}
                        if restored
                        else {}
                    ),
                    "revision_id": revision_id,
                    "revision_digest": existing["revision_digest"],
                    "revision_number": existing["revision_number"],
                    "research_state_mutation_performed": False,
                }

            base_ref = value.get("base_revision_ref")
            base_revision = None
            if head is None:
                if base_ref is not None:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "initial manuscript response must not name a base revision",
                    )
                if response_section_ids != receipt_section_ids:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                        "initial manuscript response must provide every section in the exported input",
                    )
                revision_number = 1
            else:
                if (
                    not isinstance(base_ref, Mapping)
                    or base_ref.get("revision_id") != head["revision_id"]
                    or base_ref.get("revision_digest") != head["revision_digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "Writer response must be based on the exact current manuscript revision",
                    )
                base_revision = self._load_revision(composition_id, str(head["revision_id"]))
                revision_number = int(base_revision["revision_number"]) + 1
                if (
                    base_revision["source"]["input_id"] != receipt["input_id"]
                    and response_section_ids != receipt_section_ids
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                        "a changed Writer input requires a complete fresh section response; unchanged sections are reused only within the same exact input",
                    )

            revision_id += "-" + uuid4().hex
            drafts = {str(row["section_id"]): row for row in value["sections"]}
            sections: list[dict[str, Any]] = []
            base_sections = (
                {str(row["section_id"]): row for row in base_revision.get("sections", [])}
                if base_revision is not None
                else {}
            )
            for input_section in receipt["sections"]:
                section_id = str(input_section["section_id"])
                draft = drafts.get(section_id)
                if draft is None:
                    base = base_sections.get(section_id)
                    if base is None:
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                            f"Writer response omits section without a reusable base: {section_id}",
                        )
                    sections.append(deepcopy(dict(base)))
                    continue
                row = {
                    "section_id": section_id,
                    "content": str(draft["content"]),
                    "content_digest": _sha256_text(str(draft["content"])),
                    "citations": deepcopy(list(draft.get("citations", []))),
                    "exhibit_refs": deepcopy(list(draft.get("exhibit_refs", []))),
                    **(
                        {"profile_review": deepcopy(list(draft["profile_review"]))}
                        if "profile_review" in draft
                        else {}
                    ),
                    "origin_revision_id": revision_id,
                }
                sections.append(row)

            self._validate_document_review(value, receipt, sections)
            feedback = deepcopy(list(value.get("feedback", [])))
            candidate_follow_ups = [
                {
                    "source_issue_id": str(issue["issue_id"]),
                    "instruction": str(issue["proposed_next_action"]),
                    "status": "candidate",
                    "research_state_mutation_performed": False,
                }
                for issue in feedback
            ]
            document: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "writer_manuscript_revision",
                "revision_id": revision_id,
                "revision_number": revision_number,
                "source": {
                    "input_id": receipt["input_id"],
                    "input_digest": receipt["input_digest"],
                    **receipt["source"],
                },
                "parent_revision_ref": deepcopy(dict(base_ref))
                if isinstance(base_ref, Mapping)
                else None,
                "response_id": value["response_id"],
                "response_digest": response_digest,
                "writer": deepcopy(dict(value["writer"])),
                "sections": sections,
                **(
                    {"document_review": deepcopy(value["document_review"])}
                    if "document_review" in value
                    else {}
                ),
                "writing_feedback": {
                    "issues": feedback,
                    "is_research_evidence": False,
                    "research_state_mutation_performed": False,
                },
                "candidate_follow_ups": candidate_follow_ups,
                "authority_boundary": {
                    "research_state_mutation_performed": False,
                    "evidence_verification_performed": False,
                    "finding_adoption_performed": False,
                    "recommendation_adoption_performed": False,
                },
                "created_at": _now(),
                "revision_digest": "",
            }
            document["revision_digest"] = _digest_document(document, "revision_digest")
            _validate_schema(document)
            # Retain exact immutable facts before either emitted copy. This latest
            # per-series record is also the O(1) pending-write witness on next import.
            self._write_pointer(self._checkpoint_path(composition_id), document)
            self._write_immutable(self._revision_path(composition_id, revision_id), document)
            self._write_head(
                composition_id,
                {
                    "revision_id": revision_id,
                    "revision_digest": document["revision_digest"],
                    "revision_number": revision_number,
                },
            )
        return {
            "status": "IMPORTED",
            "revision_id": revision_id,
            "revision_digest": document["revision_digest"],
            "revision_number": revision_number,
            "reused_section_ids": [
                row["section_id"] for row in sections if row["origin_revision_id"] != revision_id
            ],
            "research_state_mutation_performed": False,
        }

    def inspect(self, composition_id: str, revision_id: str | None = None) -> Mapping[str, Any]:
        self._composition_service()
        if revision_id is None:
            checkpoint = self._checkpoint_path(composition_id)
            if checkpoint.exists():
                latest = self._read_json(
                    checkpoint,
                    message="Writer continuity record is unreadable; restore an exact backup",
                )
                self._validate_revision(latest, composition_id, str(latest.get("revision_id", "")))
                head_path = self._head_path(composition_id)
                head_copy = (
                    self._read_json(
                        head_path,
                        message="manuscript head is unreadable; restore the derived pointer",
                    )
                    if head_path.exists()
                    else None
                )
                if head_copy != self._revision_ref(latest):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-RECOVERY-REQUIRED-001",
                        "manuscript import needs recovery; retry the exact stored response before requesting the latest revision",
                    )
            head = self._head(composition_id)
            if head is None:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-404", "manuscript revision head does not exist"
                )
            revision_id = str(head["revision_id"])
        revision = self._load_revision(composition_id, revision_id)
        receipt = self._load_input(str(revision["source"]["input_id"]))
        composition, package = self._validate_input_context(receipt)
        if (
            revision["source"]["composition_digest"] != composition["composition_digest"]
            or revision["source"]["research_package_digest"] != package["package_digest"]
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "manuscript revision source pins do not match its input",
            )
        if "document_review" in revision:
            self._validate_document_review(
                {
                    "document_review": revision["document_review"],
                    "feedback": revision["writing_feedback"]["issues"],
                },
                receipt,
                list(revision["sections"]),
            )

        lineage: list[dict[str, Any]] = []
        current = revision
        truncated = False
        for _ in range(MAX_INSPECT_ANCESTRY):
            lineage.append(
                {
                    "revision_id": current["revision_id"],
                    "revision_number": current["revision_number"],
                    "revision_digest": current["revision_digest"],
                    "input_id": current["source"]["input_id"],
                }
            )
            parent = current.get("parent_revision_ref")
            if not isinstance(parent, Mapping):
                break
            current = self._load_revision(composition_id, str(parent["revision_id"]))
            if current["revision_digest"] != parent["revision_digest"]:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript parent revision digest does not resolve",
                )
        else:
            truncated = isinstance(current.get("parent_revision_ref"), Mapping)

        return {
            "status": "OK",
            "document_review_target": self._document_target(receipt, list(revision["sections"])),
            "document_review_status": self._document_review_status(revision, composition, receipt),
            "source_package": {
                "package_id": package["package_id"],
                "package_digest": package["package_digest"],
                "research_snapshot": deepcopy(package["source_research_snapshot"]),
                "effective_profile_set": deepcopy(package["effective_profile_set"]),
            },
            "composition": {
                "composition_id": composition["composition_id"],
                "version": composition["version"],
                "composition_digest": composition["composition_digest"],
                "sections": deepcopy(composition["sections"]),
            },
            "writer_input": deepcopy(receipt),
            "effective_constraints": deepcopy(
                package.get("resolved_profiles", {}).get("effective_constraints", [])
            ),
            "revision": deepcopy(revision),
            "revision_lineage": lineage,
            "lineage_truncated": truncated,
            "research_state_mutation_performed": False,
        }
