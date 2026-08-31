from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.execution.models import CapabilityRunRecord, RunStatus
from core.execution.operational_trace import OperationalTraceStore
from core.execution.ports import ExecutionTraceStore, RuntimeClock


ATTEMPT_STARTED = "desktop_research.retrieval_attempt_started"
ATTEMPT_COMPLETED = "desktop_research.retrieval_attempt_completed"
OPERATIONAL_TERMINATION = "desktop_research.operational_termination"

OUTCOMES = {
    "source_captured",
    "no_relevant_source",
    "unavailable",
    "blocked",
    "duplicate",
    "out_of_scope",
    "failed",
}
UNSUCCESSFUL_OUTCOMES = OUTCOMES - {"source_captured"}


class DesktopResearchAttemptRecorder:
    """Limited Run-bound API for append-only retrieval attempt provenance."""

    def __init__(
        self,
        run: CapabilityRunRecord,
        trace_store: ExecutionTraceStore,
        operational_store: OperationalTraceStore,
        clock: RuntimeClock,
    ) -> None:
        self._run = run
        self._traces = trace_store
        self._operations = operational_store
        self._clock = clock

    def _require_running(self) -> None:
        persisted = self._traces.load_run(self._run.run_id)
        if persisted is None or persisted.status is not RunStatus.RUNNING:
            raise ValueError("retrieval attempts can start/complete only for a RUNNING Run")
        if (
            persisted.capability_id != self._run.capability_id
            or persisted.implementation_id != self._run.implementation_id
        ):
            raise ValueError("attempt recorder Run binding no longer matches persisted Run")

    def _append_running(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
    ):
        occurred_at = self._clock.now()
        append_if_status = getattr(self._operations, "append_if_run_status", None)
        if callable(append_if_status):
            return append_if_status(
                self._run.run_id,
                RunStatus.RUNNING,
                event_type,
                occurred_at,
                payload,
                event_id=event_id,
            )
        self._require_running()
        return self._operations.append(
            self._run.run_id,
            event_type,
            occurred_at,
            payload,
            event_id=event_id,
        )

    def start_attempt(
        self,
        attempt_id: str,
        *,
        strategy: str,
        coverage_dimension_ids: tuple[str, ...],
        query_or_target: str | None = None,
        provider_or_tool: str | None = None,
        target_locator: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self._require_running()
        if not attempt_id or not strategy or not coverage_dimension_ids:
            raise ValueError("attempt_id, strategy, and coverage dimensions are required")
        if attempt_id in self._index():
            raise ValueError(f"retrieval attempt identity already exists: {attempt_id}")
        payload = {
            "attempt_id": attempt_id,
            "strategy": strategy,
            "coverage_dimension_ids": list(coverage_dimension_ids),
            "query_or_target": query_or_target,
            "provider_or_tool": provider_or_tool,
            "target_locator": target_locator,
            "provenance": dict(provenance or {}),
        }
        event = self._append_running(
            ATTEMPT_STARTED,
            payload,
            event_id=f"{self._run.run_id}.{attempt_id}.start",
        )
        return {
            **payload,
            "run_id": self._run.run_id,
            "started_at": event.occurred_at,
            "outcome": None,
            "completed_at": None,
        }

    def complete_attempt(
        self,
        attempt_id: str,
        *,
        outcome: str,
        failure_or_blocking_reason: str | None = None,
        target_locator: str | None = None,
        resulting_capture_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self._require_running()
        if outcome not in OUTCOMES:
            raise ValueError(f"unsupported retrieval attempt outcome: {outcome}")
        current = self._index().get(attempt_id)
        if current is None:
            raise ValueError("retrieval attempt must be registered before completion")
        if current.get("completed_at") is not None:
            raise ValueError("retrieval attempt completion is append-only and single-use")
        if outcome == "source_captured" and not resulting_capture_id:
            raise ValueError("source_captured outcome requires resulting_capture_id")
        if outcome != "source_captured" and resulting_capture_id:
            raise ValueError("unsuccessful retrieval attempt cannot claim a capture")
        if outcome in {"unavailable", "blocked", "failed"} and not failure_or_blocking_reason:
            raise ValueError(f"{outcome} outcome requires a failure/blocking reason")
        payload = {
            "attempt_id": attempt_id,
            "outcome": outcome,
            "failure_or_blocking_reason": failure_or_blocking_reason,
            "target_locator": target_locator,
            "resulting_capture_id": resulting_capture_id,
            "provenance": dict(provenance or {}),
        }
        self._append_running(
            ATTEMPT_COMPLETED,
            payload,
            event_id=f"{self._run.run_id}.{attempt_id}.complete",
        )
        return deepcopy(self._index()[attempt_id])

    def record_operational_termination(
        self,
        reason: str,
        *,
        detail: str,
        coverage_dimension_ids: tuple[str, ...] = (),
    ) -> None:
        self._require_running()
        self._append_running(
            OPERATIONAL_TERMINATION,
            {
                "reason": reason,
                "detail": detail,
                "coverage_dimension_ids": list(coverage_dimension_ids),
            },
        )

    def attempts(self) -> tuple[Mapping[str, Any], ...]:
        index = self._index()
        return tuple(deepcopy(index[key]) for key in sorted(index))

    def _index(self) -> dict[str, dict[str, Any]]:
        return reconstruct_attempts(self._operations, self._run.run_id)


def reconstruct_attempts(
    operational_store: OperationalTraceStore,
    run_id: str,
) -> dict[str, dict[str, Any]]:
    attempts: dict[str, dict[str, Any]] = {}
    for event in operational_store.events_for(run_id):
        payload = dict(event.payload)
        if event.event_type == ATTEMPT_STARTED:
            attempt_id = str(payload["attempt_id"])
            if attempt_id in attempts:
                raise ValueError("duplicate retrieval attempt start in operational ledger")
            attempts[attempt_id] = {
                "attempt_id": attempt_id,
                "run_id": run_id,
                "strategy": str(payload["strategy"]),
                "coverage_dimension_ids": tuple(payload["coverage_dimension_ids"]),
                "query_or_target": payload.get("query_or_target"),
                "provider_or_tool": payload.get("provider_or_tool"),
                "target_locator": payload.get("target_locator"),
                "started_at": event.occurred_at,
                "outcome": None,
                "failure_or_blocking_reason": None,
                "resulting_capture_id": None,
                "completed_at": None,
                "provenance": dict(payload.get("provenance") or {}),
            }
        elif event.event_type == ATTEMPT_COMPLETED:
            attempt_id = str(payload["attempt_id"])
            current = attempts.get(attempt_id)
            if current is None or current["completed_at"] is not None:
                raise ValueError("invalid retrieval attempt completion ordering")
            current["outcome"] = str(payload["outcome"])
            current["failure_or_blocking_reason"] = payload.get(
                "failure_or_blocking_reason"
            )
            if payload.get("target_locator") is not None:
                current["target_locator"] = payload["target_locator"]
            current["resulting_capture_id"] = payload.get("resulting_capture_id")
            current["completed_at"] = event.occurred_at
            current["provenance"] = {
                **current["provenance"],
                **dict(payload.get("provenance") or {}),
            }
    return attempts


def operational_terminations(
    operational_store: OperationalTraceStore,
    run_id: str,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {"occurred_at": event.occurred_at, **dict(event.payload)}
        for event in operational_store.events_for(run_id, OPERATIONAL_TERMINATION)
    )
