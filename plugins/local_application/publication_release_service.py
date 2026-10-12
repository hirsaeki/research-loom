from __future__ import annotations

from plugins.local_durable_store import require_optional_available, register_optional_path

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
from urllib.parse import urldefrag
from typing import Any, Mapping
from xml.etree import ElementTree
import zipfile

from jsonschema import Draft202012Validator, FormatChecker

from .facade import LocalApplicationError
from .publication_docx import docx_bytes as _docx_bytes, verify_native_docx
from .publication_exhibits import prepare_exhibits, render_input_digest
from .publication_input import inspect_inputs

SCHEMA_VERSION = "0.1.0"
SERVICE_VERSION = "0.2.0"
MAX_SECTIONS = 128
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_XREF = re.compile(r"\[\[(section|exhibit|citation):([^\]]+)\]\]")
_APPLICATION_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "packages"
    / "writer-publication"
    / "publication-application.schema.json"
)
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
    b"research-loom deterministic native table/PNG docx template v0.2.0",
)
_STYLE_MAP_PIN = _artifact_pin(
    "research-loom.builtin-docx-style-map",
    b"Title=Title;heading=Heading1;heading2=Heading2;body=Normal;table=TableText;v0.2.0",
)
_RENDERER = {
    "renderer_id": "research-loom.deterministic-docx",
    "renderer_version": "0.3.0",
    "tool_digest": _sha(b"research-loom.deterministic-docx@0.3.0;misco-formal-sections;exact-pdf-review;provenance-v2"),
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


def _validate_publication_inputs(value: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = {"schema_version": SCHEMA_VERSION} if value is None else deepcopy(dict(value))
    schema = json.loads(_APPLICATION_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(normalized),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(item) for item in first.absolute_path) or "<root>"
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-INPUT-001",
            f"Publication application input is invalid at {path}: {first.message}",
        )
    for key in ("formal_spec_profile", "url_display_profile"):
        item = normalized.get(key)
        if isinstance(item, Mapping):
            source = item.get("source", {})
            digest = str(source.get("source_digest", ""))
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise LocalApplicationError("APPLICATION-PUBLICATION-INPUT-001", f"{key} source_digest is invalid")
    permission_ids = [row['source_ref'] for row in normalized.get('permissions', [])]
    if len(permission_ids) != len(set(permission_ids)):
        raise LocalApplicationError('APPLICATION-PUBLICATION-INPUT-001', 'Permissions must identify each Source once')
    return normalized


def _source_tags(source):
    return {str(source.get(key, '')).lower() for key in ['access_classification', 'source_classification', 'source_type']}


def _resource_rows(package: Mapping[str, Any], profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    resources = package.get("effective_profile_set", {}).get("effective_resources", [])
    selected = []
    for row in resources:
        if not isinstance(row, Mapping) or not str(row.get("role", "")).startswith("PUBLICATION_"):
            continue
        provenance = row.get("provenance", [])
        if any(
            isinstance(src, Mapping)
            and src.get("profile_type") == "publication"
            and src.get("profile_id") == profile.get("profile_id")
            and src.get("profile_version") == profile.get("profile_version")
            for src in provenance
        ):
            selected.append(deepcopy(dict(row)))
    return selected


def _editorial_status(review: Any, *, misco: bool) -> str:
    """Preserve incomplete reviews and reject contradictory aggregate evidence."""
    if not isinstance(review, Mapping):
        return "warning"
    rows = review.get("checks", [])
    ids = [row.get("check_id") for row in rows]
    if len(ids) != len(set(ids)) or any(row.get("status") == "failed" for row in rows):
        return "failed"
    if misco:
        overall = next((row for row in rows if row.get("check_id") == "misco-editorial-qa"), None)
        if overall is None or overall.get("status") == "not_applicable":
            return "failed"
    if not rows or any(row.get("status") in {"warning", "unevaluated"} for row in rows):
        return "warning"
    # An entirely inapplicable review contains no positive conformance evidence.
    if all(row.get("status") == "not_applicable" for row in rows):
        return "warning"
    return "passed"


def _publication_policy(package: Mapping[str, Any], profile: Mapping[str, Any], inputs: Mapping[str, Any], project_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    resources = _resource_rows(package, profile)
    by_role = {str(row.get("role")): row for row in resources}
    rules_row = by_role.get("PUBLICATION_RULES")
    source_row = by_role.get("PUBLICATION_SOURCE_DOCUMENTS")
    formal_row = by_role.get("PUBLICATION_FORMAL_SPEC")
    url_row = by_role.get("PUBLICATION_URL_DISPLAY")
    coverage_row = by_role.get("PUBLICATION_COVERAGE")
    coverage = json.loads(coverage_row["content"]) if coverage_row else None
    if profile.get("profile_id") == "misco.publication" and any(
        row is None for row in (rules_row, source_row, formal_row, url_row)
    ):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-PROFILE-001",
            "MISCO Publication requires verified rule, source-document, formal-spec, and URL-display resources",
        )
    rules = json.loads(rules_row["content"]) if rules_row else {"items": [], "missing_inputs": []}
    formal_resource = json.loads(formal_row["content"]) if formal_row else {}
    url_resource = json.loads(url_row["content"]) if url_row else {}
    pinned_formal = formal_resource.get("formal_spec_profile")
    pinned_url_profile = url_resource.get("url_display_profile")
    explicit_formal = inputs.get("formal_spec_profile")
    explicit_url_profile = inputs.get("url_display_profile")
    if isinstance(explicit_formal, Mapping) and isinstance(pinned_formal, Mapping) and dict(explicit_formal) != dict(pinned_formal):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-PROFILE-001",
            "explicit formal_spec_profile conflicts with the pinned MISCO Publication formal-spec resource",
        )
    if isinstance(explicit_url_profile, Mapping) and isinstance(pinned_url_profile, Mapping) and dict(explicit_url_profile) != dict(pinned_url_profile):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-PROFILE-001",
            "explicit url_display_profile conflicts with the pinned MISCO Publication URL-display resource",
        )
    formal = explicit_formal if isinstance(explicit_formal, Mapping) else pinned_formal
    url_profile = explicit_url_profile if isinstance(explicit_url_profile, Mapping) else pinned_url_profile
    group_type = inputs.get("research_group_type")
    if isinstance(group_type, str) and not group_type.strip():
        group_type = None
    document_mode = inputs.get("document_mode", "body_preview")
    report = inputs.get("formal_report")
    config_pin = None
    saved = None
    if project_config is not None:
        config_pin = {"config_version": project_config["config_version"], "configuration_digest": project_config["configuration_digest"]}
        if inputs.get("project_config_digest") is not None and inputs["project_config_digest"] != config_pin["configuration_digest"]:
            raise LocalApplicationError("PROJECT-CONFIG-STALE-001", "Publication input targets a different Project Config generation")
        saved = project_config.get("publication_metadata", {}).get("research_group_type") if profile.get('profile_id') == 'misco.publication' else None
        if isinstance(saved, str) and not saved.strip():
            saved = None
        if saved is not None and group_type is not None and saved != group_type:
            raise LocalApplicationError("INPUT-RESEARCH-GROUP-TYPE-CONFLICT", "Explicit Publication group conflicts with saved project metadata")
        group_type = saved or group_type
    permissions = inputs.get("permissions", [])
    editorial = inputs.get("editorial_review")
    missing = []
    if profile.get("profile_id") == "misco.publication":
        if document_mode == 'formal_report' and group_type is not None and group_type not in {'G', 'M'}:
            raise LocalApplicationError('INPUT-RESEARCH-GROUP-TYPE', 'MISCO formal report requires an explicit G or M answer')
        if document_mode == 'formal_report' and not coverage:
            missing.append('INPUT-FORMAL-COVERAGE')
        if document_mode == "formal_report" and not isinstance(report, Mapping):
            missing.append("INPUT-FORMAL-REPORT")
        if not isinstance(formal, Mapping) or not isinstance(formal.get("research_group_type_required"), bool):
            missing.append("INPUT-FORMAL-SPEC")
        elif (formal["research_group_type_required"] or document_mode == "formal_report") and document_mode == "formal_report" and not group_type:
            missing.append("INPUT-RESEARCH-GROUP-TYPE")
        if coverage and document_mode == 'formal_report' and group_type and saved is None:
            missing.append('INPUT-RESEARCH-GROUP-TYPE-SAVE')
        sources = package.get("resolved_content", {}).get("research_objects", [])
        has_reader_url = any(
            isinstance(row, Mapping)
            and row.get("kind") == "source"
            and str(row.get("canonical_locator") or "").startswith(("http://", "https://"))
            for row in sources
        )
        if has_reader_url and not isinstance(url_profile, Mapping):
            missing.append("INPUT-URL-DISPLAY")
        required_permissions = {
            str(row.get("id"))
            for row in sources
            if isinstance(row, Mapping)
            and row.get("kind") == "source"
            and bool(_source_tags(row) & {"internal", "non-public", "confidential", "interview"})
        }
        permission_by_source = {str(row.get("source_ref")): row for row in permissions if isinstance(row, Mapping)}
        if any(ref not in permission_by_source or not permission_by_source[ref].get("publication_allowed") or not permission_by_source[ref].get("original_reviewed") or permission_by_source[ref].get("company_disclosure") not in {"allowed", "anonymized"} for ref in required_permissions):
            missing.append("INPUT-PERMISSION")
    if profile.get("profile_id") == "misco.publication" and isinstance(editorial, Mapping):
        editorial_rows = {str(row.get("check_id")): row for row in editorial.get("checks", []) if isinstance(row, Mapping)}
        overall = editorial_rows.get("misco-editorial-qa")
        if overall is None:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INPUT-001",
                "MISCO editorial review must include misco-editorial-qa",
            )
    return {
        "rules": {
            "role": rules_row.get("role") if rules_row else None,
            "sha256": rules_row.get("sha256") if rules_row else None,
            "rule_ids": sorted(str(item["id"]) for item in rules.get("items", []) if isinstance(item, Mapping) and item.get("id")),
        },
        "source_documents": {
            "role": source_row.get("role") if source_row else None,
            "sha256": source_row.get("sha256") if source_row else None,
        },
        "formal_spec_resource": {
            "role": formal_row.get("role") if formal_row else None,
            "sha256": formal_row.get("sha256") if formal_row else None,
        },
        "url_display_resource": {
            "role": url_row.get("role") if url_row else None,
            "sha256": url_row.get("sha256") if url_row else None,
        },
        "formal_spec_profile": deepcopy(formal),
        "url_display_profile": deepcopy(url_profile),
        "research_group_type": group_type,
        "project_config_pin": config_pin,
        "document_mode": document_mode,
        "conformance_scope": "formal_report" if document_mode == "formal_report" else "partial_body_preview",
        "coverage": deepcopy(coverage),
        "formal_report": deepcopy(report),
        "host_questions": [{"input_id": "INPUT-RESEARCH-GROUP-TYPE", "question": "今回の報告書はG研究会とM研究会のどちらですか？", "save_via": "profile resolve publication_metadata then profile advance"}] if "INPUT-RESEARCH-GROUP-TYPE" in missing else [],
        "host_actions": [{'input_id': 'INPUT-RESEARCH-GROUP-TYPE-SAVE', 'research_group_type': group_type, 'save_via': 'profile resolve publication_metadata then profile advance', 'expected_project_config_digest': config_pin['configuration_digest'] if config_pin else None}] if 'INPUT-RESEARCH-GROUP-TYPE-SAVE' in missing else [],
        "permissions": deepcopy(list(permissions)),
        "review_conditions": {
            "interview": any('interview' in _source_tags(row) for row in package.get('resolved_content', {}).get('research_objects', []) if row.get('kind') == 'source'),
            "company_information": any(bool(_source_tags(row) & {'internal', 'non-public', 'confidential'}) for row in package.get('resolved_content', {}).get('research_objects', []) if row.get('kind') == 'source'),
        },
        "editorial_review": deepcopy(editorial),
        "missing_inputs": missing,
        "release_blocked": bool(missing),
    }


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
        require_optional_available(self.root, LocalApplicationError)

    @contextmanager
    def _file_lock(self, name: str):
        require_optional_available(self.root, LocalApplicationError)
        lock_root = self.root / "locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        register_optional_path(self.root)
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
    def _citation_label(source: Mapping[str, Any], locator: str | None, policy: Mapping[str, Any]) -> str:
        title = str(source.get("title") or source.get("name") or source.get("id") or "Source")
        canonical = str(source.get("canonical_locator") or "")
        if policy.get('document_mode') == 'formal_report':
            exceptions = source.get('bibliography_exceptions', {})
            fields = ['author', 'title', 'publisher', 'publication_or_update_date']
            missing = [key for key in fields if not str(source.get(key) or '').strip() and not (key != 'title' and str(exceptions.get(key) or '').strip())]
            if missing:
                raise LocalApplicationError('PUBLICATION-BIBLIOGRAPHY-MISSING', str(source.get('id')) + ': ' + ', '.join(missing))
            bits = [str(source[key]) for key in fields if str(source.get(key) or '').strip()]
            if locator and locator != canonical:
                bits.append(str(locator))
            if canonical.startswith(('http://', 'https://')) and canonical not in bits:
                bits.append(canonical)
            return '、'.join(bits)
        # A fragment locator refines this URL; it is not a second source URL.
        if locator and canonical.startswith(("http://", "https://")) and urldefrag(str(locator))[0] == urldefrag(canonical)[0]:
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
        policy = inspection.get("publication_policy", {})
        misco = inspection.get("publication_profile", {}).get("profile_id") == "misco.publication"
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
        report = policy.get('formal_report')
        formal_report = policy.get('document_mode') == 'formal_report' and isinstance(report, Mapping) and policy.get('research_group_type') in {'G', 'M'}
        formal_outline = {}
        if formal_report:
            from .publication_formal_report import outline
            formal_outline = outline(report['structure'], [str(row['section_id']) for row in sections])
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
                (row for row in composition.get("sections", []) if str(row.get("section_id")) == section_id),
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
                    section_bucket = locators_by_section_source.setdefault((section_id, source_ref), [])
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
                    exhibit_numbers[exhibit_ref] = ("表" if misco else "Table", table_count)
                else:
                    figure_count += 1
                    exhibit_numbers[exhibit_ref] = ("図" if misco else "Figure", figure_count)
                if formal_report:
                    scope = formal_outline[section_id]
                    if not scope['section']:
                        raise LocalApplicationError('PUBLICATION-FORMAL-STRUCTURE-001', 'Figure/table needs an explicit chapter and section scope')
                    label = exhibit_numbers[exhibit_ref][0]
                    previous = [number for previous_label, number in exhibit_numbers.values() if previous_label == label and str(number).startswith(f"{scope['chapter']}-{scope['section']}-")]
                    exhibit_numbers[exhibit_ref] = (label, f"{scope['chapter']}-{scope['section']}-{len(previous) + 1}")

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
                if formal_report:
                    locators = locators_by_section_source.get((section_id, ref), [])
                    return '（' + self._citation_label(sources[ref], '；'.join(locators) if locators else None, policy) + '）'
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
            blocks = prepare_exhibits(inspection, self.workspace)
        for diagnostic in inspection.get("visual_diagnostics", []):
            add_issue("VISUAL_ASSET_UNAVAILABLE", diagnostic["path"], None, True)
        title = resolve_text(str(package.get("project", {}).get("title") or "Publication"), "document")
        md: list[str] = [f"# {title}", ""]
        docx_lines: list[tuple[str, Any]] = [("title", title)]
        rendered_exhibits: set[str] = set()
        formal = policy.get("formal_spec_profile")
        reference_placement = str(formal.get("reference_list_placement")) if isinstance(formal, Mapping) else "end_of_document"
        reference_heading = str(formal.get("reference_list_heading") or "References") if isinstance(formal, Mapping) else "References"

        def append_reference_list(section_id: str, source_refs: list[str], scope_ids: list[str] | None = None) -> None:
            if not source_refs:
                return
            md.extend([f"### {reference_heading}", ""])
            docx_lines.append(("reference_heading", reference_heading))
            for source_ref in source_refs:
                number = citation_numbers[source_ref]
                source = sources[source_ref]
                locators = list(dict.fromkeys(locator for sid in (scope_ids or [section_id]) for locator in locators_by_section_source.get((sid, source_ref), [])))
                rendered = self._citation_label(source, None if formal_report else (locators[0] if locators else None), policy)
                if formal_report and locators:
                    rendered += ' — ' + '；'.join(locators)
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
            role = 'heading'
            if formal_report:
                entry = formal_outline[sid]
                heading = entry['label'] + '　' + heading
                role = 'heading' + str(entry['level'])
            md.extend([f"## {heading}", "", content, ""])
            docx_lines.append((role, heading))
            if formal_report and formal_outline[sid]['level'] in {1, 2}:
                docx_lines.append(('body', ''))
            for paragraph in re.split(r'\n\s*\n', content) if formal_report else [content]:
                docx_lines.append(('body', paragraph))
            inline_citations = {match.group(2) for match in _XREF.finditer(str(section.get("content", ""))) if match.group(1) == "citation"}
            structured_citations = []
            for citation in section.get("citations", []):
                source_ref = str(citation.get("source_ref", ""))
                number = citation_numbers.get(source_ref)
                if number is not None and source_ref not in inline_citations:
                    if formal_report:
                        structured_citations.append(self._citation_label(sources[source_ref], citation.get('locator_ref'), policy))
                    else:
                        structured_citations.append(f"[{number}]")
            if structured_citations:
                marker = ("出典：" if misco else "Citations: ") + ", ".join(dict.fromkeys(structured_citations))
                md.extend([marker, ""])
                docx_lines.append(("body", marker))
            for ref_value in section.get("exhibit_refs", []):
                ref = str(ref_value)
                if ref in rendered_exhibits or ref not in exhibit_numbers or ref not in exhibits:
                    continue
                rendered_exhibits.add(ref)
                exhibit = exhibits[ref]
                label, number = exhibit_numbers[ref]
                caption = resolve_text(f"{label}{number}　{exhibit.get('title') or ref}" if formal_report else f"{label} {number}. {exhibit.get('title') or ref}", sid)
                block = {**deepcopy(blocks[ref]), "ref": ref, "caption": caption}
                if block["kind"] == "table":
                    block["rows"] = [[resolve_text(cell, sid) for cell in row] for row in block["rows"]]
                    # Markdown remains a preview companion; DOCX has native cells.
                    preview_text = "\n".join("| " + " | ".join(row) + " |" for row in block["rows"])
                elif block["kind"] == "image":
                    if exhibit.get("generated_visual") is not None:
                        value = exhibit["content"]["value"]
                        semantics = exhibit["visual_semantics"]
                        note = "Source: selected verified research data." if "chart_spec" in value else "Represented research: " + "; ".join(value["request"]["allowed_labels"]) + "."
                        if "chart_spec" in value:
                            spec = value["chart_spec"]
                            note += "\n" + spec["caption"]
                            units = "; ".join(k + "=" + (v if v is not None else "not applicable") for k, v in spec["units"].items())
                            note += "\nUnits: " + units + "; denominator: " + (spec["denominator"] or "not applicable") + "; period: " + (spec["period"] or "not applicable") + "."
                            if misco:
                                unit_labels = list(dict.fromkeys(v for v in spec["units"].values() if v is not None))
                                note = "単位：" + "、".join(unit_labels) + "。"
                                if spec["caption"] != exhibit.get("title"):
                                    note = spec["caption"] + "\n" + note
                                note += "\n対象：" + (spec["denominator"] or "記載なし") + "。対象年：" + (spec["period"] or "記載なし") + "。"
                                if "legend_rows" in block:
                                    x_unit, y_unit = spec["units"][spec["x_column"]], spec["units"][spec["y_column"]]
                                    x_label = "区分" if spec["chart_type"] == "bar" else "横軸の値"
                                    block["legend_rows"][0] = ["番号", x_label + (f"（{x_unit}）" if x_unit else ""), "値" + (f"（{y_unit}）" if y_unit else "")]
                        else:
                            note += "\nRepresentation reviewed against the selected research; no new research conclusion is established by this figure."
                            if misco:
                                note = "図に示す内容：" + "、".join(value["request"]["allowed_labels"]) + "。"
                                note += "\n既存の研究内容を整理した図であり、新たな研究上の結論を示すものではない。"
                    else:
                        visual = exhibit["visual_target"]
                        locator = visual["locator"]
                        capture = block["provenance"]["source_capture"]
                        source = (capture.get("source_locators") or [capture.get("source_locator") or visual["capture_id"]])[0]
                        note = f"Source: {source}; {locator.get('label') or locator['kind']}"
                        if "page" in locator:
                            note += f"; page {locator['page']}"
                        if locator.get("region"):
                            region = locator["region"]
                            note += "; region " + ", ".join(f"{key}={region[key]}" for key in ("x", "y", "width", "height")) + f" ({region['unit']})"
                        derived = visual.get("derived_artifact")
                        note += f"; retained {derived['derivation_type']}." if derived else "; original image."
                        content_obj = exhibit.get("content", {})
                        if content_obj.get("representation") in {"text", "markdown"}:
                            note += "\n" + str(content_obj.get("value", ""))
                    if block["provenance"].get("citation_sources") and not formal_report:
                        note += "\n" + "\n".join(("出典：" if misco else "Source: ") + self._citation_label(source, source.get("canonical_locator"), policy) + "; " + str(source.get("publisher_or_author") or "") + "; " + str(source.get("publication_or_update_date") or "") for source in block["provenance"]["citation_sources"])
                    block["note"] = note if exhibit.get("generated_visual") is not None else resolve_text(note, sid)
                    preview_text = "[Exact retained image is embedded in formal.docx.]\n" + block["note"]
                    if "legend_rows" in block:
                        # Exact literals must not be parsed as manuscript reference tokens.
                        preview_text += "\n" + "\n".join("| " + " | ".join(row) + " |" for row in block["legend_rows"])
                else:
                    add_issue(block["code"], ref, sid, True)
                    preview_text = f"[UNAVAILABLE: {block['code']}. Preserve the source and supply a supported exact representation.]"
                if formal_report and block['kind'] in {'image', 'table'}:
                    citation_sources = block['provenance'].get('citation_sources', [])
                    if citation_sources:
                        visual_locator = exhibit.get('visual_target', {}).get('locator', {})
                        page_locator = str(visual_locator['page']) + '頁' if 'page' in visual_locator else None
                        block['source_text'] = '（出典）' + '；'.join(self._citation_label(source, page_locator, policy) for source in citation_sources)
                    else:
                        add_issue('PUBLICATION_EXHIBIT_SOURCE_MISSING', ref, sid, True)
                        block['source_text'] = '（出典未確認）'
                    block['explanatory_note'] = block.pop('note', '')
                    if block['kind'] == 'image' and exhibit.get('generated_visual') is None:
                        content_object = exhibit.get('content', {})
                        block['explanatory_note'] = str(content_object.get('value', '')) if content_object.get('representation') in {'text', 'markdown'} else ''
                md.extend([f"**{caption}**", "", preview_text, ""])
                docx_lines.append(("exhibit", block))
            if reference_placement == "end_of_each_section":
                if formal_report:
                    current_scope = (formal_outline[sid]['chapter'], formal_outline[sid]['section'])
                    next_id = str(sections[section_index + 1]['section_id']) if section_index + 1 < len(sections) else None
                    next_scope = (formal_outline[next_id]['chapter'], formal_outline[next_id]['section']) if next_id else None
                    if current_scope != next_scope:
                        refs = list(dict.fromkeys(ref for id_ in reference_scope_ids for ref in citation_refs_by_section.get(id_, [])))
                        append_reference_list(sid, refs, reference_scope_ids)
                        reference_scope_ids = []
                else:
                    append_reference_list(sid, citation_refs_by_section.get(sid, []))

        if citation_numbers and reference_placement == "end_of_document":
            md.extend([f"## {reference_heading}", ""])
            docx_lines.append(("reference_heading", reference_heading))
            for source_ref, number in sorted(
                citation_numbers.items(), key=lambda item: item[1]
            ):
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
        if isinstance(formal, Mapping) and formal.get("reference_list_placement") not in {"end_of_document", "end_of_each_section"}:
            add_issue("PUBLICATION_FORMAL_VALUE_UNSUPPORTED", str(formal.get("reference_list_placement")), None, True)
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
            layout['formal_document'] = True
        docx = _docx_bytes(docx_lines, layout)
        if len(markdown) + len(docx) > MAX_OUTPUT_BYTES:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-BOUND-001",
                "Publication outputs exceed supported aggregate size",
            )
        if not _verify_docx_bytes(docx) or not verify_native_docx(docx, docx_lines, layout):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RENDER-001",
                "generated DOCX failed native structure/content verification",
            )
        if formal_report:
            from .publication_formal_report import assemble, inspect_formal
            docx = assemble(docx, dict(report), policy['research_group_type'], layout)
            failures = inspect_formal(docx, dict(report), policy['research_group_type'], layout)
            if failures:
                raise LocalApplicationError('PUBLICATION-FORMAL-RENDER-001', '; '.join(failures))
            if len(markdown) + len(docx) > MAX_OUTPUT_BYTES:
                raise LocalApplicationError('APPLICATION-PUBLICATION-BOUND-001', 'Formal report outputs exceed the supported aggregate size')
        checks = {
            "citation_resolution": "failed"
            if any(item["code"] == "UNRESOLVED_CITATION" for item in issues)
            else "passed",
            "exhibit_resolution": "failed"
            if any(item["code"] in {"MISSING_EXHIBIT", "UNSUPPORTED_EXHIBIT", "VISUAL_ASSET_UNAVAILABLE"} for item in issues)
            else "passed",
            "cross_reference_resolution": "failed"
            if any(item["code"] == "UNRESOLVED_CROSS_REFERENCE" for item in issues)
            else "passed",
            "render_verification": "failed" if blocking_issues else "passed",
            "layout_verification": "warning",
            "writing_feedback": "warning" if feedback else "passed",
            "formal_specification": "failed" if policy.get("missing_inputs") or any(item["code"] == "PUBLICATION_FORMAL_VALUE_UNSUPPORTED" for item in issues) else "warning" if policy.get("coverage") else "passed",
            "editorial_qa": _editorial_status(
                policy.get("editorial_review"), misco=misco
            ),
        }
        return markdown, docx, issues, checks

    def _build_path(self, build_id: str) -> Path:
        return self.root / "builds" / _safe(build_id)

    def _release_request_path(self, request_id: str) -> Path:
        # One request replica per operation, addressed without scanning nonce IDs.
        # The full immutable request ID remains in the document and is verified.
        return self.root / "release-requests" / f"{self._request_operation_id(request_id)}.json"

    @staticmethod
    def _validation_checks(
        checks: Mapping[str, str], issues: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        code_for_check = {
            "citation_resolution": {"UNRESOLVED_CITATION"},
            "exhibit_resolution": {"MISSING_EXHIBIT", "UNSUPPORTED_EXHIBIT", "VISUAL_ASSET_UNAVAILABLE"},
            "cross_reference_resolution": {"UNRESOLVED_CROSS_REFERENCE"},
            "render_verification": {item["code"] for item in issues if item["blocking"]},
            "layout_verification": set(),
            "writing_feedback": {"WRITING_FEEDBACK_OPEN"},
            "formal_specification": {"PUBLICATION_FORMAL_INPUT_MISSING", "PUBLICATION_FORMAL_VALUE_UNSUPPORTED"},
            "editorial_qa": set(),
            "final_pdf_machine": set(),
            "final_pdf_human": set(),
        }
        result = []
        for check_id, status in checks.items():
            issue_code = code_for_check[check_id]
            refs = [
                str(issue["defect_id"])
                for issue in issues
                if issue.get("code") in issue_code
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
        policy: Mapping[str, Any],
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
        policy: Mapping[str, Any],
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
            "publication_policy": deepcopy(dict(policy)),
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
            "verification_scope": "Native DOCX structure, literal table cells, exact PNG parts, captions and resolved reference text; rendered layout requires human review.",
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
        final_pdf = receipt.get('publication_policy', {}).get('final_pdf')
        if final_pdf:
            pdf = next((row for row in receipt['outputs'] if row.get('format') == 'pdf'), None)
            canonical_pdf = next((row for row in manifest['outputs'] if row.get('format') == 'pdf'), None)
            if pdf is None or canonical_pdf is None or pdf['digest'] != canonical_pdf['output_digest'] or pdf['relative_path'] != canonical_pdf['path'] or pdf['digest'] != final_pdf.get('pdf_digest'):
                raise LocalApplicationError('APPLICATION-PUBLICATION-INTEGRITY-001', 'Publication final PDF and review/manifest binding does not verify')
        return receipt, manifest, target

    def build_preview(
        self, composition_id: str, revision_id: str | None = None,
        publication_inputs: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        publication_inputs = _validate_publication_inputs(publication_inputs)
        inspection = inspect_inputs(self.facade, composition_id, revision_id)
        package = inspection["source_package_document"]
        profile = self._profile_pin(package)
        from .workspace import LocalWorkspace
        with LocalWorkspace.open(self.workspace) as opened:
            project_config = deepcopy(dict(opened.project_config))
        policy = _publication_policy(package, profile, publication_inputs, project_config)
        revision = inspection["revision"]
        inspection["publication_policy"] = policy
        inspection["publication_profile"] = profile
        inspection["exhibit_blocks"] = prepare_exhibits(inspection, self.workspace)
        build_key = {
            "manuscript_revision_id": revision["revision_id"],
            "manuscript_revision_digest": revision["revision_digest"],
            "research_package_id": package["package_id"],
            "research_package_digest": package["package_digest"],
            "publication_profile": profile,
            "template_pin": _TEMPLATE_PIN,
            "style_map_pin": _STYLE_MAP_PIN,
            "renderer": _RENDERER,
            "publication_inputs": publication_inputs,
            "publication_policy": policy,
            "render_inputs": render_input_digest(inspection["exhibit_blocks"], inspection["visual_diagnostics"]),
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
                policy=policy,
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
                policy=policy,
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

    def finalize_pdf(self, build_id: str, input_: Mapping[str, Any]) -> Mapping[str, Any]:
        """Import a Host-rendered PDF into a new immutable, reviewed build."""
        from .workspace import _safe_locator
        from .publication_pdf import inspect_pdf, coverage_review
        from .publication_formal_report import inspect_formal
        allowed = {'pdf_path', 'pdf_digest', 'source_docx_digest', 'project_config_digest', 'host_receipt', 'review'}
        if not isinstance(input_, Mapping) or set(input_) != allowed:
            raise LocalApplicationError('PUBLICATION-PDF-INPUT', 'PDF finalization requires exact output/config bindings, Host receipt and per-output review')
        source, source_manifest, root = self._load_build(build_id)
        policy = source.get('publication_policy', {})
        if policy.get('document_mode') != 'formal_report' or not policy.get('coverage') or policy.get('missing_inputs') or policy.get('final_pdf'):
            raise LocalApplicationError('PUBLICATION-PDF-INPUT', 'PDF finalization requires a complete MISCO formal-report draft under the coverage Profile')
        self._require_current_renderer(source_manifest)
        self._require_current_project_config(source)
        docx = next(row for row in source['outputs'] if row['format'] == 'docx')
        if input_['source_docx_digest'] != docx['digest'] or input_['project_config_digest'] != policy['project_config_pin']['configuration_digest']:
            raise LocalApplicationError('PUBLICATION-PDF-BINDING', 'PDF finalization does not match the pinned DOCX and Project Config')
        path = _safe_locator(self.workspace, str(input_['pdf_path']))
        try:
            if path.stat().st_size > MAX_OUTPUT_BYTES:
                raise LocalApplicationError('PUBLICATION-PDF-INPUT', 'PDF exceeds the supported bound')
            payload = path.read_bytes()
        except OSError as exc:
            raise LocalApplicationError('PUBLICATION-PDF-INPUT', 'PDF is missing or unreadable') from exc
        if _sha(payload) != input_['pdf_digest']:
            raise LocalApplicationError('PUBLICATION-PDF-BINDING', 'PDF digest differs from the exact input binding')
        host = input_['host_receipt']
        if not isinstance(host, Mapping) or set(host) != {'source_docx_digest', 'pdf_digest', 'software', 'software_version', 'fields_updated', 'page_ranges'} or host.get('source_docx_digest') != docx['digest'] or host.get('pdf_digest') != _sha(payload) or host.get('software') != 'Microsoft Word' or not str(host.get('software_version', '')).strip() or host.get('fields_updated') is not True:
            raise LocalApplicationError('PUBLICATION-PDF-BINDING', 'Host receipt must bind the Word rendering with updated fields to these DOCX/PDF bytes')
        native = (root / docx['relative_path']).read_bytes()
        failures = inspect_formal(native, policy['formal_report'], policy['research_group_type'], policy['formal_spec_profile']['docx_layout'])
        if failures:
            raise LocalApplicationError('PUBLICATION-FORMAL-RENDER-001', '; '.join(failures))
        with zipfile.ZipFile(io.BytesIO(native)) as archive:
            document = ElementTree.fromstring(archive.read('word/document.xml'))
            word_ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            required = []
            for paragraph in document.iter('{%s}p' % word_ns):
                if len(list(paragraph.iter('{%s}p' % word_ns))) > 1:
                    continue
                texts = [t.text or '' for t in paragraph.iter('{%s}t' % word_ns)]
                if paragraph.find('.//{%s}footnoteReference' % word_ns) is not None:
                    required.extend(value for value in texts if value != '*')
                else:
                    required.append(''.join(texts))
        required = [value for value in required if value and value != '要更新']
        for footnote in policy['formal_report'].get('footnotes', []):
            required.append(footnote['text'])
        expected_parts = [node.get('{urn:research-loom:publication}part') for node in document.iter('{%s}sectPr' % word_ns)]
        machine = inspect_pdf(payload, required_text=required, page_ranges=host['page_ranges'], expected_parts=expected_parts)
        review = input_['review']
        if not isinstance(review, Mapping) or not {'pdf_digest', 'reviewer_id', 'reviewed_at', 'checks', 'pages'} <= set(review) or set(review) - {'pdf_digest', 'reviewer_id', 'reviewed_at', 'checks', 'pages', 'presentation_review'}:
            raise LocalApplicationError('PUBLICATION-PDF-INPUT', 'Review requires exact PDF digest, reviewer/time, checks and every page')
        human = coverage_review(policy['coverage'], policy, review, _sha(payload), machine['page_count'], page_ranges=host['page_ranges'])
        key = _sha(_canonical_bytes({'source_build_digest': source['content_digest'], 'finalization': dict(input_)}))
        final_id = 'PUBPDF-' + key.removeprefix('sha256:')[:24]
        target = self._build_path(final_id)
        with self._file_lock(final_id):
            if target.exists():
                existing, manifest, _ = self._load_build(final_id)
                return {'status': 'VERIFIED_REUSE', 'build': existing, 'preview_manifest': manifest, 'research_state_mutation_performed': False}
            receipt = deepcopy(source)
            manifest = deepcopy(source_manifest)
            receipt.update({'build_id': final_id, 'build_key_digest': key})
            receipt['publication_policy']['final_pdf'] = {'source_build_id': build_id, 'source_build_digest': source['content_digest'], 'host_receipt': deepcopy(host), 'machine_inspection': {k: v for k, v in machine.items() if k != 'page_text'}, 'human_review': human, 'pdf_digest': _sha(payload), 'submission_status': 'not_submitted'}
            receipt['outputs'].append({'format': 'pdf', 'relative_path': 'final.pdf', 'media_type': 'application/pdf', 'size': len(payload), 'digest': _sha(payload)})
            receipt['verification']['final_pdf_machine'] = 'failed' if machine['problems'] else 'passed'
            receipt['verification']['final_pdf_human'] = 'failed' if human['problems'] else 'passed'
            receipt['verification']['formal_specification'] = 'failed' if machine['problems'] or human['problems'] else 'passed'
            deviations = [row['check_id'] for row in human['applicability'] if row['applicable'] and row['force'] == 'should' and row['review'] and row['review']['status'] == 'warning']
            receipt['publication_policy']['final_pdf']['documented_deviations'] = deviations
            if deviations and receipt['verification']['formal_specification'] == 'passed':
                receipt['verification']['formal_specification'] = 'warning'
            receipt['verification']['editorial_qa'] = 'failed' if human['problems'] else 'passed'
            receipt['verification']['layout_verification'] = 'failed' if machine['problems'] or human['problems'] else 'passed'
            receipt['verification_scope'] = 'Native formal structure/styles and exact PDF size/page counts/text/fonts; individual original-clause checks and every rendered page explicitly reviewed by the named reviewer.'
            manifest['preview_id'] = final_id
            manifest['outputs'].append({'format': 'pdf', 'path': 'final.pdf', 'output_digest': _sha(payload), 'input_template_digest': _TEMPLATE_PIN['content_digest'], 'input_style_map_digest': _STYLE_MAP_PIN['content_digest']})
            manifest['validation_checks'] = self._validation_checks(receipt['verification'], receipt['issues'])
            manifest['content_digest'] = _digest(manifest, 'content_digest')
            _validate_preview_manifest(manifest)
            receipt['preview_manifest_digest'] = manifest['content_digest']
            receipt['content_digest'] = _digest(receipt, 'content_digest')
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix='.' + final_id + '.', dir=target.parent))
            try:
                for output in source['outputs']:
                    (staging / output['relative_path']).write_bytes((root / output['relative_path']).read_bytes())
                (staging / 'final.pdf').write_bytes(payload)
                (staging / 'preview-manifest.json').write_bytes(_json_bytes(manifest))
                (staging / 'build-receipt.json').write_bytes(_json_bytes(receipt))
                os.rename(staging, target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        return {'status': 'BUILT', 'build': receipt, 'preview_manifest': manifest, 'research_state_mutation_performed': False}

    def _require_current_project_config(self, build: Mapping[str, Any]) -> None:
        pin = build.get('publication_policy', {}).get('project_config_pin')
        if not build.get('publication_policy', {}).get('coverage'):
            return
        from .workspace import LocalWorkspace
        with LocalWorkspace.open(self.workspace) as opened:
            if not pin or pin['configuration_digest'] != opened.project_config['configuration_digest']:
                raise LocalApplicationError('PROJECT-CONFIG-STALE-001', 'Publication formal output is bound to an older Project Config')

    @staticmethod
    def _formal_output(build):
        format_ = 'pdf' if build.get('publication_policy', {}).get('coverage') else 'docx'
        return next((row for row in build['outputs'] if row['format'] == format_), None)

    @staticmethod
    def _release_checks_pass(
        build: Mapping[str, Any], preview: Mapping[str, Any]
    ) -> bool:
        if preview.get("source_epistemic_status") != "EMPIRICAL_RESEARCH_STATE":
            return False
        required_checks = ["citation_resolution", "exhibit_resolution", "cross_reference_resolution", "render_verification"]
        if build.get("publication_profile", {}).get("profile_id") == "misco.publication":
            required_checks.extend(["formal_specification", "editorial_qa"])
        if build.get('publication_policy', {}).get('coverage'):
            required_checks.extend(['final_pdf_machine', 'final_pdf_human'])
            if PublicationReleaseService._formal_output(build) is None:
                return False
        def accepted(key):
            value = build['verification'].get(key)
            if value == 'passed':
                return True
            final = build.get('publication_policy', {}).get('final_pdf', {})
            return key == 'formal_specification' and value == 'warning' and bool(final.get('documented_deviations')) and build['verification'].get('final_pdf_machine') == 'passed' and build['verification'].get('final_pdf_human') == 'passed'
        if any(not accepted(key) for key in required_checks):
            return False
        return not any(
            value == "failed"
            for key, value in build["verification"].items()
            if key != "writing_feedback"
        )

    def _request_binding(
        self, build: Mapping[str, Any], preview: Mapping[str, Any], actor_id: str,
    ) -> dict[str, Any]:
        formal = self._formal_output(build)
        return {
            "project_ref": self.facade.project_id,
            "human_actor_id": actor_id,
            "source_preview": {
                "preview_id": build["build_id"],
                "preview_digest": preview["content_digest"],
            },
            "source_manuscript": build["source_manuscript"],
            "snapshot_binding": build["research_provenance"]["research_snapshot"],
            "publication_profile": build["publication_profile"],
            "publication_policy_digest": _sha(_canonical_bytes(build.get("publication_policy", {}))),
            "output_binding": {
                "format": formal['format'], "digest": formal["digest"], "size": formal["size"],
            },
            "allowed_dispositions": ["approve_release"],
            **({"required_human_review": "Inspect every rendered page, including table cells, images, captions, reference targets, layout, and the delivered Publication editorial/formal rules before approving these exact output bytes."}
               if "layout_verification" in build["verification"] else {}),
        }

    @staticmethod
    def _require_current_renderer(preview: Mapping[str, Any]) -> None:
        if preview.get("renderer") != _RENDERER:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-REBUILD-REQUIRED-001",
                "Create a new preview with the current renderer before a new approval; retain historical releases unchanged",
            )

    @staticmethod
    def _read_release_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                f"stored Publication record is unreadable: {path.name}",
            ) from exc
        if not isinstance(value, dict):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                f"stored Publication record must be an object: {path.name}",
            )
        return value

    def _verify_release_binding(
        self, manifest: Mapping[str, Any], *, release_id: str, decision_id: str,
        request: Mapping[str, Any], build: Mapping[str, Any],
        preview: Mapping[str, Any],
    ) -> None:
        """Verify against the independently approved build, not only self-digests."""
        formal = self._formal_output(build)
        expected = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "release_manifest",
            "release_id": release_id,
            "source_preview": {
                "preview_id": build["build_id"],
                "preview_digest": preview["content_digest"],
            },
            "source_manuscript": build["source_manuscript"],
            "research_provenance": build["research_provenance"],
            "publication_profile": build["publication_profile"],
            "publication_policy_digest": _sha(_canonical_bytes(build.get("publication_policy", {}))),
            "output": {
                "relative_path": 'artifact.' + formal['format'],
                "artifact_reference": f"publication/releases/{release_id}/artifact." + formal['format'],
                "media_type": formal["media_type"],
                "size": formal["size"],
                "digest": formal["digest"],
            },
            "verification": build["verification"],
            "research_state_mutation_performed": False,
        }
        decision = manifest.get("human_release_decision")
        expected_decision = {
            "decision_id": decision_id,
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_release",
            "actor": {"actor_id": request["human_actor_id"], "actor_type": "human"},
        }
        if (
            manifest.get("content_digest") != _digest(manifest, "content_digest")
            or any(manifest.get(key) != value for key, value in expected.items())
            or not isinstance(decision, Mapping)
            or any(decision.get(key) != value for key, value in expected_decision.items())
            or decision.get("decision_digest") != _digest(decision, "decision_digest")
            or not isinstance(decision.get("decided_at"), str)
            or not decision["decided_at"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "stored Release does not match its exact approved request and preview build",
            )

    @staticmethod
    def _request_operation_id(request_id: str) -> str:
        # New IDs carry a nonce; the stable prefix addresses their operation.
        # Legacy IDs remain readable without assigning new historical facts.
        match = re.fullmatch(r"(PUBRELREQ-[0-9a-f]{24})(?:-[0-9a-f]{32})?", request_id)
        return match.group(1) if match else _safe(request_id)

    def _operation_path(self, request_id: str) -> Path:
        return self.root / "release-operations" / f"{self._request_operation_id(request_id)}.json"

    def _checked_record_path(self, path: Path) -> Path:
        from .workspace import _safe_locator
        return _safe_locator(self.workspace, path.relative_to(self.workspace).as_posix(), require_exists=False)

    def _load_release_operation(self, request_id: str) -> dict[str, Any] | None:
        path = self._checked_record_path(self._operation_path(request_id))
        if not path.exists():
            return None
        record = self._read_release_json(path)
        request = record.get("request")
        if (
            record.get("object_type") != "publication_release_operation"
            or record.get("operation_digest") != _digest(record, "operation_digest")
            or record.get("phase") not in {"PENDING", "DECIDED"}
            or not isinstance(request, dict)
            or not isinstance(request.get("request_id"), str)
            or self._request_operation_id(request["request_id"]) != self._request_operation_id(request_id)
            or request.get("request_digest") != _digest(request, "request_digest")
            or (record["phase"] == "DECIDED") != isinstance(record.get("release"), dict)
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication operation record does not verify; restore its exact backup or request a new approval with renewal_of",
            )
        return record

    def _atomic_release_write(self, path: Path, data: bytes, *, replace: bool = False) -> None:
        path = self._checked_record_path(path)
        staging = None
        fd = None
        try:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=".publication-", dir=path.parent)
                staging = Path(name)
                with os.fdopen(fd, "wb") as stream:
                    fd = None  # The stream now owns the descriptor.
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if replace:
                    os.replace(staging, path)
                else:
                    try:
                        os.link(staging, path)
                    except FileExistsError:
                        if path.read_bytes() != data:
                            raise LocalApplicationError(
                                "APPLICATION-PUBLICATION-INTEGRITY-001",
                                "Publication recovery refuses to replace different existing bytes",
                            )
            finally:
                if fd is not None:
                    os.close(fd)
                if staging is not None:
                    staging.unlink(missing_ok=True)
        except OSError as exc:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-WRITE-001",
                "Publication record could not be persisted; retry the exact request after resolving the I/O error",
            ) from exc

    def _write_release_operation(self, request: Mapping[str, Any], manifest=None) -> None:
        record = {
            "object_type": "publication_release_operation",
            "phase": "PENDING" if manifest is None else "DECIDED",
            "request": deepcopy(dict(request)),
            "release": deepcopy(manifest),
            "operation_digest": "",
        }
        record["operation_digest"] = _digest(record, "operation_digest")
        self._atomic_release_write(self._operation_path(request["request_id"]), _json_bytes(record), replace=True)

    @staticmethod
    def _lost_release_facts() -> None:
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-RECOVERY-REQUIRED-001",
            "Original Publication request/decision facts are unavailable. Restore the exact operation record, "
            "or issue release-request with renewal_of set to the old request_id and obtain a new approval; "
            "do not recreate the old identity or timestamps",
        )

    def request_release(
        self, build_id: str, actor_id: str, *, renewal_of: str | None = None,
    ) -> Mapping[str, Any]:
        if not isinstance(actor_id, str) or not actor_id:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "human release actor_id is required",
            )
        shown = self.show_preview(build_id)
        build = shown["build"]
        preview = shown["preview_manifest"]
        self._require_current_project_config(build)
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
        if renewal_of is not None:
            if not isinstance(renewal_of, str) or not renewal_of.startswith("PUBRELREQ-"):
                raise LocalApplicationError("APPLICATION-PUBLICATION-INPUT-001", "renewal_of must be a Publication request ID")
            basis["renewal_of"] = _safe(renewal_of)
        operation_id = "PUBRELREQ-" + _sha(_canonical_bytes(basis)).split(":", 1)[1][:24]
        with self._file_lock(f"request-{operation_id}"):
            operation = self._load_release_operation(operation_id)
            legacy_path = self._checked_record_path(self._release_request_path(operation_id))
            if operation is not None or legacy_path.exists():
                request = operation["request"] if operation else self._read_release_json(legacy_path)
                expected = self._request_binding(build, preview, actor_id)
                if (
                    self._request_operation_id(str(request.get("request_id", ""))) != operation_id
                    or request.get("request_digest") != _digest(request, "request_digest")
                    or any(request.get(key) != value for key, value in expected.items())
                    or request.get("renewal_of") != renewal_of
                ):
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Publication release request does not match its exact operation binding",
                    )
                if operation is None and request.get("recovery_contract") == "release-operation-v1":
                    # The replica cannot prove whether approval already committed.
                    self._lost_release_facts()
                path = self._checked_record_path(self._release_request_path(request["request_id"]))
                if path.exists():
                    if self._read_release_json(path) != request:
                        raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Publication request differs from its operation record")
                    return {"status": "VERIFIED_REUSE", "decision_request": request}
                self._atomic_release_write(path, _json_bytes(request))
                return {"status": "RESTORED", "decision_request": request,
                        "recovered_at": self.facade._application.clock.now()}

            self._require_current_renderer(preview)
            from uuid import uuid4
            request: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "publication_release_decision_request",
                "request_id": operation_id + "-" + uuid4().hex,
                **deepcopy(self._request_binding(build, preview, actor_id)),
                "issued_at": self.facade._application.clock.now(),
                "recovery_contract": "release-operation-v1",
                "renewal_of": renewal_of,
                "request_digest": "",
            }
            request["request_digest"] = _digest(request, "request_digest")
            # The operation is the write-ahead record for request/decision facts.
            # A response loss cannot invent another issued_at or decided_at.
            self._write_release_operation(request)
            self._atomic_release_write(self._release_request_path(request["request_id"]), _json_bytes(request))
        return {"status": "PENDING", "decision_request": request}

    def _load_release_request(self, request_id: str) -> Mapping[str, Any]:
        operation = self._load_release_operation(request_id)
        path = self._checked_record_path(self._release_request_path(request_id))
        if not path.exists():
            # Older replicas used the complete nonce ID. Probe only the exact
            # caller-supplied identity; do not scan unrelated request history.
            legacy = self._checked_record_path(self.root / "release-requests" / f"{_safe(request_id)}.json")
            if legacy.exists():
                path = legacy
        if operation is not None:
            request = operation["request"]
            if path.exists() and self._read_release_json(path) != request:
                raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Publication request differs from its operation record")
        elif path.is_file():
            request = self._read_release_json(path)
        else:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication request is missing; restore the exact record or issue a new release-request and approval",
            )
        if (
            request.get("request_id") != request_id
            or request.get("request_digest") != _digest(request, "request_digest")
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication release request identity/digest does not verify",
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
        if any(request.get(key) != value for key, value in self._request_binding(build, preview, str(response["actor_id"])).items()):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release request is stale or bound to another build/output",
            )
        formal = self._formal_output(build)
        decision_id = "PUBRELDEC-" + hashlib.sha256(
            (request["request_digest"] + str(response["actor_id"]) + str(response["disposition"])).encode("utf-8")
        ).hexdigest()[:24]
        release_id = "REL-" + hashlib.sha256(
            (build_id + preview["content_digest"] + decision_id).encode("utf-8")
        ).hexdigest()[:24]
        operation_id = self._request_operation_id(request["request_id"])
        with self._file_lock(f"request-{operation_id}"):
            operation = self._load_release_operation(request["request_id"])
            if operation is not None and operation["request"] != request:
                raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Publication operation changed its request identity")
            target = self._checked_record_path(self.root / "releases" / release_id)
            manifest_path = self._checked_record_path(target / "release-manifest.json")
            artifact = self._checked_record_path(target / ('artifact.' + formal['format']))
            payload = (self._build_path(build_id) / formal['relative_path']).read_bytes()
            if len(payload) != int(formal["size"]) or _sha(payload) != formal["digest"] or (formal['format'] == 'docx' and not _verify_docx_bytes(payload)):
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication DOCX does not match its exact approved preview build",
                )
            existing = self._read_release_json(manifest_path) if manifest_path.exists() else None
            if existing is not None:
                self._verify_release_binding(existing, release_id=release_id, decision_id=decision_id,
                                             request=request, build=build, preview=preview)
            if artifact.exists():
                try:
                    matches = artifact.is_file() and artifact.read_bytes() == payload
                except OSError as exc:
                    raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "stored Release artifact is unreadable") from exc
                if not matches:
                    raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "stored Release artifact differs from the exact approved output")

            fresh = operation is not None and operation["phase"] == "PENDING"
            operation_restored = False
            if operation is not None and operation["phase"] == "DECIDED":
                manifest = operation["release"]
                self._verify_release_binding(manifest, release_id=release_id, decision_id=decision_id,
                                             request=request, build=build, preview=preview)
                if existing is not None and existing != manifest:
                    raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Release differs from its retained decision facts")
            elif existing is not None:
                if fresh:
                    raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Release exists before its recorded decision")
                # Supported legacy recovery: the original immutable manifest,
                # including its decision time, still exists and verifies.
                manifest = existing
                self._write_release_operation(request, manifest)
                operation_restored = True
            elif operation is None:
                self._lost_release_facts()
            else:
                self._require_current_renderer(preview)
                self._require_current_project_config(build)
                decision = {
                    "decision_id": decision_id,
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_release",
                    "actor": {"actor_id": str(response["actor_id"]), "actor_type": "human"},
                    "decided_at": self.facade._application.clock.now(),
                    "decision_digest": "",
                }
                decision["decision_digest"] = _digest(decision, "decision_digest")
                manifest = {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "release_manifest",
                    "release_id": release_id,
                    "source_preview": {"preview_id": build_id, "preview_digest": preview["content_digest"]},
                    "source_manuscript": deepcopy(build["source_manuscript"]),
                    "research_provenance": deepcopy(build["research_provenance"]),
                    "publication_profile": deepcopy(build["publication_profile"]),
                    "publication_policy_digest": _sha(_canonical_bytes(build.get("publication_policy", {}))),
                    "output": {
                        "relative_path": 'artifact.' + formal['format'],
                        "artifact_reference": f"publication/releases/{release_id}/artifact." + formal['format'],
                        "media_type": formal["media_type"], "size": len(payload), "digest": _sha(payload),
                    },
                    "verification": deepcopy(build["verification"]),
                    "human_release_decision": decision,
                    "research_state_mutation_performed": False,
                    "content_digest": "",
                }
                manifest["content_digest"] = _digest(manifest, "content_digest")
                self._write_release_operation(request, manifest)

            restored = ["release-operation"] if operation_restored else []
            for part, data in ((self._release_request_path(request["request_id"]), _json_bytes(request)),
                               (artifact, payload), (manifest_path, _json_bytes(manifest))):
                if not part.exists():
                    self._atomic_release_write(part, data)
                    restored.append(part.name)
            result = {"status": "RELEASED" if fresh else ("RESTORED" if restored else "VERIFIED_REUSE"),
                      "release": manifest, "research_state_mutation_performed": False}
            if restored and not fresh:
                result["restored_components"] = restored
                result["recovered_at"] = self.facade._application.clock.now()
            return result
