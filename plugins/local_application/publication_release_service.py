from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping
from xml.etree import ElementTree
from xml.sax.saxutils import escape
import zipfile

from jsonschema import Draft202012Validator, FormatChecker

from .facade import LocalApplicationError

SCHEMA_VERSION = "0.1.0"
SERVICE_VERSION = "0.1.0"
MAX_SECTIONS = 128
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_XREF = re.compile(r"\[\[(section|exhibit|citation):([^\]]+)\]\]")
_PREVIEW_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "packages"
    / "writer-publication"
    / "publication-preview.schema.json"
)


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest(value: Mapping[str, Any], field: str) -> str:
    copy = deepcopy(dict(value))
    copy.pop(field, None)
    return _sha(_canonical_bytes(copy))


def _safe(value: str) -> str:
    if not value or any(
        ch
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for ch in value
    ):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-INPUT-001",
            "publication identifier contains unsupported characters",
        )
    return value


def _artifact_pin(artifact_id: str, basis: bytes) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "version": SERVICE_VERSION,
        "content_digest": _sha(basis),
    }


_TEMPLATE_PIN = _artifact_pin(
    "research-loom.builtin-docx-template",
    b"research-loom deterministic docx template v0.1.0",
)
_STYLE_MAP_PIN = _artifact_pin(
    "research-loom.builtin-docx-style-map",
    b"Title=Title;heading=Heading1;heading2=Heading2;body=Normal;v0.1.0",
)
_RENDERER = {
    "renderer_id": "research-loom.deterministic-docx",
    "renderer_version": SERVICE_VERSION,
    "tool_digest": _sha(b"research-loom.deterministic-docx@0.1.0"),
}


def _validate_preview_manifest(value: Mapping[str, Any]) -> None:
    schema = json.loads(_PREVIEW_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(item) for item in first.absolute_path) or "<root>"
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-SCHEMA-001",
            f"canonical Publication preview manifest is invalid at {path}: {first.message}",
        )


def _xml_compatible(text: str) -> bool:
    for char in text:
        code = ord(char)
        if code in {0x9, 0xA, 0xD}:
            continue
        if 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF:
            continue
        return False
    return True


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
        if not _xml_compatible(text):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RENDER-001",
                "publication text contains XML-incompatible characters",
            )
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
        paragraphs.append(
            f'<w:p>{style}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>'
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
        "</w:sectPr></w:body></w:document>"
    ).encode("utf-8")
    styles = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/></w:style></w:styles>'''
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'''
    rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    doc_rels = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
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


def _verify_docx_bytes(data: bytes) -> bool:
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/_rels/document.xml.rels",
        "word/styles.xml",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            names = set(archive.namelist())
            if not required.issubset(names):
                return False
            for name in required:
                ElementTree.fromstring(archive.read(name))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return False
    return True


class PublicationReleaseService:
    def __init__(self, facade) -> None:
        if facade._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-WORKSPACE-001",
                "Publication requires a local workspace",
            )
        self.facade = facade
        self.workspace = Path(facade._workspace_root)
        self.root = self.workspace / ".research-loom" / "publication"

    @contextmanager
    def _file_lock(self, name: str):
        lock_root = self.root / "locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        path = lock_root / f"{_safe(name)}.lock"
        handle = path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
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

    def _profile_pin(self, package: Mapping[str, Any]) -> Mapping[str, Any]:
        pins = package.get("effective_profile_set", {}).get("profile_pins", [])
        rows = [
            row
            for row in pins
            if isinstance(row, Mapping) and row.get("profile_type") == "publication"
        ]
        if len(rows) != 1:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-PROFILE-001",
                "exactly one pinned Publication Profile is required",
            )
        row = rows[0]
        digest = str(row.get("content_digest") or row.get("manifest_sha256") or "")
        if digest and not digest.startswith("sha256:"):
            digest = "sha256:" + digest
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-PROFILE-001",
                "Publication Profile digest is invalid",
            )
        return {
            "profile_id": str(row["profile_id"]),
            "profile_version": str(row["profile_version"]),
            "content_digest": digest,
        }

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
    def _citation_label(source: Mapping[str, Any], locator: str | None) -> str:
        title = str(source.get("title") or source.get("name") or source.get("id") or "Source")
        canonical = str(source.get("canonical_locator") or "")
        bits = [title]
        if canonical:
            bits.append(canonical)
        if locator and locator != canonical:
            bits.append(str(locator))
        return " — ".join(bits)

    @staticmethod
    def _issue(code: str, ref: str, section_id: str | None, blocking: bool) -> dict[str, Any]:
        basis = f"{code}|{ref}|{section_id or ''}".encode("utf-8")
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
        package = inspection["source_package_document"]
        revision = inspection["revision"]
        composition = inspection["composition"]
        sections = list(revision.get("sections", []))
        if len(sections) > MAX_SECTIONS:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-BOUND-001",
                "manuscript section count exceeds Publication bound",
            )
        known_sections = {str(row["section_id"]) for row in sections}
        heading_by_section: dict[str, str] = {}
        for row in composition.get("sections", []):
            if not isinstance(row, Mapping):
                continue
            section_id = str(row.get("section_id"))
            if section_id not in known_sections:
                continue
            heading = (
                row.get("heading")
                or row.get("generated_heading")
                or row.get("title")
                or section_id
            )
            if isinstance(heading, Mapping):
                heading = heading.get("text")
            heading_by_section[section_id] = str(heading or section_id)

        sources = self._source_index(package)
        exhibits = self._exhibit_index(package)
        exhibit_numbers: dict[str, tuple[str, int]] = {}
        citation_numbers: dict[str, int] = {}
        locators_by_source: dict[str, list[str]] = {}
        issues: list[dict[str, Any]] = []
        issue_keys: set[tuple[str, str, str | None]] = set()

        def add_issue(code: str, ref: str, section_id: str | None, blocking: bool) -> None:
            key = (code, ref, section_id)
            if key not in issue_keys:
                issue_keys.add(key)
                issues.append(self._issue(code, ref, section_id, blocking))

        table_count = 0
        figure_count = 0
        for section in sections:
            section_id = str(section["section_id"])
            for citation in section.get("citations", []):
                source_ref = str(citation.get("source_ref", ""))
                if source_ref not in sources:
                    add_issue("UNRESOLVED_CITATION", source_ref, section_id, True)
                    continue
                if source_ref not in citation_numbers:
                    citation_numbers[source_ref] = len(citation_numbers) + 1
                locator = citation.get("locator_ref")
                if locator:
                    bucket = locators_by_source.setdefault(source_ref, [])
                    locator_value = str(locator)
                    if locator_value not in bucket:
                        bucket.append(locator_value)
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
                    exhibit_numbers[exhibit_ref] = ("Table", table_count)
                else:
                    figure_count += 1
                    exhibit_numbers[exhibit_ref] = ("Figure", figure_count)

        def replace_token(match: re.Match[str], section_id: str) -> str:
            kind, ref = match.group(1), match.group(2)
            if kind == "section":
                if ref not in known_sections:
                    add_issue("UNRESOLVED_CROSS_REFERENCE", ref, section_id, True)
                    return f"[unresolved section:{ref}]"
                return f'Section “{heading_by_section.get(ref, ref)}”'
            if kind == "citation":
                if ref not in sources:
                    add_issue("UNRESOLVED_CITATION", ref, section_id, True)
                    return f"[unresolved citation:{ref}]"
                if ref not in citation_numbers:
                    citation_numbers[ref] = len(citation_numbers) + 1
                return f"[{citation_numbers[ref]}]"
            if ref not in exhibit_numbers:
                add_issue("UNRESOLVED_CROSS_REFERENCE", ref, section_id, True)
                return f"[unresolved exhibit:{ref}]"
            label, number = exhibit_numbers[ref]
            return f"{label} {number}"

        title = str(package.get("project", {}).get("title") or "Publication")
        md: list[str] = [f"# {title}", ""]
        docx_lines: list[tuple[str, str]] = [("title", title)]
        rendered_exhibits: set[str] = set()
        for section in sections:
            sid = str(section["section_id"])
            heading = heading_by_section.get(sid, sid)
            content = _XREF.sub(
                lambda match: replace_token(match, sid), str(section.get("content", ""))
            )
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
                exhibit_text = (
                    content_obj.get("value", "")
                    if isinstance(content_obj, Mapping)
                    else str(content_obj)
                )
                if not isinstance(exhibit_text, str):
                    exhibit_text = json.dumps(exhibit_text, ensure_ascii=False, sort_keys=True)
                md.extend([f"**{caption}**", "", exhibit_text, ""])
                docx_lines.extend([("heading2", caption), ("body", exhibit_text)])

        if citation_numbers:
            md.extend(["## References", ""])
            docx_lines.append(("heading", "References"))
            for source_ref, number in sorted(
                citation_numbers.items(), key=lambda item: item[1]
            ):
                source = sources[source_ref]
                locators = locators_by_source.get(source_ref, [])
                rendered = self._citation_label(source, locators[0] if locators else None)
                entry = f"[{number}] {rendered}"
                md.append(entry)
                docx_lines.append(("body", entry))
            md.append("")

        feedback = revision.get("writing_feedback", {}).get("issues", [])
        if feedback:
            add_issue("WRITING_FEEDBACK_OPEN", str(len(feedback)), None, False)

        markdown = ("\n".join(md).rstrip() + "\n").encode("utf-8")
        docx = _docx_bytes(docx_lines)
        if len(markdown) + len(docx) > MAX_OUTPUT_BYTES:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-BOUND-001",
                "Publication outputs exceed supported aggregate size",
            )
        if not _verify_docx_bytes(docx):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RENDER-001",
                "generated DOCX failed structural XML verification",
            )
        checks = {
            "citation_resolution": "failed"
            if any(item["code"] == "UNRESOLVED_CITATION" for item in issues)
            else "passed",
            "exhibit_resolution": "failed"
            if any(item["code"] == "MISSING_EXHIBIT" for item in issues)
            else "passed",
            "cross_reference_resolution": "failed"
            if any(item["code"] == "UNRESOLVED_CROSS_REFERENCE" for item in issues)
            else "passed",
            "render_verification": "passed",
            "writing_feedback": "warning" if feedback else "passed",
        }
        return markdown, docx, issues, checks

    def _build_path(self, build_id: str) -> Path:
        return self.root / "builds" / _safe(build_id)

    def _release_request_path(self, request_id: str) -> Path:
        return self.root / "release-requests" / f"{_safe(request_id)}.json"

    @staticmethod
    def _validation_checks(
        checks: Mapping[str, str], issues: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        code_for_check = {
            "citation_resolution": "UNRESOLVED_CITATION",
            "exhibit_resolution": "MISSING_EXHIBIT",
            "cross_reference_resolution": "UNRESOLVED_CROSS_REFERENCE",
            "render_verification": None,
            "writing_feedback": "WRITING_FEEDBACK_OPEN",
        }
        result = []
        for check_id, status in checks.items():
            issue_code = code_for_check[check_id]
            refs = [
                str(issue["defect_id"])
                for issue in issues
                if issue_code is not None and issue.get("code") == issue_code
            ]
            result.append(
                {
                    "check_id": check_id.replace("_", "-"),
                    "status": status,
                    "defect_refs": refs,
                }
            )
        return result

    def _preview_manifest(
        self,
        *,
        build_id: str,
        revision: Mapping[str, Any],
        package: Mapping[str, Any],
        profile: Mapping[str, Any],
        docx: bytes,
        issues: list[Mapping[str, Any]],
        checks: Mapping[str, str],
    ) -> dict[str, Any]:
        generated_at = str(
            revision.get("created_at")
            or package.get("provenance", {}).get("generated_at")
            or "1970-01-01T00:00:00Z"
        )
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "preview_artifact_manifest",
            "preview_id": build_id,
            "source_manuscript": {
                "manuscript_id": str(revision["revision_id"]),
                "manuscript_digest": str(revision["revision_digest"]),
            },
            "source_epistemic_status": str(package["source_epistemic_status"]),
            "publication_profile": deepcopy(dict(profile)),
            "template_pin": deepcopy(_TEMPLATE_PIN),
            "style_map_pin": deepcopy(_STYLE_MAP_PIN),
            "renderer": deepcopy(_RENDERER),
            "outputs": [
                {
                    "format": "docx",
                    "path": "formal.docx",
                    "output_digest": _sha(docx),
                    "input_template_digest": _TEMPLATE_PIN["content_digest"],
                    "input_style_map_digest": _STYLE_MAP_PIN["content_digest"],
                }
            ],
            "validation_checks": self._validation_checks(checks, issues),
            "preview_only": True,
            "release_eligible": False,
            "published_artifact": False,
            "release_manifest": False,
            "content_digest": "",
            "provenance": {
                "generated_at": generated_at,
                "tool_id": "research-loom.publication",
                "tool_version": SERVICE_VERSION,
                "input_digests": [
                    str(revision["revision_digest"]),
                    str(package["package_digest"]),
                    str(profile["content_digest"]),
                    _TEMPLATE_PIN["content_digest"],
                    _STYLE_MAP_PIN["content_digest"],
                ],
            },
        }
        manifest["content_digest"] = _digest(manifest, "content_digest")
        _validate_preview_manifest(manifest)
        return manifest

    def _build_receipt(
        self,
        *,
        build_id: str,
        key_digest: str,
        composition_id: str,
        revision: Mapping[str, Any],
        package: Mapping[str, Any],
        profile: Mapping[str, Any],
        preview_manifest: Mapping[str, Any],
        markdown: bytes,
        docx: bytes,
        issues: list[Mapping[str, Any]],
        checks: Mapping[str, str],
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "publication_build_receipt",
            "build_id": build_id,
            "build_key_digest": key_digest,
            "preview_manifest_digest": preview_manifest["content_digest"],
            "source_manuscript": {
                "composition_id": composition_id,
                "revision_id": revision["revision_id"],
                "revision_digest": revision["revision_digest"],
            },
            "research_provenance": {
                "research_package_id": package["package_id"],
                "research_package_digest": package["package_digest"],
                "research_snapshot": deepcopy(package["source_research_snapshot"]),
            },
            "publication_profile": deepcopy(dict(profile)),
            "outputs": [
                {
                    "format": "markdown",
                    "relative_path": "preview.md",
                    "media_type": "text/markdown",
                    "size": len(markdown),
                    "digest": _sha(markdown),
                },
                {
                    "format": "docx",
                    "relative_path": "formal.docx",
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size": len(docx),
                    "digest": _sha(docx),
                },
            ],
            "verification": deepcopy(dict(checks)),
            "issues": deepcopy(list(issues)),
            "research_state_mutation_performed": False,
            "content_digest": "",
        }
        receipt["content_digest"] = _digest(receipt, "content_digest")
        return receipt

    def _load_build(self, build_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
        target = self._build_path(build_id)
        receipt_path = target / "build-receipt.json"
        manifest_path = target / "preview-manifest.json"
        if not receipt_path.is_file() or not manifest_path.is_file():
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-404", "Publication preview build does not exist"
            )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("content_digest") != _digest(receipt, "content_digest"):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication build receipt digest does not verify",
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_preview_manifest(manifest)
        if manifest.get("content_digest") != _digest(manifest, "content_digest"):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication preview manifest digest does not verify",
            )
        if (
            manifest.get("preview_id") != build_id
            or receipt.get("preview_manifest_digest") != manifest.get("content_digest")
            or receipt.get("source_manuscript", {}).get("revision_digest")
            != manifest.get("source_manuscript", {}).get("manuscript_digest")
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication build and canonical preview manifest binding mismatch",
            )
        for output in receipt.get("outputs", []):
            path = target / str(output["relative_path"])
            if not path.is_file():
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication output is missing",
                )
            payload = path.read_bytes()
            if len(payload) != int(output["size"]) or _sha(payload) != output["digest"]:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication output no longer matches its build receipt",
                )
        formal = next(
            (row for row in receipt["outputs"] if row.get("format") == "docx"), None
        )
        canonical = next(
            (row for row in manifest["outputs"] if row.get("format") == "docx"), None
        )
        if (
            formal is None
            or canonical is None
            or formal["digest"] != canonical["output_digest"]
            or formal["relative_path"] != canonical["path"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication formal output binding does not verify",
            )
        if not _verify_docx_bytes((target / formal["relative_path"]).read_bytes()):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "stored Publication DOCX failed structural XML verification",
            )
        return receipt, manifest, target

    def build_preview(
        self, composition_id: str, revision_id: str | None = None
    ) -> Mapping[str, Any]:
        inspection = self.facade.inspect_writer_round_trip(composition_id, revision_id)
        receipt = inspection["writer_input"]
        package = self.facade._writer_composition_service()._package(
            str(receipt["source"]["research_package_id"])
        )
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
            "template_pin": _TEMPLATE_PIN,
            "style_map_pin": _STYLE_MAP_PIN,
            "renderer": _RENDERER,
        }
        key_digest = _sha(_canonical_bytes(build_key))
        build_id = "PUB-" + key_digest.split(":", 1)[1][:24]
        with self._file_lock(f"build-{build_id}"):
            target = self._build_path(build_id)
            if (target / "build-receipt.json").is_file():
                existing, manifest, _ = self._load_build(build_id)
                if existing.get("build_key_digest") != key_digest:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Publication build identity conflicts with stored content",
                    )
                return {
                    "status": "VERIFIED_REUSE",
                    "build": existing,
                    "preview_manifest": manifest,
                    "research_state_mutation_performed": False,
                }

            markdown, docx, issues, checks = self._render(inspection)
            manifest = self._preview_manifest(
                build_id=build_id,
                revision=revision,
                package=package,
                profile=profile,
                docx=docx,
                issues=issues,
                checks=checks,
            )
            build_receipt = self._build_receipt(
                build_id=build_id,
                key_digest=key_digest,
                composition_id=composition_id,
                revision=revision,
                package=package,
                profile=profile,
                preview_manifest=manifest,
                markdown=markdown,
                docx=docx,
                issues=issues,
                checks=checks,
            )
            self.root.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{build_id}.", dir=target.parent))
            try:
                (staging / "preview.md").write_bytes(markdown)
                (staging / "formal.docx").write_bytes(docx)
                (staging / "preview-manifest.json").write_bytes(_json_bytes(manifest))
                (staging / "build-receipt.json").write_bytes(_json_bytes(build_receipt))
                os.rename(staging, target)
            except OSError as exc:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-WRITE-001",
                    "Publication preview could not be persisted",
                ) from exc
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        return {
            "status": "BUILT",
            "build": build_receipt,
            "preview_manifest": manifest,
            "research_state_mutation_performed": False,
        }

    def show_preview(self, build_id: str) -> Mapping[str, Any]:
        build, manifest, root = self._load_build(build_id)
        return {
            "status": "OK",
            "build": build,
            "preview_manifest": manifest,
            "preview_markdown": (root / "preview.md").read_text(encoding="utf-8"),
            "output_root": str(root),
            "research_state_mutation_performed": False,
        }

    @staticmethod
    def _release_checks_pass(
        build: Mapping[str, Any], preview: Mapping[str, Any]
    ) -> bool:
        if preview.get("source_epistemic_status") != "EMPIRICAL_RESEARCH_STATE":
            return False
        return not any(
            value == "failed"
            for key, value in build["verification"].items()
            if key != "writing_feedback"
        )

    def request_release(self, build_id: str, actor_id: str) -> Mapping[str, Any]:
        if not isinstance(actor_id, str) or not actor_id:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "human release actor_id is required",
            )
        shown = self.show_preview(build_id)
        build = shown["build"]
        preview = shown["preview_manifest"]
        if not self._release_checks_pass(build, preview):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-CHECK-001",
                "Publication release checks have not passed",
            )
        basis = {
            "project_ref": self.facade.project_id,
            "build_id": build_id,
            "preview_digest": preview["content_digest"],
            "actor_id": actor_id,
        }
        request_id = "PUBRELREQ-" + _sha(_canonical_bytes(basis)).split(":", 1)[1][:24]
        with self._file_lock(f"request-{request_id}"):
            path = self._release_request_path(request_id)
            if path.is_file():
                request = json.loads(path.read_text(encoding="utf-8"))
                if request.get("request_digest") != _digest(request, "request_digest"):
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Publication release request digest does not verify",
                    )
                return {"status": "VERIFIED_REUSE", "decision_request": request}
            formal = next(row for row in build["outputs"] if row["format"] == "docx")
            request: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "publication_release_decision_request",
                "request_id": request_id,
                "project_ref": self.facade.project_id,
                "human_actor_id": actor_id,
                "source_preview": {
                    "preview_id": build_id,
                    "preview_digest": preview["content_digest"],
                },
                "source_manuscript": deepcopy(build["source_manuscript"]),
                "snapshot_binding": deepcopy(
                    build["research_provenance"]["research_snapshot"]
                ),
                "publication_profile": deepcopy(build["publication_profile"]),
                "output_binding": {
                    "format": "docx",
                    "digest": formal["digest"],
                    "size": formal["size"],
                },
                "allowed_dispositions": ["approve_release"],
                "issued_at": self.facade._application.clock.now(),
                "request_digest": "",
            }
            request["request_digest"] = _digest(request, "request_digest")
            path.parent.mkdir(parents=True, exist_ok=True)
            staging = path.with_suffix(".json.tmp")
            staging.write_bytes(_json_bytes(request))
            os.replace(staging, path)
        return {"status": "PENDING", "decision_request": request}

    def _load_release_request(self, request_id: str) -> Mapping[str, Any]:
        path = self._release_request_path(request_id)
        if not path.is_file():
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release decision request does not resolve",
            )
        request = json.loads(path.read_text(encoding="utf-8"))
        if request.get("request_digest") != _digest(request, "request_digest"):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication release request digest does not verify",
            )
        if request.get("project_ref") != self.facade.project_id:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release request belongs to another project",
            )
        return request

    def release(self, build_id: str, response: Mapping[str, Any]) -> Mapping[str, Any]:
        required = {"request_id", "request_digest", "disposition", "actor_id"}
        if not isinstance(response, Mapping) or set(response) != required:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "release requires the exact Publication release decision response",
            )
        request = self._load_release_request(str(response["request_id"]))
        if (
            response.get("request_digest") != request["request_digest"]
            or response.get("actor_id") != request["human_actor_id"]
            or response.get("disposition") != "approve_release"
            or response.get("disposition") not in request["allowed_dispositions"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release response does not match its exact decision request",
            )

        shown = self.show_preview(build_id)
        build = shown["build"]
        preview = shown["preview_manifest"]
        if not self._release_checks_pass(build, preview):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-CHECK-001",
                "Publication release checks have not passed",
            )
        if (
            request["source_preview"]["preview_id"] != build_id
            or request["source_preview"]["preview_digest"] != preview["content_digest"]
            or request["source_manuscript"] != build["source_manuscript"]
            or request["snapshot_binding"]
            != build["research_provenance"]["research_snapshot"]
            or request["publication_profile"] != build["publication_profile"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release request is stale or bound to another build",
            )
        formal = next(row for row in build["outputs"] if row["format"] == "docx")
        if (
            request["output_binding"]["digest"] != formal["digest"]
            or int(request["output_binding"]["size"]) != int(formal["size"])
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release request output binding is stale",
            )

        decision_id = "PUBRELDEC-" + hashlib.sha256(
            (
                request["request_digest"]
                + str(response["actor_id"])
                + str(response["disposition"])
            ).encode("utf-8")
        ).hexdigest()[:24]
        release_id = "REL-" + hashlib.sha256(
            (build_id + preview["content_digest"] + decision_id).encode("utf-8")
        ).hexdigest()[:24]
        with self._file_lock(f"release-{release_id}"):
            target = self.root / "releases" / release_id
            manifest_path = target / "release-manifest.json"
            source = self._build_path(build_id) / "formal.docx"
            payload = source.read_bytes()
            if len(payload) != int(formal["size"]) or _sha(payload) != formal["digest"]:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication DOCX no longer matches its verified preview build",
                )
            if not _verify_docx_bytes(payload):
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication DOCX failed structural XML verification",
                )
            if manifest_path.is_file():
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if existing.get("content_digest") != _digest(existing, "content_digest"):
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "stored Release Manifest digest does not verify",
                    )
                artifact = target / "artifact.docx"
                if (
                    existing.get("human_release_decision", {}).get("decision_id")
                    != decision_id
                    or not artifact.is_file()
                    or artifact.stat().st_size != int(existing["output"]["size"])
                    or _sha(artifact.read_bytes()) != existing["output"]["digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Release identity conflicts with stored release",
                    )
                return {
                    "status": "VERIFIED_REUSE",
                    "release": existing,
                    "research_state_mutation_performed": False,
                }

            decision: dict[str, Any] = {
                "decision_id": decision_id,
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_release",
                "actor": {
                    "actor_id": str(response["actor_id"]),
                    "actor_type": "human",
                },
                "decided_at": self.facade._application.clock.now(),
                "decision_digest": "",
            }
            decision["decision_digest"] = _digest(decision, "decision_digest")
            manifest: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "release_manifest",
                "release_id": release_id,
                "source_preview": {
                    "preview_id": build_id,
                    "preview_digest": preview["content_digest"],
                },
                "source_manuscript": deepcopy(build["source_manuscript"]),
                "research_provenance": deepcopy(build["research_provenance"]),
                "publication_profile": deepcopy(build["publication_profile"]),
                "output": {
                    "relative_path": "artifact.docx",
                    "artifact_reference": f"publication/releases/{release_id}/artifact.docx",
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size": len(payload),
                    "digest": _sha(payload),
                },
                "verification": deepcopy(build["verification"]),
                "human_release_decision": decision,
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
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-WRITE-001",
                    "Publication release could not be persisted",
                ) from exc
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        return {
            "status": "RELEASED",
            "release": manifest,
            "research_state_mutation_performed": False,
        }
