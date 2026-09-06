from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research.attempts import reconstruct_attempts

from .external_submission import (
    CorrectableExternalSubmissionError,
    assemble_external_submission,
    validate_external_submission,
)
from .facade import LocalApplicationError
from .question_review_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Final production facade guard for Desktop Research external intake."""

    def preflight_external(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        run, context_extension = self._desktop_external_run(run_id)
        research_result = self._research_result_input(submission, preflight=True)
        attempts = self._completed_attempts(run.run_id)
        try:
            handoff, extension = assemble_external_submission(
                self._application, run, research_result, attempts
            )
        except CorrectableExternalSubmissionError as exc:
            return self._preflight_rejection(run, exc)
        issues = validate_external_submission(
            self._application, run, context_extension, handoff, extension
        )
        return {
            "status": "PREFLIGHT_OK" if not issues else "PREFLIGHT_REJECTED",
            "run_id": run.run_id,
            "run_status": run.status.value,
            "issues": issues,
            "assembled_submission": {"handoff": handoff, "extension": extension},
        }

    def collect_external(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        run, context_extension = self._desktop_external_run(run_id)
        research_result = None
        if isinstance(submission, Mapping) and "research_result" in submission:
            research_result = self._research_result_input(submission, preflight=False)

        guard = getattr(self._application.execution_store, "require_run_status", None)
        if not callable(guard):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-ATTEMPT-001",
                "external collect requires an atomic RUNNING-state guard",
            )
        try:
            with guard(run.run_id, RunStatus.RUNNING):
                attempts = self._completed_attempts(run.run_id)
                if research_result is not None:
                    try:
                        handoff, extension = assemble_external_submission(
                            self._application, run, research_result, attempts
                        )
                    except CorrectableExternalSubmissionError as exc:
                        return self._correctable_rejection(run, (self._submission_issue(exc),))
                    issues = validate_external_submission(
                        self._application, run, context_extension, handoff, extension
                    )
                    if issues:
                        return self._correctable_rejection(run, issues)
                    submission = {"handoff": handoff, "extension": extension}
                return super().collect_external(run_id, submission)
        except LocalApplicationError:
            raise
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-RUN-STATE-001", str(exc)
            ) from exc

    def _completed_attempts(self, run_id: str):
        try:
            attempts = reconstruct_attempts(self._application.operational_store, run_id)
        except ValueError as exc:
            raise LocalApplicationError("APPLICATION-EXTERNAL-ATTEMPT-001", str(exc)) from exc
        in_progress = sorted(
            attempt_id for attempt_id, attempt in attempts.items()
            if attempt.get("completed_at") is None
        )
        if in_progress:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-ATTEMPT-001",
                "external collect requires every retrieval attempt to have a terminal outcome; "
                "in-progress attempts: " + ", ".join(in_progress),
            )
        return attempts

    @staticmethod
    def _research_result_input(submission: Mapping[str, Any], *, preflight: bool):
        if not isinstance(submission, Mapping) or set(submission) != {"research_result"}:
            label = "preflight" if preflight else "assembled external collect"
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-SUBMISSION-001",
                f"{label} accepts exactly one research_result object",
            )
        value = submission["research_result"]
        if not isinstance(value, Mapping):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-SUBMISSION-001",
                "research_result must be an object",
            )
        return deepcopy(dict(value))

    @staticmethod
    def _submission_issue(exc: CorrectableExternalSubmissionError):
        return {"code": exc.code, "message": exc.message, "retryable": False}

    @classmethod
    def _preflight_rejection(cls, run, exc: CorrectableExternalSubmissionError):
        return {
            "status": "PREFLIGHT_REJECTED",
            "run_id": run.run_id,
            "run_status": run.status.value,
            "issues": [cls._submission_issue(exc)],
            "assembled_submission": None,
        }

    @staticmethod
    def _correctable_rejection(run, issues):
        return {
            "status": "CAPABILITY_RESULT_COLLECTED",
            "execution_result": {
                "run": {"run_id": run.run_id, "status": run.status.value},
                "handoff_ref": None,
                "handoff_status": None,
                "extension_ref": None,
                "state_delta_proposal": None,
                "issues": deepcopy(issues),
            },
            "data": {"handoff": None, "state_delta_proposal": None, "issues": deepcopy(issues)},
        }
