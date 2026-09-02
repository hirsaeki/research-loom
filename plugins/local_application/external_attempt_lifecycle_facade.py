from __future__ import annotations

from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research.attempts import reconstruct_attempts

from .facade import LocalApplicationError
from .survey_analysis_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Final production facade guard for Desktop Research attempt lifecycle."""

    def collect_external(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        run, _context_extension = self._desktop_external_run(run_id)
        guard = getattr(self._application.execution_store, "require_run_status", None)
        if not callable(guard):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-ATTEMPT-001",
                "external collect requires an atomic RUNNING-state guard",
            )
        try:
            with guard(run.run_id, RunStatus.RUNNING):
                try:
                    attempts = reconstruct_attempts(
                        self._application.operational_store,
                        run.run_id,
                    )
                except ValueError as exc:
                    raise LocalApplicationError(
                        "APPLICATION-EXTERNAL-ATTEMPT-001",
                        str(exc),
                    ) from exc
                in_progress = sorted(
                    attempt_id
                    for attempt_id, attempt in attempts.items()
                    if attempt.get("completed_at") is None
                )
                if in_progress:
                    raise LocalApplicationError(
                        "APPLICATION-EXTERNAL-ATTEMPT-001",
                        "external collect requires every retrieval attempt to have a terminal outcome; "
                        "in-progress attempts: " + ", ".join(in_progress),
                    )
                return super().collect_external(run_id, submission)
        except LocalApplicationError:
            raise
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-RUN-STATE-001",
                str(exc),
            ) from exc
