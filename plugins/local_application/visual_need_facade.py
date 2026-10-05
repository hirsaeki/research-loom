"""Late visual needs return through existing Package/Composition operations."""
from copy import deepcopy
from typing import Mapping

from core.runtime import canonical_digest
from plugins.research_visual_semantics import SEMANTIC_CHANGES
from .exhibit_facade import _string_list
from .facade import LocalApplicationError
from .generated_explanation import matching_review, validate_explanation
from .visual_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

NEED_SCHEMA = "research-visual-need/v1"


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    def capture_exhibit(self, value):
        content = value.get("content", {}).get("value") if isinstance(value, Mapping) and isinstance(value.get("content"), Mapping) else None
        if isinstance(content, Mapping) and content.get("schema") == NEED_SCHEMA:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "use the source-bound visual need operation")
        return super().capture_exhibit(value)

    def _visual_need_origin(self, origin):
        if not isinstance(origin, Mapping):
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need requires an existing downstream origin")
        stage = origin.get("stage")
        if stage == "narrative" and set(origin) == {"stage", "composition_id", "composition_version"}:
            composition = self.show_writer_composition(origin["composition_id"], origin["composition_version"])["composition"]
            extra = {}
        elif stage == "writer" and set(origin) == {"stage", "composition_id", "revision_id"}:
            inspected = self.inspect_writer_round_trip(origin["composition_id"], origin["revision_id"])
            composition = self.show_writer_composition(origin["composition_id"], inspected["composition"]["version"])["composition"]
            extra = {"revision_id": inspected["revision"]["revision_id"], "revision_digest": inspected["revision"]["revision_digest"]}
        elif stage == "publication" and set(origin) == {"stage", "build_id"}:
            build = self.show_publication_preview(origin["build_id"])["build"]
            source = build["source_manuscript"]
            inspected = self.inspect_writer_round_trip(source["composition_id"], source["revision_id"])
            composition = self.show_writer_composition(source["composition_id"], inspected["composition"]["version"])["composition"]
            if build["research_provenance"]["research_package_digest"] != composition["source"]["research_package_digest"]:
                raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "Publication origin has inconsistent research binding")
            extra = {"build_id": build["build_id"], "build_digest": build["content_digest"], "revision_id": source["revision_id"], "revision_digest": source["revision_digest"]}
        else:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "unsupported visual need origin shape")
        package = self.show_research_package(composition["source"]["research_package_id"])["package"]
        if package["package_digest"] != composition["source"]["research_package_digest"]:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need origin Package changed")
        binding = {"stage": stage, "composition_id": composition["composition_id"], "composition_version": composition["version"], "composition_digest": composition["composition_digest"], **extra}
        return binding, composition, package

    def capture_visual_need(self, value):
        if not isinstance(value, Mapping) or set(value) != {"origin", "purpose", "semantic_changes", "affected_section_ids"}:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need request shape is invalid")
        origin, composition, package = self._visual_need_origin(value["origin"])
        changes = _string_list(value["semantic_changes"], "semantic_changes")
        if any(c not in SEMANTIC_CHANGES for c in changes):
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "unsupported semantic change")
        affected = _string_list(value["affected_section_ids"], "affected_section_ids", required=True)
        if not set(affected) <= {s["section_id"] for s in composition["sections"]}:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "affected sections must exist in the origin composition")
        purpose = value["purpose"]
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 2048:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need purpose must be bounded")
        depth = "research" if changes else "exhibit_capture_and_package_rebuild"
        result = super().capture_exhibit({
            "kind": "note", "title": "Visual need: " + purpose[:128], "purpose": purpose,
            "rq_ids": list(package["content"]["research_question_refs"]),
            "content": {"representation": "json", "value": {"schema": NEED_SCHEMA, "origin": origin, "package_binding": {"package_id": package["package_id"], "package_digest": package["package_digest"]}, "purpose": purpose, "semantic_changes": changes, "affected_section_ids": affected, "return_depth": depth}},
            "capture_origin": "downstream_visual_need",
        })
        return {**result, "return_depth": depth, "research_state_mutation_performed": False}

    def resume_visual_need(self, value):
        if not isinstance(value, Mapping) or set(value) != {"need_id", "exhibit_ids", "section_exhibit_refs"}:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual resume request shape is invalid")
        note = self.show_exhibit(value["need_id"])["exhibit"]
        need = note.get("content", {}).get("value")
        if not isinstance(need, Mapping) or need.get("schema") != NEED_SCHEMA:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "selected Exhibit is not a visual need")
        if set(need) != {"schema", "origin", "package_binding", "purpose", "semantic_changes", "affected_section_ids", "return_depth"}:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need record shape is invalid")
        origin = need["origin"]
        if not isinstance(origin, Mapping):
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need origin is invalid")
        fields = {"narrative": ("stage", "composition_id", "composition_version"), "writer": ("stage", "composition_id", "revision_id"), "publication": ("stage", "build_id")}.get(origin.get("stage"))
        if fields is None or any(k not in origin for k in fields):
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need origin stage is invalid")
        actual, _, _ = self._visual_need_origin({k: origin[k] for k in fields})
        if actual != origin:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need origin pins changed")
        if need["return_depth"] != "exhibit_capture_and_package_rebuild" or need["semantic_changes"]:
            raise LocalApplicationError("APPLICATION-VISUAL-RESEARCH-REQUIRED", "new research meaning requires ordinary Research work/decisions and a fresh Package")
        binding = need["package_binding"]
        package = self.show_research_package(binding["package_id"])["package"]
        if package["package_digest"] != binding["package_digest"]:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need Package binding changed")
        origin = need["origin"]
        old = self.show_writer_composition(origin["composition_id"], origin["composition_version"])["composition"]
        if old["composition_digest"] != origin["composition_digest"] or old["source"]["research_package_digest"] != package["package_digest"]:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual need Composition binding changed")
        state = self._current_state()
        current = {o["id"]: o for o in state.effective_objects()}
        objects = package["resolved_content"]["research_objects"]
        if any(o["id"] not in current or canonical_digest(current[o["id"]]) != canonical_digest(o) for o in objects):
            raise LocalApplicationError("APPLICATION-VISUAL-RESEARCH-REQUIRED", "represented research changed; use the ordinary current Research Package path")
        ids = _string_list(value["exhibit_ids"], "exhibit_ids")
        if len(ids) > 31:
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "visual resume exceeds the existing Package Exhibit bound")
        selected = [self.show_exhibit(eid)["exhibit"] for eid in ids]
        for exhibit in selected:
            semantics = exhibit.get("visual_semantics")
            if isinstance(semantics, Mapping) and semantics["semantic_changes"]:
                raise LocalApplicationError("APPLICATION-VISUAL-RESEARCH-REQUIRED", "selected visual introduces new research meaning")
            if validate_explanation(exhibit) is not None and matching_review(exhibit, selected) == "research_required":
                raise LocalApplicationError("APPLICATION-VISUAL-RESEARCH-REQUIRED", "visual review requires ordinary Research work")
        updates = value["section_exhibit_refs"]
        if not isinstance(updates, Mapping) or not set(updates) <= set(need["affected_section_ids"]):
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "only declared affected sections may change")
        sections = deepcopy(old["sections"])
        for section in sections:
            if section["section_id"] in updates:
                refs = _string_list(updates[section["section_id"]], "section_exhibit_refs")
                if not set(refs) <= set(ids):
                    raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "section visual must be selected in the rebuilt Package")
                section["exhibit_refs"] = refs
        if any(not set(s["exhibit_refs"]) <= set(ids) for s in sections):
            raise LocalApplicationError("APPLICATION-VISUAL-NEED-001", "preserved section Exhibits must remain selected")
        resolved = package["resolved_content"]; working = resolved["working_material"]
        rebuilt = self.build_research_package({
            "snapshot_id": state.current_snapshot["id"], "rq_id": package["content"]["research_question_refs"][0],
            "object_ids": [o["id"] for o in objects if o["kind"] != "research_question"],
            "run_ids": [r["run_id"] for r in working["run_candidates"]],
            "exhibit_ids": list(dict.fromkeys([*ids, note["exhibit_id"]])),
            "project_input_ids": [i["metadata"]["input_id"] for i in working["project_inputs"]],
            "materials": [{"run_id": m["run_id"], "capture_id": m["capture"]["capture_id"]} for m in resolved["materials"]],
            "gap_ids": [g["gap_id"] for g in resolved["unresolved_gaps"]],
        })
        created = self.capture_writer_composition(rebuilt["package"]["package_id"], {
            "purpose": old["purpose"], "audience": old["audience"], "sections": sections,
            "change_reason": "Late visual revision: " + need["purpose"],
            "created_by": {"type": "host_visual_revision", "visual_need_id": note["exhibit_id"], "source_composition_id": old["composition_id"], "source_composition_version": old["version"], "source_composition_digest": old["composition_digest"], "affected_section_ids": need["affected_section_ids"]},
        })
        return {"status": "RESUMABLE", "package": rebuilt["package"], "composition": created["composition"], "previous_package": binding, "previous_composition": origin, "affected_section_ids": need["affected_section_ids"], "next_work": "select the new Composition and import source-bound Writer revisions; reuse unchanged prose where its exact research scope remains valid", "research_state_mutation_performed": False, "manuscript_approval_performed": False, "release_approval_performed": False}
