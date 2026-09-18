from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping
from xml.sax.saxutils import escape
import zipfile

from .facade import LocalApplicationError

SCHEMA_VERSION = "0.1.0"
SERVICE_VERSION = "0.1.0"
MAX_SECTIONS = 128
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_XREF = re.compile(r"\[\[(section|exhibit|citation):([^\]]+)\]\]")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest(value: Mapping[str, Any], field: str) -> str:
    copy = deepcopy(dict(value))
    copy.pop(field, None)
    return _sha(_json_bytes(copy))


def _safe(value: str) -> str:
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in value):
        raise LocalApplicationError("APPLICATION-PUBLICATION-INPUT-001", "publication identifier contains unsupported characters")
    return value


def _zip_member(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o600 << 16
    info.create_system = 3
    return info, data


def _docx_bytes(lines: list[tuple[str, str]]) -> bytes:
    paragraphs = []
    for role, text in lines:
        text = text.replace("\r", "").strip("\n")
        if not text:
            paragraphs.append("<w:p/>")
            continue
        style = ""
        if role == "title":
            style = '<w:pPr><w:pStyle w:val="Title"/></w:pPr>'
        elif role == "heading":
            style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        elif role == "heading2":
            style = '<w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
        paragraphs.append(f'<w:p>{style}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + "".join(paragraphs) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
    ).encode("utf-8")
    styles = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/></w:style></w:styles>'''
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'''
    rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    doc_rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    import io
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("word/document.xml", document),
            ("word/_rels/document.xml.rels", doc_rels),
            ("word/styles.xml", styles),
        ):
            info, payload = _zip_member(name, data)
            archive.writestr(info, payload)
    return output.getvalue()


class PublicationReleaseService:
    def __init__(self, facade) -> None:
        if facade._workspace_root is None:
            raise LocalApplicationError("APPLICATION-PUBLICATION-WORKSPACE-001", "Publication requires a local workspace")
        self.facade = facade
        self.workspace = Path(facade._workspace_root)
        self.root = self.workspace / ".research-loom" / "publication"

    def _profile_pin(self, package: Mapping[str, Any]) -> Mapping[str, Any]:
        pins = package.get("effective_profile_set", {}).get("profile_pins", [])
        rows = [row for row in pins if isinstance(row, Mapping) and row.get("profile_type") == "publication"]
        if len(rows) != 1:
            raise LocalApplicationError("APPLICATION-PUBLICATION-PROFILE-001", "exactly one pinned Publication Profile is required")
        row = rows[0]
        digest = str(row.get("content_digest") or row.get("manifest_sha256") or "")
        if digest and not digest.startswith("sha256:"):
            digest = "sha256:" + digest
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise LocalApplicationError("APPLICATION-PUBLICATION-PROFILE-001", "Publication Profile digest is invalid")
        return {"profile_id": str(row["profile_id"]), "profile_version": str(row["profile_version"]), "content_digest": digest}

    @staticmethod
    def _source_index(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        objects = package.get("resolved_content", {}).get("research_objects", [])
        return {str(row["id"]): row for row in objects if isinstance(row, Mapping) and row.get("kind") == "source" and isinstance(row.get("id"), str)}

    @staticmethod
    def _exhibit_index(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        rows = package.get("resolved_content", {}).get("working_material", {}).get("research_exhibits", [])
        return {str(row["exhibit_id"]): row for row in rows if isinstance(row, Mapping) and isinstance(row.get("exhibit_id"), str)}

    @staticmethod
    def _citation_label(source: Mapping[str, Any], locator: str | None) -> str:
        title = str(source.get("title") or source.get("name") or source.get("id") or "Source")
        canonical = str(source.get("canonical_locator") or "")
        bits = [title]
        if canonical:
            bits.append(canonical)
        if locator and locator != canonical:
            bits.append(str(locator))
        return " — ".join(bits)

    def _render(self, inspection: Mapping[str, Any]) -> tuple[bytes, bytes, list[dict[str, Any]], dict[str, Any]]:
        package = inspection["source_package_document"]
        revision = inspection["revision"]
        composition = inspection["composition"]
        if len(revision.get("sections", [])) > MAX_SECTIONS:
            raise LocalApplicationError("APPLICATION-PUBLICATION-BOUND-001", "manuscript section count exceeds Publication bound")
        heading_by_section = {}
        for row in composition.get("sections", []):
            if not isinstance(row, Mapping):
                continue
            heading = row.get("heading") or row.get("generated_heading") or row.get("title") or row.get("section_id")
            if isinstance(heading, Mapping):
                heading = heading.get("text")
            heading_by_section[str(row.get("section_id"))] = str(heading or row.get("section_id"))

        sources = self._source_index(package)
        exhibits = self._exhibit_index(package)
        exhibit_numbers: dict[str, tuple[str, int]] = {}
        citation_numbers: dict[str, int] = {}
        issues: list[dict[str, Any]] = []
        known_sections = set(heading_by_section)

        for section in revision.get("sections", []):
            for citation in section.get("citations", []):
                source_ref = str(citation.get("source_ref", ""))
                if source_ref not in sources:
                    issues.append({"code": "UNRESOLVED_CITATION", "ref": source_ref, "section_id": section["section_id"], "blocking": True})
                elif source_ref not in citation_numbers:
                    citation_numbers[source_ref] = len(citation_numbers) + 1
            for exhibit_ref in section.get("exhibit_refs", []):
                exhibit_ref = str(exhibit_ref)
                exhibit = exhibits.get(exhibit_ref)
                if exhibit is None:
                    issues.append({"code": "MISSING_EXHIBIT", "ref": exhibit_ref, "section_id": section["section_id"], "blocking": True})
                elif exhibit_ref not in exhibit_numbers:
                    kind = "Table" if str(exhibit.get("kind")) in {"table", "matrix"} else "Figure"
                    count = 1 + sum(1 for label, _ in exhibit_numbers.values() if label == kind)
                    exhibit_numbers[exhibit_ref] = (kind, count)

        def replace_token(match: re.Match[str], section_id: str) -> str:
            kind, ref = match.group(1), match.group(2)
            if kind == "section":
                if ref not in known_sections:
                    issues.append({"code": "UNRESOLVED_CROSS_REFERENCE", "ref": ref, "section_id": section_id, "blocking": True})
                    return f"[unresolved section:{ref}]"
                return f'Section “{heading_by_section[ref]}”'
            if kind == "citation":
                if ref not in citation_numbers:
                    issues.append({"code": "UNRESOLVED_CITATION", "ref": ref, "section_id": section_id, "blocking": True})
                    return f"[unresolved citation:{ref}]"
                return f"[{citation_numbers[ref]}]"
            if ref not in exhibit_numbers:
                issues.append({"code": "UNRESOLVED_CROSS_REFERENCE", "ref": ref, "section_id": section_id, "blocking": True})
                return f"[unresolved exhibit:{ref}]"
            label, number = exhibit_numbers[ref]
            return f"{label} {number}"

        title = str(package.get("project", {}).get("title") or "Publication")
        md: list[str] = [f"# {title}", ""]
        docx_lines: list[tuple[str, str]] = [("title", title)]
        rendered_exhibits: set[str] = set()
        for section in revision.get("sections", []):
            sid = str(section["section_id"])
            heading = heading_by_section.get(sid, sid)
            content = str(section.get("content", ""))
            content = _XREF.sub(lambda match: replace_token(match, sid), content)
            md.extend([f"## {heading}", "", content, ""])
            docx_lines.extend([("heading", heading), ("body", content)])
            structured_citations = []
            for citation in section.get("citations", []):
                source_ref = str(citation.get("source_ref", ""))
                number = citation_numbers.get(source_ref)
                if number is not None:
                    structured_citations.append(f"[{number}]")
            if structured_citations:
                marker = "Citations: " + ", ".join(dict.fromkeys(structured_citations))
                md.extend([marker, ""])
                docx_lines.append(("body", marker))
            for ref_value in section.get("exhibit_refs", []):
                ref = str(ref_value)
                if ref in rendered_exhibits or ref not in exhibit_numbers or ref not in exhibits:
                    continue
                rendered_exhibits.add(ref)
                exhibit = exhibits[ref]
                label, number = exhibit_numbers[ref]
                caption = f"{label} {number}. {exhibit.get('title') or ref}"
                content_obj = exhibit.get("content", {})
                exhibit_text = content_obj.get("value", "") if isinstance(content_obj, Mapping) else str(content_obj)
                if not isinstance(exhibit_text, str):
                    exhibit_text = json.dumps(exhibit_text, ensure_ascii=False, sort_keys=True)
                md.extend([f"**{caption}**", "", exhibit_text, ""])
                docx_lines.extend([("heading2", caption), ("body", exhibit_text)])

        if citation_numbers:
            md.extend(["## References", ""])
            docx_lines.append(("heading", "References"))
            for source_ref, number in sorted(citation_numbers.items(), key=lambda item: item[1]):
                source = sources[source_ref]
                locators = []
                for section in revision.get("sections", []):
                    for citation in section.get("citations", []):
                        if str(citation.get("source_ref", "")) == source_ref and citation.get("locator_ref"):
                            locators.append(str(citation["locator_ref"]))
                rendered = self._citation_label(source, locators[0] if locators else None)
                entry = f"[{number}] {rendered}"
                md.append(entry)
                docx_lines.append(("body", entry))
            md.append("")

        feedback = revision.get("writing_feedback", {}).get("issues", [])
        if feedback:
            issues.append({"code": "WRITING_FEEDBACK_OPEN", "ref": str(len(feedback)), "section_id": None, "blocking": False})

        markdown = ("\n".join(md).rstrip() + "\n").encode("utf-8")
        docx = _docx_bytes(docx_lines)
        if len(markdown) + len(docx) > MAX_OUTPUT_BYTES:
            raise LocalApplicationError("APPLICATION-PUBLICATION-BOUND-001", "Publication outputs exceed supported aggregate size")
        checks = {
            "citation_resolution": "failed" if any(x["code"] == "UNRESOLVED_CITATION" for x in issues) else "passed",
            "exhibit_resolution": "failed" if any(x["code"] == "MISSING_EXHIBIT" for x in issues) else "passed",
            "cross_reference_resolution": "failed" if any(x["code"] == "UNRESOLVED_CROSS_REFERENCE" for x in issues) else "passed",
            "render_verification": "passed" if docx.startswith(b"PK") and markdown else "failed",
            "writing_feedback": "warning" if feedback else "passed",
        }
        return markdown, docx, issues, checks

    def _build_path(self, build_id: str) -> Path:
        return self.root / "builds" / _safe(build_id)

    def build_preview(self, composition_id: str, revision_id: str | None = None) -> Mapping[str, Any]:
        inspection = self.facade.inspect_writer_round_trip(composition_id, revision_id)
        # Preserve the complete pinned package document for Publication; inspect's compact source projection is not enough.
        receipt = inspection["writer_input"]
        package = self.facade._writer_composition_service()._package(str(receipt["source"]["research_package_id"]))
        inspection = deepcopy(dict(inspection))
        inspection["source_package_document"] = package
        profile = self._profile_pin(package)
        revision = inspection["revision"]
        build_key = {
            "manuscript_revision_id": revision["revision_id"],
            "manuscript_revision_digest": revision["revision_digest"],
            "research_package_id": package["package_id"],
            "research_package_digest": package["package_digest"],
            "publication_profile": profile,
            "renderer": {"renderer_id": "research-loom.deterministic-docx", "renderer_version": SERVICE_VERSION},
        }
        key_digest = _sha(_json_bytes(build_key))
        build_id = "PUB-" + key_digest.split(":", 1)[1][:24]
        target = self._build_path(build_id)
        manifest_path = target / "preview-manifest.json"
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("build_key_digest") != key_digest:
                raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Publication build identity conflicts with stored content")
            for output in existing.get("outputs", []):
                path = target / output["relative_path"]
                if not path.is_file() or _sha(path.read_bytes()) != output["digest"]:
                    raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "stored Publication output no longer matches its manifest")
            return {"status": "VERIFIED_REUSE", "build": existing, "research_state_mutation_performed": False}

        markdown, docx, issues, checks = self._render(inspection)
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "publication_preview_build",
            "build_id": build_id,
            "build_key_digest": key_digest,
            "source_manuscript": {"composition_id": composition_id, "revision_id": revision["revision_id"], "revision_digest": revision["revision_digest"]},
            "research_provenance": {"research_package_id": package["package_id"], "research_package_digest": package["package_digest"], "research_snapshot": deepcopy(package["source_research_snapshot"])},
            "publication_profile": profile,
            "renderer": {"renderer_id": "research-loom.deterministic-docx", "renderer_version": SERVICE_VERSION, "equivalence": "byte-identical for identical pinned inputs"},
            "outputs": [
                {"format": "markdown", "relative_path": "preview.md", "media_type": "text/markdown", "size": len(markdown), "digest": _sha(markdown)},
                {"format": "docx", "relative_path": "formal.docx", "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": len(docx), "digest": _sha(docx)},
            ],
            "verification": checks,
            "issues": issues,
            "preview_only": True,
            "release_recorded": False,
            "research_state_mutation_performed": False,
            "content_digest": "",
        }
        manifest["content_digest"] = _digest(manifest, "content_digest")
        self.root.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{build_id}.", dir=target.parent))
        try:
            (staging / "preview.md").write_bytes(markdown)
            (staging / "formal.docx").write_bytes(docx)
            (staging / "preview-manifest.json").write_bytes(_json_bytes(manifest))
            os.rename(staging, target)
        except OSError as exc:
            raise LocalApplicationError("APPLICATION-PUBLICATION-WRITE-001", "Publication preview could not be persisted") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return {"status": "BUILT", "build": manifest, "research_state_mutation_performed": False}

    def show_preview(self, build_id: str) -> Mapping[str, Any]:
        path = self._build_path(build_id) / "preview-manifest.json"
        if not path.is_file():
            raise LocalApplicationError("APPLICATION-PUBLICATION-404", "Publication preview build does not exist")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("content_digest") != _digest(value, "content_digest"):
            raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Publication preview manifest digest does not verify")
        preview_path = self._build_path(build_id) / "preview.md"
        if not preview_path.is_file():
            raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Publication Markdown preview is missing")
        return {
            "status": "OK",
            "build": value,
            "preview_markdown": preview_path.read_text(encoding="utf-8"),
            "output_root": str(self._build_path(build_id)),
            "research_state_mutation_performed": False,
        }

    def release(self, build_id: str, decision: Mapping[str, Any]) -> Mapping[str, Any]:
        shown = self.show_preview(build_id)["build"]
        if any(value == "failed" for key, value in shown["verification"].items() if key != "writing_feedback"):
            raise LocalApplicationError("APPLICATION-PUBLICATION-RELEASE-CHECK-001", "Publication release checks have not passed")
        required = {"decision_id", "actor_id", "disposition", "build_id", "build_digest"}
        if set(decision) != required or decision.get("disposition") != "approve_release" or decision.get("build_id") != build_id or decision.get("build_digest") != shown["content_digest"]:
            raise LocalApplicationError("APPLICATION-PUBLICATION-RELEASE-DECISION-001", "exact human release approval for this preview build is required")
        decision_id = str(decision["decision_id"])
        actor_id = str(decision["actor_id"])
        if not decision_id or not actor_id:
            raise LocalApplicationError("APPLICATION-PUBLICATION-RELEASE-DECISION-001", "human release decision identity is required")
        source = self._build_path(build_id) / "formal.docx"
        payload = source.read_bytes()
        release_id = "REL-" + hashlib.sha256((build_id + shown["content_digest"] + decision_id).encode("utf-8")).hexdigest()[:24]
        target = self.root / "releases" / release_id
        manifest_path = target / "release-manifest.json"
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("human_release_decision") != dict(decision) or existing.get("output", {}).get("digest") != _sha(payload):
                raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Release identity conflicts with stored release")
            return {"status": "VERIFIED_REUSE", "release": existing, "research_state_mutation_performed": False}
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "release_manifest",
            "release_id": release_id,
            "source_preview": {"build_id": build_id, "build_digest": shown["content_digest"]},
            "source_manuscript": deepcopy(shown["source_manuscript"]),
            "research_provenance": deepcopy(shown["research_provenance"]),
            "publication_profile": deepcopy(shown["publication_profile"]),
            "output": {"relative_path": "artifact.docx", "artifact_reference": f"publication/releases/{release_id}/artifact.docx", "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": len(payload), "digest": _sha(payload)},
            "verification": deepcopy(shown["verification"]),
            "human_release_decision": deepcopy(dict(decision)),
            "research_state_mutation_performed": False,
            "content_digest": "",
        }
        manifest["content_digest"] = _digest(manifest, "content_digest")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{release_id}.", dir=target.parent))
        try:
            (staging / "artifact.docx").write_bytes(payload)
            (staging / "release-manifest.json").write_bytes(_json_bytes(manifest))
            os.rename(staging, target)
        except OSError as exc:
            raise LocalApplicationError("APPLICATION-PUBLICATION-WRITE-001", "Publication release could not be persisted") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return {"status": "RELEASED", "release": manifest, "research_state_mutation_performed": False}
