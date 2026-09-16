from __future__ import annotations

from html.parser import HTMLParser
from threading import RLock
from typing import Any, Mapping

from .facade import LocalApplicationError
from . import new_material_continuation_service as _base

_INSTALL_LOCK = RLock()
_INSTALLED = False
_BASE_CAPTURE = _base.NewMaterialContinuationService._capture_new_material_version


class _SafeG1HtmlTextParser(HTMLParser):
    """Conservatively preserve skip scope across malformed HTML end tags."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag in _base._HTML_SKIP_TAGS:
            self.skip_tags.append(tag)
        elif not self.skip_tags and tag in _base._HTML_BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_tags:
            if tag == self.skip_tags[-1]:
                self.skip_tags.pop()
            return
        if tag in _base._HTML_CONTAINER_BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_tags:
            self.parts.append(data)


def _capture_budget_for_run(self, new_run) -> Mapping[str, Any]:
    extension = self._application.context_extension_store.load(
        new_run.capability_id,
        new_run.capability_version,
        new_run.function_id,
        new_run.context_pack_id,
    )
    budget = extension.get("budget") if isinstance(extension, Mapping) else None
    if not isinstance(budget, Mapping):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
            "new Desktop Research Run has no valid capture budget binding",
        )
    return budget


def _capture_with_pinned_html_budget(
    self,
    new_run,
    historical,
    historical_extension: Mapping[str, Any],
    result: Mapping[str, Any],
    new_artifact,
    reacquisition_run_id: str,
) -> dict[str, str]:
    kind = str(result.get("new_material_kind") or result.get("kind") or "")
    if kind == "original":
        budget = _capture_budget_for_run(self, new_run)
        try:
            store_limit = int(self._application.execution_store.config.max_artifact_bytes)
            original_declared = budget.get("max_original_capture_bytes")
            original_limit = (
                store_limit
                if original_declared is None
                else min(store_limit, int(original_declared))
            )
            text_limit = min(store_limit, int(budget["max_text_rendition_bytes"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                "new Desktop Research Run capture budget is malformed",
            ) from exc
        if min(original_limit, text_limit) < 0:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                "new Desktop Research Run capture budget is malformed",
            )
        if len(new_artifact.content) > original_limit:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                "reacquired original exceeds the pinned capture budget",
            )
        _base._render_reacquired_html_rendition(
            new_artifact.content,
            new_artifact.media_type,
            max_bytes=text_limit,
        )
    return _BASE_CAPTURE(
        self,
        new_run,
        historical,
        historical_extension,
        result,
        new_artifact,
        reacquisition_run_id,
    )


def install_new_material_continuation_html_hardening() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _base._G1HtmlTextParser = _SafeG1HtmlTextParser
        _base.NewMaterialContinuationService._capture_new_material_version = (
            _capture_with_pinned_html_budget
        )
        _INSTALLED = True
