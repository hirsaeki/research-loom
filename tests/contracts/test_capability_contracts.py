from __future__ import annotations
from copy import deepcopy
import hashlib, json, unittest
from pathlib import Path
import rfc8785, yaml
from jsonschema import Draft202012Validator
from capability_oracle import *

ROOT=Path(__file__).resolve().parents[2]
PATHS={"descriptor":ROOT/"core/packages/capability-descriptor.schema.json","context":ROOT/"core/packages/capability-context-pack.schema.json","invocation":ROOT/"core/packages/capability-invocation.schema.json","handoff":ROOT/"core/packages/capability-handoff.schema.json","semantics":ROOT/"core/packages/capability-semantics.schema.json"}
FIX={"descriptor":ROOT/"core/fixtures/capabilities/valid/generic-capability-descriptor.json","context":ROOT/"core/fixtures/capabilities/valid/generic-capability-context-pack.json","invocation":ROOT/"core/fixtures/capabilities/valid/generic-capability-invocation.json","handoff":ROOT/"core/fixtures/capabilities/valid/generic-capability-handoff.json"}
class CapabilityContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.schemas={k:json.loads(p.read_text()) for k,p in PATHS.items()}; cls.v={k:Draft202012Validator(s) for k,s in cls.schemas.items()}; cls.f={k:json.loads(p.read_text()) for k,p in FIX.items()}
  cls.project=json.loads((ROOT/"projects/fixtures/valid/generic-project-config.json").read_text()); cls.eps=json.loads((ROOT/"profiles/fixtures/valid/effective-profile-set.json").read_text()); cls.objects=json.loads((ROOT/"core/fixtures/research-objects/valid.json").read_text())["objects"]; cls.sem=yaml.safe_load((ROOT/"core/packages/capability-semantics.yaml").read_text())
 def valid(self,k,d): self.assertFalse(list(self.v[k].iter_errors(d)))
 def invalid(self,k,d): self.assertTrue(list(self.v[k].iter_errors(d)))
 def test_valid_chain_and_digests(self):
  for s in self.schemas.values(): Draft202012Validator.check_schema(s)
  for k,d in self.f.items(): self.valid(k,d)
  self.valid("semantics",self.sem); d,c,i,h=(self.f[x] for x in ("descriptor","context","invocation","handoff"))
  self.assertIsNone(descriptor_semantic_error(d)); self.assertIsNone(context_semantic_error(c,self.project,self.eps,self.objects)); self.assertIsNone(invocation_semantic_error(i,d,c)); self.assertIsNone(handoff_semantic_error(h,i,c))
  self.assertEqual(d["descriptor_digest"],expected_descriptor_digest(d)); self.assertEqual(c["context_pack_digest"],expected_context_pack_digest(c)); self.assertEqual(i["invocation_digest"],expected_invocation_digest(i)); self.assertEqual(h["handoff_digest"],expected_handoff_digest(h)); self.assertEqual(c["pins"]["effective_profile_set"]["content_digest"],"sha256:"+hashlib.sha256(rfc8785.dumps(self.eps)).hexdigest())
 def test_context_pins_and_preserves_governance(self):
  c=self.f["context"]; self.assertEqual(c["research_attention"],self.project["research_attention"]); self.assertEqual(c["project_constraints"],self.project["project_constraints"]); self.assertEqual(c["effective_constraints"],self.eps["effective_constraints"])
  pins=[{k:p[k] for k in ("profile_id","profile_type","profile_version","manifest_sha256")} for p in self.eps["effective_profiles"]]; self.assertEqual(c["pins"]["effective_profile_set"]["profile_pins"],pins)
  bad=deepcopy(c); bad["bounds"]["max_resources"]=2; refresh_digest("context",bad); self.assertEqual("CAP-CONTEXT-BOUND-001",context_semantic_error(bad,self.project,self.eps,self.objects))
  bad=deepcopy(c); bad["project_constraints"]["must_not_claim"]=[]; refresh_digest("context",bad); self.assertEqual("CAP-CONTEXT-BINDING-001",context_semantic_error(bad,self.project,self.eps,self.objects))
 def test_availability_and_project_hints_are_not_authorization(self):
  d,i=self.f["descriptor"],self.f["invocation"]; self.assertEqual("available",d["availability"]["declaration"]); self.assertEqual("no_project_objection",self.project["capability_hints"][0]["permission_hint"])
  bad=deepcopy(d); bad["runtime_authorization_evidence"]=i["runtime_authorization_evidence"]; self.invalid("descriptor",bad)
  bad=deepcopy(i); bad["runtime_authorization_evidence"]=self.project["capability_hints"][0]; self.invalid("invocation",bad)
 def test_invocation_requires_declared_function_mode_and_resource_authorization(self):
  d,c,i=self.f["descriptor"],self.f["context"],self.f["invocation"]
  bad=deepcopy(i); bad["capability"]["function_id"]="choose-next-method"; refresh_digest("invocation",bad); self.assertEqual("CAP-DESCRIPTOR-BINDING-001",invocation_semantic_error(bad,d,c))
  bad=deepcopy(i); bad["runtime_authorization_evidence"]["resource_reference_ids"].remove("REF-ARTIFACT-001"); refresh_digest("invocation",bad); self.assertEqual("CAP-AUTH-001",invocation_semantic_error(bad,d,c))
 def test_virtual_output_never_becomes_empirical(self):
  h,i,c=self.f["handoff"],self.f["invocation"],self.f["context"]; bad=deepcopy(h); bad["outputs"]["evidence_candidates"][0]["epistemic_mode"]="empirical"; refresh_digest("handoff",bad); self.assertEqual("CAP-MODE-001",handoff_semantic_error(bad,i,c)); self.assertFalse(self.sem["execution_modes"]["virtual"]["empirical_candidate_possible"]); self.assertFalse(self.sem["execution_modes"]["synthetic_test"]["empirical_candidate_possible"])
 def test_sources_may_be_pre_registered_or_newly_acquired_but_artifacts_are_not_evidence(self):
  h,i,c=self.f["handoff"],self.f["invocation"],self.f["context"]; acquired=deepcopy(h); acquired["outputs"]["source_captures"][0]["origin"]={"origin_type":"acquired_source","acquisition_locator":"https://example.invalid/fixture"}; refresh_digest("handoff",acquired); self.valid("handoff",acquired); self.assertIsNone(handoff_semantic_error(acquired,i,c))
  artifact=next(x for x in c["resources"] if x["reference_type"]=="artifact"); bad=deepcopy(h); bad["outputs"]["counterevidence"][0]["source_basis"]={"basis_type":"resource_reference","resource_reference_id":artifact["reference_id"]}; refresh_digest("handoff",bad); self.assertEqual("CAP-RESOURCE-001",handoff_semantic_error(bad,i,c))
 def test_handoff_is_candidate_only_structured_source_of_truth(self):
  h=self.f["handoff"]; b=h["adoption_boundary"]; self.assertEqual((False,True,True),(b["research_state_mutation_performed"],b["outputs_are_candidates"],b["human_decision_required_for_authoritative_transition"]))
  for key,value in [("research_state_patch",{"findings":["FND-X"]}),("conversational_handoff","authoritative prose")]: bad=deepcopy(h); bad[key]=value; self.invalid("handoff",bad)
  bad=deepcopy(h); bad["outputs"]["candidate_findings"][0]["adoption_state"]="approved"; self.invalid("handoff",bad); bad=deepcopy(h); bad["outputs"]["candidate_next_methods"][0]["selected"]=True; self.invalid("handoff",bad)
 def test_handoff_preserves_governance_and_closed_references(self):
  h,i,c=self.f["handoff"],self.f["invocation"],self.f["context"]; bad=deepcopy(h); bad["preserved_context"]["research_attention_ids"]=["ATT-FIXTURE-001"]; refresh_digest("handoff",bad); self.assertEqual("CAP-HANDOFF-PRESERVE-001",handoff_semantic_error(bad,i,c))
  bad=deepcopy(h); bad["outputs"]["candidate_findings"][0]["question_ids"]=["RQ-NOT-IN-CONTEXT"]; refresh_digest("handoff",bad); self.assertEqual("CAP-HANDOFF-REF-001",handoff_semantic_error(bad,i,c)); bad=deepcopy(h); bad["outputs"]["unknowns"][0]["unknown_id"]="OBS-001"; refresh_digest("handoff",bad); self.assertEqual("CAP-HANDOFF-IDENTITY-001",handoff_semantic_error(bad,i,c))
 def test_validation_status_is_not_adoption(self):
  h,i,c=self.f["handoff"],self.f["invocation"],self.f["context"]
  for status in ("partial","rejected"):
   x=deepcopy(h); x["validation"]={"status":status,"issues":[{"code":"FIXTURE_ISSUE","severity":"warning" if status=="partial" else "error","message":"fixture"}]}; refresh_digest("handoff",x); self.assertIsNone(handoff_semantic_error(x,i,c)); self.assertTrue(x["adoption_boundary"]["outputs_are_candidates"])
  bad=deepcopy(h); bad["validation"]["status"]="partial"; refresh_digest("handoff",bad); self.assertEqual("CAP-HANDOFF-VALIDATION-001",handoff_semantic_error(bad,i,c))
 def test_semantic_mutation_fixtures(self):
  bases=self.f; cases=json.loads((ROOT/"core/fixtures/capabilities/semantic/cases.json").read_text())["cases"]
  for case in cases:
   x=apply_fixture_mutation(bases[case["target"]],case["mutation"])
   if case.get("rehash"): refresh_digest(case["target"],x)
   self.valid(case["target"],x); err=semantic_case_error(case["target"],x,descriptor=bases["descriptor"],context=bases["context"],invocation=bases["invocation"],project_config=self.project,effective_profile_set=self.eps,core_objects=self.objects); self.assertEqual(case["expected_error"],err,case["id"])
 def test_semantics_closes_ownership_and_authority_boundaries(self):
  self.assertTrue(all(v is False for v in self.sem["principles"].values())); self.assertEqual({"common_contracts":"core/packages","imperative_implementations":"plugins","project_config":"configures_not_owns","profiles":"constrain_not_implement"},self.sem["ownership"]); self.assertEqual("Core Human Decision semantics",self.sem["adoption_boundary"]["authoritative_transition_owner"])
if __name__=="__main__": unittest.main()
