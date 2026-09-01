from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research import DesktopResearchCaptureService
from plugins.local_execution_store import LocalExecutionStoreError, read_controlled_file

from .external_desktop_facade import (
    _CAPTURE_FIELDS,
    _ORIGINAL_ROLE,
    _TEXT_ROLE,
    _input_object,
    _provenance,
    _required_string,
)
from .facade import LocalApplicationError
from .material_inventory_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """PR39 facade: preserve the normal capture path and add oversized fallback."""

    def capture_external_source(
        self,
        run_id: str,
        submission: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            return super().capture_external_source(run_id, submission)
        except LocalApplicationError as exc:
            if (
                exc.code != "APPLICATION-EXTERNAL-FILE-002"
                or "file exceeds configured intake size limit" not in exc.message
            ):
                raise
        return self._capture_external_source_with_large_original(run_id, submission)

    def _capture_external_source_with_large_original(
        self,
        run_id: str,
        submission: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        run, context_extension = self._desktop_external_run(run_id)
        value = _input_object(submission, _CAPTURE_FIELDS, "external capture")
        capture_id = _required_string(value, "capture_id")
        source_category = _required_string(value, "source_category")
        exact_locator = _required_string(value, "exact_locator")
        acquired_at = _required_string(value, "acquired_at")
        original_media_type = _required_string(value, "original_media_type")
        original_path = self._workspace_capture_path(_required_string(value, "original_file"))
        text_path = self._workspace_capture_path(_required_string(value, "text_rendition_file"))
        provenance = _provenance(value, capture=True)

        allowed_categories = {
            str(item) for item in context_extension.get("allowed_source_categories", ())
        }
        if source_category not in allowed_categories:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-CAPTURE-001",
                f"source_category is not allowed by this Desktop Research Run: {source_category}",
            )
        budget = context_extension.get("budget")
        if not isinstance(budget, Mapping):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "Desktop Research Run has no valid capture budget binding",
            )
        store = self._application.execution_store
        try:
            capture_limit = int(budget["max_acquired_source_captures"])
            text_limit = int(budget["max_text_rendition_bytes"])
            artifact_limit = int(budget.get("max_capture_artifacts", 2 * capture_limit))
            original_declared = budget.get("max_original_capture_bytes")
            if original_declared is None:
                # Legacy Contexts intentionally retain the old generic artifact bound.
                original_limit = int(store.config.max_artifact_bytes)
            else:
                original_limit = int(original_declared)
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "Desktop Research Run capture budget is malformed",
            ) from exc
        if min(original_limit, text_limit, capture_limit, artifact_limit) < 0:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "Desktop Research Run capture budget is malformed",
            )
        pair_limit = min(capture_limit, artifact_limit // 2)
        if pair_limit <= 0:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-CAPTURE-001",
                "Desktop Research capture budget is exhausted",
            )

        try:
            text_bytes = read_controlled_file(
                store,
                text_path,
                max_bytes=min(text_limit, store.config.max_artifact_bytes),
            )
            text_bytes.decode("utf-8")
        except FileNotFoundError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-FILE-002",
                "capture input file is missing",
            ) from exc
        except PermissionError as exc:
            message = str(exc)
            code = (
                "APPLICATION-EXTERNAL-FILE-002"
                if "only regular files" in message
                else "APPLICATION-EXTERNAL-FILE-001"
            )
            raise LocalApplicationError(code, message) from exc
        except UnicodeDecodeError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-UTF8-001",
                "text rendition must be valid UTF-8",
            ) from exc
        except (LocalExecutionStoreError, OSError, ValueError) as exc:
            raise LocalApplicationError("APPLICATION-EXTERNAL-FILE-002", str(exc)) from exc

        if original_declared is None or original_limit <= store.config.max_artifact_bytes:
            # The initial normal path already proved this is not a valid large-original
            # case; do not use the fallback to weaken legacy/generic intake limits.
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-CAPTURE-001",
                "original capture is not permitted to exceed the generic artifact bound",
            )

        trusted = {
            "capture_id": capture_id,
            "source_category": source_category,
            "exact_locator": exact_locator,
            "acquired_at": acquired_at,
            **dict(provenance),
        }
        original_id = f"{run.run_id}.{capture_id}.original"
        text_id = f"{run.run_id}.{capture_id}.text"
        role_byte_limits = {
            _ORIGINAL_ROLE: original_limit,
            _TEXT_ROLE: text_limit,
        }
        role_count_limits = {
            _ORIGINAL_ROLE: pair_limit,
            _TEXT_ROLE: pair_limit,
        }
        writer = getattr(store, "put_desktop_research_capture_files", None)
        if not callable(writer):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-CAPTURE-001",
                "execution store does not support managed large original capture",
            )
        try:
            original, text = writer(
                run,
                original_path=original_path,
                original_media_type=original_media_type,
                original_artifact_id=original_id,
                original_provenance={**trusted, "rendition_role": "original"},
                text_content=text_bytes,
                text_artifact_id=text_id,
                text_provenance={**trusted, "rendition_role": "text"},
                max_original_bytes=original_limit,
                role_byte_limits=role_byte_limits,
                role_count_limits=role_count_limits,
                expected_status=RunStatus.RUNNING,
            )
        except (LocalExecutionStoreError, PermissionError, OSError, TypeError, ValueError) as exc:
            raise LocalApplicationError("APPLICATION-EXTERNAL-CAPTURE-001", str(exc)) from exc

        detail = DesktopResearchCaptureService._detail(
            capture_id,
            source_category,
            exact_locator,
            acquired_at,
            original,
            text,
        )
        return {"status": "EXTERNAL_SOURCE_CAPTURED", "capture": deepcopy(dict(detail))}
