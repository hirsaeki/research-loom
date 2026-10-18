"""Organization-specific Publication conventions behind one extension point (#495).

Generic Publication code never branches on a Profile id. It asks the dialect that
the composition root maps to the pinned Publication Profile; a Profile without an
entry gets the generic ``PublicationDialect``. Organization layers subclass it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublicationDialect:
    """Generic Publication conventions; every hook leaves the generic result unchanged."""

    table_label: str = "Table"
    figure_label: str = "Figure"
    citations_prefix: str = "Citations: "
    source_prefix: str = "Source: "
    # Visual exhibits must cite exact Sources with bibliographic metadata.
    strict_visual_sources: bool = False
    # Verification checks a release needs on top of the generic ones.
    release_checks: tuple[str, ...] = ()
    # Editorial check that records the overall review verdict and must be present.
    editorial_overall_check: str | None = None
    # Body page range a final PDF should meet, and the check recording a deviation.
    body_page_range: tuple[int, int] | None = None
    body_length_check: str | None = None

    def require_resources(self, by_role: Mapping[str, Any]) -> None:
        """Reject a Profile whose pinned Publication resources are incomplete."""

    def saved_research_group_type(self, project_config: Mapping[str, Any]) -> Any:
        """Research group type saved in the Project Config, when the dialect uses one."""
        return None

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
        """Publication inputs the dialect still requires, as INPUT-* codes."""
        return []

    def validate_editorial_review(self, editorial: Any) -> None:
        """Reject an editorial review that lacks what the dialect requires."""

    def chart_note(
        self, note: str, spec: Mapping[str, Any], exhibit: Mapping[str, Any], block: dict[str, Any]
    ) -> str:
        """Note under a generated chart; may also relabel the block's legend header."""
        return note

    def diagram_note(self, note: str, value: Mapping[str, Any]) -> str:
        """Note under a generated diagram."""
        return note


GENERIC_PUBLICATION_DIALECT = PublicationDialect()


def dialect_for(
    profile: Mapping[str, Any], dialects: Mapping[str, PublicationDialect]
) -> PublicationDialect:
    """Dialect mapped to a Publication Profile id, or the generic one."""
    return dialects.get(str(profile.get("profile_id")), GENERIC_PUBLICATION_DIALECT)
