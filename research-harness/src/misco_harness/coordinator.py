from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from misco_harness.models import (
    CoordinatorTrace,
    DecisionRequest,
    InteractiveWorkNextAction,
    OrchestratorState,
    WorkExecutionRequest,
)
from misco_harness.orchestrator import DiscoveryOrchestrator
from misco_harness.trace_store import sha256_tree


class CoordinatorError(RuntimeError):
    """A control-plane error surfaced by the coordinator boundary."""


WorkExecutor = Callable[[InteractiveWorkNextAction], str | Path]


class InteractiveWorkResearchCoordinator:
    """Thin client-side loop for human-interactive Work.

    The coordinator only observes Harness state, exposes the next permitted
    action, and submits a result through ``DiscoveryOrchestrator``. It does
    not inspect research material, choose methods, or record decisions.
    ``execute_work`` is an injected callback so this module never assumes a
    Work API or automates a Desktop UI.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        orchestrator: DiscoveryOrchestrator | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.orchestrator = orchestrator or DiscoveryOrchestrator(self.workspace)
        self.runtime = self.workspace / ".rh"

    def current_state(self) -> OrchestratorState:
        """Return the Harness state without advancing orchestration."""

        return self.orchestrator.status()

    # ``status`` is intentionally an alias for clients that already use the
    # CLI terminology.
    status = current_state

    def next_action(self, *, advance: bool = True) -> InteractiveWorkNextAction:
        """Observe or materialize the next Harness-authorized action.

        ``advance`` only controls creation of the next bounded run when the
        Harness is READY. Existing Work or Decision boundaries are always
        returned immediately. A mock backend is never started by this client.
        """

        try:
            state = self.orchestrator.status()
            if state.worker_backend != "interactive-work":
                action = self._error_action(
                    state,
                    "Interactive Work Coordinator requires worker_backend='interactive-work'; refusing to run MockWorker.",
                    recovery="Initialize or resume the workspace with --worker-backend interactive-work.",
                )
                self._trace(action)
                return action

            existing = self._action_for_state(state)
            if existing is not None:
                self._trace(existing)
                return existing

            if not advance:
                action = self._blocked_action(
                    state,
                    "The Harness is READY but no Work task has been materialized.",
                    recovery="Call the coordinator next action with advance enabled.",
                )
                self._trace(action)
                return action

            # The existing orchestrator remains the only component allowed to
            # plan/build/dispatch a run. With the interactive backend this
            # creates a WORK_EXECUTION_REQUIRED boundary and does not execute
            # substantive research.
            self.orchestrator.continue_until_stop(run_limit=1)
            state = self.orchestrator.status()
            action = self._action_for_state(state)
            if action is None:
                action = self._blocked_action(
                    state,
                    "The Harness did not expose a permitted next action.",
                    recovery="Inspect Harness state and resolve the reported phase or contract issue.",
                )
            self._trace(action)
            return action
        except (OSError, ValueError, RuntimeError) as error:
            state = self._safe_state()
            action = self._error_action(
                state,
                f"Harness next-action query failed: {type(error).__name__}: {error}",
                recovery="Inspect the Harness error and repair the reported input before retrying.",
            )
            self._trace(action)
            return action

    def submit_result(
        self,
        result_path: str | Path | None = None,
        *,
        reacquire: bool = False,
    ) -> InteractiveWorkNextAction:
        """Submit the pending Work result through the Harness boundary.

        If ``result_path`` is omitted, the exact result destination generated
        in the Work exchange is used. This is a pointer convenience only; the
        existing boundary still performs path, schema, audit, and reduction
        checks.
        """

        request: WorkExecutionRequest | None = None
        try:
            state = self.orchestrator.status()
            if state.worker_backend != "interactive-work":
                action = self._error_action(
                    state,
                    "Interactive Work Coordinator requires worker_backend='interactive-work'; refusing MockWorker state.",
                    recovery="Use the ordinary Harness CLI for explicit mock tests, never the Interactive Work Coordinator.",
                )
                self._trace(action, submitted_result=str(result_path) if result_path else None)
                return action
            request = state.pending_work
            if state.execution_state != "WORK_EXECUTION_REQUIRED" or request is None:
                action = self._action_for_state(state)
                if action is None:
                    action = self._blocked_action(
                        state,
                        "No interactive Work result is pending.",
                        recovery="Ask the Harness for the next action before submitting a result.",
                    )
                self._trace(action, submitted_result=str(result_path) if result_path else None)
                return action
            self._validate_work_request(request)
            if reacquire:
                if request.expected_output_schema != "ProvenanceAuditHandoff":
                    raise CoordinatorError("--reacquire is valid only for a pending PROVENANCE_AUDIT Work run")
                self.orchestrator.reacquire_provenance_audit()
                next_state = self.orchestrator.status()
                action = self._action_for_state(next_state)
                if action is None:
                    action = self._blocked_action(
                        next_state,
                        "A fresh PROVENANCE_AUDIT Work exchange was not exposed.",
                        recovery="Inspect the immutable discarded run and Harness state.",
                    )
                self._trace(action, submitted_run_id=request.run_id)
                return action
            submitted = Path(result_path or request.expected_output_file).resolve()
            self.orchestrator.collect_work_result(request.run_id, submitted, run_limit=1)
            next_state = self.orchestrator.status()
            action = self._action_for_state(next_state)
            if action is None:
                action = self._blocked_action(
                    next_state,
                    "Work result was accepted, but the Harness did not expose a permitted next action.",
                    recovery="Inspect the immutable run audit and Harness state.",
                )
            self._trace(action, submitted_result=str(submitted), submitted_run_id=request.run_id)
            return action
        except (OSError, ValueError, RuntimeError) as error:
            current = self._safe_state()
            action = self._error_action(
                current,
                f"Work result submission failed: {type(error).__name__}: {error}",
                recovery=(
                    "Inspect the current Harness state and immutable submission trace. Retry only if the same Work run remains pending; "
                    "otherwise resolve the newly reported blocked/error state."
                ),
            )
            self._trace(
                action,
                submitted_result=str(result_path) if result_path else None,
                submitted_run_id=request.run_id if request else None,
            )
            return action

    # ``collect`` is the compact client-facing spelling used by some Work
    # prompts. It delegates to the same single submission path.
    collect = submit_result

    def run_until_stop(
        self,
        *,
        execute_work: WorkExecutor | None = None,
        run_limit: int = 10,
    ) -> InteractiveWorkNextAction:
        """Continue Work tasks until a decision, terminal state, or failure.

        ``execute_work`` is intentionally external. A Work host can execute
        the generated ``TASK.md`` and return its structured result path; the
        coordinator then performs collection through the Harness. With no
        executor, the first Work action is returned so the host can perform
        the task interactively.
        """

        if run_limit < 1:
            raise ValueError("run_limit must be at least 1")
        for _ in range(run_limit):
            action = self.next_action()
            if action.state != "WORK_EXECUTION_REQUIRED":
                return action
            if execute_work is None:
                return action
            try:
                result_path = execute_work(action)
            except Exception as error:  # noqa: BLE001 - external Work callback is an opaque boundary.
                state = self._safe_state()
                failure = self._error_action(
                    state,
                    f"Interactive Work execution failed: {type(error).__name__}: {error}",
                    recovery="Inspect the Work task and retry only the currently pending run.",
                )
                self._trace(failure)
                return failure
            submitted = self.submit_result(result_path)
            if submitted.state != "WORK_EXECUTION_REQUIRED":
                return submitted
        return self.next_action(advance=False)

    def _action_for_state(self, state: OrchestratorState) -> InteractiveWorkNextAction | None:
        # An implementation-only provenance repair may run beside a pending
        # Research Human Decision. It is safe to expose that Work boundary
        # first because the repair does not consume or mutate the decision.
        if (
            state.execution_state == "WORK_EXECUTION_REQUIRED"
            and state.pending_work is not None
            and state.pending_work.expected_output_schema == "ProvenanceAuditHandoff"
        ):
            return self._work_action(state, state.pending_work)
        if state.pending_decision_ids:
            return self._decision_action(state, state.pending_decision_ids[0])
        if state.execution_state == "WORK_EXECUTION_REQUIRED" and state.pending_work is not None:
            return self._work_action(state, state.pending_work)
        if state.terminal:
            return InteractiveWorkNextAction(
                state="COMPLETE",
                observed_state_id=state.state_id,
                phase=state.phase,
                worker_backend=state.worker_backend,
                message="Research orchestration is terminal; no further Work task is permitted.",
            )
        return None

    def _work_action(
        self,
        state: OrchestratorState,
        request: WorkExecutionRequest,
    ) -> InteractiveWorkNextAction:
        self._validate_work_request(request)
        return InteractiveWorkNextAction(
            state="WORK_EXECUTION_REQUIRED",
            observed_state_id=state.state_id,
            phase=state.phase,
            worker_backend=state.worker_backend,
            message=(
                "Execute TASK.md using only the authorized Context Pack. "
                "Repository access for Harness control is not permission to use repository contents as Research Context."
            ),
            run_id=request.run_id,
            task_type=self._run_task_type(request.run_id),
            context_pack=request.context_pack,
            task_file=request.task_file,
            result_schema=request.expected_output_schema,
            result_schema_file=request.expected_output_schema_file,
            result_destination=request.expected_output_file,
            resume_instruction=f"Submit the structured result with the coordinator for run {request.run_id}.",
        )

    def _decision_action(self, state: OrchestratorState, decision_id: str) -> InteractiveWorkNextAction:
        request_path = self.runtime / "decisions" / decision_id / "request.json"
        packet_path = self.runtime / "decisions" / decision_id / "request.md"
        try:
            request = DecisionRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return self._blocked_action(
                state,
                f"Human Decision {decision_id!r} is pending but its Decision Packet is unavailable: {error}",
                recovery="Restore or regenerate the immutable Decision Packet before resuming.",
                decision_id=decision_id,
            )
        return InteractiveWorkNextAction(
            state="DECISION_REQUIRED",
            observed_state_id=state.state_id,
            phase=state.phase,
            worker_backend=state.worker_backend,
            message="Human Decision is required. The coordinator will not choose or record a decision.",
            decision_id=decision_id,
            decision_packet=str(packet_path.resolve()) if packet_path.is_file() else None,
            decision_request=str(request_path.resolve()),
            decision_options=request.options,
            resume_instruction=(
                f"Record the human choice with: rh --root {self.workspace} decision record "
                f"{decision_id} --choice <OPTION_ID> --by <HUMAN>"
            ),
        )

    def _validate_work_request(self, request: WorkExecutionRequest) -> None:
        context_pack = Path(request.context_pack).resolve()
        exchange = Path(request.exchange_directory).resolve()
        context_root = (self.runtime / "context_packs").resolve()
        exchange_root = (self.runtime / "work_exchange").resolve()
        if not context_pack.is_dir() or not context_pack.is_relative_to(context_root):
            raise CoordinatorError("pending Work Context Pack is outside the Harness Context Pack root")
        actual_digest = sha256_tree(context_pack)
        if request.context_pack_sha256 is None:
            raise CoordinatorError(
                "pending Work request predates Context Pack tree binding; recreate the pending run before execution"
            )
        if actual_digest != request.context_pack_sha256:
            raise CoordinatorError("pending Work Context Pack tree hash does not match its frozen request")
        if not exchange.is_dir() or not exchange.is_relative_to(exchange_root):
            raise CoordinatorError("pending Work exchange is outside the Harness work_exchange root")
        expected_manifest = context_pack / "manifest.json"
        if Path(request.manifest).resolve() != expected_manifest.resolve():
            raise CoordinatorError("pending Work manifest is not the immutable Context Pack manifest")
        for pointer in (request.task_file, request.expected_output_schema_file, request.expected_output_file):
            path = Path(pointer).resolve()
            if not path.is_relative_to(exchange):
                raise CoordinatorError("pending Work pointer escapes its exchange directory")
        if not Path(request.task_file).is_file():
            raise CoordinatorError("generated TASK.md is missing")
        if not Path(request.expected_output_schema_file).is_file():
            raise CoordinatorError("generated result schema is missing")

    def _run_task_type(self, run_id: str) -> str | None:
        try:
            data = self.orchestrator.store.read_json(Path("runs") / run_id / "manifest.json")
            return str(data.get("task_type")) if data.get("task_type") else None
        except (OSError, ValueError):
            return None

    def _safe_state(self) -> OrchestratorState:
        try:
            return self.orchestrator.status()
        except (OSError, ValueError):
            return OrchestratorState(state_id="unavailable", worker_backend="interactive-work")

    @staticmethod
    def _error_action(
        state: OrchestratorState,
        message: str,
        *,
        recovery: str,
    ) -> InteractiveWorkNextAction:
        return InteractiveWorkNextAction(
            state="ERROR",
            observed_state_id=state.state_id,
            phase=state.phase,
            worker_backend=state.worker_backend,
            message=message,
            recovery=recovery,
        )

    @staticmethod
    def _blocked_action(
        state: OrchestratorState,
        message: str,
        *,
        recovery: str,
        decision_id: str | None = None,
    ) -> InteractiveWorkNextAction:
        return InteractiveWorkNextAction(
            state="BLOCKED",
            observed_state_id=state.state_id,
            phase=state.phase,
            worker_backend=state.worker_backend,
            message=message,
            recovery=recovery,
            decision_id=decision_id,
        )

    def _trace(
        self,
        action: InteractiveWorkNextAction,
        *,
        submitted_result: str | None = None,
        submitted_run_id: str | None = None,
    ) -> None:
        trace = CoordinatorTrace(
            trace_id=f"coordinator-{uuid.uuid4().hex[:12]}",
            observed_state_id=action.observed_state_id,
            action_state=action.state,
            phase=action.phase,
            run_id=action.run_id,
            task_file=action.task_file,
            context_pack=action.context_pack,
            submitted_result=submitted_result,
            submitted_run_id=submitted_run_id,
            decision_id=action.decision_id,
            message=action.message,
        )
        self.orchestrator.store.write_immutable(Path("coordinator") / "traces" / f"{trace.trace_id}.json", trace)


# A concise alias for callers that do not need the longer class name.
ResearchCoordinator = InteractiveWorkResearchCoordinator

# The Work-chat control-plane contract is a separate thin boundary. Keep the
# existing Desktop Research coordinator intact and expose the new service from
# this discoverable module without making either coordinator a second planner.
from misco_harness.conversation import WorkConversationCoordinator

ConversationCoordinator = WorkConversationCoordinator
