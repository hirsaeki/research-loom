from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.runtime.normalization import (
    CapabilityNormalizationBoundary,
    NormalizationRejected,
)

from .models import (
    CapabilityExecutionError,
    CapabilityExecutionRequest,
    CapabilityRunRecord,
    ExecutionFailureCode,
    ExecutionIssue,
    ExecutionResult,
    ExecutionStyle,
    PreparedExecution,
    RunLifecycleEvent,
    RunStatus,
)
from .ports import (
    ExecutionArtifactStore,
    ExecutionTraceStore,
    ResourceProvider,
    RuntimeAuthorizationProvider,
    RuntimeClock,
    StateViewProvider,
)
from .registry import CapabilityRegistry
from .resource_access import BoundedResourceAccess
from .validation import CanonicalCapabilityExecutionValidator


_ALLOWED_TRANSITIONS = {
    RunStatus.PREPARED: {
        RunStatus.RUNNING,
        RunStatus.ABORTED,
        RunStatus.SUPERSEDED,
    },
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.ABORTED,
        RunStatus.SUPERSEDED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.ABORTED: set(),
    RunStatus.SUPERSEDED: set(),
}
_TERMINAL_STATUSES = frozenset(
    status
    for status, allowed_next in _ALLOWED_TRANSITIONS.items()
    if not allowed_next
)


class CapabilityExecutionService:
    """Execute or collect one PR9 Capability Run without mutating Research State."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        trace_store: ExecutionTraceStore,
        state_provider: StateViewProvider,
        authorization_provider: RuntimeAuthorizationProvider,
        resource_provider: ResourceProvider,
        normalization_boundary: CapabilityNormalizationBoundary,
        clock: RuntimeClock,
        *,
        artifact_store: ExecutionArtifactStore | None = None,
        validator: CanonicalCapabilityExecutionValidator | None = None,
    ) -> None:
        self._registry = registry
        self._traces = trace_store
        self._states = state_provider
        self._authorization = authorization_provider
        self._resources = resource_provider
        self._artifact_store = artifact_store
        self._normalization = normalization_boundary
        self._clock = clock
        self._validator = validator or CanonicalCapabilityExecutionValidator()

    def execute_managed(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        *,
        lineage_ref: str,
    ) -> ExecutionResult:
        """Run a managed adapter and return at most a candidate StateDeltaProposal."""
        run, adapter, access = self._prepare(
            descriptor,
            invocation,
            context_pack,
            lineage_ref=lineage_ref,
            expected_style=ExecutionStyle.MANAGED,
        )
        run = self._transition(
            run,
            RunStatus.RUNNING,
            "managed execution started",
            started_at=self._clock.now(),
        )
        try:
            output = adapter.execute(
                CapabilityExecutionRequest(
                    run,
                    deepcopy(dict(descriptor)),
                    deepcopy(dict(invocation)),
                    deepcopy(dict(context_pack)),
                    access,
                )
            )
        except CapabilityExecutionError as exc:
            return self._fail(run, exc.issue)
        except Exception as exc:
            return self._fail(
                run,
                ExecutionIssue(
                    ExecutionFailureCode.EXECUTION_FAILED.value,
                    f"capability adapter failed: {exc}",
                    True,
                ),
            )
        return self._accept_output(
            run,
            output.handoff,
            output.extension,
            output.artifacts,
        )

    def prepare_external(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        *,
        lineage_ref: str,
    ) -> PreparedExecution:
        """Prepare immutable inputs for an external/interactive execution."""
        run, _adapter, _access = self._prepare(
            descriptor,
            invocation,
            context_pack,
            lineage_ref=lineage_ref,
            expected_style=ExecutionStyle.EXTERNAL,
        )
        run = self._transition(
            run,
            RunStatus.RUNNING,
            "external/interactive execution prepared",
            started_at=self._clock.now(),
        )
        return PreparedExecution(
            run,
            run.invocation_digest,
            run.context_pack_digest,
        )

    def collect_external(
        self,
        run_id: str,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None = None,
        artifacts=(),
    ) -> ExecutionResult:
        """Collect a Handoff against the exact immutable external Run inputs."""
        run = self._require_run(run_id)
        if run.status in {RunStatus.ABORTED, RunStatus.SUPERSEDED}:
            self._traces.store_diagnostic(
                run_id,
                "late_result",
                deepcopy(dict(handoff)),
            )
            return ExecutionResult(
                run,
                None,
                None,
                None,
                None,
                (
                    ExecutionIssue(
                        ExecutionFailureCode.RUN_ABORTED.value,
                        "late result retained only as diagnostic; terminal Run cannot adopt it",
                    ),
                ),
            )
        if run.status is not RunStatus.RUNNING:
            raise CapabilityExecutionError(
                ExecutionFailureCode.INVOCATION_INVALID,
                f"Run {run_id} is not collecting external output from RUNNING state",
            )
        invocation = self._required_doc(
            self._traces.load_invocation(run.invocation_id),
            "stored invocation",
        )
        context = self._required_doc(
            self._traces.load_context_pack(run.context_pack_id),
            "stored Context Pack",
        )
        descriptor = self._required_doc(
            self._traces.load_descriptor(run.descriptor_digest),
            "stored descriptor",
        )
        self._validator.validate_documents(descriptor, invocation, context)
        if (
            invocation.get("invocation_digest") != run.invocation_digest
            or context.get("context_pack_digest") != run.context_pack_digest
            or descriptor.get("descriptor_digest") != run.descriptor_digest
        ):
            raise CapabilityExecutionError(
                ExecutionFailureCode.INVOCATION_INVALID,
                "stored execution documents no longer match Run pins",
            )
        self._validate_authorization(invocation, context)
        adapter = self._registry.resolve(
            run.capability_id,
            run.capability_version,
            run.function_id,
            run.execution_mode,
        )
        if (
            adapter.implementation_id,
            adapter.implementation_version,
        ) != (
            run.implementation_id,
            run.implementation_version,
        ):
            raise CapabilityExecutionError(
                ExecutionFailureCode.IMPLEMENTATION_AMBIGUOUS,
                "external collection no longer resolves to the implementation pinned by the Run",
            )
        return self._accept_output(run, handoff, extension, artifacts)

    def abort(
        self,
        run_id: str,
        *,
        reason: str = "explicit abort",
    ) -> CapabilityRunRecord:
        """Attempt an atomic terminal abort and best-effort adapter cancellation."""
        run = self._require_run(run_id)
        if run.status not in {RunStatus.PREPARED, RunStatus.RUNNING}:
            return run
        try:
            aborted = self._transition(
                run,
                RunStatus.ABORTED,
                reason,
                completed_at=self._clock.now(),
            )
        except CapabilityExecutionError:
            return self._require_run(run_id)
        try:
            adapter = self._registry.resolve(
                run.capability_id,
                run.capability_version,
                run.function_id,
                run.execution_mode,
            )
            adapter.cancel(run_id)
        except Exception as exc:
            self._traces.store_diagnostic(
                run_id,
                "cancellation_failed",
                {
                    "reason": str(exc),
                    "implementation_id": run.implementation_id,
                    "implementation_version": run.implementation_version,
                },
            )
        return aborted

    def _prepare(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        *,
        lineage_ref: str,
        expected_style: ExecutionStyle,
    ):
        self._validator.validate_documents(
            descriptor,
            invocation,
            context_pack,
        )
        try:
            state = self._states.load_state_view(
                str(invocation["project_id"]),
                lineage_ref,
            )
        except KeyError as exc:
            raise CapabilityExecutionError(
                ExecutionFailureCode.STALE_STATE,
                "Invocation project/lineage does not resolve to current Research State",
            ) from exc
        self._validator.validate_state_binding(context_pack, state)

        capability = invocation["capability"]
        adapter = self._registry.resolve(
            capability["capability_id"],
            capability["capability_version"],
            capability["function_id"],
            invocation["execution_mode"],
        )
        if adapter.execution_style is not expected_style:
            raise CapabilityExecutionError(
                ExecutionFailureCode.IMPLEMENTATION_NOT_FOUND,
                f"resolved adapter is {adapter.execution_style.value}, not {expected_style.value}",
            )
        decision = self._validate_authorization(invocation, context_pack)

        parent_run_id = invocation["trace"].get("parent_run_id")
        attempt = 1
        if parent_run_id:
            parent = self._require_run(parent_run_id)
            if parent.run_id == invocation["run_id"]:
                raise CapabilityExecutionError(
                    ExecutionFailureCode.INVOCATION_INVALID,
                    "retry must use a new Run ID",
                )
            if parent.project_ref != str(invocation["project_id"]):
                raise CapabilityExecutionError(
                    ExecutionFailureCode.INVOCATION_INVALID,
                    "retry parent must belong to the same project",
                )
            if (
                parent.capability_id,
                parent.capability_version,
                parent.function_id,
                parent.execution_mode,
            ) != (
                capability["capability_id"],
                capability["capability_version"],
                capability["function_id"],
                invocation["execution_mode"],
            ):
                raise CapabilityExecutionError(
                    ExecutionFailureCode.INVOCATION_INVALID,
                    "retry parent must preserve capability/function/execution mode",
                )
            if parent.status not in _TERMINAL_STATUSES:
                raise CapabilityExecutionError(
                    ExecutionFailureCode.INVOCATION_INVALID,
                    "retry parent Run must be terminal before a new attempt is prepared",
                )
            attempt = parent.attempt + 1

        now = self._clock.now()
        snapshot = context_pack["pins"]["research_snapshot"]
        run = CapabilityRunRecord(
            run_id=invocation["run_id"],
            invocation_id=invocation["invocation_id"],
            invocation_digest=invocation["invocation_digest"],
            capability_id=capability["capability_id"],
            capability_version=capability["capability_version"],
            descriptor_digest=capability["descriptor_digest"],
            implementation_id=adapter.implementation_id,
            implementation_version=adapter.implementation_version,
            function_id=capability["function_id"],
            execution_mode=invocation["execution_mode"],
            context_pack_id=context_pack["context_pack_id"],
            context_pack_digest=context_pack["context_pack_digest"],
            project_ref=invocation["project_id"],
            lineage_ref=lineage_ref,
            snapshot_ref=snapshot["snapshot_id"],
            snapshot_digest=snapshot["content_digest"],
            attempt=attempt,
            parent_run_id=parent_run_id,
            status=RunStatus.PREPARED,
            prepared_at=now,
            provenance={"trace_id": invocation["trace"]["trace_id"]},
        )
        self._traces.store_descriptor(deepcopy(dict(descriptor)))
        self._traces.store_invocation(deepcopy(dict(invocation)))
        self._traces.store_context_pack(deepcopy(dict(context_pack)))
        self._traces.create_run(run)
        self._traces.append_run_event(
            RunLifecycleEvent(
                run.run_id,
                1,
                None,
                RunStatus.PREPARED,
                now,
                "validated immutable execution documents",
            )
        )
        access = BoundedResourceAccess(
            context_pack,
            decision.resource_reference_ids,
            self._resources,
            artifact_store=self._artifact_store,
        )
        return run, adapter, access

    def _validate_authorization(
        self,
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
    ):
        decision = self._authorization.validate(
            invocation["runtime_authorization_evidence"],
            invocation=invocation,
            context_pack=context_pack,
            now=self._clock.now(),
        )
        if not decision.allowed:
            message = (
                "; ".join(issue.message for issue in decision.issues)
                or "runtime authorization denied"
            )
            raise CapabilityExecutionError(
                ExecutionFailureCode.AUTHORIZATION_DENIED,
                message,
            )
        required = {
            item["reference_id"] for item in context_pack["resources"]
        }
        if not required.issubset(set(decision.resource_reference_ids)):
            raise CapabilityExecutionError(
                ExecutionFailureCode.AUTHORIZATION_DENIED,
                "authorization provider did not grant every bounded Context Pack resource",
            )
        return decision

    def _accept_output(
        self,
        run: CapabilityRunRecord,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        artifacts,
    ) -> ExecutionResult:
        invocation = self._required_doc(
            self._traces.load_invocation(run.invocation_id),
            "stored invocation",
        )
        context = self._required_doc(
            self._traces.load_context_pack(run.context_pack_id),
            "stored Context Pack",
        )
        extension_ref = None
        try:
            self._traces.store_handoff(deepcopy(dict(handoff)))
            if extension is not None:
                extension_ref = self._traces.store_result_extension(
                    run.run_id,
                    deepcopy(dict(extension)),
                )
            for artifact in artifacts:
                if (
                    artifact.run_id != run.run_id
                    or artifact.execution_mode != run.execution_mode
                ):
                    return self._fail(
                        run,
                        ExecutionIssue(
                            ExecutionFailureCode.HANDOFF_INVALID.value,
                            "artifact metadata does not match Run identity/mode",
                        ),
                    )
                self._traces.register_output_artifact(artifact)
        except Exception as exc:
            return self._fail(
                run,
                ExecutionIssue(
                    ExecutionFailureCode.EXECUTION_FAILED.value,
                    f"execution trace capture failed: {exc}",
                ),
            )

        try:
            self._validator.validate_handoff(handoff, invocation, context)
            provenance = handoff["provenance"]
            if (
                provenance["implementation_id"] != run.implementation_id
                or provenance["implementation_version"]
                != run.implementation_version
            ):
                raise CapabilityExecutionError(
                    "CAP-HANDOFF-PROVENANCE-001",
                    "Handoff implementation provenance does not match the pinned adapter",
                )
        except CapabilityExecutionError as exc:
            return self._fail(run, exc.issue)

        status = str(handoff["validation"]["status"])
        try:
            completed = self._transition(
                run,
                RunStatus.COMPLETED,
                f"canonical Handoff {status}",
                completed_at=self._clock.now(),
                handoff_ref=handoff["handoff_id"],
                handoff_digest=handoff["handoff_digest"],
            )
        except CapabilityExecutionError as exc:
            current = self._require_run(run.run_id)
            self._traces.store_diagnostic(
                run.run_id,
                "late_or_racing_result",
                deepcopy(dict(handoff)),
            )
            return ExecutionResult(
                current,
                None,
                None,
                extension_ref,
                None,
                (exc.issue,),
            )

        if status == "rejected":
            return ExecutionResult(
                completed,
                handoff["handoff_id"],
                status,
                extension_ref,
                None,
                (
                    ExecutionIssue(
                        ExecutionFailureCode.HANDOFF_REJECTED.value,
                        "rejected Handoff is retained for audit but cannot be normalized",
                    ),
                ),
            )

        try:
            current = self._states.load_state_view(
                run.project_ref,
                run.lineage_ref,
            )
        except KeyError:
            return ExecutionResult(
                completed,
                handoff["handoff_id"],
                status,
                extension_ref,
                None,
                (
                    ExecutionIssue(
                        ExecutionFailureCode.STALE_STATE.value,
                        "Run project/lineage no longer resolves; Handoff retained without normalization",
                    ),
                ),
            )

        try:
            proposal = self._normalization.normalize(
                handoff,
                extension=extension,
                state=current,
                context={
                    "run_id": run.run_id,
                    "implementation_id": run.implementation_id,
                },
            )
            return ExecutionResult(
                completed,
                handoff["handoff_id"],
                status,
                extension_ref,
                proposal,
                (),
            )
        except NormalizationRejected as exc:
            snapshot = current.current_snapshot
            code = (
                ExecutionFailureCode.STALE_STATE.value
                if (
                    snapshot.get("id") != run.snapshot_ref
                    or snapshot.get("content_digest") != run.snapshot_digest
                )
                else ExecutionFailureCode.NORMALIZATION_REJECTED.value
            )
            return ExecutionResult(
                completed,
                handoff["handoff_id"],
                status,
                extension_ref,
                None,
                (ExecutionIssue(code, str(exc)),),
            )

    def _transition(
        self,
        run: CapabilityRunRecord,
        status: RunStatus,
        reason: str,
        **changes: Any,
    ) -> CapabilityRunRecord:
        if status not in _ALLOWED_TRANSITIONS[run.status]:
            raise CapabilityExecutionError(
                ExecutionFailureCode.INVOCATION_INVALID,
                f"illegal Run lifecycle transition {run.status.value} -> {status.value}",
            )
        updated = run.with_status(status, **changes)
        sequence = 2 if run.status is RunStatus.PREPARED else 3
        event = RunLifecycleEvent(
            run.run_id,
            sequence,
            run.status,
            status,
            self._clock.now(),
            reason,
        )
        if not self._traces.transition_run(run.status, updated, event):
            current = self._require_run(run.run_id)
            code = (
                ExecutionFailureCode.RUN_ABORTED
                if current.status in {RunStatus.ABORTED, RunStatus.SUPERSEDED}
                else ExecutionFailureCode.INVOCATION_INVALID
            )
            raise CapabilityExecutionError(
                code,
                "Run lifecycle changed concurrently; stale transition was rejected",
            )
        return updated

    def _fail(
        self,
        run: CapabilityRunRecord,
        issue: ExecutionIssue,
    ) -> ExecutionResult:
        try:
            failed = self._transition(
                run,
                RunStatus.FAILED,
                issue.message,
                completed_at=self._clock.now(),
                failure=issue,
            )
            return ExecutionResult(
                failed,
                None,
                None,
                None,
                None,
                (issue,),
            )
        except CapabilityExecutionError as conflict:
            current = self._require_run(run.run_id)
            return ExecutionResult(
                current,
                None,
                None,
                None,
                None,
                (issue, conflict.issue),
            )

    def _require_run(self, run_id: str) -> CapabilityRunRecord:
        run = self._traces.load_run(run_id)
        if run is None:
            raise CapabilityExecutionError(
                ExecutionFailureCode.INVOCATION_INVALID,
                f"unknown Run {run_id}",
            )
        return run

    @staticmethod
    def _required_doc(value, label):
        if value is None:
            raise CapabilityExecutionError(
                ExecutionFailureCode.INVOCATION_INVALID,
                f"{label} is missing from execution trace",
            )
        return value