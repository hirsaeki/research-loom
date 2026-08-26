from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.runtime.normalization import CapabilityNormalizationBoundary, NormalizationRejected

from .models import (
    CapabilityExecutionError, CapabilityExecutionRequest, CapabilityRunRecord,
    ExecutionFailureCode, ExecutionIssue, ExecutionResult, ExecutionStyle,
    PreparedExecution, RunLifecycleEvent, RunStatus,
)
from .ports import ExecutionTraceStore, ResourceProvider, RuntimeAuthorizationProvider, RuntimeClock, StateViewProvider
from .registry import CapabilityRegistry
from .resource_access import BoundedResourceAccess
from .validation import CanonicalCapabilityExecutionValidator


_ALLOWED_TRANSITIONS = {
    RunStatus.PREPARED: {RunStatus.RUNNING, RunStatus.ABORTED, RunStatus.SUPERSEDED},
    RunStatus.RUNNING: {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED, RunStatus.SUPERSEDED},
    RunStatus.COMPLETED: set(), RunStatus.FAILED: set(), RunStatus.ABORTED: set(), RunStatus.SUPERSEDED: set(),
}


class CapabilityExecutionService:
    def __init__(self, registry: CapabilityRegistry, trace_store: ExecutionTraceStore, state_provider: StateViewProvider,
                 authorization_provider: RuntimeAuthorizationProvider, resource_provider: ResourceProvider,
                 normalization_boundary: CapabilityNormalizationBoundary, clock: RuntimeClock, *,
                 validator: CanonicalCapabilityExecutionValidator | None = None) -> None:
        self._registry=registry; self._traces=trace_store; self._states=state_provider; self._authorization=authorization_provider
        self._resources=resource_provider; self._normalization=normalization_boundary; self._clock=clock
        self._validator=validator or CanonicalCapabilityExecutionValidator()

    def execute_managed(self, descriptor: Mapping[str, Any], invocation: Mapping[str, Any], context_pack: Mapping[str, Any], *, lineage_ref: str) -> ExecutionResult:
        run, adapter, access = self._prepare(descriptor, invocation, context_pack, lineage_ref=lineage_ref, expected_style=ExecutionStyle.MANAGED)
        run=self._transition(run,RunStatus.RUNNING,"managed execution started",started_at=self._clock.now())
        try:
            output=adapter.execute(CapabilityExecutionRequest(run,deepcopy(dict(descriptor)),deepcopy(dict(invocation)),deepcopy(dict(context_pack)),access))
        except CapabilityExecutionError as exc:
            return self._fail(run,exc.issue)
        except Exception as exc:
            return self._fail(run,ExecutionIssue(ExecutionFailureCode.EXECUTION_FAILED.value,f"capability adapter failed: {exc}",True))
        return self._accept_output(run,output.handoff,output.extension,output.artifacts)

    def prepare_external(self, descriptor: Mapping[str, Any], invocation: Mapping[str, Any], context_pack: Mapping[str, Any], *, lineage_ref: str) -> PreparedExecution:
        run,_adapter,_access=self._prepare(descriptor,invocation,context_pack,lineage_ref=lineage_ref,expected_style=ExecutionStyle.EXTERNAL)
        run=self._transition(run,RunStatus.RUNNING,"external/interactive execution prepared",started_at=self._clock.now())
        return PreparedExecution(run,run.invocation_digest,run.context_pack_digest)

    def collect_external(self, run_id: str, handoff: Mapping[str, Any], extension: Mapping[str, Any] | None = None, artifacts=()) -> ExecutionResult:
        run=self._require_run(run_id)
        if run.status in {RunStatus.ABORTED,RunStatus.SUPERSEDED}:
            self._traces.store_diagnostic(run_id,"late_result",deepcopy(dict(handoff)))
            return ExecutionResult(run,None,None,None,None,(ExecutionIssue(ExecutionFailureCode.RUN_ABORTED.value,"late result retained only as diagnostic; terminal Run cannot adopt it"),))
        if run.status is not RunStatus.RUNNING:
            raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,f"Run {run_id} is not collecting external output from RUNNING state")
        invocation=self._required_doc(self._traces.load_invocation(run.invocation_id),"stored invocation")
        context=self._required_doc(self._traces.load_context_pack(run.context_pack_id),"stored Context Pack")
        descriptor=self._required_doc(self._traces.load_descriptor(run.descriptor_digest),"stored descriptor")
        if invocation.get("invocation_digest") != run.invocation_digest or context.get("context_pack_digest") != run.context_pack_digest or descriptor.get("descriptor_digest") != run.descriptor_digest:
            raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,"stored execution documents no longer match Run pins")
        self._validate_authorization(invocation,context)
        adapter=self._registry.resolve(run.capability_id,run.capability_version,run.function_id,run.execution_mode)
        if (adapter.implementation_id,adapter.implementation_version)!=(run.implementation_id,run.implementation_version):
            raise CapabilityExecutionError(ExecutionFailureCode.IMPLEMENTATION_AMBIGUOUS,"external collection no longer resolves to the implementation pinned by the Run")
        return self._accept_output(run,handoff,extension,artifacts)

    def abort(self, run_id: str, *, reason: str = "explicit abort") -> CapabilityRunRecord:
        run=self._require_run(run_id)
        if run.status not in {RunStatus.PREPARED,RunStatus.RUNNING}: return run
        aborted=self._transition(run,RunStatus.ABORTED,reason,completed_at=self._clock.now())
        try:
            self._registry.resolve(run.capability_id,run.capability_version,run.function_id,run.execution_mode).cancel(run_id)
        except Exception:
            pass
        return aborted

    def _prepare(self, descriptor, invocation, context_pack, *, lineage_ref: str, expected_style: ExecutionStyle):
        state=self._states.load_state_view(str(invocation.get("project_id","")),lineage_ref)
        self._validator.validate_preflight(descriptor,invocation,context_pack,state)
        capability=invocation["capability"]
        adapter=self._registry.resolve(capability["capability_id"],capability["capability_version"],capability["function_id"],invocation["execution_mode"])
        if adapter.execution_style is not expected_style:
            raise CapabilityExecutionError(ExecutionFailureCode.IMPLEMENTATION_NOT_FOUND,f"resolved adapter is {adapter.execution_style.value}, not {expected_style.value}")
        decision=self._validate_authorization(invocation,context_pack)
        parent_run_id=invocation["trace"].get("parent_run_id"); attempt=1
        if parent_run_id:
            parent=self._require_run(parent_run_id)
            if parent.run_id==invocation["run_id"]: raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,"retry must use a new Run ID")
            if parent.execution_mode!=invocation["execution_mode"]: raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,"retry may not implicitly change execution mode")
            attempt=parent.attempt+1
        now=self._clock.now(); snapshot=context_pack["pins"]["research_snapshot"]
        run=CapabilityRunRecord(
            run_id=invocation["run_id"],invocation_id=invocation["invocation_id"],invocation_digest=invocation["invocation_digest"],
            capability_id=capability["capability_id"],capability_version=capability["capability_version"],descriptor_digest=capability["descriptor_digest"],
            implementation_id=adapter.implementation_id,implementation_version=adapter.implementation_version,function_id=capability["function_id"],execution_mode=invocation["execution_mode"],
            context_pack_id=context_pack["context_pack_id"],context_pack_digest=context_pack["context_pack_digest"],project_ref=invocation["project_id"],lineage_ref=lineage_ref,
            snapshot_ref=snapshot["snapshot_id"],snapshot_digest=snapshot["content_digest"],attempt=attempt,parent_run_id=parent_run_id,status=RunStatus.PREPARED,prepared_at=now,
            provenance={"trace_id":invocation["trace"]["trace_id"]},)
        self._traces.store_descriptor(deepcopy(dict(descriptor))); self._traces.store_invocation(deepcopy(dict(invocation))); self._traces.store_context_pack(deepcopy(dict(context_pack)))
        self._traces.create_run(run); self._traces.append_run_event(RunLifecycleEvent(run.run_id,1,None,RunStatus.PREPARED,now,"validated immutable execution documents"))
        return run,adapter,BoundedResourceAccess(context_pack,decision.resource_reference_ids,self._resources)

    def _validate_authorization(self, invocation, context_pack):
        decision=self._authorization.validate(invocation["runtime_authorization_evidence"],invocation=invocation,context_pack=context_pack,now=self._clock.now())
        if not decision.allowed:
            message="; ".join(issue.message for issue in decision.issues) or "runtime authorization denied"
            raise CapabilityExecutionError(ExecutionFailureCode.AUTHORIZATION_DENIED,message)
        if not {item["reference_id"] for item in context_pack["resources"]}.issubset(set(decision.resource_reference_ids)):
            raise CapabilityExecutionError(ExecutionFailureCode.AUTHORIZATION_DENIED,"authorization provider did not grant every bounded Context Pack resource")
        return decision

    def _accept_output(self, run, handoff, extension, artifacts):
        invocation=self._required_doc(self._traces.load_invocation(run.invocation_id),"stored invocation"); context=self._required_doc(self._traces.load_context_pack(run.context_pack_id),"stored Context Pack")
        self._traces.store_handoff(deepcopy(dict(handoff)))
        extension_ref=self._traces.store_result_extension(run.run_id,deepcopy(dict(extension))) if extension is not None else None
        for artifact in artifacts:
            if artifact.run_id!=run.run_id or artifact.execution_mode!=run.execution_mode:
                return self._fail(run,ExecutionIssue(ExecutionFailureCode.HANDOFF_INVALID.value,"artifact metadata does not match Run identity/mode"))
            self._traces.register_output_artifact(artifact)
        try: self._validator.validate_handoff(handoff,invocation,context)
        except CapabilityExecutionError as exc: return self._fail(run,exc.issue)
        status=str(handoff["validation"]["status"])
        completed=self._transition(run,RunStatus.COMPLETED,f"canonical Handoff {status}",completed_at=self._clock.now(),handoff_ref=handoff["handoff_id"],handoff_digest=handoff["handoff_digest"])
        if status=="rejected":
            return ExecutionResult(completed,handoff["handoff_id"],status,extension_ref,None,(ExecutionIssue(ExecutionFailureCode.HANDOFF_REJECTED.value,"rejected Handoff is retained for audit but cannot be normalized"),))
        current=self._states.load_state_view(run.project_ref,run.lineage_ref)
        try:
            proposal=self._normalization.normalize(handoff,extension=extension,state=current,context={"run_id":run.run_id,"implementation_id":run.implementation_id})
            return ExecutionResult(completed,handoff["handoff_id"],status,extension_ref,proposal,())
        except NormalizationRejected as exc:
            code=ExecutionFailureCode.STALE_STATE.value if "stale" in str(exc).lower() else ExecutionFailureCode.NORMALIZATION_REJECTED.value
            return ExecutionResult(completed,handoff["handoff_id"],status,extension_ref,None,(ExecutionIssue(code,str(exc)),))

    def _transition(self, run: CapabilityRunRecord, status: RunStatus, reason: str, **changes: Any) -> CapabilityRunRecord:
        if status not in _ALLOWED_TRANSITIONS[run.status]: raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,f"illegal Run lifecycle transition {run.status.value} -> {status.value}")
        updated=run.with_status(status,**changes); self._traces.update_run(updated)
        events_for=getattr(self._traces,"events_for",lambda _run_id: ())
        self._traces.append_run_event(RunLifecycleEvent(run.run_id,len(events_for(run.run_id))+1,run.status,status,self._clock.now(),reason)); return updated

    def _fail(self, run: CapabilityRunRecord, issue: ExecutionIssue) -> ExecutionResult:
        failed=self._transition(run,RunStatus.FAILED,issue.message,completed_at=self._clock.now(),failure=issue); return ExecutionResult(failed,None,None,None,None,(issue,))

    def _require_run(self, run_id: str) -> CapabilityRunRecord:
        run=self._traces.load_run(run_id)
        if run is None: raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,f"unknown Run {run_id}")
        return run

    @staticmethod
    def _required_doc(value,label):
        if value is None: raise CapabilityExecutionError(ExecutionFailureCode.INVOCATION_INVALID,f"{label} is missing from execution trace")
        return value
