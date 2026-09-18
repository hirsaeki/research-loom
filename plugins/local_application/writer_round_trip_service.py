from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from core.runtime import canonical_digest
from .facade import LocalApplicationError
from .research_package_format import safe_component
from .writer_composition_service import _digest_document, _material_ref, _object_index, _package_ref_sets

SCHEMA_VERSION = "0.1.0"
MAX_SECTIONS = 64
MAX_FEEDBACK_ISSUES = 128
MAX_INSPECT_ANCESTRY = 64
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SCHEMA = Path(__file__).resolve().parents[2] / "core/packages/writer-publication/writer-round-trip.schema.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        self.inputs_root = self.root / "inputs"
        self.series_root = self.root / "series"

    def _composition_service(self):
        return self.facade._writer_composition_service()

    def _input_path(self, input_id: str) -> Path:
        return self.inputs_root / f"{safe_component(input_id, 'input_id')}.json"

    def _revision_root(self, composition_id: str) -> Path:
        return self.series_root / safe_component(composition_id, "composition_id")

    def _revision_path(self, composition_id: str, revision_id: str) -> Path:
        return self._revision_root(composition_id) / "revisions" / f"{safe_component(revision_id, 'revision_id')}.json"

    def _head_path(self, composition_id: str) -> Path:
        return self._revision_root(composition_id) / "head.json"

    def _read_json(self, path: Path, *, message: str) -> Mapping[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", message) from exc
        if not isinstance(value, Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", message)
        return value

    def _write_immutable(self, path: Path, value: Mapping[str, Any]) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _json_bytes(value)
        if path.exists():
            existing = self._read_json(path, message="immutable Writer round-trip record is unreadable")
            if dict(existing) != dict(value):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001",
                    "immutable Writer round-trip identity already contains different content",
                )
            return True
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                existing = self._read_json(path, message="immutable Writer round-trip record is unreadable")
                if dict(existing) != dict(value):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001",
                        "immutable Writer round-trip identity raced with different content",
                    )
                return True
            return False
        except OSError as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-WRITE-001",
                "Writer round-trip immutable persistence failed",
            ) from exc
        finally:
            tmp.unlink(missing_ok=True)

    def _write_head(self, composition_id: str, value: Mapping[str, Any]) -> None:
        path = self._head_path(composition_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".head.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(_json_bytes(value))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-WRITE-001",
                "Writer manuscript head persistence failed",
            ) from exc
        finally:
            tmp.unlink(missing_ok=True)

    def _load_input(self, input_id: str) -> Mapping[str, Any]:
        path = self._input_path(input_id)
        if not path.is_file():
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-404", "Writer input does not exist")
        value = self._read_json(path, message="Writer input receipt is unreadable")
        _validate_schema(value)
        if _digest_document(value, "input_digest") != value.get("input_digest"):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "Writer input digest mismatch")
        self._validate_input_context(value)
        return value

    def _load_revision(self, composition_id: str, revision_id: str) -> Mapping[str, Any]:
        path = self._revision_path(composition_id, revision_id)
        if not path.is_file():
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-404", "manuscript revision does not exist")
        value = self._read_json(path, message="manuscript revision is unreadable")
        _validate_schema(value)
        if _digest_document(value, "revision_digest") != value.get("revision_digest"):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript revision digest mismatch")
        return value

    def _head(self, composition_id: str) -> Mapping[str, Any] | None:
        path = self._head_path(composition_id)
        if not path.exists():
            return None
        value = self._read_json(path, message="manuscript revision head is unreadable")
        revision_id = value.get("revision_id")
        revision_digest = value.get("revision_digest")
        if not isinstance(revision_id, str) or not isinstance(revision_digest, str):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript revision head is invalid")
        revision = self._load_revision(composition_id, revision_id)
        if revision.get("revision_digest") != revision_digest:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript revision head digest does not resolve")
        return value

    @staticmethod
    def _section_scope(section_input: Mapping[str, Any]) -> Mapping[str, Any]:
        contract = section_input["section_contract"]
        locators: dict[str, set[str]] = {str(source): set() for source in contract.get("source_refs", [])}
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
            if obj.get("kind") == "source" and isinstance(obj.get("id"), str) and isinstance(obj.get("canonical_locator"), str):
                locators.setdefault(str(obj["id"]), set()).add(str(obj["canonical_locator"]))
            if obj.get("kind") == "evidence" and isinstance(obj.get("source_id"), str) and isinstance(obj.get("locator"), str):
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
                {"source_ref": source, "locators": sorted(values)} for source, values in sorted(locators.items())
            ],
            "exhibit_refs": list(contract.get("exhibit_refs", [])),
        }

    def _validate_input_context(self, value: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        source = value["source"]
        composer = self._composition_service()
        composition = composer._load_version(str(source["composition_id"]), int(source["composition_version"]))
        if composition.get("composition_digest") != source.get("composition_digest"):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "Writer input composition pin no longer resolves")
        package = composer._package(str(source["research_package_id"]))
        composer._validate_source_pin(composition["source"], package)
        expected_source = {
            "composition_id": composition["composition_id"],
            "composition_version": composition["version"],
            "composition_digest": composition["composition_digest"],
            **composition["source"],
        }
        if dict(source) != expected_source:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "Writer input pins do not match the immutable composition and Research Package")

        by_id = {str(section["section_id"]): section for section in composition["sections"]}
        package_objects = _object_index(package)
        package_materials = {
            _material_ref(material): material
            for material in package.get("resolved_content", {}).get("materials", [])
            if isinstance(material, Mapping) and _material_ref(material)
        }
        package_exhibits = {
            str(exhibit.get("exhibit_id")): exhibit
            for exhibit in package.get("resolved_content", {}).get("working_material", {}).get("research_exhibits", [])
            if isinstance(exhibit, Mapping) and isinstance(exhibit.get("exhibit_id"), str)
        }
        package_gaps = {
            str(gap.get("gap_id")): gap
            for gap in package.get("resolved_content", {}).get("unresolved_gaps", [])
            if isinstance(gap, Mapping) and isinstance(gap.get("gap_id"), str)
        }
        run_candidates = {
            str(run.get("run_id")): run
            for run in package.get("resolved_content", {}).get("working_material", {}).get("run_candidates", [])
            if isinstance(run, Mapping) and isinstance(run.get("run_id"), str)
        }
        expected_constraints = package.get("resolved_profiles", {}).get("effective_constraints", [])

        for row in value["sections"]:
            section = by_id.get(str(row["section_id"]))
            embedded = row.get("section_input")
            if (
                section is None
                or section.get("section_digest") != row.get("section_digest")
                or not isinstance(embedded, Mapping)
            ):
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "Writer input section pin no longer resolves")
            if _digest_document(embedded, "section_input_digest") != embedded.get("section_input_digest"):
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "embedded section Writer input digest mismatch")
            if dict(embedded.get("source", {})) != expected_source or embedded.get("section_contract") != section:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "embedded section Writer input does not match the pinned composition")
            if embedded.get("resolved_profile_constraints") != expected_constraints:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "embedded Writer profile constraints do not match the pinned Effective Profile Set")

            expected_objects = [
                deepcopy(dict(package_objects[object_id]))
                for object_id in embedded.get("resolved_object_ids", [])
                if object_id in package_objects
            ]
            if len(expected_objects) != len(embedded.get("resolved_object_ids", [])) or embedded.get("resolved_research_objects") != expected_objects:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "embedded Writer research objects do not match the pinned Research Package")

            expected_materials = []
            for embedded_material in embedded.get("resolved_materials", []):
                material_ref = embedded_material.get("material_ref") if isinstance(embedded_material, Mapping) else None
                base = package_materials.get(material_ref)
                if base is None:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "embedded Writer material does not resolve in the pinned Research Package")
                expected_material = deepcopy(dict(base))
                expected_material["material_ref"] = material_ref
                expected_material["text_rendition"]["content"] = composer._resolve_material_text(package, base)
                run = run_candidates.get(str(expected_material.get("run_id")))
                expected_material["candidate_only"] = bool(run.get("candidate_only")) if run else False
                expected_materials.append(expected_material)
            if embedded.get("resolved_materials") != expected_materials:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "embedded Writer material bodies do not match the pinned Research Package")

            expected_exhibits = [
                deepcopy(dict(package_exhibits[exhibit_id]))
                for exhibit_id in section.get("exhibit_refs", [])
                if exhibit_id in package_exhibits
            ]
            expected_gaps = [
                deepcopy(dict(package_gaps[gap_id]))
                for gap_id in section.get("gap_refs", [])
                if gap_id in package_gaps
            ]
            if embedded.get("resolved_exhibits") != expected_exhibits or embedded.get("unresolved_gaps") != expected_gaps:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "embedded Writer Exhibit/Gap bindings do not match the pinned Research Package")

            expected_scope = dict(self._section_scope(embedded))
            for key in ("section_id", "section_digest", "section_input_digest", "source_refs", "citation_scope", "exhibit_refs"):
                if row.get(key) != expected_scope.get(key):
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "Writer input receipt summary does not match its embedded section input")
        return composition, package

    def export_input(self, composition_id: str, section_ids: list[str], output_dir: str | Path) -> Mapping[str, Any]:
        if not isinstance(section_ids, list) or not section_ids or len(section_ids) > MAX_SECTIONS:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "section_ids must be a bounded non-empty array")
        if any(not isinstance(section_id, str) or not section_id for section_id in section_ids) or len(set(section_ids)) != len(section_ids):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "section_ids must contain unique non-empty IDs")
        out = Path(output_dir).expanduser()
        managed = (self.workspace / ".research-loom").resolve(strict=False)
        resolved = out.resolve(strict=False)
        if resolved == managed or resolved.is_relative_to(managed):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-EXPORT-001", "Writer input export must not write into managed workspace state")
        if out.exists():
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-EXPORT-001", "Writer input export will not overwrite an existing path")
        parent = out.parent
        if not parent.exists():
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-EXPORT-001", "Writer input export parent must exist")
        composer = self._composition_service()
        selection = composer._selection(composition_id)
        if not selection or not isinstance(selection.get("selected"), Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-SELECTION-001", "a composition version must be explicitly selected before Writer export")
        selected = selection["selected"]
        composition = composer._load_version(composition_id, int(selected["version"]))
        if composition["composition_digest"] != selected["digest"]:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "selected composition digest no longer resolves")
        package = composer._package(composition["source"]["research_package_id"])
        composer._validate_source_pin(composition["source"], package)
        section_map = {str(row["section_id"]): row for row in composition["sections"]}
        missing = [section_id for section_id in section_ids if section_id not in section_map]
        if missing:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-404", "selected Writer sections do not exist: " + ", ".join(missing))

        reservation = parent / f".{out.name}.writer-round-trip-reserved"
        try:
            reservation.mkdir()
        except FileExistsError as exc:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-EXPORT-001", "Writer input export destination is busy") from exc
        tmp: Path | None = None
        try:
            tmp = Path(tempfile.mkdtemp(prefix=".writer-input-", dir=parent))
            staging = tmp / "payload"
            staging.mkdir()
            section_records: list[dict[str, Any]] = []
            sections_root = staging / "sections"
            sections_root.mkdir()
            for section_id in section_ids:
                section_out = sections_root / safe_component(section_id, "section_id")
                composer.export_section_input(composition_id, section_id, section_out)
                section_input = json.loads((section_out / "section-writer-input.json").read_text(encoding="utf-8"))
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
            reused = self._write_immutable(self._input_path(document["input_id"]), document)
            (staging / "writer-input.json").write_bytes(_json_bytes(document))
            if out.exists():
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-EXPORT-001", "Writer input export will not overwrite an existing path")
            os.rename(staging, out)
        except LocalApplicationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-WRITE-001", "Writer input export failed") from exc
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(reservation, ignore_errors=True)
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

    def _validate_response_semantics(self, response: Mapping[str, Any], receipt: Mapping[str, Any], package: Mapping[str, Any]) -> None:
        section_scope = {str(row["section_id"]): row for row in receipt["sections"]}
        response_ids: set[str] = set()
        for draft in response["sections"]:
            section_id = str(draft["section_id"])
            if section_id in response_ids:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", f"duplicate Writer response section: {section_id}")
            response_ids.add(section_id)
            scope = section_scope.get(section_id)
            if scope is None:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", f"Writer response section was not exported by the pinned input: {section_id}")
            allowed_exhibits = set(map(str, scope.get("exhibit_refs", [])))
            if not set(map(str, draft.get("exhibit_refs", []))) <= allowed_exhibits:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", f"Writer response introduces an unavailable Exhibit in {section_id}")
            citation_scope = {
                str(row["source_ref"]): set(map(str, row.get("locators", [])))
                for row in scope.get("citation_scope", [])
                if isinstance(row, Mapping)
            }
            for citation in draft.get("citations", []):
                source = str(citation["source_ref"])
                locator = citation.get("locator_ref")
                if source not in citation_scope:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", f"Writer response citation Source is unavailable: {source}")
                if locator is not None and str(locator) not in citation_scope[source]:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", f"Writer response citation locator is unavailable: {locator}")
        known_refs = self._known_package_refs(package)
        for issue in response.get("feedback", []):
            target_type = issue["target_type"]
            target_id = str(issue["target_id"])
            if target_type == "section" and target_id not in section_scope:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", f"Writer feedback targets an unavailable section: {target_id}")
            if target_type == "package" and target_id != package["package_id"]:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", "Writer feedback targets the wrong Research Package")
            if target_type in {"research_object", "argument"} and target_id not in known_refs:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", f"Writer feedback target is not in the pinned Research Package: {target_id}")
            unknown_support = sorted(set(map(str, issue.get("supporting_package_refs", []))) - known_refs)
            if unknown_support:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001", "Writer feedback references material outside the pinned Research Package: " + ", ".join(unknown_support))

    def import_response(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "Writer response must be an object")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-BOUND-001", "Writer response exceeds supported size")
        _validate_schema(value)
        input_ref = value["input_ref"]
        receipt = self._load_input(str(input_ref["input_id"]))
        if input_ref["input_digest"] != receipt["input_digest"]:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "Writer response does not name the exact exported input digest")
        composition, package = self._validate_input_context(receipt)
        self._validate_response_semantics(value, receipt, package)
        composition_id = str(composition["composition_id"])
        composer = self._composition_service()

        response_digest = canonical_digest(value)
        revision_id = "WMR-" + response_digest.split(":", 1)[1][:24]
        response_section_ids = {str(row["section_id"]) for row in value["sections"]}
        receipt_section_ids = {str(row["section_id"]) for row in receipt["sections"]}
        with composer._series_lock(composition_id):
            existing_path = self._revision_path(composition_id, revision_id)
            if existing_path.is_file():
                existing = self._load_revision(composition_id, revision_id)
                if existing.get("response_digest") != response_digest or existing.get("source", {}).get("input_digest") != receipt["input_digest"]:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001", "existing manuscript revision identity conflicts with this response")
                head = self._head(composition_id)
                if head is None or int(head["revision_number"]) < int(existing["revision_number"]):
                    self._write_head(
                        composition_id,
                        {
                            "revision_id": revision_id,
                            "revision_digest": existing["revision_digest"],
                            "revision_number": existing["revision_number"],
                        },
                    )
                elif int(head["revision_number"]) == int(existing["revision_number"]) and (
                    head["revision_id"] != revision_id or head["revision_digest"] != existing["revision_digest"]
                ):
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript head conflicts with an existing revision at the same revision number")
                return {
                    "status": "VERIFIED_REUSE",
                    "revision_id": revision_id,
                    "revision_digest": existing["revision_digest"],
                    "revision_number": existing["revision_number"],
                    "research_state_mutation_performed": False,
                }

            head = self._head(composition_id)
            base_ref = value.get("base_revision_ref")
            base_revision = None
            if head is None:
                if base_ref is not None:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-STALE-001", "initial manuscript response must not name a base revision")
                if response_section_ids != receipt_section_ids:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "initial manuscript response must provide every section in the exported input")
                revision_number = 1
            else:
                if not isinstance(base_ref, Mapping) or base_ref.get("revision_id") != head["revision_id"] or base_ref.get("revision_digest") != head["revision_digest"]:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-STALE-001", "Writer response must be based on the exact current manuscript revision")
                base_revision = self._load_revision(composition_id, str(head["revision_id"]))
                revision_number = int(base_revision["revision_number"]) + 1
                if base_revision["source"]["input_id"] != receipt["input_id"] and response_section_ids != receipt_section_ids:
                    raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "a changed Writer input requires a complete fresh section response; unchanged sections are reused only within the same exact input")

            drafts = {str(row["section_id"]): row for row in value["sections"]}
            sections: list[dict[str, Any]] = []
            base_sections = {
                str(row["section_id"]): row for row in base_revision.get("sections", [])
            } if base_revision is not None else {}
            for input_section in receipt["sections"]:
                section_id = str(input_section["section_id"])
                draft = drafts.get(section_id)
                if draft is None:
                    base = base_sections.get(section_id)
                    if base is None:
                        raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INPUT-001", f"Writer response omits section without a reusable base: {section_id}")
                    sections.append(deepcopy(dict(base)))
                    continue
                row = {
                    "section_id": section_id,
                    "content": str(draft["content"]),
                    "content_digest": _sha256_text(str(draft["content"])),
                    "citations": deepcopy(list(draft.get("citations", []))),
                    "exhibit_refs": deepcopy(list(draft.get("exhibit_refs", []))),
                    "origin_revision_id": revision_id,
                }
                sections.append(row)

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
                "parent_revision_ref": deepcopy(dict(base_ref)) if isinstance(base_ref, Mapping) else None,
                "response_id": value["response_id"],
                "response_digest": response_digest,
                "writer": deepcopy(dict(value["writer"])),
                "sections": sections,
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
        composer = self._composition_service()
        if revision_id is None:
            head = self._head(composition_id)
            if head is None:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-404", "manuscript revision head does not exist")
            revision_id = str(head["revision_id"])
        revision = self._load_revision(composition_id, revision_id)
        receipt = self._load_input(str(revision["source"]["input_id"]))
        composition, package = self._validate_input_context(receipt)
        if revision["source"]["composition_digest"] != composition["composition_digest"] or revision["source"]["research_package_digest"] != package["package_digest"]:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PIN-001", "manuscript revision source pins do not match its input")

        lineage: list[dict[str, Any]] = []
        current = revision
        truncated = False
        for _ in range(MAX_INSPECT_ANCESTRY):
            lineage.append({
                "revision_id": current["revision_id"],
                "revision_number": current["revision_number"],
                "revision_digest": current["revision_digest"],
                "input_id": current["source"]["input_id"],
            })
            parent = current.get("parent_revision_ref")
            if not isinstance(parent, Mapping):
                break
            current = self._load_revision(composition_id, str(parent["revision_id"]))
            if current["revision_digest"] != parent["revision_digest"]:
                raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001", "manuscript parent revision digest does not resolve")
        else:
            truncated = isinstance(current.get("parent_revision_ref"), Mapping)

        return {
            "status": "OK",
            "source_package": {
                "package_id": package["package_id"],
                "package_digest": package["package_digest"],
                "research_snapshot": deepcopy(package["research_snapshot"]),
                "effective_profile_set": deepcopy(package["effective_profile_set"]),
            },
            "composition": {
                "composition_id": composition["composition_id"],
                "version": composition["version"],
                "composition_digest": composition["composition_digest"],
                "sections": deepcopy(composition["sections"]),
            },
            "writer_input": deepcopy(receipt),
            "effective_constraints": deepcopy(package.get("resolved_profiles", {}).get("effective_constraints", [])),
            "revision": deepcopy(revision),
            "revision_lineage": lineage,
            "lineage_truncated": truncated,
            "research_state_mutation_performed": False,
        }
