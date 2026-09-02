from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research import (
    DesktopResearchAttemptRecorder,
    DesktopResearchCaptureService,
    DesktopResearchExternalAdapter,
    reconstruct_attempts,
)
from plugins.desktop_research.capture import DesktopResearchCaptureError
from plugins.local_execution_store import (
    LocalExecutionStoreError,
    bind_controlled_import_root,
    read_controlled_file,
)

from .facade import LocalApplicationError
from .resume_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


_ATTEMPT_START_FIELDS = {
    "attempt_id",
    "strategy",
    "coverage_dimension_ids",
    "query_or_target",
    "provider_or_tool",
    "target_locator",
    "provenance",
}
_ATTEMPT_COMPLETE_FIELDS = {
    "attempt_id",
    "outcome",
    "failure_or_blocking_reason",
    "target_locator",
    "resulting_capture_id",
    "provenance",
}
_CAPTURE_FIELDS = {
    "capture_id",
    "source_category",
    "exact_locator",
    "acquired_at",
    "original_file",
    "original_media_type",
    "text_rendition_file",
    "provenance",
}
_RESERVED_CAPTURE_PROVENANCE_FIELDS = {
    "artifact_id",
    "byte_length",
    "capture_id",
    "content_digest",
    "content_reference",
    "digest",
    "execution_mode",
    "exact_locator",
    "original_capture",
    "parent_artifact_refs",
    "rendition_role",
    "size",
    "source_category",
    "source_run_id",
    "storage_locator",
    "stored_at",
    "stored_by",
    "text_rendition",
    "acquired_at",
}

_ORIGINAL_ROLE = "desktop_research.original_capture"
_TEXT_ROLE = "desktop_research.text_rendition"


def _input_object(value: Mapping[str, Any], allowed: set[str], operation: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-INPUT-001",
            f"{operation} input must be an object",
        )
    unknown = set(value) - allowed
    if unknown:
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-INPUT-001",
            f"{operation} input contains unknown or forbidden fields: "
            + ", ".join(sorted(str(item) for item in unknown)),
        )
    return deepcopy(dict(value))


def _required_string(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-INPUT-001",
            f"{field} must be a non-empty string",
        )
    return item


def _optional_string(value: Mapping[str, Any], field: str) -> str | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, str) or not item.strip():
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-INPUT-001",
            f"{field} must be null or a non-empty string",
        )
    return item


def _provenance(value: Mapping[str, Any], *, capture: bool = False) -> dict[str, Any]:
    item = value.get("provenance", {})
    if not isinstance(item, Mapping):
        raise LocalApplicationError(
            "APPLICATION-EXTERNAL-INPUT-001",
            "provenance must be an object",
        )
    if capture:
        forbidden = set(item) & _RESERVED_CAPTURE_PROVENANCE_FIELDS
        if forbidden:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INPUT-001",
                "capture provenance may not supply trusted artifact/capture metadata: "
                + ", ".join(sorted(str(field) for field in forbidden)),
            )
    return deepcopy(dict(item))


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extended with Run-bound external Desktop Research intake."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self._workspace_root is not None:
            try:
                bind_controlled_import_root(self._application.execution_store, self._workspace_root)
            except (OSError, PermissionError) as exc:
                raise LocalApplicationError(
                    "APPLICATION-EXTERNAL-FILE-001",
                    "workspace could not be bound as the controlled intake root",
                ) from exc


    def replay_completed_desktop_research_run(self, run_id: str) -> Mapping[str, Any]:
        if not isinstance(run_id, str) or not run_id:
            raise LocalApplicationError("APPLICATION-RUN-REPLAY-001", "run_id is required")
        parent = self._application.execution_store.load_run(run_id)
        if parent is None or parent.project_ref != self._project_id:
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "replay parent Run does not resolve in this project",
            )
        if (
            parent.capability_id != "desktop-research"
            or parent.function_id != "investigate"
            or parent.execution_mode != "real"
        ):
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "run replay currently supports external Desktop Research investigate Runs only",
            )
        if parent.status is not RunStatus.COMPLETED:
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "replay parent Run must be COMPLETED",
            )
        attempts = reconstruct_attempts(self._application.operational_store, run_id)
        unresolved = [
            deepcopy(item)
            for item in attempts.values()
            if item.get("completed_at") is None
        ]
        if not unresolved:
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "completed Run has no unresolved retrieval attempts to replay",
            )
        correlation = self._application.conversation_store.load_run_correlation(run_id)
        if correlation is None:
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "replay parent Run is not correlated to a public conversation action",
            )
        proposal = self._application.conversation_store.load_proposal(
            str(correlation["proposal_id"])
        )
        if proposal is None or proposal.get("action", {}).get("action_type") != "desktop_research.investigate":
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "replay parent action is unavailable or unsupported",
            )
        payload = deepcopy(dict(proposal["action"]["payload"]))
        payload["parent_run_id"] = run_id
        replay = self.submit_action({
            "action_type": "desktop_research.investigate",
            "payload": payload,
            "rationale": f"Replay unresolved retrieval work from completed Run {run_id}.",
        })
        child_run_id = replay.get("run_id")
        if not isinstance(child_run_id, str) or not child_run_id:
            raise LocalApplicationError(
                "APPLICATION-RUN-REPLAY-001",
                "replay did not prepare a related child Run",
            )
        carried = []
        for attempt in unresolved:
            provenance = deepcopy(dict(attempt.get("provenance") or {}))
            provenance["replayed_from_run_id"] = run_id
            provenance["replayed_from_attempt_id"] = str(attempt["attempt_id"])
            started = self.start_external_retrieval_attempt(child_run_id, {
                "attempt_id": str(attempt["attempt_id"]),
                "strategy": str(attempt["strategy"]),
                "coverage_dimension_ids": list(attempt["coverage_dimension_ids"]),
                "query_or_target": attempt.get("query_or_target"),
                "provider_or_tool": attempt.get("provider_or_tool"),
                "target_locator": attempt.get("target_locator"),
                "provenance": provenance,
            })
            carried.append(started["attempt"])
        return {
            "status": "RUN_REPLAY_PREPARED",
            "parent_run_id": run_id,
            "run_id": child_run_id,
            "attempt": self._application.execution_store.load_run(child_run_id).attempt,
            "carried_unresolved_attempts": carried,
        }

    def start_external_retrieval_attempt(
        self,
        run_id: str,
        submission: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        run, context_extension = self._desktop_external_run(run_id)
        value = _input_object(submission, _ATTEMPT_START_FIELDS, "external attempt start")
        attempt_id = _required_string(value, "attempt_id")
        strategy = _required_string(value, "strategy")
        dimensions = value.get("coverage_dimension_ids")
        if (
            not isinstance(dimensions, list)
            or not dimensions
            or any(not isinstance(item, str) or not item.strip() for item in dimensions)
            or len(dimensions) != len(set(dimensions))
        ):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-INPUT-001",
                "coverage_dimension_ids must be a non-empty array of unique non-empty strings",
            )
        configured = {
            str(item.get("dimension_id"))
            for item in context_extension.get("coverage_dimensions", ())
            if isinstance(item, Mapping) and item.get("dimension_id")
        }
        unknown = sorted(set(dimensions) - configured)
        if unknown:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-ATTEMPT-001",
                "retrieval attempt references unknown coverage dimensions: " + ", ".join(unknown),
            )
        recorder = DesktopResearchAttemptRecorder(
            run,
            self._application.execution_store,
            self._application.operational_store,
            self._application.clock,
        )
        try:
            detail = recorder.start_attempt(
                attempt_id,
                strategy=strategy,
                coverage_dimension_ids=tuple(dimensions),
                query_or_target=_optional_string(value, "query_or_target"),
                provider_or_tool=_optional_string(value, "provider_or_tool"),
                target_locator=_optional_string(value, "target_locator"),
                provenance=_provenance(value),
            )
        except ValueError as exc:
            raise LocalApplicationError("APPLICATION-EXTERNAL-ATTEMPT-001", str(exc)) from exc
        return {"status": "EXTERNAL_ATTEMPT_STARTED", "attempt": deepcopy(dict(detail))}

    def complete_external_retrieval_attempt(
        self,
        run_id: str,
        submission: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        run, _context_extension = self._desktop_external_run(run_id)
        value = _input_object(submission, _ATTEMPT_COMPLETE_FIELDS, "external attempt complete")
        recorder = DesktopResearchAttemptRecorder(
            run,
            self._application.execution_store,
            self._application.operational_store,
            self._application.clock,
        )
        try:
            detail = recorder.complete_attempt(
                _required_string(value, "attempt_id"),
                outcome=_required_string(value, "outcome"),
                failure_or_blocking_reason=_optional_string(value, "failure_or_blocking_reason"),
                target_locator=_optional_string(value, "target_locator"),
                resulting_capture_id=_optional_string(value, "resulting_capture_id"),
                provenance=_provenance(value),
            )
        except ValueError as exc:
            raise LocalApplicationError("APPLICATION-EXTERNAL-ATTEMPT-001", str(exc)) from exc
        return {"status": "EXTERNAL_ATTEMPT_COMPLETED", "attempt": deepcopy(dict(detail))}

    def capture_external_source(
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
            text_limit = int(budget["max_text_rendition_bytes"])
            capture_limit = int(budget["max_acquired_source_captures"])
            original_declared = budget.get("max_original_capture_bytes")
            original_limit = (
                store.config.max_artifact_bytes
                if original_declared is None
                else int(original_declared)
            )
            artifact_limit = int(
                budget.get("max_capture_artifacts", 2 * capture_limit)
            )
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

        # Every capture is exactly one original + one text artifact. This converts
        # the optional aggregate artifact budget into an equivalent atomic pair cap.
        pair_limit = min(capture_limit, artifact_limit // 2)
        if pair_limit <= 0:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-CAPTURE-001",
                "Desktop Research capture budget is exhausted",
            )

        try:
            original_bytes = read_controlled_file(
                store,
                original_path,
                max_bytes=min(original_limit, store.config.max_artifact_bytes),
            )
            text_bytes = read_controlled_file(
                store,
                text_path,
                max_bytes=min(text_limit, store.config.max_artifact_bytes),
            )
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
        except (LocalExecutionStoreError, OSError, ValueError) as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-FILE-002",
                str(exc),
            ) from exc

        try:
            text_rendition = text_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-UTF8-001",
                "text rendition must be valid UTF-8",
            ) from exc

        role_byte_limits = {_TEXT_ROLE: text_limit}
        if original_declared is not None:
            # Result validation treats the optional original-byte budget as
            # cumulative only when the Context explicitly declares it.
            role_byte_limits[_ORIGINAL_ROLE] = int(original_declared)
        role_count_limits = {
            _ORIGINAL_ROLE: pair_limit,
            _TEXT_ROLE: pair_limit,
        }

        service = DesktopResearchCaptureService(store)
        try:
            detail = service.capture(
                run,
                capture_id=capture_id,
                source_category=source_category,
                exact_locator=exact_locator,
                acquired_at=acquired_at,
                original_bytes=original_bytes,
                original_media_type=original_media_type,
                text_rendition=text_rendition,
                provenance=provenance,
                artifact_write_options={
                    "expected_status": RunStatus.RUNNING,
                    "role_byte_limits": role_byte_limits,
                    "role_count_limits": role_count_limits,
                },
            )
        except (
            DesktopResearchCaptureError,
            LocalExecutionStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise LocalApplicationError("APPLICATION-EXTERNAL-CAPTURE-001", str(exc)) from exc
        return {"status": "EXTERNAL_SOURCE_CAPTURED", "capture": deepcopy(dict(detail))}

    def _desktop_external_run(self, run_id: str):
        if not isinstance(run_id, str) or not run_id:
            raise LocalApplicationError("APPLICATION-EXTERNAL-INPUT-001", "run_id is required")
        run = self._application.execution_store.load_run(run_id)
        if run is None:
            raise LocalApplicationError("APPLICATION-EXTERNAL-RUN-001", "unknown external Run")
        if run.project_ref != self._project_id:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "external Run belongs to another project",
            )
        if (
            run.capability_id != DesktopResearchExternalAdapter.capability_id
            or run.capability_version != DesktopResearchExternalAdapter.capability_version
            or run.implementation_id != DesktopResearchExternalAdapter.implementation_id
            or run.implementation_version != DesktopResearchExternalAdapter.implementation_version
            or run.function_id != "investigate"
            or run.execution_mode != "real"
        ):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "Run is not the expected real external Desktop Research execution",
            )
        if run.status is not RunStatus.RUNNING:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-RUN-STATE-001",
                "external Desktop Research intake requires a RUNNING Run",
            )
        extension = self._application.context_extension_store.load(
            run.capability_id,
            run.capability_version,
            run.function_id,
            run.context_pack_id,
        )
        if not isinstance(extension, Mapping):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "Desktop Research Context extension does not resolve for Run",
            )
        binding = extension.get("context_binding")
        if (
            not isinstance(binding, Mapping)
            or str(binding.get("project_id")) != self._project_id
            or str(binding.get("context_pack_id")) != run.context_pack_id
            or str(binding.get("context_pack_digest")) != run.context_pack_digest
        ):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-BINDING-001",
                "Desktop Research Context extension does not match Run binding",
            )
        return run, extension

    def _workspace_capture_path(self, locator: str) -> Path:
        if self._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-FILE-001",
                "external file capture requires an opened production workspace",
            )
        relative = Path(locator)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-FILE-001",
                "capture file must be a workspace-relative path without traversal",
            )
        return self._workspace_root.joinpath(relative)
