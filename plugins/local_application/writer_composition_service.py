from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from core.runtime import canonical_digest
from .facade import LocalApplicationError
from .research_package_format import safe_component

SCHEMA_VERSION = "0.1.0"
MAX_COMPOSITIONS = 64
MAX_VERSIONS = 64
MAX_SECTIONS = 64
MAX_SECTION_REFS = 128
MAX_SECTION_INPUT_BYTES = 4 * 1024 * 1024
MAX_SELECTION_EVENTS = 256
SCHEMA = Path(__file__).resolve().parents[2] / "core/packages/writer-publication/writer-composition.schema.json"


def _validate_schema(value: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda e: list(e.absolute_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "canonical Writer Composition schema is unavailable") from exc
    if errors:
        first = errors[0]
        path = ".".join(map(str, first.absolute_path)) or "$"
        raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-SCHEMA-001", f"Writer Composition contract violation at {path}: {first.message}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{field} must be a non-empty string")
    return value


def _strings(value: Any, field: str, limit: int = MAX_SECTION_REFS) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(x, str) or not x for x in value):
        raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{field} must be a bounded array of IDs")
    if len(set(value)) != len(value):
        raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{field} must not contain duplicates")
    return list(value)


def _digest_document(value: Mapping[str, Any], digest_field: str) -> str:
    basis = deepcopy(dict(value))
    basis.pop(digest_field, None)
    return canonical_digest(basis)


def _profile_constraint_map(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(row.get("path")): deepcopy(row.get("value"))
        for row in package.get("resolved_profiles", {}).get("effective_constraints", [])
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }


def _package_ref_sets(package: Mapping[str, Any]) -> dict[str, set[str]]:
    content = package.get("content", {})
    source_refs = content.get("source_refs", []) if isinstance(content, Mapping) else []
    exhibits = package.get("resolved_content", {}).get("working_material", {}).get("research_exhibits", [])
    gaps = package.get("resolved_content", {}).get("unresolved_gaps", [])
    return {
        "argument_refs": set(map(str, content.get("argument_refs", []))),
        "finding_refs": set(map(str, content.get("finding_refs", []))),
        "evidence_refs": set(map(str, content.get("evidence_refs", []))),
        "source_refs": {str(x.get("source_id")) for x in source_refs if isinstance(x, Mapping) and x.get("source_id")},
        "counter_review_refs": set(map(str, content.get("counter_review_refs", []))),
        "qualifier_refs": set(map(str, content.get("qualifier_refs", []))),
        "limitation_refs": {
            str(x.get("limitation_id")) for x in content.get("limitations", [])
            if isinstance(x, Mapping) and x.get("limitation_id")
        },
        "contribution_refs": set(map(str, content.get("contribution_refs", []))),
        "recommendation_refs": set(),
        "exhibit_refs": {str(x.get("exhibit_id")) for x in exhibits if isinstance(x, Mapping) and x.get("exhibit_id")},
        "gap_refs": {str(x.get("gap_id")) for x in gaps if isinstance(x, Mapping) and x.get("gap_id")},
        "material_refs": {f"{x.get('run_id')}:{x.get('capture', {}).get('capture_id')}" for x in package.get("resolved_content", {}).get("materials", []) if isinstance(x, Mapping) and x.get("run_id") and isinstance(x.get("capture"), Mapping) and x.get("capture", {}).get("capture_id")},
    }


def _object_index(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(x.get("id")): x for x in package.get("resolved_content", {}).get("research_objects", [])
        if isinstance(x, Mapping) and x.get("id")
    }


def _linked_ids(value: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    target = value.get("target")
    if isinstance(target, Mapping) and isinstance(target.get("id"), str):
        ids.add(str(target["id"]))
    for key, item in value.items():
        if key.endswith("_id") and isinstance(item, str):
            ids.add(item)
        elif key.endswith("_ids") and isinstance(item, list):
            ids.update(str(x) for x in item if isinstance(x, str))
        elif key.endswith("_refs") and isinstance(item, list):
            ids.update(str(x) for x in item if isinstance(x, str))
    return ids


class WriterCompositionService:
    def __init__(self, facade) -> None:
        self.facade = facade
        self.workspace = facade._workspace_root
        if self.workspace is None:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-001", "opened workspace is required")
        self.root = self.workspace / ".research-loom" / "writer-compositions"

    def _package_service(self):
        return self.facade._research_package_service()

    def _package(self, package_id: str) -> Mapping[str, Any]:
        return self._package_service().show(package_id)["package"]

    def _series_root(self, composition_id: str) -> Path:
        try:
            safe_component(composition_id, "composition_id")
        except LocalApplicationError as exc:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", "invalid composition_id") from exc
        if len(composition_id) > 128:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", "invalid composition_id")
        return self.root / composition_id

    @contextmanager
    def _file_lock(self, lock_path: Path, message: str):
        self.root.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError) as exc:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-BUSY-001", message) from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    @contextmanager
    def _series_lock(self, composition_id: str):
        safe_id = self._series_root(composition_id).name
        if not self._versions(composition_id):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-404", "composition series does not exist")
        with self._file_lock(self.root / f".{safe_id}.lock", "composition series is being updated"):
            yield

    @contextmanager
    def _creation_lock(self):
        with self._file_lock(self.root / ".creation.lock", "composition series creation is being updated"):
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

    def _load_version(self, composition_id: str, version: int, package_cache: dict[tuple[str, str], Mapping[str, Any]] | None = None) -> Mapping[str, Any]:
        path = self._version_path(composition_id, version)
        if not path.is_file():
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-404", "composition version does not exist")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "saved composition version is unreadable") from exc
        if _digest_document(value, "composition_digest") != value.get("composition_digest"):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "saved composition digest mismatch")
        package_id = str(value["source"]["research_package_id"])
        package_digest = str(value["source"]["research_package_digest"])
        key = (package_id, package_digest)
        package = package_cache.get(key) if package_cache is not None else None
        if package is None:
            package = self._package(package_id)
            if package_cache is not None:
                package_cache[key] = package
        self._validate_source_pin(value["source"], package)
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

    def _source_pin(self, package: Mapping[str, Any], *, lineage_ref: str | None = None) -> dict[str, Any]:
        snapshot = package["source_research_snapshot"]
        package_lineage = snapshot.get("lineage_ref")
        if isinstance(package_lineage, str) and package_lineage:
            lineage_ref = package_lineage
        elif lineage_ref is None:
            lineage_ref = str(self.facade._application.state_repository.load_active_lineage_ref(self.facade._project_id))
        return {
            "research_package_id": package["package_id"],
            "research_package_digest": package["package_digest"],
            "project_id": package["project"]["project_id"],
            "lineage_ref": lineage_ref,
            "research_snapshot_id": snapshot["snapshot_id"],
            "research_snapshot_digest": snapshot["content_digest"],
            "effective_profile_set_ref": package["effective_profile_set"]["effective_profile_set_ref"],
            "effective_profile_set_digest": package["effective_profile_set"]["content_digest"],
        }

    def _validate_source_pin(self, pin: Mapping[str, Any], package: Mapping[str, Any]) -> None:
        lineage_ref = pin.get("lineage_ref")
        if not isinstance(lineage_ref, str) or not lineage_ref:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "composition source lineage pin is missing")
        if dict(pin) != self._source_pin(package, lineage_ref=lineage_ref):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "composition source pin does not match the immutable Research Package")
        try:
            state = self.facade._application.state_repository.load_state_view(str(pin["project_id"]), lineage_ref)
        except Exception as exc:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "composition source lineage does not resolve") from exc
        current = state.current_snapshot; seen = set(); found = False
        while current is not None:
            sid = str(current.get("id"))
            if sid in seen: break
            seen.add(sid)
            if sid == pin.get("research_snapshot_id"):
                found = str(current.get("content_digest")) == pin.get("research_snapshot_digest"); break
            prior = current.get("prior_snapshot_id")
            if not isinstance(prior, str) or not prior: break
            current = self.facade._application.state_repository.load_snapshot(prior)
        if not found:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "composition source Snapshot is not in the pinned Research Lineage")

    def _narrative_defs(self, package: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]], list[Mapping[str, Any]], set[str]]:
        constraints = _profile_constraint_map(package)
        stages = {str(x["id"]): x for x in constraints.get("narrative.stages.definitions", []) if isinstance(x, Mapping) and x.get("id")}
        purposes = {str(x["id"]): x for x in constraints.get("narrative.section_purposes.definitions", []) if isinstance(x, Mapping) and x.get("id")}
        edges = [x for x in constraints.get("narrative.dependencies.required", []) if isinstance(x, Mapping)]
        preservation = set(map(str, constraints.get("narrative.preservation.required_content", [])))
        return stages, purposes, edges, preservation

    def _validate_graph(self, stages: Mapping[str, Mapping[str, Any]], edges: list[Mapping[str, Any]]) -> None:
        graph = {key: set() for key in stages}
        for edge in edges:
            a, b = str(edge.get("from_stage")), str(edge.get("to_stage"))
            if a not in graph or b not in graph:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", "Narrative dependency references an unknown stage")
            graph[a].add(b)
        visiting: set[str] = set(); done: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", "Narrative dependency cycle detected")
            if node in done:
                return
            visiting.add(node)
            for nxt in graph[node]: visit(nxt)
            visiting.remove(node); done.add(node)
        for node in graph: visit(node)

    def _validate_sections(self, sections: Any, package: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(sections, list) or not sections or len(sections) > MAX_SECTIONS:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", "sections must be a bounded non-empty array")
        refs = _package_ref_sets(package); objects = _object_index(package)
        stages, purposes, edges, preservation = self._narrative_defs(package); self._validate_graph(stages, edges)
        seen: set[str] = set(); normalized = []; diagnostics = []
        for index, raw in enumerate(sections):
            if not isinstance(raw, Mapping):
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", "each section must be an object")
            sid = _require_string(raw.get("section_id"), f"sections[{index}].section_id")
            if sid in seen:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", f"duplicate section_id: {sid}")
            seen.add(sid)
            stage_refs = _strings(raw.get("narrative_stage_refs"), f"{sid}.narrative_stage_refs")
            purpose_refs = _strings(raw.get("semantic_purpose_refs"), f"{sid}.semantic_purpose_refs")
            if not stage_refs:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", f"section {sid} has no Narrative stage")
            unknown = [x for x in stage_refs if x not in stages]
            if unknown:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", f"section {sid} references unknown Narrative stages: {', '.join(unknown)}")
            unknown_p = [x for x in purpose_refs if x not in purposes]
            if unknown_p:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", f"section {sid} references unknown purposes: {', '.join(unknown_p)}")
            for purpose_id in purpose_refs:
                allowed = set(map(str, purposes[purpose_id].get("stage_ids", [])))
                if allowed and not allowed.intersection(stage_refs):
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", f"section {sid} purpose {purpose_id} is not placed in an allowed stage")
            section: dict[str, Any] = {
                "section_id": sid,
                "parent_section_id": raw.get("parent_section_id"),
                "order": int(raw.get("order", index + 1)),
                "heading": _require_string(raw.get("heading"), f"{sid}.heading"),
                "reader_question": _require_string(raw.get("reader_question"), f"{sid}.reader_question"),
                "purpose": _require_string(raw.get("purpose"), f"{sid}.purpose"),
                "narrative_stage_refs": stage_refs,
                "semantic_purpose_refs": purpose_refs,
                "messages": [str(x) for x in raw.get("messages", []) if isinstance(x, str) and x],
                "opening_intent": str(raw.get("opening_intent") or "TBD"),
                "closing_intent": str(raw.get("closing_intent") or "TBD"),
                "previous_section_id": raw.get("previous_section_id"),
                "next_section_id": raw.get("next_section_id"),
                "length_hint": raw.get("length_hint"),
                "prohibited_claims": [str(x) for x in raw.get("prohibited_claims", []) if isinstance(x, str) and x],
                "unresolved_items": [str(x) for x in raw.get("unresolved_items", []) if isinstance(x, str) and x],
                "detailed": bool(raw.get("detailed", True)),
            }
            for field in refs:
                section[field] = _strings(raw.get(field), f"{sid}.{field}")
                missing = sorted(set(section[field]) - refs[field])
                if missing:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-REFERENCE-001", f"section {sid} references material not supplied by the Research Package: {', '.join(missing)}")
            citations = raw.get("citation_requirements", [])
            if not isinstance(citations, list) or len(citations) > MAX_SECTION_REFS:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{sid}.citation_requirements must be bounded")
            section["citation_requirements"] = []
            for citation in citations:
                if not isinstance(citation, Mapping):
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INPUT-001", f"{sid}.citation_requirements entries must be objects")
                source_id = _require_string(citation.get("source_ref"), "source_ref")
                if source_id not in refs["source_refs"]:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-REFERENCE-001", f"section {sid} citation references an unavailable Source: {source_id}")
                section["citation_requirements"].append({"source_ref": source_id, "locator_ref": citation.get("locator_ref")})
            required_kinds = set()
            for stage_id in stage_refs:
                required_kinds.update(map(str, stages[stage_id].get("requires", [])))
            available_by_kind = {
                "argument": bool(section["argument_refs"]), "finding": bool(section["finding_refs"]),
                "evidence": bool(section["evidence_refs"]), "source": bool(section["source_refs"]),
                "counter_review": bool(section["counter_review_refs"]), "contribution": bool(section["contribution_refs"]),
                "recommendation": bool(section["recommendation_refs"]),
                "research_question": True,
            }
            unmet = sorted(kind for kind in required_kinds if not available_by_kind.get(kind, False))
            if unmet:
                diagnostics.append({"section_id": sid, "code": "WRITER-COMPOSITION-NARRATIVE-UNMET", "unmet_requires": unmet})
            # Preservation is claim-local when target links are available; otherwise package-wide adverse content is conservative.
            affected = set(section["finding_refs"] + section["argument_refs"] + section["contribution_refs"] + section["recommendation_refs"])
            for field, vocabulary in (("counter_review_refs", "counter_findings"), ("qualifier_refs", "qualifiers"), ("limitation_refs", "limitations")):
                if vocabulary not in preservation:
                    continue
                required = set()
                for object_id in refs[field]:
                    obj = objects.get(object_id)
                    links = _linked_ids(obj) if obj else set()
                    if not links or links.intersection(affected): required.add(object_id)
                missing = sorted(required - set(section[field]))
                if missing and affected:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PRESERVATION-001", f"section {sid} drops required {field}: {', '.join(missing)}")
            section["section_digest"] = _digest_document(section, "section_digest")
            normalized.append(section)
        # Parent/bridge refs must resolve inside the proposal.
        for section in normalized:
            for field in ("parent_section_id", "previous_section_id", "next_section_id"):
                target = section.get(field)
                if target is not None and target not in seen:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-REFERENCE-001", f"section {section['section_id']} has unknown {field}: {target}")
        # Preserve only declared Narrative partial order; unrelated stages may move freely.
        stage_occurrences: dict[str, list[tuple[int, str]]] = {x: [] for x in stages}
        for section in normalized:
            for stage_id in section["narrative_stage_refs"]:
                stage_occurrences[stage_id].append((section["order"], section["section_id"]))
        for edge in edges:
            a, b = str(edge["from_stage"]), str(edge["to_stage"])
            for a_order, a_section in stage_occurrences[a]:
                for b_order, b_section in stage_occurrences[b]:
                    if a_section != b_section and a_order > b_order:
                        raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-001", f"Narrative dependency order is violated: {a} -> {b}")
        return normalized, diagnostics

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
            versions = self._versions(composition_id)
            base_version = value.get("base_version")
            base_digest = value.get("base_digest")
            if versions:
                latest = versions[-1]
                if base_version != latest:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-STALE-001", "composition update is based on a stale version; automatic rebase is not supported")
                base = self._load_version(composition_id, latest)
                if base_digest != base["composition_digest"]:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-STALE-001", "composition update base digest mismatch")
                if base["source"] != self._source_pin(package):
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "a composition series cannot be rebound to another Research Package")
                version = latest + 1
            else:
                if base_version is not None or base_digest is not None:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-STALE-001", "initial composition must not declare a base version")
                if self.root.exists() and sum(1 for item in self.root.iterdir() if item.is_dir()) >= MAX_COMPOSITIONS:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-BOUND-001", "composition series bound exceeded")
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
            root = self._series_root(composition_id); versions_root = root / "versions"
            if len(versions) >= MAX_VERSIONS:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-BOUND-001", "composition version bound exceeded")
            versions_root.mkdir(parents=True, exist_ok=True)
            path = self._version_path(composition_id, version)
            if path.exists():
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-IMMUTABLE-001", "composition version already exists")
            tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                os.replace(tmp, path)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", "composition persistence failed") from exc
        return {"status": "CAPTURED", "composition": deepcopy(document), "selection_changed": False}

    def list(self) -> Mapping[str, Any]:
        if not self.root.exists(): return {"status": "OK", "compositions": [], "truncated": False}
        roots = [x for x in sorted(self.root.iterdir()) if x.is_dir()][:MAX_COMPOSITIONS + 1]
        rows = []
        package_cache: dict[tuple[str, str], Mapping[str, Any]] = {}
        for root in roots[:MAX_COMPOSITIONS]:
            versions = self._versions(root.name)
            if not versions: continue
            latest = self._load_version(root.name, versions[-1], package_cache)
            selection = self._selection(root.name)
            rows.append({"composition_id": root.name, "latest_version": versions[-1], "latest_digest": latest["composition_digest"], "source": latest["source"], "selected": selection.get("selected") if selection else None})
        return {"status": "OK", "compositions": rows, "truncated": len(roots) > MAX_COMPOSITIONS}

    def show(self, composition_id: str, version: int) -> Mapping[str, Any]:
        return {"status": "OK", "composition": deepcopy(dict(self._load_version(composition_id, version))), "selection": self._selection(composition_id)}

    def export(self, composition_id: str, version: int, output: str | Path) -> Mapping[str, Any]:
        document = self._load_version(composition_id, version)
        proposal = {
            "composition_id": composition_id,
            "base_version": version,
            "base_digest": document["composition_digest"],
            "purpose": document["purpose"], "audience": document["audience"], "sections": document["sections"],
            "change_reason": "describe revision",
            "created_by": {"type": "external_or_human"},
        }
        path = Path(output).expanduser()
        managed = (self.workspace / ".research-loom").resolve(strict=False)
        resolved = path.resolve(strict=False)
        if resolved == managed or resolved.is_relative_to(managed):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-EXPORT-001", "composition export must not write into managed workspace state")
        if path.exists(): raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-EXPORT-001", "composition export will not overwrite an existing path")
        if not path.parent.exists(): raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-EXPORT-001", "composition export parent must exist")
        try: path.write_text(json.dumps(proposal, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        except OSError as exc: raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", "composition export failed") from exc
        return {"status": "EXPORTED", "composition_id": composition_id, "version": version, "output": str(path), "content_digest": canonical_digest(proposal)}

    def diff(self, composition_id: str, from_version: int, to_version: int) -> Mapping[str, Any]:
        before = self._load_version(composition_id, from_version); after = self._load_version(composition_id, to_version)
        b = {x["section_id"]: x for x in before["sections"]}; a = {x["section_id"]: x for x in after["sections"]}
        changes = []
        for sid in sorted(set(b) | set(a)):
            if sid not in b: changes.append({"section_id": sid, "change": "added", "fields": sorted(a[sid])}); continue
            if sid not in a: changes.append({"section_id": sid, "change": "removed", "fields": sorted(b[sid])}); continue
            fields = sorted(key for key in set(b[sid]) | set(a[sid]) if key != "section_digest" and b[sid].get(key) != a[sid].get(key))
            if fields: changes.append({"section_id": sid, "change": "modified", "fields": fields})
        return {"status": "OK", "composition_id": composition_id, "from": {"version": from_version, "digest": before["composition_digest"]}, "to": {"version": to_version, "digest": after["composition_digest"]}, "change_reason": after.get("change_reason"), "section_changes": changes}

    def _selection(self, composition_id: str) -> Mapping[str, Any] | None:
        path = self._series_root(composition_id) / "selection.json"
        if not path.exists(): return None
        try: return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc: raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "composition selection history is unreadable") from exc

    def select(self, composition_id: str, version: int, digest: str) -> Mapping[str, Any]:
        if not self._versions(composition_id):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-404", "composition series does not exist")
        with self._series_lock(composition_id):
            document = self._load_version(composition_id, version)
            if digest != document["composition_digest"]:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-PIN-001", "selection must name the exact composition digest")
            path = self._series_root(composition_id) / "selection.json"; previous = self._selection(composition_id)
            history = list(previous.get("history", [])) if previous else []
            if len(history) >= MAX_SELECTION_EVENTS:
                raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-BOUND-001", "composition selection history bound exceeded")
            event = {"version": version, "digest": digest, "selected_at": _now()}; history.append(event)
            value = {"selected": event, "history": history}
            tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
            try: tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8"); os.replace(tmp, path)
            except OSError as exc: tmp.unlink(missing_ok=True); raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", "composition selection persistence failed") from exc
        return {"status": "SELECTED", "composition_id": composition_id, "selection": event, "research_state_mutation_performed": False}

    def _resolve_material_text(self, package: Mapping[str, Any], material: Mapping[str, Any]) -> str:
        rel = material["text_rendition"]["attachment_path"]
        path = self._package_service().root / str(package["package_id"]) / rel
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", f"Research Package attachment is missing or unreadable: {rel}") from exc
        meta = material["text_rendition"]
        import hashlib
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if len(data) != int(meta.get("byte_length", -1)) or actual != meta.get("content_digest"):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", f"Research Package attachment size/digest mismatch: {rel}")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", f"Research Package material is not valid UTF-8: {rel}") from exc

    def export_section_input(self, composition_id: str, section_id: str, output_dir: str | Path) -> Mapping[str, Any]:
        selection = self._selection(composition_id)
        if not selection or not isinstance(selection.get("selected"), Mapping):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-SELECTION-001", "a composition version must be explicitly selected before section export")
        selected = selection["selected"]; document = self._load_version(composition_id, int(selected["version"]))
        if document["composition_digest"] != selected["digest"]:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-INTEGRITY-001", "selected composition digest no longer resolves")
        section = next((x for x in document["sections"] if x["section_id"] == section_id), None)
        if section is None: raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-404", "selected section does not exist")
        unmet = [x for x in document["validation"]["diagnostics"] if x.get("section_id") == section_id and x.get("code") == "WRITER-COMPOSITION-NARRATIVE-UNMET"]
        if unmet: raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-NARRATIVE-UNMET", "selected section has unmet Narrative prerequisites")
        package = self._package(document["source"]["research_package_id"]); self._validate_source_pin(document["source"], package)
        objects = _object_index(package); needed_ids = set()
        for field in ("argument_refs","finding_refs","evidence_refs","source_refs","counter_review_refs","qualifier_refs","limitation_refs","contribution_refs","recommendation_refs"):
            needed_ids.update(section[field])
        selected_objects = [deepcopy(dict(objects[x])) for x in sorted(needed_ids) if x in objects]
        exhibits_by_id = {str(x.get("exhibit_id")): x for x in package.get("resolved_content", {}).get("working_material", {}).get("research_exhibits", []) if isinstance(x, Mapping)}
        exhibits = [deepcopy(dict(exhibits_by_id[x])) for x in section["exhibit_refs"] if x in exhibits_by_id]
        source_ids = set(section["source_refs"]); material_refs = set(section["material_refs"])
        materials = []
        for material in package.get("resolved_content", {}).get("materials", []):
            source_id = material.get("source_id")
            capture_id = material.get("capture", {}).get("capture_id") if isinstance(material.get("capture"), Mapping) else None
            material_ref = f"{material.get('run_id')}:{capture_id}" if capture_id else None
            if source_id in source_ids or material_ref in material_refs:
                row = deepcopy(dict(material)); row["material_ref"] = material_ref; row["text_rendition"]["content"] = self._resolve_material_text(package, material); materials.append(row)
        gaps_by_id = {str(x.get("gap_id")): x for x in package.get("resolved_content", {}).get("unresolved_gaps", []) if isinstance(x, Mapping)}
        gaps = [deepcopy(dict(gaps_by_id[x])) for x in section["gap_refs"] if x in gaps_by_id]
        ordered = sorted(document["sections"], key=lambda x: (x["order"], x["section_id"])); pos = next(i for i,x in enumerate(ordered) if x["section_id"] == section_id)
        context = [{"section_id": x["section_id"], "heading": x["heading"], "purpose": x["purpose"], "order": x["order"]} for x in ordered]
        input_doc = {
            "schema_version": SCHEMA_VERSION, "object_type": "section_writer_input",
            "source": {"composition_id": composition_id, "composition_version": document["version"], "composition_digest": document["composition_digest"], **document["source"]},
            "communication": {"purpose": document["purpose"], "audience": document["audience"], "core_message": package.get("communication_brief", {}).get("core_message"), "must_not_claim": list(dict.fromkeys(package.get("communication_brief", {}).get("must_not_claim", []) + package.get("project_constraints", {}).get("must_not_claim", [])))},
            "outline_context": {"sections": context, "target_index": pos, "previous": context[pos-1] if pos else None, "next": context[pos+1] if pos+1 < len(context) else None},
            "section_contract": deepcopy(section),
            "resolved_research_objects": selected_objects,
            "resolved_materials": materials,
            "resolved_exhibits": exhibits,
            "unresolved_gaps": gaps,
            "resolved_profile_constraints": deepcopy(package.get("resolved_profiles", {}).get("effective_constraints", [])),
            "authority_boundary": {"evidence_verification_performed": False, "finding_adoption_performed": False, "recommendation_adoption_performed": False, "research_state_mutation_performed": False},
        }
        input_doc["section_input_digest"] = _digest_document(input_doc, "section_input_digest")
        _validate_schema(input_doc)
        payload = (json.dumps(input_doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(payload) > MAX_SECTION_INPUT_BYTES:
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-BOUND-001", "section Writer input exceeds output bound; narrow the section material")
        out = Path(output_dir).expanduser()
        managed = (self.workspace / ".research-loom").resolve(strict=False)
        resolved = out.resolve(strict=False)
        if resolved == managed or resolved.is_relative_to(managed):
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-EXPORT-001", "section input export must not write into managed workspace state")
        if out.exists(): raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-EXPORT-001", "section input export will not overwrite an existing path")
        parent = out.parent
        if not parent.exists(): raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-EXPORT-001", "section input export parent must exist")
        tmp = Path(tempfile.mkdtemp(prefix=".section-input-", dir=parent)); staging = tmp / "payload"; staging.mkdir()
        import hashlib
        manifest = {"schema_version": SCHEMA_VERSION, "object_type": "section_writer_input_manifest", "files": [{"path": "section-writer-input.json", "byte_length": len(payload), "content_digest": "sha256:" + hashlib.sha256(payload).hexdigest()}]}
        manifest["manifest_digest"] = _digest_document(manifest, "manifest_digest")
        _validate_schema(manifest)
        try:
            (staging / "section-writer-input.json").write_bytes(payload)
            (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
            os.replace(staging, out); shutil.rmtree(tmp, ignore_errors=True)
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", "section input export failed") from exc
        return {"status": "EXPORTED", "composition_id": composition_id, "version": document["version"], "section_id": section_id, "output": str(out), "section_input_digest": input_doc["section_input_digest"], "manifest_digest": manifest["manifest_digest"]}
