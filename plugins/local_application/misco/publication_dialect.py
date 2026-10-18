"""MISCO Publication conventions, selected by the ``misco.publication`` Profile (#495)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from plugins.application_errors import LocalApplicationError

from ..publication.publication_dialect import PublicationDialect
from ..publication.publication_release_support import source_tags
from . import formal_report

MISCO_PUBLICATION_PROFILE_ID = "misco.publication"
MISCO_EDITORIAL_QA = "misco-editorial-qa"


@dataclass(frozen=True)
class MiscoPublicationDialect(PublicationDialect):
    table_label: str = "表"
    figure_label: str = "図"
    citations_prefix: str = "出典："
    source_prefix: str = "出典："
    strict_visual_sources: bool = True
    release_checks: tuple[str, ...] = ("formal_specification", "editorial_qa")
    editorial_overall_check: str | None = MISCO_EDITORIAL_QA
    body_page_range: tuple[int, int] | None = (50, 60)
    body_length_check: str | None = "misco-body-length"

    def require_resources(self, by_role: Mapping[str, Any]) -> None:
        roles = (
            "PUBLICATION_RULES",
            "PUBLICATION_SOURCE_DOCUMENTS",
            "PUBLICATION_FORMAL_SPEC",
            "PUBLICATION_URL_DISPLAY",
        )
        if any(by_role.get(role) is None for role in roles):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-PROFILE-001",
                "MISCO Publication requires verified rule, source-document, formal-spec, and URL-display resources",
            )

    def saved_research_group_type(self, project_config: Mapping[str, Any]) -> Any:
        return project_config.get("publication_metadata", {}).get("research_group_type")

    def missing_inputs(
        self,
        *,
        package: Mapping[str, Any],
        document_mode: Any,
        group_type: Any,
        saved_group_type: Any,
        coverage: Any,
        report: Any,
        formal: Any,
        url_profile: Any,
        permissions: Any,
    ) -> list[str]:
        missing = []
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
        if (
            coverage
            and document_mode == "formal_report"
            and group_type
            and saved_group_type is None
        ):
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
            and bool(source_tags(row) & {"internal", "non-public", "confidential", "interview"})
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
        return missing

    def validate_editorial_review(self, editorial: Any) -> None:
        if not isinstance(editorial, Mapping):
            return
        editorial_rows = {
            str(row.get("check_id")): row
            for row in editorial.get("checks", [])
            if isinstance(row, Mapping)
        }
        if editorial_rows.get(MISCO_EDITORIAL_QA) is None:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INPUT-001",
                "MISCO editorial review must include misco-editorial-qa",
            )

    def chart_note(
        self, note: str, spec: Mapping[str, Any], exhibit: Mapping[str, Any], block: dict[str, Any]
    ) -> str:
        unit_labels = list(dict.fromkeys(v for v in spec["units"].values() if v is not None))
        note = "単位：" + "、".join(unit_labels) + "。"
        if spec["caption"] != exhibit.get("title"):
            note = spec["caption"] + "\n" + note
        note += (
            "\n対象："
            + (spec["denominator"] or "記載なし")
            + "。対象年："
            + (spec["period"] or "記載なし")
            + "。"
        )
        if "legend_rows" in block:
            x_unit, y_unit = (
                spec["units"][spec["x_column"]],
                spec["units"][spec["y_column"]],
            )
            x_label = "区分" if spec["chart_type"] == "bar" else "横軸の値"
            block["legend_rows"][0] = [
                "番号",
                x_label + (f"（{x_unit}）" if x_unit else ""),
                "値" + (f"（{y_unit}）" if y_unit else ""),
            ]
        return note

    def diagram_note(self, note: str, value: Mapping[str, Any]) -> str:
        note = "図に示す内容：" + "、".join(value["request"]["allowed_labels"]) + "。"
        note += "\n既存の研究内容を整理した図であり、新たな研究上の結論を示すものではない。"
        return note

    def formal_report_requested(self, policy: Mapping[str, Any]) -> bool:
        return (
            policy.get("document_mode") == "formal_report"
            and isinstance(policy.get("formal_report"), Mapping)
            and policy.get("research_group_type") in {"G", "M"}
        )

    def formal_outline(self, structure: Any, section_ids: list[str]) -> dict[str, Any]:
        return formal_report.outline(structure, section_ids)

    def assemble_formal_report(self, docx: bytes, report: dict, group: str, layout: dict) -> bytes:
        return formal_report.assemble(docx, report, group, layout)

    def inspect_formal_report(
        self, docx: bytes, report: dict, group: str, layout: dict
    ) -> list[str]:
        return formal_report.inspect_formal(docx, report, group, layout)


MISCO_PUBLICATION_DIALECT = MiscoPublicationDialect()
PUBLICATION_DIALECTS = {MISCO_PUBLICATION_PROFILE_ID: MISCO_PUBLICATION_DIALECT}
