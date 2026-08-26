from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .context_extensions import (
    CapabilityContextExtensionRegistry,
    CapabilityContextExtensionStore,
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
from .resource_access import BoundedResourceAccess
from .service import (
    CapabilityExecutionService as _BaseCapabilityExecutionService,
    _TERMINAL_STATUSES,
)


@dataclass(frozen=True)
class CapabilityExecutionRequestWithContext(CapabilityExecutionRequest):
    """Internal runtime request that exposes the validated Context extension."""

    context_extension: Mapping[str, Any] | None = None


class CapabilityExecutionService(_BaseCapabilityExecutionService):
    """PR22 execution service with a generic capability Context preflight hook.

    The base PR22/23 service remains the implementation of lifecycle,
    authorization, Handoff capture, and normalization. This subclass only adds
    the capability-neutral extension validation/storage seam required before an
    EXTERNAL Run can enter PREPARED/RUNNING.
    """

    def __init__(self, *args, context_extension_registry=None,
                 context_extension_store=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._context_extension_registry = (
            context_extension_registry or CapabilityContextExtensionRegistry()
        )
        self._context_extension_store: CapabilityContextExtensionStore | None = (
            context_extension_store
        )

    def execute_managed(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        *,
        lineage_ref: str,
        context_extension: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        run, adapter, access = self._prepare_with_context_extension(
            descriptor,
            invocation,
            context_pack,
            context_extension,
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
                CapabilityExecutionRequestWithContext(
                    run,
                    deepcopy(dict(descriptor)),
                    deepcopy(dict(invocation)),
                    deepcopy(dict(context_pack)),
                    access,
                    context_extension=deepcopy(dict(context_extension))
                    if context_extension is not None else None,
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
        context_extension: Mapping[str, Any] | None = None,
    ) -> PreparedExecution:
        run, _adapter, _access = self._prepare_with_context_extension(
            descriptor,
            invocation,
            context_pack,
            context_extension,
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

    def collect_external(self, run_id: str, handoff, extension=None, artifacts=()):
        run = self._traces.load_run(run_id)
        if run is not None and run.status is RunStatus.RUNNING:
            adapter = self._registry.resolve(
                run.capability_id,
                run.capability_version,
                run.function_id,
                run.execution_mode,
            )
            if getattr(adapter, "requires_context_extension", False):
                if self._context_extension_store is None:
                    raise CapabilityExecutionError(
                        ExecutionFailureCode.CONTEXT_INVALID,
                        "required Context extension store is unavailable at collection",
                    )
                stored = self._context_extension_store.load(
                    run.capability_id,
                    run.capability_version,
                    run.function_id,
                    run.context_pack_id,
                )
                if stored is None:
                    raise CapabilityExecutionError(
                        ExecutionFailureCode.CONTEXT_INVALID,
                        "validated Context extension is missing at collection",
                    )
        return super().collect_external(run_id, handoff, extension, artifacts)

    def _prepare_with_context_extension(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        context_extension: Mapping[str, Any] | None,
        *,
        lineage_ref: str,
        expected_style: ExecutionStyle,
    ):
        self._validator.validate_documents(descriptor, invocation, context_pack)
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

        required = bool(getattr(adapter, "requires_context_extension", False))
        self._context_extension_registry.validate(
            descriptor,
            invocation,
            context_pack,
            context_extension,
            state,
            required=required,
        )
        if context_extension is not None and self._context_extension_store is None:
            raise CapabilityExecutionError(
                ExecutionFailureCode.CONTEXT_INVALID,
                "validated capability Context extension has no immutable runtime store",
            )

        decision = self._validate_authorization(invocation, context_pack)

        if context_extension is not None:
            try:
                self._context_extension_store.store(
                    str(capability["capability_id"]),
                    str(capability["capability_version"]),
                    str(capability["function_id"]),
                    str(context_pack["context_pack_id"]),
                    deepcopy(dict(context_extension)),
                )
            except CapabilityExecutionError:
                raise
            except Exception as exc:
                raise CapabilityExecutionError(
                    ExecutionFailureCode.CONTEXT_INVALID,
                    f"capability Context extension persistence failed: {exc}",
                ) from exc

        parent_run_id = invocation["trace"].get("parent_run_id")
        attempt = 1
        if parent_run_id:
            parent = self._require_run(parent_run_id)
            if parent.run_id == invocation["run_id"]:
                raise CapabilityExecutionError(
                    ExecutionFailureCode.INVOCATION_INVALID,
                    "retry must use a new Run ID",
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
                "validated immutable execution documents and capability Context extension",
            )
        )
        access = BoundedResourceAccess(
            context_pack,
            decision.resource_reference_ids,
            self._resources,
            artifact_store=self._artifact_store,
        )
        return run, adapter, access
