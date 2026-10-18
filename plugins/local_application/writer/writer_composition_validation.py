"""Source pin, graph and section validation for writer compositions (#494)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.runtime import canonical_digest
from plugins.application_errors import LocalApplicationError

from .writer_composition_support import (
    MAX_SECTION_REFS,
    MAX_SECTIONS,
    _citation_inventory,
    _digest_document,
    _known_locators_for_source,
    _linked_ids,
    _object_index,
    _object_is_authoritative,
    _package_epistemic,
    _package_ref_sets,
    _profile_constraint_map,
    _require_string,
    _source_exhibit_inventory,
    _strings,
)


class WriterCompositionValidationMixin:
    def _source_pin(
        self, package: Mapping[str, Any], *, lineage_ref: str | None = None
    ) -> dict[str, Any]:
        snapshot = package["source_research_snapshot"]
        package_lineage = snapshot.get("lineage_ref")
        if isinstance(package_lineage, str) and package_lineage:
            lineage_ref = package_lineage
        elif lineage_ref is None:
            lineage_ref = str(
                self.facade._application.state_repository.load_active_lineage_ref(
                    self.facade._project_id
                )
            )
        return {
            "research_package_id": package["package_id"],
            "research_package_digest": package["package_digest"],
            "project_id": package["project"]["project_id"],
            "lineage_ref": lineage_ref,
            "research_snapshot_id": snapshot["snapshot_id"],
            "research_snapshot_digest": snapshot["content_digest"],
            "effective_profile_set_ref": package["effective_profile_set"][
                "effective_profile_set_ref"
            ],
            "effective_profile_set_digest": package["effective_profile_set"]["content_digest"],
            **_package_epistemic(package),
        }

    def _validate_source_pin(self, pin: Mapping[str, Any], package: Mapping[str, Any]) -> None:
        lineage_ref = pin.get("lineage_ref")
        if not isinstance(lineage_ref, str) or not lineage_ref:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PIN-001",
                "composition source lineage pin is missing",
            )
        if dict(pin) != self._source_pin(package, lineage_ref=lineage_ref):
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PIN-001",
                "composition source pin does not match the immutable Research Package",
            )
        try:
            state = self.facade._application.state_repository.load_state_view(
                str(pin["project_id"]), lineage_ref
            )
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PIN-001",
                "composition source lineage does not resolve",
            ) from exc
        current = state.current_snapshot
        seen = set()
        found = False
        while current is not None:
            sid = str(current.get("id"))
            if sid in seen:
                break
            seen.add(sid)
            if sid == pin.get("research_snapshot_id"):
                found = str(current.get("content_digest")) == pin.get("research_snapshot_digest")
                break
            prior = current.get("prior_snapshot_id")
            if not isinstance(prior, str) or not prior:
                break
            current = self.facade._application.state_repository.load_snapshot(prior)
        if not found:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-PIN-001",
                "composition source Snapshot is not in the pinned Research Lineage",
            )

    def _narrative_defs(
        self, package: Mapping[str, Any]
    ) -> tuple[
        dict[str, Mapping[str, Any]],
        dict[str, Mapping[str, Any]],
        list[Mapping[str, Any]],
        set[str],
    ]:
        constraints = _profile_constraint_map(package)
        stages = {
            str(x["id"]): x
            for x in constraints.get("narrative.stages.definitions", [])
            if isinstance(x, Mapping) and x.get("id")
        }
        purposes = {
            str(x["id"]): x
            for x in constraints.get("narrative.section_purposes.definitions", [])
            if isinstance(x, Mapping) and x.get("id")
        }
        edges = [
            x
            for x in constraints.get("narrative.dependencies.required", [])
            if isinstance(x, Mapping)
        ]
        preservation = set(map(str, constraints.get("narrative.preservation.required_content", [])))
        return stages, purposes, edges, preservation

    def _validate_graph(
        self, stages: Mapping[str, Mapping[str, Any]], edges: list[Mapping[str, Any]]
    ) -> None:
        graph = {key: set() for key in stages}
        for edge in edges:
            a, b = str(edge.get("from_stage")), str(edge.get("to_stage"))
            if a not in graph or b not in graph:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                    "Narrative dependency references an unknown stage",
                )
            graph[a].add(b)
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                    "Narrative dependency cycle detected",
                )
            if node in done:
                return
            visiting.add(node)
            for nxt in graph[node]:
                visit(nxt)
            visiting.remove(node)
            done.add(node)

        for node in graph:
            visit(node)

    def _validate_sections(
        self, sections: Any, package: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(sections, list) or not sections or len(sections) > MAX_SECTIONS:
            raise LocalApplicationError(
                "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                "sections must be a bounded non-empty array",
            )
        refs = _package_ref_sets(package)
        objects = _object_index(package)
        stages, purposes, edges, preservation = self._narrative_defs(package)
        self._validate_graph(stages, edges)
        seen: set[str] = set()
        normalized = []
        diagnostics = []
        for index, raw in enumerate(sections):
            if not isinstance(raw, Mapping):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-INPUT-001", "each section must be an object"
                )
            sid = _require_string(raw.get("section_id"), f"sections[{index}].section_id")
            if sid in seen:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-INPUT-001", f"duplicate section_id: {sid}"
                )
            seen.add(sid)
            stage_refs = _strings(raw.get("narrative_stage_refs"), f"{sid}.narrative_stage_refs")
            purpose_refs = _strings(
                raw.get("semantic_purpose_refs"), f"{sid}.semantic_purpose_refs"
            )
            if not stage_refs:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                    f"section {sid} has no Narrative stage",
                )
            unknown = [x for x in stage_refs if x not in stages]
            if unknown:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                    f"section {sid} references unknown Narrative stages: {', '.join(unknown)}",
                )
            unknown_p = [x for x in purpose_refs if x not in purposes]
            if unknown_p:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                    f"section {sid} references unknown purposes: {', '.join(unknown_p)}",
                )
            for purpose_id in purpose_refs:
                allowed = set(map(str, purposes[purpose_id].get("stage_ids", [])))
                if allowed and not allowed.intersection(stage_refs):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                        f"section {sid} purpose {purpose_id} is not placed in an allowed stage",
                    )
            section: dict[str, Any] = {
                "section_id": sid,
                "parent_section_id": raw.get("parent_section_id"),
                "order": int(raw.get("order", index + 1)),
                "heading": _require_string(raw.get("heading"), f"{sid}.heading"),
                "reader_question": _require_string(
                    raw.get("reader_question"), f"{sid}.reader_question"
                ),
                "purpose": _require_string(raw.get("purpose"), f"{sid}.purpose"),
                "narrative_stage_refs": stage_refs,
                "semantic_purpose_refs": purpose_refs,
                "messages": [str(x) for x in raw.get("messages", []) if isinstance(x, str) and x],
                "opening_intent": str(raw.get("opening_intent") or "TBD"),
                "closing_intent": str(raw.get("closing_intent") or "TBD"),
                "previous_section_id": raw.get("previous_section_id"),
                "next_section_id": raw.get("next_section_id"),
                "length_hint": raw.get("length_hint"),
                "prohibited_claims": [
                    str(x) for x in raw.get("prohibited_claims", []) if isinstance(x, str) and x
                ],
                "unresolved_items": [
                    str(x) for x in raw.get("unresolved_items", []) if isinstance(x, str) and x
                ],
                "detailed": bool(raw.get("detailed", True)),
            }
            for field in refs:
                section[field] = _strings(raw.get(field), f"{sid}.{field}")
                missing = sorted(set(section[field]) - refs[field])
                if missing:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} references material not supplied by the Research Package: {', '.join(missing)}",
                    )
            citations = raw.get("citation_requirements", [])
            if not isinstance(citations, list) or len(citations) > MAX_SECTION_REFS:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                    f"{sid}.citation_requirements must be bounded",
                )
            section["citation_requirements"] = []
            for citation in citations:
                if not isinstance(citation, Mapping):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                        f"{sid}.citation_requirements entries must be objects",
                    )
                source_id = _require_string(citation.get("source_ref"), "source_ref")
                if source_id not in refs["source_refs"]:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} citation references an unavailable Source: {source_id}",
                    )
                locator = citation.get("locator_ref")
                if locator is not None and (
                    not isinstance(locator, str)
                    or locator not in _known_locators_for_source(package, source_id)
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} citation references an unavailable locator for Source {source_id}: {locator}",
                    )
                section["citation_requirements"].append(
                    {"source_ref": source_id, "locator_ref": locator}
                )
            citation_bindings = raw.get("citation_bindings", [])
            if not isinstance(citation_bindings, list) or len(citation_bindings) > MAX_SECTION_REFS:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                    f"{sid}.citation_bindings must be bounded",
                )
            section["citation_bindings"] = []
            inventory = _citation_inventory(package)
            for binding in citation_bindings:
                if not isinstance(binding, Mapping) or set(binding) != {
                    "argument_id",
                    "evidence_id",
                    "citation_role",
                    "status",
                }:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                        f"{sid}.citation_bindings entry is invalid",
                    )
                evidence_id = _require_string(binding.get("evidence_id"), "evidence_id")
                argument_id = _require_string(binding.get("argument_id"), "argument_id")
                role = str(binding.get("citation_role", ""))
                if (
                    role
                    not in {"primary_support", "corroboration", "background", "counterevidence"}
                    or binding.get("status") != "selected"
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                        f"{sid}.citation_bindings role/status is invalid",
                    )
                if (
                    evidence_id not in refs["evidence_refs"]
                    or argument_id not in refs["argument_refs"]
                    or evidence_id not in inventory
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} citation binding is outside the Research Package selection",
                    )
                for field, object_id in (
                    ("argument_refs", argument_id),
                    ("evidence_refs", evidence_id),
                ):
                    if object_id not in section[field]:
                        section[field].append(object_id)
                argument_obj = objects.get(argument_id, {})
                row = inventory[evidence_id]
                if role != "background" and evidence_id not in set(
                    map(str, argument_obj.get("evidence_ids", []))
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} citation binding does not connect the Argument to Evidence",
                    )
                evidence_kind = str(row.get("evidence_role", ""))
                if role == "counterevidence" and evidence_kind != "counterevidence":
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} counterevidence citation role conflicts with Evidence meaning",
                    )
                if (
                    role in {"primary_support", "corroboration"}
                    and evidence_kind == "counterevidence"
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} supporting citation role conflicts with counterevidence",
                    )
                source_id = str(row["source_id"])
                locator = row.get("locator")
                requirement = {"source_ref": source_id, "locator_ref": locator}
                if requirement not in section["citation_requirements"]:
                    section["citation_requirements"].append(requirement)
                section["citation_bindings"].append(
                    {
                        "argument_id": argument_id,
                        "evidence_id": evidence_id,
                        "citation_role": role,
                        "status": "selected",
                    }
                )
            exhibit_bindings = raw.get("exhibit_bindings", [])
            if not isinstance(exhibit_bindings, list) or len(exhibit_bindings) > MAX_SECTION_REFS:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                    f"{sid}.exhibit_bindings must be bounded",
                )
            section["exhibit_bindings"] = []
            source_exhibits = _source_exhibit_inventory(package)
            for binding in exhibit_bindings:
                if not isinstance(binding, Mapping) or set(binding) != {
                    "exhibit_id",
                    "use_mode",
                    "status",
                }:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                        f"{sid}.exhibit_bindings entry is invalid",
                    )
                exhibit_id = _require_string(binding.get("exhibit_id"), "exhibit_id")
                use_mode = str(binding.get("use_mode", ""))
                if (
                    use_mode not in {"reproduce", "adapt", "derive"}
                    or binding.get("status") != "selected"
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-INPUT-001",
                        f"{sid}.exhibit_bindings use_mode/status is invalid",
                    )
                if exhibit_id not in section["exhibit_refs"] or exhibit_id not in source_exhibits:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {sid} source Exhibit binding is outside the selected source exhibit inventory",
                    )
                section["exhibit_bindings"].append(
                    {"exhibit_id": exhibit_id, "use_mode": use_mode, "status": "selected"}
                )
            required_kinds = set()
            for stage_id in stage_refs:
                required_kinds.update(map(str, stages[stage_id].get("requires", [])))
            refs_by_kind = {
                "argument": section["argument_refs"],
                "finding": section["finding_refs"],
                "evidence": section["evidence_refs"],
                "source": section["source_refs"],
                "counter_review": section["counter_review_refs"],
                "contribution": section["contribution_refs"],
                "recommendation": section["recommendation_refs"],
                "research_question": list(
                    package.get("content", {}).get("research_question_refs", [])
                ),
            }
            available_by_kind = {
                kind: any(
                    (objects.get(ref_id) is not None and _object_is_authoritative(objects[ref_id]))
                    for ref_id in ref_ids
                )
                for kind, ref_ids in refs_by_kind.items()
            }
            unmet = sorted(
                kind for kind in required_kinds if not available_by_kind.get(kind, False)
            )
            if unmet:
                diagnostics.append(
                    {
                        "section_id": sid,
                        "code": "WRITER-COMPOSITION-NARRATIVE-UNMET",
                        "unmet_requires": unmet,
                    }
                )
            # Preservation is claim-local when target links are available; otherwise package-wide adverse content is conservative.
            affected = set(
                section["finding_refs"]
                + section["argument_refs"]
                + section["contribution_refs"]
                + section["recommendation_refs"]
            )
            for field, vocabulary in (
                ("counter_review_refs", "counter_findings"),
                ("qualifier_refs", "qualifiers"),
                ("limitation_refs", "limitations"),
            ):
                if vocabulary not in preservation:
                    continue
                required = set()
                for object_id in refs[field]:
                    obj = objects.get(object_id)
                    links = _linked_ids(obj) if obj else set()
                    if not links or links.intersection(affected):
                        required.add(object_id)
                missing = sorted(required - set(section[field]))
                if missing and affected:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-PRESERVATION-001",
                        f"section {sid} drops required {field}: {', '.join(missing)}",
                    )
            exhibits_by_id = {
                str(x.get("exhibit_id")): x
                for x in package.get("resolved_content", {})
                .get("working_material", {})
                .get("research_exhibits", [])
                if isinstance(x, Mapping) and isinstance(x.get("exhibit_id"), str)
            }
            gaps_by_id = {
                str(x.get("gap_id")): x
                for x in package.get("resolved_content", {}).get("unresolved_gaps", [])
                if isinstance(x, Mapping) and isinstance(x.get("gap_id"), str)
            }
            section["exhibit_pins"] = [
                {
                    "exhibit_id": exhibit_id,
                    "content_digest": str(exhibits_by_id[exhibit_id]["content_digest"]),
                }
                for exhibit_id in section["exhibit_refs"]
            ]
            section["gap_pins"] = [
                {"gap_id": gap_id, "content_digest": canonical_digest(gaps_by_id[gap_id])}
                for gap_id in section["gap_refs"]
            ]
            section["section_digest"] = _digest_document(section, "section_digest")
            normalized.append(section)
        # Parent/bridge refs must resolve inside the proposal.
        for section in normalized:
            for field in ("parent_section_id", "previous_section_id", "next_section_id"):
                target = section.get(field)
                if target is not None and target not in seen:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-REFERENCE-001",
                        f"section {section['section_id']} has unknown {field}: {target}",
                    )
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
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001",
                            f"Narrative dependency order is violated: {a} -> {b}",
                        )
        return normalized, diagnostics
