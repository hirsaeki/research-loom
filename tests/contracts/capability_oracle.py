from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import rfc8785

DIGEST_FIELDS={"descriptor":"descriptor_digest","context":"context_pack_digest","invocation":"invocation_digest","handoff":"handoff_digest"}

def canonical_digest(document:dict[str,Any],digest_field:str)->str:
    payload=deepcopy(document); payload.pop(digest_field,None)
    return "sha256:"+hashlib.sha256(rfc8785.dumps(payload)).hexdigest()

def expected_descriptor_digest(d): return canonical_digest(d,"descriptor_digest")
def expected_context_pack_digest(d): return canonical_digest(d,"context_pack_digest")
def expected_invocation_digest(d): return canonical_digest(d,"invocation_digest")
def expected_handoff_digest(d): return canonical_digest(d,"handoff_digest")
def refresh_digest(target,document): document[DIGEST_FIELDS[target]]=canonical_digest(document,DIGEST_FIELDS[target])

def apply_fixture_mutation(document,mutation):
    result=deepcopy(document)
    if mutation["op"]!="set": raise ValueError(f"unsupported fixture mutation: {mutation['op']}")
    cursor=result
    for part in mutation["path"][:-1]: cursor=cursor[part]
    cursor[mutation["path"][-1]]=deepcopy(mutation["value"])
    return result

def _canonical(v): return rfc8785.dumps(v)
def _profile_pin(p): return {k:p[k] for k in ("profile_id","profile_type","profile_version","manifest_sha256")}
def _flatten_guard_ids(c): return [g["guard_id"] for key in ("requirements","prohibitions","must_not_claim") for g in c[key]]

def descriptor_semantic_error(descriptor):
    if descriptor["descriptor_digest"]!=expected_descriptor_digest(descriptor): return "CAP-DESCRIPTOR-DIGEST-001"
    ids=[x["function_id"] for x in descriptor["declared_functions"]]
    if len(ids)!=len(set(ids)): return "CAP-DESCRIPTOR-BINDING-001"

def context_semantic_error(context,project_config,effective_profile_set,core_objects):
    if context["context_pack_digest"]!=expected_context_pack_digest(context): return "CAP-CONTEXT-DIGEST-001"
    b=context["bounds"]
    actual={"max_questions":len(context["question_ids"]),"max_research_object_references":len(context["research_object_references"]),"max_resources":len(context["resources"]),"max_attention_items":len(context["research_attention"]),"max_project_guards":sum(len(context["project_constraints"][k]) for k in ("requirements","prohibitions","must_not_claim")),"max_effective_constraints":len(context["effective_constraints"])}
    if any(actual[k]>b[k] for k in actual): return "CAP-CONTEXT-BOUND-001"
    if context["project_id"]!=project_config["project"]["project_id"]: return "CAP-CONTEXT-BINDING-001"
    if context["pins"]["project_config"]["configuration_digest"]!=project_config["configuration_digest"]: return "CAP-PIN-001"
    aps=context["pins"]["effective_profile_set"]
    if aps["schema_version"]!=effective_profile_set["schema_version"]: return "CAP-PIN-001"
    if aps["content_digest"]!="sha256:"+hashlib.sha256(rfc8785.dumps(effective_profile_set)).hexdigest(): return "CAP-PIN-001"
    if aps["core_contracts"]!=effective_profile_set["core_contracts"]: return "CAP-PIN-001"
    if _canonical(aps["profile_pins"])!=_canonical([_profile_pin(p) for p in effective_profile_set["effective_profiles"]]): return "CAP-PIN-001"
    if _canonical(context["research_attention"])!=_canonical(project_config["research_attention"]): return "CAP-CONTEXT-BINDING-001"
    if _canonical(context["project_constraints"])!=_canonical(project_config["project_constraints"]): return "CAP-CONTEXT-BINDING-001"
    if _canonical(context["effective_constraints"])!=_canonical(effective_profile_set["effective_constraints"]): return "CAP-CONTEXT-BINDING-001"
    questions={x["question_id"] for x in project_config["research_questions"]["references"]}
    if not set(context["question_ids"]).issubset(questions): return "CAP-CONTEXT-BINDING-001"
    index={(o["kind"],o["id"],o["revision"]):o for o in core_objects}
    for ref in context["research_object_references"]:
        if (ref["kind"],ref["id"],ref["revision"]) not in index: return "CAP-CONTEXT-BINDING-001"
    sp=context["pins"]["research_snapshot"]; snap=index.get(("snapshot",sp["snapshot_id"],sp["revision"]))
    if snap is None or sp["content_digest"]!="sha256:"+hashlib.sha256(rfc8785.dumps(snap)).hexdigest(): return "CAP-PIN-001"
    configured={x["reference_id"]:x for x in project_config["resource_references"]}
    for resource in context["resources"]:
        src=configured.get(resource["reference_id"])
        if src is None: return "CAP-CONTEXT-BINDING-001"
        for key in ("reference_type","object_id","locator","digest"):
            if resource.get(key)!=src.get(key): return "CAP-CONTEXT-BINDING-001"
        if resource["evidentiary_use"]=="candidate_source" and resource["reference_type"]!="source": return "CAP-RESOURCE-001"

def invocation_semantic_error(invocation,descriptor,context):
    if invocation["invocation_digest"]!=expected_invocation_digest(invocation): return "CAP-INVOCATION-DIGEST-001"
    c=invocation["capability"]
    if (c["capability_id"],c["capability_version"],c["descriptor_digest"])!=(descriptor["capability_id"],descriptor["capability_version"],descriptor["descriptor_digest"]): return "CAP-DESCRIPTOR-BINDING-001"
    function=next((x for x in descriptor["declared_functions"] if x["function_id"]==c["function_id"]),None)
    if function is None or invocation["execution_mode"] not in function["supported_execution_modes"]: return "CAP-DESCRIPTOR-BINDING-001"
    if invocation["project_id"]!=context["project_id"] or invocation["context_pack"]!={"context_pack_id":context["context_pack_id"],"context_pack_digest":context["context_pack_digest"]} or _canonical(invocation["pins"])!=_canonical(context["pins"]): return "CAP-PIN-001"
    a=invocation["runtime_authorization_evidence"]
    if a["capability_id"]!=c["capability_id"] or a["function_id"]!=c["function_id"] or invocation["execution_mode"] not in a["execution_modes"]: return "CAP-AUTH-001"
    if not {x["reference_id"] for x in context["resources"]}.issubset(set(a["resource_reference_ids"])): return "CAP-AUTH-001"

def _resource_index(context): return {r["reference_id"]:r for r in context["resources"]}
def _capture_index(handoff): return {c["capture_id"]:c for c in handoff["outputs"]["source_captures"]}
def _basis_is_evidence_eligible(basis,context,handoff):
    resources=_resource_index(context)
    if basis["basis_type"]=="resource_reference": resource=resources.get(basis["resource_reference_id"])
    else:
        capture=_capture_index(handoff).get(basis["capture_id"])
        if capture is None: return False
        origin=capture["origin"]
        if origin["origin_type"]=="acquired_source": return True
        resource=resources.get(origin["resource_reference_id"])
    return bool(resource and resource["reference_type"]=="source" and resource["evidentiary_use"]=="candidate_source")

def handoff_semantic_error(handoff,invocation,context):
    if handoff["handoff_digest"]!=expected_handoff_digest(handoff): return "CAP-HANDOFF-DIGEST-001"
    if handoff["invocation_id"]!=invocation["invocation_id"] or handoff["run_id"]!=invocation["run_id"] or handoff["project_id"]!=invocation["project_id"]: return "CAP-PIN-001"
    if _canonical(handoff["capability"])!=_canonical(invocation["capability"]) or handoff["execution_mode"]!=invocation["execution_mode"]: return "CAP-DESCRIPTOR-BINDING-001"
    expected={"invocation_digest":invocation["invocation_digest"],"context_pack_digest":context["context_pack_digest"],"project_config_digest":context["pins"]["project_config"]["configuration_digest"],"effective_profile_set_digest":context["pins"]["effective_profile_set"]["content_digest"],"research_snapshot":context["pins"]["research_snapshot"]}
    if _canonical(handoff["input_pins"])!=_canonical(expected): return "CAP-PIN-001"
    p=handoff["preserved_context"]
    if set(p["research_attention_ids"])!={x["attention_id"] for x in context["research_attention"]} or set(p["project_guard_ids"])!=set(_flatten_guard_ids(context["project_constraints"])) or set(p["effective_constraint_paths"])!={x["path"] for x in context["effective_constraints"]}: return "CAP-HANDOFF-PRESERVE-001"
    o=handoff["outputs"]; fields={"observations":"observation_id","source_captures":"capture_id","evidence_candidates":"evidence_candidate_id","candidate_findings":"candidate_finding_id","counterevidence":"counterevidence_id","conflicts":"conflict_id","unknowns":"unknown_id","evidence_gaps":"gap_id","candidate_next_actions":"proposal_id","candidate_next_methods":"proposal_id"}
    ids=[x[f] for collection,f in fields.items() for x in o[collection]]
    if len(ids)!=len(set(ids)): return "CAP-HANDOFF-IDENTITY-001"
    resources=_resource_index(context)
    for capture in o["source_captures"]:
        origin=capture["origin"]
        if origin["origin_type"]=="project_source_reference":
            r=resources.get(origin["resource_reference_id"])
            if not r or r["reference_type"]!="source" or r["evidentiary_use"]!="candidate_source": return "CAP-HANDOFF-REF-001"
    evid={x["evidence_candidate_id"] for x in o["evidence_candidates"]}; counter={x["counterevidence_id"] for x in o["counterevidence"]}; q=set(context["question_ids"]); all_ids=set(ids)
    for x in o["observations"]:
        if not set(x.get("evidence_candidate_ids",[])).issubset(evid): return "CAP-HANDOFF-REF-001"
    for x in o["candidate_findings"]:
        if not set(x["question_ids"]).issubset(q) or not set(x["supporting_evidence_candidate_ids"]).issubset(evid) or not set(x["counterevidence_candidate_ids"]).issubset(counter): return "CAP-HANDOFF-REF-001"
    if any(not set(x["question_ids"]).issubset(q) for x in o["evidence_gaps"]): return "CAP-HANDOFF-REF-001"
    if any(not set(x["related_output_ids"]).issubset(all_ids) for x in o["conflicts"]): return "CAP-HANDOFF-REF-001"
    if handoff["execution_mode"] in {"virtual","synthetic_test"} and any(x["epistemic_mode"]!="synthetic" for x in o["observations"]+o["evidence_candidates"]+o["candidate_findings"]+o["counterevidence"]): return "CAP-MODE-001"
    if any(not _basis_is_evidence_eligible(x["source_basis"],context,handoff) for x in o["evidence_candidates"]+o["counterevidence"]): return "CAP-RESOURCE-001"
    v=handoff["validation"]
    if (v["status"]=="valid" and v["issues"]) or (v["status"] in {"partial","rejected"} and not v["issues"]): return "CAP-HANDOFF-VALIDATION-001"

def semantic_case_error(target,document,*,descriptor,context,invocation,project_config,effective_profile_set,core_objects):
    if target=="descriptor": return descriptor_semantic_error(document)
    if target=="context": return context_semantic_error(document,project_config,effective_profile_set,core_objects)
    if target=="invocation": return invocation_semantic_error(document,descriptor,context)
    if target=="handoff": return handoff_semantic_error(document,invocation,context)
    raise ValueError(f"unknown semantic case target: {target}")
