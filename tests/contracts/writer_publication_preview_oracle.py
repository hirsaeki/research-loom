from __future__ import annotations

import hashlib
import rfc8785

ERROR_IDS = {
    "WP-RP-DIGEST-001", "WP-RP-SNAPSHOT-BINDING-001", "WP-RP-PROFILE-BINDING-001",
    "WP-EPISTEMIC-FIREWALL-001", "WP-OUTLINE-DIGEST-001", "WP-OUTLINE-BINDING-001",
    "WP-SECTION-TRACEABILITY-001", "WP-PRESERVATION-001", "WP-FEEDBACK-DIGEST-001",
    "WP-RESEARCH-STATE-AUTHORITY-001", "WP-MANUSCRIPT-DIGEST-001", "WP-MANUSCRIPT-BINDING-001",
    "WP-CITATION-SOURCE-001", "WP-VIRTUAL-REAL-PROMOTION-001", "WP-PREVIEW-MANIFEST-DIGEST-001",
    "WP-PUBLICATION-PIN-001", "WP-PROFILE-DEFECT-AUTHORITY-001", "WP-PREVIEW-ITERATION-001",
    "WP-CONVERSATION-ROUTING-001",
}


def canonical_digest(document, digest_field):
    body = {k: v for k, v in document.items() if k != digest_field}
    return "sha256:" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()


def _source_binding_tuple(binding):
    return (
        binding["research_package_id"], binding["research_package_digest"],
        binding["research_snapshot_id"], binding["research_snapshot_digest"],
    )


def _expected_source_binding_tuple(p):
    snap = p["source_research_snapshot"]
    return p["package_id"], p["package_digest"], snap["snapshot_id"], snap["content_digest"]


def _profile_pin_tuple(pin):
    return pin["profile_id"], pin["profile_version"], pin["content_digest"]


def _package_profile_pin_tuples(p, profile_type):
    return {
        (pin["profile_id"], pin["profile_version"], pin["content_digest"])
        for pin in p["effective_profile_set"]["profile_pins"]
        if pin["profile_type"] == profile_type
    }


def research_package_error(p):
    if p["package_digest"] != canonical_digest(p, "package_digest"):
        return "WP-RP-DIGEST-001"
    snap = p["source_research_snapshot"]
    if snap["content_digest"] not in p["provenance"]["input_digests"]:
        return "WP-RP-SNAPSHOT-BINDING-001"
    pins = p["effective_profile_set"]["profile_pins"]
    if not {"narrative", "publication"}.issubset({x["profile_type"] for x in pins}):
        return "WP-RP-PROFILE-BINDING-001"
    if p["effective_profile_set"]["content_digest"] not in p["provenance"]["input_digests"]:
        return "WP-RP-PROFILE-BINDING-001"
    if p["source_epistemic_status"] == "SYNTHETIC_TEST_ONLY" and not (
        p["package_mode"] == "preview" and p["preview_only"] and not p["authoritative_research_freeze"]
        and not p["release_eligible"] and snap["execution_mode"] == "virtual"
    ):
        return "WP-EPISTEMIC-FIREWALL-001"
    return None


def _catalog(p):
    c = p["content"]
    return {
        "argument": set(c["argument_refs"]), "finding": set(c["finding_refs"]),
        "evidence": set(c["evidence_refs"]), "counter_review": set(c["counter_review_refs"]),
        "qualifier": set(c["qualifier_refs"]), "limitation": {x["limitation_id"] for x in c["limitations"]},
        "contribution": set(c["contribution_refs"]), "source": {x["source_id"] for x in c["source_refs"]},
    }


def outline_error(o, p):
    if o["outline_digest"] != canonical_digest(o, "outline_digest"):
        return "WP-OUTLINE-DIGEST-001"
    s, snap = o["source"], p["source_research_snapshot"]
    if (s["research_package_id"], s["research_package_digest"], s["research_snapshot_id"], s["research_snapshot_digest"]) != (p["package_id"], p["package_digest"], snap["snapshot_id"], snap["content_digest"]):
        return "WP-OUTLINE-BINDING-001"
    if o["source_epistemic_status"] != p["source_epistemic_status"]:
        return "WP-EPISTEMIC-FIREWALL-001"
    cat = _catalog(p); stages = set(p["narrative_constraints"]["stage_refs"]); purposes = set(p["narrative_constraints"]["section_purpose_refs"])
    src = {x["source_id"]: x for x in p["content"]["source_refs"]}; preserved = set()
    fields = {"argument_refs":"argument","finding_refs":"finding","evidence_refs":"evidence","counter_review_refs":"counter_review","qualifier_refs":"qualifier","limitation_refs":"limitation","contribution_refs":"contribution"}
    for sec in o["sections"]:
        if sec["narrative_stage_ref"] not in stages or sec["semantic_purpose_ref"] not in purposes:
            return "WP-SECTION-TRACEABILITY-001"
        for field, kind in fields.items():
            if not set(sec[field]).issubset(cat[kind]): return "WP-SECTION-TRACEABILITY-001"
        for cite in sec["citation_requirements"]:
            sid = cite["source_ref"]
            if sid not in src or not src[sid]["citation_capable"] or cite["locator_ref"] not in src[sid]["locator_refs"]:
                return "WP-CITATION-SOURCE-001"
        preserved.update(sec["counter_review_refs"] + sec["qualifier_refs"] + sec["limitation_refs"])
    if not set(p["narrative_constraints"]["required_preservation_refs"]).issubset(preserved):
        return "WP-PRESERVATION-001"
    return None


def feedback_error(f, p, o):
    if f["feedback_digest"] != canonical_digest(f, "feedback_digest"):
        return "WP-FEEDBACK-DIGEST-001"
    if _source_binding_tuple(f["source"]) != _expected_source_binding_tuple(p):
        return "WP-OUTLINE-BINDING-001"
    if (f["source_outline_ref"]["outline_id"], f["source_outline_ref"]["outline_digest"]) != (o["outline_id"], o["outline_digest"]):
        return "WP-OUTLINE-BINDING-001"
    if f["is_research_evidence"] or f["research_state_mutation_performed"]:
        return "WP-RESEARCH-STATE-AUTHORITY-001"
    return None


def manuscript_error(m, p, o):
    if m["content_digest"] != canonical_digest(m, "content_digest"):
        return "WP-MANUSCRIPT-DIGEST-001"
    if _source_binding_tuple(m["source"]) != _expected_source_binding_tuple(p):
        return "WP-MANUSCRIPT-BINDING-001"
    if (m["outline_ref"]["outline_id"], m["outline_ref"]["outline_version"], m["outline_ref"]["outline_digest"]) != (o["outline_id"], o["outline_version"], o["outline_digest"]):
        return "WP-MANUSCRIPT-BINDING-001"
    eps = m["effective_profile_set"]
    if (eps["effective_profile_set_ref"], eps["content_digest"]) != (
        p["effective_profile_set"]["effective_profile_set_ref"], p["effective_profile_set"]["content_digest"]
    ):
        return "WP-MANUSCRIPT-BINDING-001"
    if {_profile_pin_tuple(pin) for pin in m["narrative_profile_pins"]} != _package_profile_pin_tuples(p, "narrative"):
        return "WP-MANUSCRIPT-BINDING-001"
    publication_pins = _package_profile_pin_tuples(p, "publication")
    if len(publication_pins) != 1 or _profile_pin_tuple(m["publication_profile_pin"]) not in publication_pins:
        return "WP-MANUSCRIPT-BINDING-001"
    if m["source_epistemic_status"] != p["source_epistemic_status"]:
        return "WP-EPISTEMIC-FIREWALL-001"
    if m["manuscript_mode"] == "real_draft" and (m["lineage"].get("promoted_from_virtual_manuscript_ref") or not m["lineage"]["newly_generated_from_research_package"]):
        return "WP-VIRTUAL-REAL-PROMOTION-001"
    if p["source_epistemic_status"] == "SYNTHETIC_TEST_ONLY" and not (m["manuscript_mode"] == "preview" and m["preview_only"] and not m["release_eligible"]):
        return "WP-EPISTEMIC-FIREWALL-001"
    if not set(p["narrative_constraints"]["required_preservation_refs"]).issubset(set(m["preserved_refs"])):
        return "WP-PRESERVATION-001"
    src = {x["source_id"]: x for x in p["content"]["source_refs"]}
    for cite in m["citations"]:
        sid = cite["source_ref"]
        if sid not in src or cite["locator_ref"] not in src[sid]["locator_refs"] or cite["namespace"] != src[sid]["citation_namespace"]:
            return "WP-CITATION-SOURCE-001"
        if not src[sid]["citation_capable"]:
            return "WP-CITATION-SOURCE-001"
    return None


def preview_manifest_error(a, m):
    if a["content_digest"] != canonical_digest(a, "content_digest"):
        return "WP-PREVIEW-MANIFEST-DIGEST-001"
    if (a["source_manuscript"]["manuscript_id"], a["source_manuscript"]["manuscript_digest"]) != (m["manuscript_id"], m["content_digest"]) or a["source_epistemic_status"] != m["source_epistemic_status"]:
        return "WP-MANUSCRIPT-BINDING-001"
    if not (a["preview_only"] and not a["release_eligible"] and not a["published_artifact"] and not a["release_manifest"]):
        return "WP-EPISTEMIC-FIREWALL-001"
    if a["publication_profile"] != m["publication_profile_pin"]:
        return "WP-PUBLICATION-PIN-001"
    tpl, style = a["template_pin"]["content_digest"], a["style_map_pin"]["content_digest"]
    for out in a["outputs"]:
        if out["input_template_digest"] != tpl or out["input_style_map_digest"] != style:
            return "WP-PUBLICATION-PIN-001"
    required = {m["content_digest"], a["publication_profile"]["content_digest"], tpl, style}
    if not required.issubset(set(a["provenance"]["input_digests"])): return "WP-PUBLICATION-PIN-001"
    return None


def profile_defect_error(d):
    if d["content_digest"] != canonical_digest(d, "content_digest") or d["mutation_performed"] or d["core_invariant_weakening_proposed"]:
        return "WP-PROFILE-DEFECT-AUTHORITY-001"
    return None


def preview_iteration_error(i):
    if i["content_digest"] != canonical_digest(i, "content_digest"):
        return "WP-PREVIEW-ITERATION-001"
    if i["previous_preview"]["preview_id"] == i["new_preview"]["preview_id"] or i["previous_profile_pin"]["content_digest"] == i["new_profile_pin"]["content_digest"] or i["previous_artifact_overwritten"] or not i["input_pins_changed"] or not i["human_reviewed_revision"]:
        return "WP-PREVIEW-ITERATION-001"
    return None


def conversation_routing_error(r, p):
    q = r["action_proposal"]; a=q["action"]; payload=a["payload"]
    if q["route"] != {"route_type":"harness_service","service_id":"writer-publication.preview"} or q["commitment_mode"] != "proposal_only" or a["effect"] != "read_only":
        return "WP-CONVERSATION-ROUTING-001"
    if payload["research_package_digest"] != p["package_digest"] or payload["research_freeze"] or payload["manuscript_freeze"] or payload["publication_release"] or r["auto_release"]:
        return "WP-CONVERSATION-ROUTING-001"
    return None
