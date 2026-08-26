from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.execution import (
    CapabilityContextExtensionRegistry,
    CapabilityExecutionService,
    CapabilityRegistry,
)
from core.execution.testing import AllowListedAuthorizationProvider, StaticClock
from core.runtime import (
    CapabilityNormalizationBoundary,
    StateTransitionService,
    TransitionAction,
    TransitionKind,
)
from plugins.desktop_research import (
    DesktopResearchAttemptRecorder,
    DesktopResearchCaptureService,
    DesktopResearchContextValidator,
    DesktopResearchExternalAdapter,
    DesktopResearchNormalizer,
    DesktopResearchResultValidator,
    build_result_extension,
    with_context_extension_digest,
)
from plugins.local_execution_store import (
    LocalCapabilityContextExtensionStore,
    LocalExecutionStore,
    LocalOperationalTraceStore,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository
from runtime_fixtures import SCHEMA_VALIDATOR, make_request, project, rq, seed_state


ROOT = Path(__file__).resolve().parents[2]
DR_DESCRIPTOR = json.loads(
    (ROOT / "core/packages/desktop-research/desktop-research-capability-descriptor.json").read_text()
)


def refresh(document: dict, field: str) -> dict:
    payload = deepcopy(document)
    payload.pop(field, None)
    document[field] = "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return document


def build_context(state) -> dict:
    snapshot = state.current_snapshot
    context = {
        "schema_version": "0.1.0",
        "context_pack_id": "CTX-DR-001",
        "project_id": state.project_ref,
        "purpose": "Production Desktop Research external flow fixture.",
        "pins": {
            "project_config": {"configuration_digest": state.project_config_digest},
            "effective_profile_set": {
                "schema_version": "0.1.0",
                "content_digest": state.effective_profile_set_digest,
                "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
                "profile_pins": [{
                    "profile_id": "fixture.research", "profile_type": "research",
                    "profile_version": "1.0.0", "manifest_sha256": "1" * 64,
                }],
            },
            "research_snapshot": {
                "snapshot_id": snapshot["id"], "revision": snapshot["revision"],
                "content_digest": snapshot["content_digest"],
            },
        },
        "question_ids": ["RQ-1"],
        "research_object_references": [{"kind": "research_question", "id": "RQ-1", "revision": 0}],
        "resources": [], "research_attention": [],
        "project_constraints": {"requirements": [], "prohibitions": [], "must_not_claim": []},
        "effective_constraints": [],
        "bounds": {"max_questions": 1, "max_research_object_references": 1, "max_resources": 0,
                   "max_attention_items": 0, "max_project_guards": 0, "max_effective_constraints": 0},
    }
    return refresh(context, "context_pack_digest")


def build_invocation(context: dict, *, run_id: str = "RUN-DR-001") -> dict:
    invocation = {
        "schema_version": "0.1.0", "invocation_id": f"INV-{run_id}", "run_id": run_id,
        "project_id": context["project_id"],
        "capability": {"capability_id": "desktop-research", "capability_version": "0.1.0",
                       "descriptor_digest": DR_DESCRIPTOR["descriptor_digest"], "function_id": "investigate"},
        "execution_mode": "real",
        "context_pack": {"context_pack_id": context["context_pack_id"], "context_pack_digest": context["context_pack_digest"]},
        "pins": deepcopy(context["pins"]),
        "runtime_authorization_evidence": {
            "authorization_id": f"AUTH-{run_id}", "authorization_digest": "sha256:" + "a" * 64,
            "capability_id": "desktop-research", "function_id": "investigate",
            "execution_modes": ["real"], "resource_reference_ids": [],
        },
        "trace": {"trace_id": f"TRACE-{run_id}"},
    }
    return refresh(invocation, "invocation_digest")


def build_context_extension(context: dict, *, extra_empty_dimension: bool = False) -> dict:
    dimensions = [
        {"dimension_id": "COV-SUPPORT", "label": "Supporting material", "required": True},
        {"dimension_id": "COV-OPPOSE", "label": "Opposing material", "required": True},
    ]
    if extra_empty_dimension:
        dimensions.append({"dimension_id": "COV-EMPTY", "label": "Unattempted dimension", "required": True})
    return with_context_extension_digest({
        "schema_version": "0.1.0", "extension_type": "desktop_research_context",
        "context_binding": {"context_pack_id": context["context_pack_id"],
                            "context_pack_digest": context["context_pack_digest"], "project_id": context["project_id"]},
        "target": {"target_type": "research_question", "question_id": "RQ-1"},
        "retrieval_scope": {"scope_statement": "Bounded production Desktop Research test.",
                            "in_scope": ["authorized external source retrieval"],
                            "out_of_scope": ["Writer and Publication artifacts as evidence"]},
        "allowed_source_categories": ["other"], "resource_role_bindings": [],
        "forbidden_resource_roles": ["writer_material", "publication_material", "publication_feedback", "archive_provenance"],
        "coverage_dimensions": dimensions,
        "budget": {"max_total_resources": 0, "max_candidate_source_resources": 0, "max_artifact_resources": 0,
                   "max_acquired_source_captures": 2, "max_search_trace_entries": 5,
                   "max_text_rendition_bytes": 4096, "max_original_capture_bytes": 4096,
                   "max_capture_artifacts": 4},
    })


class Flow:
    def __init__(self, *, extra_empty_dimension: bool = False, run_id="RUN-DR-001"):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.seed = seed_state(objects=[project(), rq(state="approved")], mode="real", snapshot_id="SNP-DR-0")
        self.state_repo = SQLiteResearchStateRepository(self.root / "state.sqlite3")
        self.state_repo.initialize_from_validated_state_view(self.seed)
        self.exec_store = LocalExecutionStore(self.root / "execution")
        self.context_store = LocalCapabilityContextExtensionStore(self.exec_store.root)
        self.ops = LocalOperationalTraceStore(self.exec_store.root, self.exec_store)
        self.clock = StaticClock("2026-08-27T00:00:00Z")
        self.context = build_context(self.seed); self.invocation = build_invocation(self.context, run_id=run_id)
        self.context_extension = build_context_extension(self.context, extra_empty_dimension=extra_empty_dimension)
        registry = CapabilityRegistry(); registry.register(DesktopResearchExternalAdapter(), DR_DESCRIPTOR)
        self.normalizer = DesktopResearchNormalizer(self.exec_store, self.context_store, self.exec_store, self.ops)
        self.service = CapabilityExecutionService(
            registry, self.exec_store, self.state_repo,
            AllowListedAuthorizationProvider((self.invocation["runtime_authorization_evidence"]["authorization_digest"],)),
            self.exec_store, CapabilityNormalizationBoundary((self.normalizer,)), self.clock,
            artifact_store=self.exec_store,
            context_extension_registry=CapabilityContextExtensionRegistry((DesktopResearchContextValidator(),)),
            context_extension_store=self.context_store,
        )
        self.prepared = self.service.prepare_external(DR_DESCRIPTOR, self.invocation, self.context,
            lineage_ref="LIN-1", context_extension=self.context_extension)
        self.recorder = DesktopResearchAttemptRecorder(self.prepared.run, self.exec_store, self.ops, self.clock)
        self.capture = DesktopResearchCaptureService(self.exec_store)

    def close(self):
        try: self.ops.close()
        except Exception: pass
        try: self.context_store.close()
        except Exception: pass
        self.exec_store.close(); self.state_repo.close(); self.temp.cleanup()

    def build_golden(self):
        self.recorder.start_attempt("ATT-1", strategy="support search", coverage_dimension_ids=("COV-SUPPORT",),
                                    query_or_target="support terms", provider_or_tool="external.fixture")
        cap1 = self.capture.capture(self.prepared.run, capture_id="CAP-1", source_category="other",
            exact_locator="https://example.test/source-a#section-1", acquired_at="2026-08-27T00:00:00Z",
            original_bytes=b"original source A bytes", original_media_type="text/html",
            text_rendition="Source A contains the exact supporting excerpt used here.")
        self.recorder.complete_attempt("ATT-1", outcome="source_captured", resulting_capture_id="CAP-1",
                                       target_locator="https://example.test/source-a")
        self.recorder.start_attempt("ATT-2", strategy="opposition search", coverage_dimension_ids=("COV-OPPOSE",),
                                    query_or_target="opposing terms", provider_or_tool="external.fixture")
        cap2 = self.capture.capture(self.prepared.run, capture_id="CAP-2", source_category="other",
            exact_locator="https://example.test/source-b#section-2", acquired_at="2026-08-27T00:00:00Z",
            original_bytes=b"original source B bytes", original_media_type="text/html",
            text_rendition="Source B contains the exact counter excerpt used here.")
        self.recorder.complete_attempt("ATT-2", outcome="source_captured", resulting_capture_id="CAP-2",
                                       target_locator="https://example.test/source-b")
        self.recorder.start_attempt("ATT-3", strategy="additional opposition search",
                                    coverage_dimension_ids=("COV-OPPOSE",), query_or_target="additional opposing terms")
        self.recorder.complete_attempt("ATT-3", outcome="no_relevant_source")
        handoff = self._handoff(
            source_captures=[
                {"capture_id":"CAP-1","origin":{"origin_type":"acquired_source","acquisition_locator":"https://example.test/source-a"},
                 "locator":"https://example.test/source-a#section-1","content_digest":cap1["original_capture"]["content_digest"]},
                {"capture_id":"CAP-2","origin":{"origin_type":"acquired_source","acquisition_locator":"https://example.test/source-b"},
                 "locator":"https://example.test/source-b#section-2","content_digest":cap2["original_capture"]["content_digest"]},
            ],
            observations=[{"observation_id":"OBS-NULL","statement":"No additional relevant opposing source was found in the bounded search.","epistemic_mode":"empirical"}],
            evidence_candidates=[{"evidence_candidate_id":"EVC-1","statement":"Captured support candidate.",
                "source_basis":{"basis_type":"source_capture","capture_id":"CAP-1"},
                "locator":"https://example.test/source-a#quote-1","epistemic_mode":"empirical",
                "limitations":["Candidate only; not verified Evidence."]}],
            counterevidence=[{"counterevidence_id":"CEV-1","statement":"Captured counterevidence candidate.",
                "source_basis":{"basis_type":"source_capture","capture_id":"CAP-2"},
                "locator":"https://example.test/source-b#quote-2","epistemic_mode":"empirical"}],
            candidate_findings=[{"candidate_finding_id":"CF-1","question_ids":["RQ-1"],
                "statement":"The bounded material is mixed and incomplete.",
                "supporting_evidence_candidate_ids":["EVC-1"],"counterevidence_candidate_ids":["CEV-1"],
                "boundary_conditions":["Bounded external retrieval only."],"limitations":["A material coverage gap remains."],
                "epistemic_mode":"empirical"}],
            unknowns=[], gaps=[{"gap_id":"GAP-1","statement":"Additional opposing coverage remains material.","question_ids":["RQ-1"]}],
            next_methods=[{"proposal_id":"NM-1","method_family":"survey","rationale":"A later method may address the remaining gap.","status":"candidate"}],
        )
        extension = build_result_extension(
            handoff, self.context, source_capture_details=[cap1,cap2],
            citation_details=[
                {"citation_id":"CIT-1","handoff_output_kind":"evidence_candidate","handoff_output_id":"EVC-1","capture_id":"CAP-1",
                 "excerpt":"exact supporting excerpt","excerpt_locator":"https://example.test/source-a#quote-1",
                 "text_rendition_digest":cap1["text_rendition"]["content_digest"],"capture_integrity_verified":True,
                 "excerpt_containment_verified":True,"evidence_adoption_performed":False},
                {"citation_id":"CIT-2","handoff_output_kind":"counterevidence","handoff_output_id":"CEV-1","capture_id":"CAP-2",
                 "excerpt":"exact counter excerpt","excerpt_locator":"https://example.test/source-b#quote-2",
                 "text_rendition_digest":cap2["text_rendition"]["content_digest"],"capture_integrity_verified":True,
                 "excerpt_containment_verified":True,"evidence_adoption_performed":False},
            ],
            search_trace={"entries":[
                {"trace_entry_id":"ATT-1","strategy":"support search","coverage_dimension_ids":["COV-SUPPORT"],"outcome":"source_captured","related_handoff_output_ids":["EVC-1"],"source_capture_ids":["CAP-1"]},
                {"trace_entry_id":"ATT-2","strategy":"opposition search","coverage_dimension_ids":["COV-OPPOSE"],"outcome":"source_captured","related_handoff_output_ids":["CEV-1"],"source_capture_ids":["CAP-2"]},
                {"trace_entry_id":"ATT-3","strategy":"additional opposition search","coverage_dimension_ids":["COV-OPPOSE"],"outcome":"no_relevant_source","related_handoff_output_ids":["OBS-NULL","GAP-1"],"source_capture_ids":[]},
            ],"unsuccessful_entry_ids":["ATT-3"]},
            null_results=[{"null_id":"NULL-1","statement":"No additional relevant opposing source was found.","question_ids":["RQ-1"],
                           "handoff_projection":{"output_kind":"observation","output_id":"OBS-NULL"}}],
            evidence_gap_assessments=[{"gap_id":"GAP-1","materiality":"material","coverage_dimension_ids":["COV-OPPOSE"],"rationale":"Opposing coverage remains incomplete."}],
            coverage_assessment={
                "dimensions":[
                    {"dimension_id":"COV-SUPPORT","status":"covered","trace_entry_ids":["ATT-1"],"rationale":"Captured support."},
                    {"dimension_id":"COV-OPPOSE","status":"partial","trace_entry_ids":["ATT-2","ATT-3"],"rationale":"One counter source plus an explicit null search."},
                ] + ([{"dimension_id":"COV-EMPTY","status":"covered","trace_entry_ids":[],"rationale":"Tampered covered-without-attempt fixture."}]
                     if any(item["dimension_id"]=="COV-EMPTY" for item in self.context_extension["coverage_dimensions"]) else []),
                "saturation":{"level":"medium","rationale":"Partial saturation only."},
                "remaining_information_value":{"level":"high","rationale":"A material gap remains."},
                "stopping_recommendation":{"stop_recommended":False,"basis":["coverage","saturation","evidence_gaps","remaining_information_value"],
                    "rationale":"Continue research if operationally possible.","research_completion_claimed":False,"human_decision_performed":False},
            }, candidate_next_method_ids=["NM-1"])
        return handoff, extension

    def build_inaccessible(self):
        self.recorder.start_attempt("ATT-BLOCK", strategy="restricted source fetch", coverage_dimension_ids=("COV-SUPPORT",),
                                    target_locator="https://example.test/restricted#section")
        self.recorder.complete_attempt("ATT-BLOCK", outcome="blocked", failure_or_blocking_reason="authentication required",
                                       target_locator="https://example.test/restricted#section")
        handoff = self._handoff(source_captures=[], observations=[], evidence_candidates=[], counterevidence=[], candidate_findings=[],
            unknowns=[{"unknown_id":"UNK-1","statement":"Relevant restricted material could not be acquired."}],
            gaps=[{"gap_id":"GAP-1","statement":"Material may exist behind an inaccessible source.","question_ids":["RQ-1"]}], next_methods=[])
        extension = build_result_extension(handoff,self.context,source_capture_details=[],citation_details=[],
            search_trace={"entries":[{"trace_entry_id":"ATT-BLOCK","strategy":"restricted source fetch","coverage_dimension_ids":["COV-SUPPORT"],
                "outcome":"blocked","related_handoff_output_ids":["UNK-1","GAP-1"],"source_capture_ids":[]}],"unsuccessful_entry_ids":["ATT-BLOCK"]},
            null_results=[], evidence_gap_assessments=[{"gap_id":"GAP-1","materiality":"unknown","coverage_dimension_ids":["COV-SUPPORT"],
                "rationale":"Acquisition failure prevents materiality determination."}],
            coverage_assessment={"dimensions":[
                {"dimension_id":"COV-SUPPORT","status":"partial","trace_entry_ids":["ATT-BLOCK"],"rationale":"Blocked acquisition."},
                {"dimension_id":"COV-OPPOSE","status":"uncovered","trace_entry_ids":[],"rationale":"No attempt completed before operational end."}],
                "saturation":{"level":"low","rationale":"Acquisition was blocked."},
                "remaining_information_value":{"level":"unknown","rationale":"Inaccessible material may matter."},
                "stopping_recommendation":{"stop_recommended":False,"basis":["coverage","evidence_gaps","remaining_information_value"],
                    "rationale":"Operational blockage is not research completion.","research_completion_claimed":False,"human_decision_performed":False}},
            candidate_next_method_ids=[])
        return handoff, extension

    def _handoff(self, *, source_captures, observations, evidence_candidates, counterevidence, candidate_findings, unknowns, gaps, next_methods):
        handoff = {
            "schema_version":"0.1.0","handoff_id":f"HND-{self.prepared.run.run_id}","invocation_id":self.invocation["invocation_id"],
            "run_id":self.prepared.run.run_id,"project_id":self.context["project_id"],"capability":deepcopy(self.invocation["capability"]),
            "execution_mode":"real",
            "input_pins":{"invocation_digest":self.invocation["invocation_digest"],"context_pack_digest":self.context["context_pack_digest"],
                "project_config_digest":self.context["pins"]["project_config"]["configuration_digest"],
                "effective_profile_set_digest":self.context["pins"]["effective_profile_set"]["content_digest"],
                "research_snapshot":deepcopy(self.context["pins"]["research_snapshot"])},
            "preserved_context":{"research_attention_ids":[],"project_guard_ids":[],"effective_constraint_paths":[]},
            "validation":{"status":"valid","issues":[]},
            "outputs":{"observations":observations,"source_captures":source_captures,"evidence_candidates":evidence_candidates,
                "candidate_findings":candidate_findings,"counterevidence":counterevidence,"conflicts":[],"unknowns":unknowns,
                "evidence_gaps":gaps,"candidate_next_actions":[],"candidate_next_methods":next_methods},
            "provenance":{"trace_id":self.invocation["trace"]["trace_id"],"produced_at":"2026-08-27T00:00:00Z",
                "implementation_id":DesktopResearchExternalAdapter.implementation_id,
                "implementation_version":DesktopResearchExternalAdapter.implementation_version,
                "input_content_digests":[DR_DESCRIPTOR["descriptor_digest"],self.context["context_pack_digest"],self.invocation["invocation_digest"]]},
            "adoption_boundary":{"research_state_mutation_performed":False,"outputs_are_candidates":True,"human_decision_required_for_authoritative_transition":True},
        }
        return refresh(handoff,"handoff_digest")


class DesktopResearchProductionTests(unittest.TestCase):
    def setUp(self): self.flows=[]
    def tearDown(self):
        for flow in reversed(self.flows): flow.close()
    def flow(self,**kwargs):
        flow=Flow(**kwargs); self.flows.append(flow); return flow

    def test_golden_external_flow_returns_candidate_proposal_without_state_mutation(self):
        flow=self.flow(); before=flow.state_repo.load_state_view("PRJ-1","LIN-1").current_snapshot
        handoff,extension=flow.build_golden(); result=flow.service.collect_external(flow.prepared.run.run_id,handoff,extension)
        after=flow.state_repo.load_state_view("PRJ-1","LIN-1").current_snapshot
        self.assertEqual((before["id"],before["content_digest"]),(after["id"],after["content_digest"]))
        self.assertIsNotNone(result.state_delta_proposal); self.assertTrue(result.state_delta_proposal.candidate_only)
        self.assertEqual(result.run.status.value,"COMPLETED")
        kinds=[a.payload["object"]["kind"] for a in result.state_delta_proposal.proposed_actions]
        self.assertIn("source",kinds); self.assertIn("evidence",kinds); self.assertIn("finding",kinds)
        finding=next(a.payload["object"] for a in result.state_delta_proposal.proposed_actions if a.payload["object"]["kind"]=="finding")
        self.assertNotIn("confidence",finding); self.assertEqual(finding["adoption_state"],"candidate")

    def test_stale_state_keeps_trace_but_returns_no_proposal_and_no_rebase(self):
        flow=self.flow(run_id="RUN-DR-STALE"); handoff,extension=flow.build_golden()
        self.assertEqual(DesktopResearchResultValidator(flow.exec_store,flow.ops).validate(handoff,extension,flow.context,flow.context_extension,run_id=flow.prepared.run.run_id),())
        current=flow.state_repo.load_state_view("PRJ-1","LIN-1")
        claim={"schema_version":"0.1.0","id":"CLM-STALE","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"Competing state update","assessment":"proposed"}
        receipt=StateTransitionService(flow.state_repo,schema_validator=SCHEMA_VALIDATOR).apply(make_request(current,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim})],suffix="9"))
        self.assertTrue(hasattr(receipt,"new_snapshot_ref"))
        result=flow.service.collect_external(flow.prepared.run.run_id,handoff,extension)
        self.assertIsNone(result.state_delta_proposal); self.assertEqual(result.issues[0].code,"STALE_STATE")
        self.assertIsNotNone(flow.exec_store.load_run(flow.prepared.run.run_id).handoff_ref)

    def test_capture_corruption_and_citation_tampering_block_normalization(self):
        flow=self.flow(run_id="RUN-DR-CORRUPT"); handoff,extension=flow.build_golden()
        text_ref=extension["source_capture_details"][0]["text_rendition"]["content_reference"]
        meta=next(x for x in flow.exec_store.artifacts_for(flow.prepared.run.run_id) if x.artifact_id==text_ref)
        h=meta.digest.removeprefix("sha256:"); (flow.exec_store.blob_root/h[:2]/h).write_bytes(b"tampered")
        result=flow.service.collect_external(flow.prepared.run.run_id,handoff,extension)
        self.assertIsNone(result.state_delta_proposal); self.assertIn("DR-CITATION-001",result.issues[0].message)
        other=self.flow(run_id="RUN-DR-CITATION"); handoff,extension=other.build_golden()
        extension["citation_details"][0]["excerpt"]="text not present in stored rendition"; refresh(extension,"extension_digest")
        result=other.service.collect_external(other.prepared.run.run_id,handoff,extension)
        self.assertIsNone(result.state_delta_proposal); self.assertIn("DR-CITATION-001",result.issues[0].message)

    def test_attempt_ledger_reconciliation_rejects_deleted_or_altered_attempts(self):
        flow=self.flow(run_id="RUN-DR-TRACE-DELETE"); handoff,extension=flow.build_golden()
        extension["search_trace"]["entries"]=extension["search_trace"]["entries"][:2]; extension["search_trace"]["unsuccessful_entry_ids"]=[]
        extension["coverage_assessment"]["dimensions"][1]["trace_entry_ids"]=["ATT-2"]; refresh(extension,"extension_digest")
        codes=DesktopResearchResultValidator(flow.exec_store,flow.ops).validate(handoff,extension,flow.context,flow.context_extension,run_id=flow.prepared.run.run_id)
        self.assertIn("DR-SEARCH-TRACE-001",codes)
        other=self.flow(run_id="RUN-DR-TRACE-ALTER"); handoff,extension=other.build_golden()
        extension["search_trace"]["entries"][2]["outcome"]="unavailable"; refresh(extension,"extension_digest")
        codes=DesktopResearchResultValidator(other.exec_store,other.ops).validate(handoff,extension,other.context,other.context_extension,run_id=other.prepared.run.run_id)
        self.assertIn("DR-SEARCH-TRACE-001",codes)

    def test_covered_dimension_without_attempt_is_rejected(self):
        flow=self.flow(extra_empty_dimension=True,run_id="RUN-DR-COVERAGE"); handoff,extension=flow.build_golden()
        codes=DesktopResearchResultValidator(flow.exec_store,flow.ops).validate(handoff,extension,flow.context,flow.context_extension,run_id=flow.prepared.run.run_id)
        self.assertIn("DR-COVERAGE-001",codes)

    def test_operational_termination_cannot_be_converted_to_research_stop(self):
        flow=self.flow(run_id="RUN-DR-OPSTOP"); handoff,extension=flow.build_golden()
        flow.recorder.record_operational_termination("budget_exhausted",detail="artifact budget exhausted",coverage_dimension_ids=("COV-OPPOSE",))
        extension["evidence_gap_assessments"][0]["materiality"]="non_material"
        extension["coverage_assessment"]["remaining_information_value"]={"level":"low","rationale":"Fixture removes independent RIV blocker."}
        extension["coverage_assessment"]["stopping_recommendation"]["stop_recommended"]=True; refresh(extension,"extension_digest")
        codes=DesktopResearchResultValidator(flow.exec_store,flow.ops).validate(handoff,extension,flow.context,flow.context_extension,run_id=flow.prepared.run.run_id)
        self.assertIn("DR-STOP-BASIS-001",codes)

    def test_all_relevant_sources_inaccessible_preserves_unknown_gap_and_partial_coverage(self):
        flow=self.flow(run_id="RUN-DR-INACCESSIBLE"); handoff,extension=flow.build_inaccessible()
        result=flow.service.collect_external(flow.prepared.run.run_id,handoff,extension)
        self.assertIsNotNone(result.state_delta_proposal)
        self.assertEqual(extension["evidence_gap_assessments"][0]["materiality"],"unknown")
        self.assertEqual(extension["coverage_assessment"]["remaining_information_value"]["level"],"unknown")
        self.assertFalse(extension["coverage_assessment"]["stopping_recommendation"]["stop_recommended"])
        self.assertEqual(handoff["outputs"]["unknowns"][0]["unknown_id"],"UNK-1")

    def test_attempt_history_survives_store_restart_and_abort(self):
        flow=self.flow(run_id="RUN-DR-RESTART")
        flow.recorder.start_attempt("ATT-RESTART",strategy="blocked fetch",coverage_dimension_ids=("COV-SUPPORT",))
        flow.recorder.complete_attempt("ATT-RESTART",outcome="blocked",failure_or_blocking_reason="login required")
        reopened=LocalOperationalTraceStore(flow.exec_store.root,flow.exec_store)
        try:
            self.assertEqual(len(reopened.events_for(flow.prepared.run.run_id)),2)
            flow.service.abort(flow.prepared.run.run_id,reason="operator abort")
            self.assertEqual(len(reopened.events_for(flow.prepared.run.run_id)),2)
        finally: reopened.close()

    def test_plugin_has_no_source_category_quality_mapping(self):
        python="\n".join(path.read_text() for path in (ROOT/"plugins/desktop_research").glob("*.py"))
        self.assertNotIn("quality_score",python); self.assertNotIn("quality_tier",python); self.assertNotIn("source_category_to_quality",python)


if __name__ == "__main__": unittest.main()
