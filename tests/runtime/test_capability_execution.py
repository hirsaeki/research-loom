from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

import rfc8785

from core.execution import (
    CapabilityExecutionError, CapabilityExecutionOutput, CapabilityExecutionService,
    CapabilityRegistry, ExecutionStyle, RunStatus,
)
from core.execution.testing import AllowListedAuthorizationProvider, InMemoryExecutionTraceStore, InMemoryResourceProvider, StaticClock
from core.runtime import CapabilityNormalizationBoundary, LineageView, ObjectRef, StateDeltaProposal, StateView, TransitionAction, TransitionKind

ROOT=Path(__file__).resolve().parents[2]
FIX=ROOT/"core/fixtures/capabilities/valid"

def load(name): return json.loads((FIX/name).read_text(encoding="utf-8"))
def refresh(doc,field):
    body=deepcopy(doc); body.pop(field,None); doc[field]="sha256:"+hashlib.sha256(rfc8785.dumps(body)).hexdigest(); return doc

DESCRIPTOR=load("generic-capability-descriptor.json"); CONTEXT=load("generic-capability-context-pack.json"); INVOCATION=load("generic-capability-invocation.json"); HANDOFF=load("generic-capability-handoff.json")

class MutableStateProvider:
    def __init__(self,state): self.state=state
    def load_state_view(self,project_ref,lineage_ref):
        if project_ref!=self.state.project_ref or lineage_ref!=self.state.lineage_ref: raise KeyError((project_ref,lineage_ref))
        return self.state

def state_for_context(context=CONTEXT):
    pin=context["pins"]["research_snapshot"]
    snap={"id":pin["snapshot_id"],"revision":pin["revision"],"content_digest":pin["content_digest"],"mode":"virtual","members":[]}
    line=LineageView("LIN-1","primary",pin["snapshot_id"],pin["content_digest"],pin["revision"],"virtual",project_config_ref="CFG-1",project_config_digest=context["pins"]["project_config"]["configuration_digest"],effective_profile_set_ref="EPS-1",effective_profile_set_digest=context["pins"]["effective_profile_set"]["content_digest"])
    return StateView(context["project_id"],"LIN-1",snap,(),(),(),(line,),"LIN-1","CFG-1",line.project_config_digest,"EPS-1",line.effective_profile_set_digest)

class GenericNormalizer:
    def supports(self,capability_contract_id,function_id,contract_version): return (capability_contract_id,function_id,contract_version)==("fixture.research-support","investigate","1.0.0")
    def validate_extension(self,handoff,extension,context): return ()
    def normalize(self,handoff,extension,context):
        proposal=StateDeltaProposal("SDP-EXEC-1",context["project_ref"],context["lineage_ref"],(handoff["handoff_id"],),(),(),"generic execution fixture",(),context["current_snapshot_ref"],context["current_snapshot_digest"],{"run_id":context["run_id"]})
        return proposal.with_calculated_digest()

class Adapter:
    implementation_id="plugin.fixture.research-support"; implementation_version="1.0.0"; capability_id="fixture.research-support"; capability_version="1.0.0"
    supported_functions=("investigate",); supported_execution_modes=("virtual",); execution_style=ExecutionStyle.MANAGED
    def __init__(self,handoff=None,hook=None,fail=False): self.handoff=deepcopy(handoff or HANDOFF); self.hook=hook; self.fail=fail; self.cancelled=[]
    def execute(self,request):
        if self.hook: self.hook(request)
        if self.fail: raise RuntimeError("fixture adapter failure")
        return CapabilityExecutionOutput(deepcopy(self.handoff))
    def cancel(self,run_id): self.cancelled.append(run_id)
class ExternalAdapter(Adapter):
    implementation_id="plugin.fixture.external"; execution_style=ExecutionStyle.EXTERNAL
    def execute(self,request): raise AssertionError("external adapter must not execute")

class CapabilityExecutionRuntimeTests(unittest.TestCase):
    def make_service(self,adapter,*,state=None,normalizers=None,auth=True):
        registry=CapabilityRegistry(); registry.register(adapter,DESCRIPTOR)
        traces=InMemoryExecutionTraceStore(); states=MutableStateProvider(state or state_for_context())
        authorization=AllowListedAuthorizationProvider((INVOCATION["runtime_authorization_evidence"]["authorization_digest"],) if auth else (),denied=not auth)
        resources=InMemoryResourceProvider({ref:b"fixture" for ref in INVOCATION["runtime_authorization_evidence"]["resource_reference_ids"]})
        service=CapabilityExecutionService(registry,traces,states,authorization,resources,CapabilityNormalizationBoundary(tuple(normalizers or (GenericNormalizer(),))),StaticClock())
        return service,traces,states,registry

    def test_valid_managed_invocation_completes_and_returns_candidate_proposal(self):
        service,traces,_,_=self.make_service(Adapter())
        result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.COMPLETED); self.assertIsNotNone(result.state_delta_proposal); self.assertEqual(result.handoff_status,"valid")
        self.assertEqual([event.to_status for event in traces.events_for("RUN-001")],[RunStatus.PREPARED,RunStatus.RUNNING,RunStatus.COMPLETED])

    def test_external_prepare_collect_completes(self):
        service,traces,_,_=self.make_service(ExternalAdapter())
        prepared=service.prepare_external(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1"); self.assertEqual(prepared.run.status,RunStatus.RUNNING)
        result=service.collect_external("RUN-001",HANDOFF); self.assertEqual(result.run.status,RunStatus.COMPLETED); self.assertIsNotNone(result.state_delta_proposal)

    def test_unknown_and_ambiguous_registry_bindings_fail_closed(self):
        registry=CapabilityRegistry()
        with self.assertRaises(CapabilityExecutionError) as cm: registry.resolve("fixture.research-support","1.0.0","investigate","virtual")
        self.assertEqual(cm.exception.issue.code,"IMPLEMENTATION_NOT_FOUND")
        registry.register(Adapter(),DESCRIPTOR); registry.register(Adapter(),DESCRIPTOR)
        with self.assertRaises(CapabilityExecutionError) as cm: registry.resolve("fixture.research-support","1.0.0","investigate","virtual")
        self.assertEqual(cm.exception.issue.code,"IMPLEMENTATION_AMBIGUOUS")

    def test_invalid_descriptor_context_and_authorization_are_blocked_before_run(self):
        service,traces,_,_=self.make_service(Adapter())
        bad=deepcopy(DESCRIPTOR); bad["descriptor_digest"]="sha256:"+"0"*64
        with self.assertRaises(CapabilityExecutionError): service.execute_managed(bad,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        bad_context=deepcopy(CONTEXT); bad_context["context_pack_digest"]="sha256:"+"0"*64
        with self.assertRaises(CapabilityExecutionError): service.execute_managed(DESCRIPTOR,INVOCATION,bad_context,lineage_ref="LIN-1")
        denied,denied_traces,_,_=self.make_service(Adapter(),auth=False)
        with self.assertRaises(CapabilityExecutionError) as cm: denied.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(cm.exception.issue.code,"AUTHORIZATION_DENIED"); self.assertFalse(denied_traces.runs)

    def test_stale_snapshot_before_execution_is_blocked(self):
        stale=state_for_context(); stale.current_snapshot=dict(stale.current_snapshot,content_digest="sha256:"+"9"*64)
        service,traces,_,_=self.make_service(Adapter(),state=stale)
        with self.assertRaises(CapabilityExecutionError) as cm: service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(cm.exception.issue.code,"STALE_STATE"); self.assertFalse(traces.runs)

    def test_adapter_failure_marks_run_failed(self):
        service,_,_,_=self.make_service(Adapter(fail=True)); result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.FAILED); self.assertEqual(result.issues[0].code,"EXECUTION_FAILED")

    def test_mismatched_run_and_virtual_empirical_handoff_fail_but_remain_auditable(self):
        mismatch=deepcopy(HANDOFF); mismatch["run_id"]="RUN-OTHER"; refresh(mismatch,"handoff_digest")
        service,traces,_,_=self.make_service(Adapter(mismatch)); result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.FAILED); self.assertIn(mismatch["handoff_id"],traces.handoffs)
        empirical=deepcopy(HANDOFF); empirical["outputs"]["observations"][0]["epistemic_mode"]="empirical"; refresh(empirical,"handoff_digest")
        service,traces,_,_=self.make_service(Adapter(empirical)); result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.FAILED); self.assertEqual(result.issues[0].code,"CAP-MODE-001")

    def test_rejected_handoff_is_completed_but_never_normalized(self):
        rejected=deepcopy(HANDOFF); rejected["validation"]={"status":"rejected","issues":[{"code":"FIXTURE_REJECT","severity":"error","message":"fixture rejection"}]}; refresh(rejected,"handoff_digest")
        service,traces,_,_=self.make_service(Adapter(rejected)); result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.COMPLETED); self.assertIsNone(result.state_delta_proposal); self.assertEqual(result.issues[0].code,"HANDOFF_REJECTED"); self.assertIn(rejected["handoff_id"],traces.handoffs)

    def test_partial_handoff_preserves_issues_and_normalizes(self):
        partial=deepcopy(HANDOFF); partial["validation"]={"status":"partial","issues":[{"code":"FIXTURE_GAP","severity":"warning","message":"gap remains"}]}; refresh(partial,"handoff_digest")
        service,_,_,_=self.make_service(Adapter(partial)); result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.handoff_status,"partial"); self.assertIsNotNone(result.state_delta_proposal)

    def test_head_change_during_execution_keeps_handoff_and_rejects_stale_normalization(self):
        holder={}
        def advance(_request):
            state=holder["states"].state; holder["states"].state=StateView(state.project_ref,state.lineage_ref,dict(state.current_snapshot,id="SNP-2",content_digest="sha256:"+"8"*64),state.objects,state.decisions,state.used_decision_ids,state.lineages,state.active_lineage_ref,state.project_config_ref,state.project_config_digest,state.effective_profile_set_ref,state.effective_profile_set_digest)
        adapter=Adapter(hook=advance); service,traces,states,_=self.make_service(adapter); holder["states"]=states
        result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.COMPLETED); self.assertIsNone(result.state_delta_proposal); self.assertEqual(result.issues[0].code,"STALE_STATE"); self.assertIn("HND-001",traces.handoffs)

    def test_abort_keeps_late_external_result_diagnostic_only(self):
        adapter=ExternalAdapter(); service,traces,_,_=self.make_service(adapter); service.prepare_external(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        aborted=service.abort("RUN-001"); self.assertEqual(aborted.status,RunStatus.ABORTED); self.assertEqual(adapter.cancelled,["RUN-001"])
        result=service.collect_external("RUN-001",HANDOFF); self.assertEqual(result.run.status,RunStatus.ABORTED); self.assertIsNone(result.state_delta_proposal); self.assertTrue(traces.diagnostics); self.assertFalse(traces.handoffs)

    def test_run_id_and_invocation_identity_collisions_are_rejected(self):
        service,_,_,_=self.make_service(ExternalAdapter()); service.prepare_external(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        with self.assertRaises((ValueError,CapabilityExecutionError)): service.prepare_external(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")

    def test_bounded_resource_access_denies_out_of_context_reference(self):
        class ReadingAdapter(Adapter):
            def execute(self,request):
                request.resources.read("NOT-IN-CONTEXT"); return CapabilityExecutionOutput(HANDOFF)
        service,_,_,_=self.make_service(ReadingAdapter()); result=service.execute_managed(DESCRIPTOR,INVOCATION,CONTEXT,lineage_ref="LIN-1")
        self.assertEqual(result.run.status,RunStatus.FAILED); self.assertEqual(result.issues[0].code,"RESOURCE_DENIED")

class DependencyBoundaryTests(unittest.TestCase):
    def test_execution_core_has_no_capability_specific_or_sqlite_dependency(self):
        text="\n".join(path.read_text(encoding="utf-8") for path in (ROOT/"core/execution").glob("*.py"))
        for forbidden in ("import sqlite3","plugins.sqlite","survey","delphi","case_study","desktop_research","StateTransitionService"):
            self.assertNotIn(forbidden,text)

if __name__=="__main__": unittest.main()
