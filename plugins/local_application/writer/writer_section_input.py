"""Detached section input export for writer compositions (#494)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from plugins.application_errors import LocalApplicationError

from ..research_package.research_package_format import package_required_refs
from .writer_composition_support import (
    MAX_SECTION_REFS,
    MAX_WRITER_EXPORT_OPERATION_BYTES,
    SCHEMA_VERSION,
    _digest_document,
    _linked_ids,
    _material_ref,
    _object_index,
    _validate_schema,
    _writer_profile_delivery,
    verify_section_input_root,
)


class WriterSectionInputMixin:
    def _resolve_material_text(
        self, package: Mapping[str, Any], material: Mapping[str, Any]
    ) -> str:
        rel = material["text_rendition"]["attachment_path"]
        path = self._package_service().root / str(package["package_id"]) / rel
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"Research Package attachment is missing or unreadable: {rel}",
            ) from exc
        meta = material["text_rendition"]

        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if len(data) != int(meta.get("byte_length", -1)) or actual != meta.get("content_digest"):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"Research Package attachment size/digest mismatch: {rel}",
            )
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                f"Research Package material is not valid UTF-8: {rel}",
            ) from exc

    def _build_section_input_document(
        self,
        composition_id: str,
        section_id: str,
        *,
        version: int,
        digest: str,
    ) -> Mapping[str, Any]:
        document = self._load_version(composition_id, int(version))
        if document["composition_digest"] != digest:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INTEGRITY-001",
                "composition digest no longer resolves",
            )
        section = next((x for x in document["sections"] if x["section_id"] == section_id), None)
        if section is None:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-404", "section does not exist"
            )
        unmet = [
            x
            for x in document["validation"]["diagnostics"]
            if x.get("section_id") == section_id
            and x.get("code") == "WRITER-COMPOSITION-NARRATIVE-UNMET"
        ]
        if unmet:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-NARRATIVE-UNMET",
                "section has unmet Narrative prerequisites",
            )
        package = self._package(document["source"]["research_package_id"])
        self._validate_source_pin(document["source"], package)
        objects = _object_index(package)
        needed_ids = set()
        for field in (
            "argument_refs",
            "finding_refs",
            "evidence_refs",
            "source_refs",
            "counter_review_refs",
            "qualifier_refs",
            "limitation_refs",
            "contribution_refs",
            "recommendation_refs",
        ):
            needed_ids.update(section[field])
        needed_ids.update(
            str(x)
            for x in package.get("content", {}).get("research_question_refs", [])
            if isinstance(x, str)
        )
        package_materials = {
            _material_ref(row): row
            for row in package.get("resolved_content", {}).get("materials", [])
            if isinstance(row, Mapping) and _material_ref(row)
        }
        for material_ref in section["material_refs"]:
            material = package_materials.get(material_ref)
            source_id = material.get("source_id") if isinstance(material, Mapping) else None
            if isinstance(source_id, str):
                needed_ids.add(source_id)
        for citation in section["citation_requirements"]:
            source_id = citation["source_ref"]
            needed_ids.add(source_id)
            locator = citation.get("locator_ref")
            if locator is not None:
                needed_ids.update(
                    object_id
                    for object_id, obj in objects.items()
                    if obj.get("kind") == "evidence"
                    and obj.get("source_id") == source_id
                    and obj.get("locator") == locator
                )
        pending = list(needed_ids)
        while pending:
            object_id = pending.pop()
            obj = objects.get(object_id)
            if obj is None:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                    f"section input object does not resolve in Research Package: {object_id}",
                )
            for _kind, ref_id in package_required_refs(obj):
                if ref_id not in needed_ids:
                    needed_ids.add(ref_id)
                    pending.append(ref_id)
            for counter_id, counter in objects.items():
                if (
                    counter.get("kind") == "counter_review"
                    and object_id in _linked_ids(counter)
                    and counter_id not in needed_ids
                ):
                    needed_ids.add(counter_id)
                    pending.append(counter_id)
            if len(needed_ids) > MAX_SECTION_REFS:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-BOUND-001",
                    "section research-object closure exceeds supported bound",
                )
        selected_objects = [deepcopy(dict(objects[x])) for x in sorted(needed_ids)]
        exhibits_by_id = {
            str(x.get("exhibit_id")): x
            for x in package.get("resolved_content", {})
            .get("working_material", {})
            .get("research_exhibits", [])
            if isinstance(x, Mapping)
        }
        exhibits = [
            deepcopy(dict(exhibits_by_id[x]))
            for x in section["exhibit_refs"]
            if x in exhibits_by_id
        ]
        source_ids = {
            object_id for object_id in needed_ids if objects[object_id].get("kind") == "source"
        }
        material_refs = set(section["material_refs"])
        run_candidates = {
            str(row.get("run_id")): row
            for row in package.get("resolved_content", {})
            .get("working_material", {})
            .get("run_candidates", [])
            if isinstance(row, Mapping) and isinstance(row.get("run_id"), str)
        }
        materials = []
        for material in package.get("resolved_content", {}).get("materials", []):
            source_id = material.get("source_id")
            material_ref = _material_ref(material)
            if source_id in source_ids or material_ref in material_refs:
                row = deepcopy(dict(material))
                row["material_ref"] = material_ref
                row["text_rendition"]["content"] = self._resolve_material_text(package, material)
                run = run_candidates.get(str(row.get("run_id")))
                row["candidate_only"] = bool(run.get("candidate_only")) if run else False
                materials.append(row)
        missing_source_bodies = sorted(
            source_ids
            - {
                str(row.get("source_id"))
                for row in materials
                if isinstance(row.get("source_id"), str)
            }
        )
        if missing_source_bodies:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                "section input Source has no resolved material body: "
                + ", ".join(missing_source_bodies),
            )
        for citation in section["citation_requirements"]:
            if citation["source_ref"] not in source_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                    "citation Source is not connected to the resolved section evidence: "
                    + str(citation["source_ref"]),
                )
        gaps_by_id = {
            str(x.get("gap_id")): x
            for x in package.get("resolved_content", {}).get("unresolved_gaps", [])
            if isinstance(x, Mapping)
        }
        gaps = [deepcopy(dict(gaps_by_id[x])) for x in section["gap_refs"] if x in gaps_by_id]
        ordered = sorted(document["sections"], key=lambda x: (x["order"], x["section_id"]))
        pos = next(i for i, x in enumerate(ordered) if x["section_id"] == section_id)
        context = [
            {
                "section_id": x["section_id"],
                "heading": x["heading"],
                "purpose": x["purpose"],
                "order": x["order"],
            }
            for x in ordered
        ]
        writer_profile = _writer_profile_delivery(package)
        input_doc = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "section_writer_input",
            "source": {
                "composition_id": composition_id,
                "composition_version": document["version"],
                "composition_digest": document["composition_digest"],
                **document["source"],
            },
            "communication": {
                "purpose": document["purpose"],
                "audience": document["audience"],
                "core_message": package.get("communication_brief", {}).get("core_message"),
                "must_not_claim": list(
                    dict.fromkeys(
                        package.get("communication_brief", {}).get("must_not_claim", [])
                        + package.get("project_constraints", {}).get("must_not_claim", [])
                    )
                ),
            },
            "outline_context": {
                "sections": context,
                "target_index": pos,
                "previous": context[pos - 1] if pos else None,
                "next": context[pos + 1] if pos + 1 < len(context) else None,
            },
            "section_contract": deepcopy(section),
            "resolved_object_ids": sorted(needed_ids),
            "resolved_material_refs": sorted(
                row["material_ref"] for row in materials if isinstance(row.get("material_ref"), str)
            ),
            "resolved_research_objects": selected_objects,
            "resolved_materials": materials,
            "resolved_exhibits": exhibits,
            "unresolved_gaps": gaps,
            "resolved_profile_constraints": deepcopy(
                package.get("resolved_profiles", {}).get("effective_constraints", [])
            ),
            **({"writer_profile": writer_profile} if writer_profile is not None else {}),
            "authority_boundary": {
                "evidence_verification_performed": False,
                "finding_adoption_performed": False,
                "recommendation_adoption_performed": False,
                "research_state_mutation_performed": False,
            },
        }
        input_doc["section_input_digest"] = _digest_document(input_doc, "section_input_digest")
        _validate_schema(input_doc)
        return input_doc

    def export_section_input(
        self, composition_id: str, section_id: str, output_dir: str | Path
    ) -> Mapping[str, Any]:
        selection = self._selection(composition_id)
        if not selection or not isinstance(selection.get("selected"), Mapping):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-SELECTION-001",
                "a composition version must be explicitly selected before section export",
            )
        selected = selection["selected"]
        input_doc = self._build_section_input_document(
            composition_id,
            section_id,
            version=int(selected["version"]),
            digest=str(selected["digest"]),
        )
        payload = (
            json.dumps(input_doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        out = Path(output_dir).expanduser()
        managed = (self.workspace / ".research-loom").resolve(strict=False)
        resolved = out.resolve(strict=False)
        if resolved == managed or resolved.is_relative_to(managed):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-EXPORT-001",
                "section input export must not write into managed workspace state",
            )
        if out.exists():
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-EXPORT-001",
                "section input export will not overwrite an existing path",
            )
        parent = out.parent
        if not parent.exists():
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-EXPORT-001",
                "section input export parent must exist",
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "section_writer_input_manifest",
            "files": [
                {
                    "path": "section-writer-input.json",
                    "byte_length": len(payload),
                    "content_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        manifest["manifest_digest"] = _digest_document(manifest, "manifest_digest")
        _validate_schema(manifest)
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        operation_bytes = len(payload) + len(manifest_bytes)
        if operation_bytes > MAX_WRITER_EXPORT_OPERATION_BYTES:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-BOUND-001",
                f"section Writer export generated {operation_bytes} bytes, above its {MAX_WRITER_EXPORT_OPERATION_BYTES}-byte operation budget; narrow the section in a new composition version",
            )
        tmp = Path(tempfile.mkdtemp(prefix=".section-input-", dir=parent))
        staging = tmp / "payload"
        staging.mkdir()
        try:
            (staging / "section-writer-input.json").write_bytes(payload)
            (staging / "manifest.json").write_bytes(manifest_bytes)
            verify_section_input_root(staging)
            os.replace(staging, out)
            shutil.rmtree(tmp, ignore_errors=True)
        except LocalApplicationError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-WRITE-001",
                "section input export failed",
            ) from exc
        return {
            "status": "EXPORTED",
            "composition_id": composition_id,
            "version": int(selected["version"]),
            "section_id": section_id,
            "output": str(out),
            "section_input_digest": input_doc["section_input_digest"],
            "manifest_digest": manifest["manifest_digest"],
        }
