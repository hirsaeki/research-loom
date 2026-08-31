from __future__ import annotations

from typing import Any, Iterable, Mapping

from plugins.desktop_research.attempts import (
    OUTCOMES,
    operational_terminations,
    reconstruct_attempts,
)
from plugins.local_execution_store import diagnostics_for

from .external_desktop_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .facade import LocalApplicationError, _jsonable


_RUN_INSPECTION_ITEM_LIMIT = 100


def _bounded(values: Iterable[Any]) -> tuple[list[Any], bool]:
    items = list(values)
    return items[:_RUN_INSPECTION_ITEM_LIMIT], len(items) > _RUN_INSPECTION_ITEM_LIMIT


def _run_projection(run) -> Mapping[str, Any]:
    return {
        "run_id": run.run_id,
        "capability_id": run.capability_id,
        "capability_version": run.capability_version,
        "implementation_id": run.implementation_id,
        "implementation_version": run.implementation_version,
        "function_id": run.function_id,
        "execution_mode": run.execution_mode,
        "attempt": run.attempt,
        "parent_run_id": run.parent_run_id,
        "status": run.status.value,
        "prepared_at": run.prepared_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "failure": (
            {
                "code": run.failure.code,
                "message": run.failure.message,
                "retryable": bool(run.failure.retryable),
            }
            if run.failure is not None
            else None
        ),
        "bindings": {
            "invocation_id": run.invocation_id,
            "invocation_digest": run.invocation_digest,
            "descriptor_digest": run.descriptor_digest,
            "context_pack_id": run.context_pack_id,
            "context_pack_digest": run.context_pack_digest,
            "project_ref": run.project_ref,
            "lineage_ref": run.lineage_ref,
            "snapshot_ref": run.snapshot_ref,
            "snapshot_digest": run.snapshot_digest,
        },
        "handoff": (
            {"ref": run.handoff_ref, "digest": run.handoff_digest}
            if run.handoff_ref is not None
            else None
        ),
    }


def _lifecycle_projection(events) -> list[Mapping[str, Any]]:
    return [
        {
            "sequence": event.sequence,
            "from_status": event.from_status.value if event.from_status is not None else None,
            "to_status": event.to_status.value,
            "occurred_at": event.occurred_at,
            "reason": event.reason,
        }
        for event in events
    ]


def _artifact_projection(artifacts) -> list[Mapping[str, Any]]:
    return [
        {
            "artifact_id": artifact.artifact_id,
            "role": artifact.role,
            "media_type": artifact.media_type,
            "byte_length": artifact.size,
            "digest": artifact.digest,
            "execution_mode": artifact.execution_mode,
            "provenance": _jsonable(artifact.provenance),
        }
        for artifact in artifacts
    ]


def _desktop_research_projection(operational_store, run_id: str) -> tuple[Mapping[str, Any], bool, bool]:
    attempts_by_id = reconstruct_attempts(operational_store, run_id)
    attempts = [_jsonable(attempts_by_id[key]) for key in sorted(attempts_by_id)]
    attempt_items, attempts_truncated = _bounded(attempts)

    summary = {"total": len(attempts), "in_progress": 0}
    for outcome in sorted(OUTCOMES):
        summary[outcome] = 0
    for attempt in attempts_by_id.values():
        outcome = attempt.get("outcome")
        if outcome is None:
            summary["in_progress"] += 1
        elif str(outcome) in summary:
            summary[str(outcome)] += 1

    terminations, terminations_truncated = _bounded(
        _jsonable(operational_terminations(operational_store, run_id))
    )
    return (
        {
            "retrieval_attempt_summary": summary,
            "retrieval_attempts": attempt_items,
            "operational_terminations": terminations,
        },
        attempts_truncated,
        terminations_truncated,
    )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extended with bounded read-only Run inspection."""

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        if not isinstance(run_id, str) or not run_id:
            raise LocalApplicationError("APPLICATION-RUN-INPUT-001", "run_id is required")

        try:
            run = self._application.execution_store.load_run(run_id)
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-RUN-READ-001",
                "persisted Run data could not be read",
            ) from exc
        if run is None:
            raise LocalApplicationError("APPLICATION-RUN-001", "unknown Run")
        if run.project_ref != self._project_id:
            raise LocalApplicationError(
                "APPLICATION-RUN-BINDING-001",
                "Run belongs to another project",
            )

        probe_limit = _RUN_INSPECTION_ITEM_LIMIT + 1
        try:
            lifecycle = _lifecycle_projection(
                self._application.execution_store.events_for(run_id)
            )
            diagnostic_probe = diagnostics_for(
                self._application.execution_store,
                run_id,
                limit=probe_limit,
            )
            diagnostic_items, diagnostics_truncated = _bounded(
                _jsonable(diagnostic_probe)
            )

            artifact_probe = self._application.execution_store.artifacts_for(run_id)
            artifact_items, artifacts_truncated = _bounded(
                _artifact_projection(artifact_probe)
            )

            desktop_research = None
            retrieval_attempts_truncated = False
            operational_terminations_truncated = False
            if run.capability_id == "desktop-research":
                (
                    desktop_research,
                    retrieval_attempts_truncated,
                    operational_terminations_truncated,
                ) = _desktop_research_projection(
                    self._application.operational_store,
                    run_id,
                )
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-RUN-READ-001",
                "persisted Run inspection data could not be read",
            ) from exc

        result: dict[str, Any] = {
            "status": "OK",
            "project_id": self._project_id,
            "run": _run_projection(run),
            "lifecycle": lifecycle,
            "diagnostics": diagnostic_items,
            "artifacts": artifact_items,
            "truncated": {
                "diagnostics": diagnostics_truncated,
                "artifacts": artifacts_truncated,
                "retrieval_attempts": retrieval_attempts_truncated,
                "operational_terminations": operational_terminations_truncated,
            },
        }
        if desktop_research is not None:
            result["desktop_research"] = desktop_research
        return result
