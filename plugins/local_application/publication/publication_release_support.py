"""Publication release constants, pins, policy and input validation (#494)."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from xml.etree import ElementTree

from jsonschema import Draft202012Validator, FormatChecker

from core.resources import resource_path
from plugins.application_errors import LocalApplicationError

SCHEMA_VERSION = "0.1.0"
SERVICE_VERSION = "0.2.0"
MAX_SECTIONS = 128
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_XREF = re.compile(r"\[\[(section|exhibit|citation):([^\]]+)\]\]")
_APPLICATION_SCHEMA = resource_path(
    "core/packages/writer-publication/publication-application.schema.json"
)
_PREVIEW_SCHEMA = resource_path("core/packages/writer-publication/publication-preview.schema.json")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest(value: Mapping[str, Any], field: str) -> str:
    copy = deepcopy(dict(value))
    copy.pop(field, None)
    return _sha(_canonical_bytes(copy))


def _safe(value: str) -> str:
    if not value or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
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
    "tool_digest": _sha(
        b"research-loom.deterministic-docx@0.3.0;misco-formal-sections;exact-pdf-review;provenance-v2"
    ),
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
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INPUT-001", f"{key} source_digest is invalid"
                )
    permission_ids = [row["source_ref"] for row in normalized.get("permissions", [])]
    if len(permission_ids) != len(set(permission_ids)):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-INPUT-001", "Permissions must identify each Source once"
        )
    return normalized


def _source_tags(source):
    return {
        str(source.get(key, "")).lower()
        for key in ["access_classification", "source_classification", "source_type"]
    }


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


def _publication_policy(
    package: Mapping[str, Any],
    profile: Mapping[str, Any],
    inputs: Mapping[str, Any],
    project_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
    if (
        isinstance(explicit_formal, Mapping)
        and isinstance(pinned_formal, Mapping)
        and dict(explicit_formal) != dict(pinned_formal)
    ):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-PROFILE-001",
            "explicit formal_spec_profile conflicts with the pinned MISCO Publication formal-spec resource",
        )
    if (
        isinstance(explicit_url_profile, Mapping)
        and isinstance(pinned_url_profile, Mapping)
        and dict(explicit_url_profile) != dict(pinned_url_profile)
    ):
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-PROFILE-001",
            "explicit url_display_profile conflicts with the pinned MISCO Publication URL-display resource",
        )
    formal = explicit_formal if isinstance(explicit_formal, Mapping) else pinned_formal
    url_profile = (
        explicit_url_profile if isinstance(explicit_url_profile, Mapping) else pinned_url_profile
    )
    group_type = inputs.get("research_group_type")
    if isinstance(group_type, str) and not group_type.strip():
        group_type = None
    document_mode = inputs.get("document_mode", "body_preview")
    report = inputs.get("formal_report")
    config_pin = None
    saved = None
    if project_config is not None:
        config_pin = {
            "config_version": project_config["config_version"],
            "configuration_digest": project_config["configuration_digest"],
        }
        if (
            inputs.get("project_config_digest") is not None
            and inputs["project_config_digest"] != config_pin["configuration_digest"]
        ):
            raise LocalApplicationError(
                "PROJECT-CONFIG-STALE-001",
                "Publication input targets a different Project Config generation",
            )
        saved = (
            project_config.get("publication_metadata", {}).get("research_group_type")
            if profile.get("profile_id") == "misco.publication"
            else None
        )
        if isinstance(saved, str) and not saved.strip():
            saved = None
        if saved is not None and group_type is not None and saved != group_type:
            raise LocalApplicationError(
                "INPUT-RESEARCH-GROUP-TYPE-CONFLICT",
                "Explicit Publication group conflicts with saved project metadata",
            )
        group_type = saved or group_type
    permissions = inputs.get("permissions", [])
    editorial = inputs.get("editorial_review")
    missing = []
    if profile.get("profile_id") == "misco.publication":
        if (
            document_mode == "formal_report"
            and group_type is not None
            and group_type not in {"G", "M"}
        ):
            raise LocalApplicationError(
                "INPUT-RESEARCH-GROUP-TYPE",
                "MISCO formal report requires an explicit G or M answer",
            )
        if document_mode == "formal_report" and not coverage:
            missing.append("INPUT-FORMAL-COVERAGE")
        if document_mode == "formal_report" and not isinstance(report, Mapping):
            missing.append("INPUT-FORMAL-REPORT")
        if not isinstance(formal, Mapping) or not isinstance(
            formal.get("research_group_type_required"), bool
        ):
            missing.append("INPUT-FORMAL-SPEC")
        elif (
            (formal["research_group_type_required"] or document_mode == "formal_report")
            and document_mode == "formal_report"
            and not group_type
        ):
            missing.append("INPUT-RESEARCH-GROUP-TYPE")
        if coverage and document_mode == "formal_report" and group_type and saved is None:
            missing.append("INPUT-RESEARCH-GROUP-TYPE-SAVE")
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
        permission_by_source = {
            str(row.get("source_ref")): row for row in permissions if isinstance(row, Mapping)
        }
        if any(
            ref not in permission_by_source
            or not permission_by_source[ref].get("publication_allowed")
            or not permission_by_source[ref].get("original_reviewed")
            or permission_by_source[ref].get("company_disclosure") not in {"allowed", "anonymized"}
            for ref in required_permissions
        ):
            missing.append("INPUT-PERMISSION")
    if profile.get("profile_id") == "misco.publication" and isinstance(editorial, Mapping):
        editorial_rows = {
            str(row.get("check_id")): row
            for row in editorial.get("checks", [])
            if isinstance(row, Mapping)
        }
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
            "rule_ids": sorted(
                str(item["id"])
                for item in rules.get("items", [])
                if isinstance(item, Mapping) and item.get("id")
            ),
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
        "conformance_scope": "formal_report"
        if document_mode == "formal_report"
        else "partial_body_preview",
        "coverage": deepcopy(coverage),
        "formal_report": deepcopy(report),
        "host_questions": [
            {
                "input_id": "INPUT-RESEARCH-GROUP-TYPE",
                "question": "今回の報告書はG研究会とM研究会のどちらですか？",
                "save_via": "profile resolve publication_metadata then profile advance",
            }
        ]
        if "INPUT-RESEARCH-GROUP-TYPE" in missing
        else [],
        "host_actions": [
            {
                "input_id": "INPUT-RESEARCH-GROUP-TYPE-SAVE",
                "research_group_type": group_type,
                "save_via": "profile resolve publication_metadata then profile advance",
                "expected_project_config_digest": config_pin["configuration_digest"]
                if config_pin
                else None,
            }
        ]
        if "INPUT-RESEARCH-GROUP-TYPE-SAVE" in missing
        else [],
        "permissions": deepcopy(list(permissions)),
        "review_conditions": {
            "interview": any(
                "interview" in _source_tags(row)
                for row in package.get("resolved_content", {}).get("research_objects", [])
                if row.get("kind") == "source"
            ),
            "company_information": any(
                bool(_source_tags(row) & {"internal", "non-public", "confidential"})
                for row in package.get("resolved_content", {}).get("research_objects", [])
                if row.get("kind") == "source"
            ),
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
