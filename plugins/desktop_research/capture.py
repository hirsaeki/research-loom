from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from core.execution.models import CapabilityRunRecord, ExecutionArtifactMetadata
from core.execution.ports import ExecutionArtifactStore


class DesktopResearchCaptureError(ValueError):
    pass


def _is_utc(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _looks_like_real_web_locator(locator: str) -> bool:
    return locator.startswith("http://") or locator.startswith("https://")


class DesktopResearchCaptureService:
    """Run-bound trusted source-capture intake backed by the PR23 Artifact Store."""

    def __init__(self, artifact_store: ExecutionArtifactStore) -> None:
        self._artifacts = artifact_store

    def capture(
        self,
        run: CapabilityRunRecord,
        *,
        capture_id: str,
        source_category: str,
        exact_locator: str,
        acquired_at: str,
        original_bytes: bytes,
        original_media_type: str,
        text_rendition: str | bytes,
        provenance: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not capture_id or not source_category or not exact_locator:
            raise DesktopResearchCaptureError("capture identity/category/exact locator are required")
        if not _is_utc(acquired_at):
            raise DesktopResearchCaptureError("acquired_at must be RFC3339 UTC")
        if run.execution_mode != "real" and _looks_like_real_web_locator(exact_locator):
            raise DesktopResearchCaptureError(
                "virtual/synthetic capture may not masquerade a placeholder as a real web locator"
            )
        if not isinstance(original_bytes, bytes):
            raise DesktopResearchCaptureError("original capture must be bytes")
        if isinstance(text_rendition, str):
            text_bytes = text_rendition.encode("utf-8")
        elif isinstance(text_rendition, bytes):
            try:
                text_rendition.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DesktopResearchCaptureError("text rendition must be valid UTF-8") from exc
            text_bytes = text_rendition
        else:
            raise DesktopResearchCaptureError("text rendition must be str or UTF-8 bytes")

        trusted = {
            "capture_id": capture_id,
            "source_category": source_category,
            "exact_locator": exact_locator,
            "acquired_at": acquired_at,
            **dict(provenance or {}),
        }
        original = self._artifacts.put_bytes(
            run,
            role="desktop_research.original_capture",
            media_type=original_media_type,
            content=original_bytes,
            artifact_id=f"{run.run_id}.{capture_id}.original",
            provenance={**trusted, "rendition_role": "original"},
        )
        text = self._artifacts.put_bytes(
            run,
            role="desktop_research.text_rendition",
            media_type="text/plain",
            content=text_bytes,
            artifact_id=f"{run.run_id}.{capture_id}.text",
            provenance={**trusted, "rendition_role": "text"},
            parent_artifact_refs=(original.artifact_id,),
        )
        return self._detail(
            capture_id,
            source_category,
            exact_locator,
            acquired_at,
            original,
            text,
        )

    @staticmethod
    def _detail(
        capture_id: str,
        source_category: str,
        exact_locator: str,
        acquired_at: str,
        original: ExecutionArtifactMetadata,
        text: ExecutionArtifactMetadata,
    ) -> Mapping[str, Any]:
        return {
            "capture_id": capture_id,
            "source_category": source_category,
            "exact_locator": exact_locator,
            "acquired_at": acquired_at,
            "original_capture": {
                "content_reference": original.artifact_id,
                "content_digest": original.digest,
                "media_type": original.media_type,
                "byte_length": original.size,
            },
            "text_rendition": {
                "content_reference": text.artifact_id,
                "content_digest": text.digest,
                "media_type": "text/plain",
                "byte_length": text.size,
                "encoding": "UTF-8",
            },
        }
