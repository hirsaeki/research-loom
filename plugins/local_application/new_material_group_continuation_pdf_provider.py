from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from threading import RLock

from .facade import LocalApplicationError
from . import new_material_group_continuation_service as _group
from .material_reacquisition_facade import MaterialReacquisitionRetrievalError
from .material_reacquisition_pypdf_provider import (
    _regenerate_text_rendition as _regenerate_pinned_text_rendition,
)

_INSTALL_LOCK = RLock()
_INSTALLED = False
_BASE_RENDER = _group._render_reacquired_html_rendition
_BASE_CAPTURE_SERVICE = _group.DesktopResearchCaptureService
_BASE_CAPTURE_GROUP = _group.PairedNewMaterialContinuationService._capture_group
_PDF_RENDITION_PROVIDER: ContextVar[str | None] = ContextVar(
    "paired_new_material_pdf_rendition_provider", default=None
)


def _render_with_pdf_support(
    original_content: bytes,
    media_type: str | None,
    *,
    max_bytes: int,
) -> bytes:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    if normalized != "application/pdf":
        return _BASE_RENDER(original_content, media_type, max_bytes=max_bytes)

    try:
        # The provider's locator is not persisted here. The group capture keeps the
        # historical exact locator independently; only the bounded bytes/provider
        # are consumed from this existing pinned renderer.
        rendered = _regenerate_pinned_text_rendition(
            original_content,
            normalized,
            "",
            max_bytes=max_bytes,
        )
    except MaterialReacquisitionRetrievalError as exc:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
            "divergent PDF original rendition regeneration failed",
        ) from exc
    _PDF_RENDITION_PROVIDER.set(rendered.provider)
    return rendered.content


class _ProviderAwareCaptureService(_BASE_CAPTURE_SERVICE):
    def capture(self, run, **kwargs):
        provider = _PDF_RENDITION_PROVIDER.get()
        if provider is not None:
            provenance = deepcopy(dict(kwargs.get("provenance") or {}))
            provenance["text_rendition_provider"] = provider
            kwargs["provenance"] = provenance
        try:
            return super().capture(run, **kwargs)
        finally:
            _PDF_RENDITION_PROVIDER.set(None)


def _capture_group_with_provider_reset(self, *args, **kwargs):
    token = _PDF_RENDITION_PROVIDER.set(None)
    try:
        return _BASE_CAPTURE_GROUP(self, *args, **kwargs)
    finally:
        _PDF_RENDITION_PROVIDER.reset(token)


def install_new_material_group_continuation_pdf_provider() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _group._render_reacquired_html_rendition = _render_with_pdf_support
        _group.DesktopResearchCaptureService = _ProviderAwareCaptureService
        _group.PairedNewMaterialContinuationService._capture_group = (
            _capture_group_with_provider_reset
        )
        _INSTALLED = True
