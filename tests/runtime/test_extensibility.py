from __future__ import annotations

import ast
import json
import unittest

from core.runtime import CapabilityNormalizationBoundary, NormalizationRejected, ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind, canonical_digest
from core.runtime.transition_models import CommitReceipt
from runtime_fixtures import *

class RuntimeDependencyRuleTests(unittest.TestCase):
    def test_reducer_has_no_concrete_capability_or_storage_dependency(self):
        source_text=(ROOT/"core/runtime/state_reducer.py").read_text(encoding="utf-8")
        tree=ast.parse(source_text)
        imported_modules=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                imported_modules.append(node.module or "")
        forbidden={"plugins","survey","delphi","case_study","desktop_research","writer","publication","sqlite","sqlite3","sqlmodel","requests","boto3"}
        for module in imported_modules:
            parts=set(module.lower().split("."))
            self.assertTrue(parts.isdisjoint(forbidden),f"forbidden reducer dependency: {module}")
        self.assertNotIn("fixture.future-research-capability",source_text)

    def test_transition_vocabulary_contains_no_capability_kind(self):
        values={item.value for item in TransitionKind}
        for fragment in ("SURVEY","DELPHI","CASE","DESKTOP_RESEARCH","POC"):
            self.assertFalse(any(fragment in value for value in values))

class FutureCapabilityNormalizationTests(unittest.TestCase):
    class FutureNormalizer:
        def supports(self, capability_contract_id, function_id, contract_version):
            return (capability_contract_id,function_id,contract_version)==("fixture.future-research-capability","evaluate","1.0.0")

        def validate_extension(self,handoff,extension,context):
            if not isinstance(extension,dict) or extension.get("extension_type")!="fixture_future_evaluate_result":
                return ("unsupported future fixture extension",)
            if extension.get("handoff_binding")!={"handoff_id":handoff["handoff_id"],"handoff_digest":handoff["handoff_digest"]}:
                return ("future extension handoff binding mismatch",)
            basis=dict(extension); supplied=basis.pop("extension_digest",None)
            if supplied!=canonical_digest(basis):
                return ("future extension digest mismatch",)
            return ()

        def normalize(self,handoff,extension,context):
            candidate=extension["candidate_claim"]
            obj={"schema_version":"0.1.0","id":candidate["id"],"kind":"claim","revision":0,"project_id":context["project_ref"],"question_id":candidate["question_id"],"statement":candidate["statement"],"assessment":"proposed"}
            proposal=StateDeltaProposal(
                proposal_id="SDP-FUTURE-001",project_ref=context["project_ref"],lineage_ref=context["lineage_ref"],source_refs=(handoff["handoff_id"],),
                proposed_actions=(TransitionAction(TransitionKind.CREATE_OBJECT,{"object":obj},source_refs=(handoff["handoff_id"],)),),
                affected_refs=(ObjectRef("claim",obj["id"]),),rationale="Normalize a future capability to existing Core claim semantics.",
                required_human_decision_kinds=(),current_snapshot_ref=context["current_snapshot_ref"],current_snapshot_digest=context["current_snapshot_digest"],
                provenance={"handoff_id":handoff["handoff_id"],"handoff_digest":handoff["handoff_digest"]},candidate_only=True,
            )
            return proposal.with_calculated_digest()

    def _state(self):
        p=project("PRJ-FUTURE")
        q={"schema_version":"0.1.0","id":"RQ-FUTURE","kind":"research_question","revision":0,"project_id":"PRJ-FUTURE","text":"Future RQ","adoption_state":"candidate"}
        snap={"schema_version":"0.1.0","id":"SNP-FUTURE","kind":"snapshot","revision":0,"project_id":"PRJ-FUTURE","snapshot_type":"research","created_at":"2026-08-25T00:00:00Z","mode":"real","members":[{"kind":"project","id":"PRJ-FUTURE","revision":0,"digest":canonical_digest(p)},{"kind":"research_question","id":"RQ-FUTURE","revision":0,"digest":canonical_digest(q)}],"content_digest":"sha256:"+"1"*64}
        line=LineageView("LIN-1","primary","SNP-FUTURE","sha256:"+"1"*64,0,"real",project_config_ref="CFG-1",project_config_digest="sha256:"+"2"*64,effective_profile_set_ref="EPS-1",effective_profile_set_digest="sha256:"+"3"*64)
        return StateView("PRJ-FUTURE","LIN-1",snap,(p,q,snap),(),(),(line,),"LIN-1","CFG-1","sha256:"+"2"*64,"EPS-1","sha256:"+"3"*64)

    def test_unknown_extension_fails_closed(self):
        handoff=json.loads((ROOT/"core/fixtures/capabilities/valid/generic-future-capability-handoff.json").read_text())
        ext=json.loads((ROOT/"core/fixtures/capabilities/valid/generic-future-capability-result-extension.json").read_text())
        with self.assertRaises(NormalizationRejected):
            CapabilityNormalizationBoundary(()).normalize(handoff,extension=ext,state=self._state())

    def test_handoff_validation_status_must_be_valid_or_partial(self):
        handoff=json.loads((ROOT/"core/fixtures/capabilities/valid/generic-future-capability-handoff.json").read_text())
        ext=json.loads((ROOT/"core/fixtures/capabilities/valid/generic-future-capability-result-extension.json").read_text())
        state=self._state()
        for status in (None,"unknown","rejected"):
            invalid=json.loads(json.dumps(handoff))
            if status is None:
                invalid["validation"].pop("status",None)
            else:
                invalid["validation"]["status"]=status
            with self.assertRaises(NormalizationRejected):
                CapabilityNormalizationBoundary((self.FutureNormalizer(),)).normalize(invalid,extension=ext,state=state)

    def test_future_capability_normalizes_without_reducer_capability_branch(self):
        handoff=json.loads((ROOT/"core/fixtures/capabilities/valid/generic-future-capability-handoff.json").read_text())
        ext=json.loads((ROOT/"core/fixtures/capabilities/valid/generic-future-capability-result-extension.json").read_text())
        state=self._state()
        proposal=CapabilityNormalizationBoundary((self.FutureNormalizer(),)).normalize(handoff,extension=ext,state=state)
        self.assertEqual(proposal.proposed_actions[0].kind,TransitionKind.CREATE_OBJECT)
        repo,svc=service(state)
        request=make_request(state,proposal.proposed_actions,suffix="7",source_refs=proposal.source_refs)
        receipt=svc.apply(request)
        self.assertIsInstance(receipt,CommitReceipt)
        current=repo.load_state_view("PRJ-FUTURE","LIN-1")
        self.assertIsNotNone(current.latest_object("claim","CLM-FUTURE-001"))
        persisted=json.dumps(current.current_snapshot,sort_keys=True)+json.dumps(current.latest_object("claim","CLM-FUTURE-001"),sort_keys=True)
        self.assertNotIn("fixture.future-research-capability",persisted)
