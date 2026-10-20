"""Rendering a Publication preview from inspected inputs (#494)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import urldefrag

from plugins.application_errors import LocalApplicationError

from .publication_docx import docx_bytes as _docx_bytes
from .publication_docx import verify_native_docx
from .publication_exhibits import prepare_exhibits
from .publication_release_support import (
    _XREF,
    MAX_OUTPUT_BYTES,
    _editorial_status,
    _verify_docx_bytes,
)


class PublicationRenderMixin:
    @staticmethod
    def _source_index(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        objects = package.get("resolved_content", {}).get("research_objects", [])
        return {
            str(row["id"]): row
            for row in objects
            if isinstance(row, Mapping)
            and row.get("kind") == "source"
            and isinstance(row.get("id"), str)
        }

    @staticmethod
    def _exhibit_index(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        rows = (
            package.get("resolved_content", {})
            .get("working_material", {})
            .get("research_exhibits", [])
        )
        return {
            str(row["exhibit_id"]): row
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("exhibit_id"), str)
        }

    @staticmethod
    def _citation_label(
        source: Mapping[str, Any], locator: str | None, policy: Mapping[str, Any]
    ) -> str:
        title = str(source.get("title") or source.get("name") or source.get("id") or "Source")
        canonical = str(source.get("canonical_locator") or "")
        if policy.get("document_mode") == "formal_report":
            exceptions = source.get("bibliography_exceptions", {})
            fields = ["author", "title", "publisher", "publication_or_update_date"]
            missing = [
                key
                for key in fields
                if not str(source.get(key) or "").strip()
                and not (key != "title" and str(exceptions.get(key) or "").strip())
            ]
            if missing:
                raise LocalApplicationError(
                    "PUBLICATION-BIBLIOGRAPHY-MISSING",
                    str(source.get("id")) + ": " + ", ".join(missing),
                )
            bits = [str(source[key]) for key in fields if str(source.get(key) or "").strip()]
            if locator and locator != canonical:
                bits.append(str(locator))
            if canonical.startswith(("http://", "https://")) and canonical not in bits:
                bits.append(canonical)
            return "、".join(bits)
        # A fragment locator refines this URL; it is not a second source URL.
        if (
            locator
            and canonical.startswith(("http://", "https://"))
            and urldefrag(str(locator))[0] == urldefrag(canonical)[0]
        ):
            canonical = str(locator)
        url_profile = policy.get("url_display_profile")
        if canonical.startswith(("http://", "https://")) and isinstance(url_profile, Mapping):
            template = str(url_profile.get("template", ""))
            rendered = template.replace("{title}", title).replace("{url}", canonical)
            if "{" in rendered or "}" in rendered:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INPUT-001",
                    "URL display template contains unsupported placeholders",
                )
            bits = [rendered]
        else:
            bits = [title]
            if canonical:
                bits.append(canonical)
        if locator and locator != canonical:
            bits.append(str(locator))
        return " — ".join(bits)

    @staticmethod
    def _issue(code: str, ref: str, section_id: str | None, blocking: bool) -> dict[str, Any]:
        basis = f"{code}|{ref}|{section_id or ''}".encode()
        return {
            "defect_id": "PD-PUB-" + hashlib.sha256(basis).hexdigest()[:20],
            "code": code,
            "ref": ref,
            "section_id": section_id,
            "blocking": blocking,
        }

    def _render(
        self, inspection: Mapping[str, Any]
    ) -> tuple[bytes, bytes, list[dict[str, Any]], dict[str, str]]:
        policy = inspection.get("publication_policy", {})
        dialect = self._dialect(inspection.get("publication_profile", {}))
        package = inspection["source_package_document"]
        revision = inspection["revision"]
        composition = inspection["composition"]
        sections = list(revision.get("sections", []))
        known_sections = {str(row["section_id"]) for row in sections}
        report = policy.get("formal_report")
        formal_report = dialect.formal_report_requested(policy)
        formal_outline = {}
        if formal_report:
            formal_outline = dialect.formal_outline(
                report["structure"], [str(row["section_id"]) for row in sections]
            )
        heading_by_section: dict[str, str] = {}
        for row in composition.get("sections", []):
            if not isinstance(row, Mapping):
                continue
            section_id = str(row.get("section_id"))
            if section_id not in known_sections:
                continue
            heading = (
                row.get("heading") or row.get("generated_heading") or row.get("title") or section_id
            )
            if isinstance(heading, Mapping):
                heading = heading.get("text")
            heading_by_section[section_id] = str(heading or section_id)

        sources = self._source_index(package)
        exhibits = self._exhibit_index(package)
        exhibit_numbers: dict[str, tuple[str, int]] = {}
        citation_numbers: dict[str, int] = {}
        locators_by_source: dict[str, list[str]] = {}
        citation_refs_by_section: dict[str, list[str]] = {}
        citation_ref_sets_by_section: dict[str, set[str]] = {}
        locators_by_section_source: dict[tuple[str, str], list[str]] = {}
        issues: list[dict[str, Any]] = []
        issue_keys: set[tuple[str, str, str | None]] = set()

        def add_issue(code: str, ref: str, section_id: str | None, blocking: bool) -> None:
            key = (code, ref, section_id)
            if key not in issue_keys:
                issue_keys.add(key)
                issues.append(self._issue(code, ref, section_id, blocking))

        citation_inventory = {
            str(row.get("evidence_id")): row
            for row in package.get("inventories", {}).get("citation_inventory", [])
            if isinstance(row, Mapping) and isinstance(row.get("evidence_id"), str)
        }
        table_count = 0
        figure_count = 0
        for section in sections:
            section_id = str(section["section_id"])
            composition_section = next(
                (
                    row
                    for row in composition.get("sections", [])
                    if str(row.get("section_id")) == section_id
                ),
                {},
            )
            for binding in composition_section.get("citation_bindings", []):
                if not isinstance(binding, Mapping) or binding.get("status") != "selected":
                    continue
                evidence_id = str(binding.get("evidence_id", ""))
                row = citation_inventory.get(evidence_id)
                citation_present = row is not None and any(
                    isinstance(citation, Mapping)
                    and citation.get("source_ref") == row.get("source_id")
                    and citation.get("locator_ref") == row.get("locator")
                    for citation in section.get("citations", [])
                )
                if row is None or not row.get("citation_ready") or not citation_present:
                    add_issue("UNRESOLVED_CITATION", evidence_id, section_id, True)
            for citation in section.get("citations", []):
                source_ref = str(citation.get("source_ref", ""))
                if source_ref not in sources:
                    add_issue("UNRESOLVED_CITATION", source_ref, section_id, True)
                    continue
                if source_ref not in citation_numbers:
                    citation_numbers[source_ref] = len(citation_numbers) + 1
                section_refs = citation_refs_by_section.setdefault(section_id, [])
                section_ref_set = citation_ref_sets_by_section.setdefault(section_id, set())
                if source_ref not in section_ref_set:
                    section_ref_set.add(source_ref)
                    section_refs.append(source_ref)
                locator = citation.get("locator_ref")
                if locator:
                    bucket = locators_by_source.setdefault(source_ref, [])
                    locator_value = str(locator)
                    if locator_value not in bucket:
                        bucket.append(locator_value)
                    section_bucket = locators_by_section_source.setdefault(
                        (section_id, source_ref), []
                    )
                    if locator_value not in section_bucket:
                        section_bucket.append(locator_value)
            for exhibit_ref_value in section.get("exhibit_refs", []):
                exhibit_ref = str(exhibit_ref_value)
                exhibit = exhibits.get(exhibit_ref)
                if exhibit is None:
                    add_issue("MISSING_EXHIBIT", exhibit_ref, section_id, True)
                    continue
                if exhibit_ref in exhibit_numbers:
                    continue
                if str(exhibit.get("kind")) in {"table", "matrix"}:
                    table_count += 1
                    exhibit_numbers[exhibit_ref] = (dialect.table_label, table_count)
                else:
                    figure_count += 1
                    exhibit_numbers[exhibit_ref] = (dialect.figure_label, figure_count)
                if formal_report:
                    scope = formal_outline[section_id]
                    if not scope["section"]:
                        raise LocalApplicationError(
                            "PUBLICATION-FORMAL-STRUCTURE-001",
                            "Figure/table needs an explicit chapter and section scope",
                        )
                    label = exhibit_numbers[exhibit_ref][0]
                    previous = [
                        number
                        for previous_label, number in exhibit_numbers.values()
                        if previous_label == label
                        and str(number).startswith(f"{scope['chapter']}-{scope['section']}-")
                    ]
                    exhibit_numbers[exhibit_ref] = (
                        label,
                        f"{scope['chapter']}-{scope['section']}-{len(previous) + 1}",
                    )

        def replace_token(match: re.Match[str], section_id: str) -> str:
            kind, ref = match.group(1), match.group(2)
            if kind == "section":
                if ref not in known_sections:
                    add_issue("UNRESOLVED_CROSS_REFERENCE", ref, section_id, True)
                    return f"[unresolved section:{ref}]"
                return f"Section “{heading_by_section.get(ref, ref)}”"
            if kind == "citation":
                if ref not in sources:
                    add_issue("UNRESOLVED_CITATION", ref, section_id, True)
                    return f"[unresolved citation:{ref}]"
                if ref not in citation_numbers:
                    citation_numbers[ref] = len(citation_numbers) + 1
                if formal_report:
                    locators = locators_by_section_source.get((section_id, ref), [])
                    return (
                        "（"
                        + self._citation_label(
                            sources[ref], "；".join(locators) if locators else None, policy
                        )
                        + "）"
                    )
                return f"[{citation_numbers[ref]}]"
            if ref not in exhibit_numbers:
                add_issue("UNRESOLVED_CROSS_REFERENCE", ref, section_id, True)
                return f"[unresolved exhibit:{ref}]"
            label, number = exhibit_numbers[ref]
            return f"{label} {number}"

        def resolve_text(text: str, section_id: str) -> str:
            result = _XREF.sub(lambda match: replace_token(match, section_id), text)
            if "[[" in result:
                add_issue("UNRESOLVED_CROSS_REFERENCE", "malformed-token", section_id, True)
            return result

        blocks = inspection.get("exhibit_blocks")
        if blocks is None:
            blocks = prepare_exhibits(inspection, self.workspace, dialect=dialect)
        for diagnostic in inspection.get("visual_diagnostics", []):
            add_issue("VISUAL_ASSET_UNAVAILABLE", diagnostic["path"], None, True)
        title = resolve_text(
            str(package.get("project", {}).get("title") or "Publication"), "document"
        )
        md: list[str] = [f"# {title}", ""]
        docx_lines: list[tuple[str, Any]] = [("title", title)]
        rendered_exhibits: set[str] = set()
        formal = policy.get("formal_spec_profile")
        reference_placement = (
            str(formal.get("reference_list_placement"))
            if isinstance(formal, Mapping)
            else "end_of_document"
        )
        reference_heading = (
            str(formal.get("reference_list_heading") or "References")
            if isinstance(formal, Mapping)
            else "References"
        )

        def append_reference_list(
            section_id: str, source_refs: list[str], scope_ids: list[str] | None = None
        ) -> None:
            if not source_refs:
                return
            md.extend([f"### {reference_heading}", ""])
            docx_lines.append(("reference_heading", reference_heading))
            for source_ref in source_refs:
                number = citation_numbers[source_ref]
                source = sources[source_ref]
                locators = list(
                    dict.fromkeys(
                        locator
                        for sid in (scope_ids or [section_id])
                        for locator in locators_by_section_source.get((sid, source_ref), [])
                    )
                )
                rendered = self._citation_label(
                    source, None if formal_report else (locators[0] if locators else None), policy
                )
                if formal_report and locators:
                    rendered += " — " + "；".join(locators)
                entry = resolve_text(f"[{number}] {rendered}", section_id)
                md.append(entry)
                docx_lines.append(("reference", entry))
            md.append("")

        reference_scope_ids = []
        for section_index, section in enumerate(sections):
            sid = str(section["section_id"])
            reference_scope_ids.append(sid)
            heading = resolve_text(heading_by_section.get(sid, sid), sid)
            content = resolve_text(str(section.get("content", "")), sid)
            role = "heading"
            if formal_report:
                entry = formal_outline[sid]
                heading = entry["label"] + "　" + heading
                role = "heading" + str(entry["level"])
            md.extend([f"## {heading}", "", content, ""])
            docx_lines.append((role, heading))
            if formal_report and formal_outline[sid]["level"] in {1, 2}:
                docx_lines.append(("body", ""))
            for paragraph in re.split(r"\n\s*\n", content) if formal_report else [content]:
                docx_lines.append(("body", paragraph))
            inline_citations = {
                match.group(2)
                for match in _XREF.finditer(str(section.get("content", "")))
                if match.group(1) == "citation"
            }
            structured_citations = []
            for citation in section.get("citations", []):
                source_ref = str(citation.get("source_ref", ""))
                number = citation_numbers.get(source_ref)
                if number is not None and source_ref not in inline_citations:
                    if formal_report:
                        structured_citations.append(
                            self._citation_label(
                                sources[source_ref], citation.get("locator_ref"), policy
                            )
                        )
                    else:
                        structured_citations.append(f"[{number}]")
            if structured_citations:
                marker = dialect.citations_prefix + ", ".join(dict.fromkeys(structured_citations))
                md.extend([marker, ""])
                docx_lines.append(("body", marker))
            for ref_value in section.get("exhibit_refs", []):
                ref = str(ref_value)
                if ref in rendered_exhibits or ref not in exhibit_numbers or ref not in exhibits:
                    continue
                rendered_exhibits.add(ref)
                exhibit = exhibits[ref]
                label, number = exhibit_numbers[ref]
                caption = resolve_text(
                    f"{label}{number}　{exhibit.get('title') or ref}"
                    if formal_report
                    else f"{label} {number}. {exhibit.get('title') or ref}",
                    sid,
                )
                block = {**deepcopy(blocks[ref]), "ref": ref, "caption": caption}
                if block["kind"] == "table":
                    block["rows"] = [
                        [resolve_text(cell, sid) for cell in row] for row in block["rows"]
                    ]
                    # Markdown remains a preview companion; DOCX has native cells.
                    preview_text = "\n".join("| " + " | ".join(row) + " |" for row in block["rows"])
                elif block["kind"] == "image":
                    if exhibit.get("generated_visual") is not None:
                        value = exhibit["content"]["value"]
                        exhibit["visual_semantics"]  # fail closed when semantics are missing
                        note = (
                            "Source: selected verified research data."
                            if "chart_spec" in value
                            else "Represented research: "
                            + "; ".join(value["request"]["allowed_labels"])
                            + "."
                        )
                        if "chart_spec" in value:
                            spec = value["chart_spec"]
                            note += "\n" + spec["caption"]
                            units = "; ".join(
                                k + "=" + (v if v is not None else "not applicable")
                                for k, v in spec["units"].items()
                            )
                            note += (
                                "\nUnits: "
                                + units
                                + "; denominator: "
                                + (spec["denominator"] or "not applicable")
                                + "; period: "
                                + (spec["period"] or "not applicable")
                                + "."
                            )
                            note = dialect.chart_note(note, spec, exhibit, block)
                        else:
                            note += "\nRepresentation reviewed against the selected research; no new research conclusion is established by this figure."
                            note = dialect.diagram_note(note, value)
                    else:
                        visual = exhibit["visual_target"]
                        locator = visual["locator"]
                        capture = block["provenance"]["source_capture"]
                        source = (
                            capture.get("source_locators")
                            or [capture.get("source_locator") or visual["capture_id"]]
                        )[0]
                        note = f"Source: {source}; {locator.get('label') or locator['kind']}"
                        if "page" in locator:
                            note += f"; page {locator['page']}"
                        if locator.get("region"):
                            region = locator["region"]
                            note += (
                                "; region "
                                + ", ".join(
                                    f"{key}={region[key]}" for key in ("x", "y", "width", "height")
                                )
                                + f" ({region['unit']})"
                            )
                        derived = visual.get("derived_artifact")
                        note += (
                            f"; retained {derived['derivation_type']}."
                            if derived
                            else "; original image."
                        )
                        content_obj = exhibit.get("content", {})
                        if content_obj.get("representation") in {"text", "markdown"}:
                            note += "\n" + str(content_obj.get("value", ""))
                    if block["provenance"].get("citation_sources") and not formal_report:
                        note += "\n" + "\n".join(
                            dialect.source_prefix
                            + self._citation_label(source, source.get("canonical_locator"), policy)
                            + "; "
                            + str(source.get("publisher_or_author") or "")
                            + "; "
                            + str(source.get("publication_or_update_date") or "")
                            for source in block["provenance"]["citation_sources"]
                        )
                    block["note"] = (
                        note
                        if exhibit.get("generated_visual") is not None
                        else resolve_text(note, sid)
                    )
                    preview_text = (
                        "[Exact retained image is embedded in formal.docx.]\n" + block["note"]
                    )
                    if "legend_rows" in block:
                        # Exact literals must not be parsed as manuscript reference tokens.
                        preview_text += "\n" + "\n".join(
                            "| " + " | ".join(row) + " |" for row in block["legend_rows"]
                        )
                else:
                    add_issue(block["code"], ref, sid, True)
                    preview_text = f"[UNAVAILABLE: {block['code']}. Preserve the source and supply a supported exact representation.]"
                if formal_report and block["kind"] in {"image", "table"}:
                    citation_sources = block["provenance"].get("citation_sources", [])
                    if citation_sources:
                        visual_locator = exhibit.get("visual_target", {}).get("locator", {})
                        page_locator = (
                            str(visual_locator["page"]) + "頁" if "page" in visual_locator else None
                        )
                        block["source_text"] = "（出典）" + "；".join(
                            self._citation_label(source, page_locator, policy)
                            for source in citation_sources
                        )
                    else:
                        add_issue("PUBLICATION_EXHIBIT_SOURCE_MISSING", ref, sid, True)
                        block["source_text"] = "（出典未確認）"
                    block["explanatory_note"] = block.pop("note", "")
                    if block["kind"] == "image" and exhibit.get("generated_visual") is None:
                        content_object = exhibit.get("content", {})
                        block["explanatory_note"] = (
                            str(content_object.get("value", ""))
                            if content_object.get("representation") in {"text", "markdown"}
                            else ""
                        )
                md.extend([f"**{caption}**", "", preview_text, ""])
                docx_lines.append(("exhibit", block))
            if reference_placement == "end_of_each_section":
                if formal_report:
                    current_scope = (formal_outline[sid]["chapter"], formal_outline[sid]["section"])
                    next_id = (
                        str(sections[section_index + 1]["section_id"])
                        if section_index + 1 < len(sections)
                        else None
                    )
                    next_scope = (
                        (formal_outline[next_id]["chapter"], formal_outline[next_id]["section"])
                        if next_id
                        else None
                    )
                    if current_scope != next_scope:
                        refs = list(
                            dict.fromkeys(
                                ref
                                for id_ in reference_scope_ids
                                for ref in citation_refs_by_section.get(id_, [])
                            )
                        )
                        append_reference_list(sid, refs, reference_scope_ids)
                        reference_scope_ids = []
                else:
                    append_reference_list(sid, citation_refs_by_section.get(sid, []))

        if citation_numbers and reference_placement == "end_of_document":
            md.extend([f"## {reference_heading}", ""])
            docx_lines.append(("reference_heading", reference_heading))
            for source_ref, number in sorted(citation_numbers.items(), key=lambda item: item[1]):
                source = sources[source_ref]
                locators = locators_by_source.get(source_ref, [])
                rendered = self._citation_label(source, locators[0] if locators else None, policy)
                entry = resolve_text(f"[{number}] {rendered}", "references")
                md.append(entry)
                docx_lines.append(("reference", entry))
            md.append("")

        feedback = revision.get("writing_feedback", {}).get("issues", [])
        if feedback:
            add_issue("WRITING_FEEDBACK_OPEN", str(len(feedback)), None, False)
        formal = policy.get("formal_spec_profile")
        if isinstance(formal, Mapping) and formal.get("reference_list_placement") not in {
            "end_of_document",
            "end_of_each_section",
        }:
            add_issue(
                "PUBLICATION_FORMAL_VALUE_UNSUPPORTED",
                str(formal.get("reference_list_placement")),
                None,
                True,
            )
        for missing in policy.get("missing_inputs", []):
            add_issue("PUBLICATION_FORMAL_INPUT_MISSING", str(missing), None, True)

        blocking_issues = [item for item in issues if item["blocking"]]
        if blocking_issues:
            md.extend(["## Publication diagnostics — release blocked", ""])
            docx_lines.append(("heading", "Publication diagnostics — release blocked"))
            for item in blocking_issues:
                message = f"{item['code']}: {item['ref']}. Restore exact bytes or create a supported new material/version; rebuild this preview."
                md.extend([message, ""])
                docx_lines.append(("body", message))
        layout_note = "Machine verification checks native structure, content, image bytes and references only. Inspect every rendered page before approving release; layout quality is not automatically verified."
        md.extend([layout_note, ""])
        if blocking_issues:
            docx_lines.append(("body", layout_note))
        markdown = ("\n".join(md).rstrip() + "\n").encode("utf-8")
        formal = policy.get("formal_spec_profile")
        layout = dict(formal.get("docx_layout", {})) if isinstance(formal, Mapping) else None
        if formal_report:
            layout["formal_document"] = True
        docx = _docx_bytes(docx_lines, layout)
        if len(markdown) + len(docx) > MAX_OUTPUT_BYTES:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-BOUND-001",
                "Publication outputs exceed the 16 MiB operation budget; "
                "split the report into separately bounded volumes and retry",
            )
        if not _verify_docx_bytes(docx) or not verify_native_docx(docx, docx_lines, layout):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RENDER-001",
                "generated DOCX failed native structure/content verification",
            )
        if formal_report:
            docx = dialect.assemble_formal_report(
                docx, dict(report), policy["research_group_type"], layout
            )
            failures = dialect.inspect_formal_report(
                docx, dict(report), policy["research_group_type"], layout
            )
            if failures:
                raise LocalApplicationError("PUBLICATION-FORMAL-RENDER-001", "; ".join(failures))
            if len(markdown) + len(docx) > MAX_OUTPUT_BYTES:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-BOUND-001",
                    "Formal report outputs exceed the 16 MiB operation budget; "
                    "split the report into separately bounded volumes and retry",
                )
        checks = {
            "citation_resolution": "failed"
            if any(item["code"] == "UNRESOLVED_CITATION" for item in issues)
            else "passed",
            "exhibit_resolution": "failed"
            if any(
                item["code"]
                in {"MISSING_EXHIBIT", "UNSUPPORTED_EXHIBIT", "VISUAL_ASSET_UNAVAILABLE"}
                for item in issues
            )
            else "passed",
            "cross_reference_resolution": "failed"
            if any(item["code"] == "UNRESOLVED_CROSS_REFERENCE" for item in issues)
            else "passed",
            "render_verification": "failed" if blocking_issues else "passed",
            "layout_verification": "warning",
            "writing_feedback": "warning" if feedback else "passed",
            "formal_specification": "failed"
            if policy.get("missing_inputs")
            or any(item["code"] == "PUBLICATION_FORMAL_VALUE_UNSUPPORTED" for item in issues)
            else "warning"
            if policy.get("coverage")
            else "passed",
            "editorial_qa": _editorial_status(
                policy.get("editorial_review"), overall_check=dialect.editorial_overall_check
            ),
        }
        return markdown, docx, issues, checks
