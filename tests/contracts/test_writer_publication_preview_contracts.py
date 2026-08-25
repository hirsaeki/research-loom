from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from writer_publication_preview_oracle import (
    ERROR_IDS, canonical_digest, conversation_routing_error, feedback_error,
    manuscript_error, outline_error, preview_iteration_error, preview_manifest_error,
    profile_defect_error, research_package_error,
)

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages/writer-publication"
FIX = ROOT / "core/fixtures/writer-publication/valid/generic-writer-publication-preview-fixtures.json"
CONV = ROOT / "core/fixtures/conversation/valid/writer-publication-preview-routing.json"
WORK = ROOT / "core/packages/work-conversation.schema.json"


def load(path): return json.loads(path.read_text(encoding="utf-8"))
def refresh(doc, field): doc[field] = canonical_digest(doc, field)
def fill(c): return "sha256:" + c * 64


class WriterPublicationPreviewContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {n: load(PKG / n) for n in ("research-package.schema.json","writer-preview.schema.json","manuscript-package.schema.json","publication-preview.schema.json")}
        cls.f = load(FIX); cls.route = load(CONV)
        cls.sem = yaml.safe_load((PKG / "writer-publication-semantics.yaml").read_text(encoding="utf-8"))

    def validate(self, name, doc):
        schema=self.schemas[name]; Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(doc)

    def test_schemas_and_valid_fixtures(self):
        f=self.f
        self.validate("research-package.schema.json",f["research_package"])
        self.validate("writer-preview.schema.json",f["outline_package"]); self.validate("writer-preview.schema.json",f["writing_feedback_package"])
        self.validate("manuscript-package.schema.json",f["manuscript_package"]); self.validate("publication-preview.schema.json",f["preview_artifact_manifest"]); self.validate("publication-preview.schema.json",f["preview_iteration"])
        for d in f["profile_defect_candidates"]: self.validate("publication-preview.schema.json",d)

    def test_error_catalog_exact(self): self.assertEqual(set(self.sem["errors"]), ERROR_IDS)

    def test_research_package_binding_and_firewall(self):
        p=self.f["research_package"]; self.assertIsNone(research_package_error(p))
        b=deepcopy(p); b["release_eligible"]=True; refresh(b,"package_digest"); self.assertEqual(research_package_error(b),"WP-EPISTEMIC-FIREWALL-001")
        b=deepcopy(p); b["provenance"]["input_digests"].remove(p["source_research_snapshot"]["content_digest"]); refresh(b,"package_digest"); self.assertEqual(research_package_error(b),"WP-RP-SNAPSHOT-BINDING-001")

    def test_outline_traceability_and_preservation(self):
        p,o=self.f["research_package"],self.f["outline_package"]; self.assertIsNone(outline_error(o,p))
        b=deepcopy(o); b["sections"][1]["limitation_refs"]=[]; refresh(b,"outline_digest"); self.assertEqual(outline_error(b,p),"WP-PRESERVATION-001")
        b=deepcopy(o); b["sections"][0]["finding_refs"]=["FND-FABRICATED"]; refresh(b,"outline_digest"); self.assertEqual(outline_error(b,p),"WP-SECTION-TRACEABILITY-001")

    def test_writing_feedback(self):
        f=self.f; fb=f["writing_feedback_package"]; self.assertIsNone(feedback_error(fb,f["research_package"],f["outline_package"]))
        self.assertEqual({i["issue_category"] for i in fb["issues"]},{"MISSING_EVIDENCE","NARRATIVE_CONSTRAINT_CONFLICT"}); self.assertFalse(fb["is_research_evidence"])

    def test_preview_manuscript_and_publication(self):
        f=self.f; self.assertIsNone(manuscript_error(f["manuscript_package"],f["research_package"],f["outline_package"])); self.assertIsNone(preview_manifest_error(f["preview_artifact_manifest"],f["manuscript_package"]))

    def test_docx_pdf_and_defects(self):
        f=self.f; self.assertEqual({x["format"] for x in f["preview_artifact_manifest"]["outputs"]},{"docx","pdf"})
        self.assertTrue({"UNRESOLVED_CITATION","MISSING_EXHIBIT","CROSS_REFERENCE","PROFILE_RULE_CONFLICT","NARRATIVE_CONSTRAINT_CONFLICT"}.issubset({d["defect_kind"] for d in f["profile_defect_candidates"]}))
        for d in f["profile_defect_candidates"]: self.assertIsNone(profile_defect_error(d))

    def test_profile_revision_rerun(self):
        i=self.f["preview_iteration"]; self.assertIsNone(preview_iteration_error(i)); b=deepcopy(i); b["new_preview"]=deepcopy(b["previous_preview"]); refresh(b,"content_digest"); self.assertEqual(preview_iteration_error(b),"WP-PREVIEW-ITERATION-001")

    def test_synthetic_empirical_relabel_forbidden(self):
        f=self.f; b=deepcopy(f["manuscript_package"]); b["source_epistemic_status"]="EMPIRICAL_RESEARCH_STATE"; refresh(b,"content_digest"); self.assertEqual(manuscript_error(b,f["research_package"],f["outline_package"]),"WP-EPISTEMIC-FIREWALL-001")

    def test_virtual_draft_real_promotion_forbidden(self):
        f=self.f; p=deepcopy(f["research_package"]); p["package_id"]="RP-REAL"; p["package_mode"]="real"; p["source_epistemic_status"]="EMPIRICAL_RESEARCH_STATE"; p["preview_only"]=False; p["source_research_snapshot"].update(snapshot_id="SNAP-REAL",content_digest=fill("d"),execution_mode="real"); p["provenance"]["input_digests"]=[p["project_config_digest"],p["effective_profile_set"]["content_digest"],fill("d")]; refresh(p,"package_digest")
        o=deepcopy(f["outline_package"]); o["outline_id"]="OUT-REAL"; o["outline_mode"]="real"; o["source_epistemic_status"]="EMPIRICAL_RESEARCH_STATE"; o["source"].update(research_package_id=p["package_id"],research_package_digest=p["package_digest"],research_snapshot_id="SNAP-REAL",research_snapshot_digest=fill("d")); refresh(o,"outline_digest")
        m=deepcopy(f["manuscript_package"]); m["manuscript_mode"]="real_draft"; m["source_epistemic_status"]="EMPIRICAL_RESEARCH_STATE"; m["preview_only"]=False; m["source"]=deepcopy(o["source"]); m["outline_ref"].update(outline_id=o["outline_id"],outline_digest=o["outline_digest"]); m["lineage"]={"newly_generated_from_research_package":False,"promoted_from_virtual_manuscript_ref":"MS-PREVIEW-1"}; refresh(m,"content_digest"); self.assertEqual(manuscript_error(m,p,o),"WP-VIRTUAL-REAL-PROMOTION-001")

    def test_fabricated_citation_forbidden(self):
        f=self.f; b=deepcopy(f["manuscript_package"]); b["citations"][0]["source_ref"]="SRC-FAKE"; refresh(b,"content_digest"); self.assertEqual(manuscript_error(b,f["research_package"],f["outline_package"]),"WP-CITATION-SOURCE-001")

    def test_stale_profile_template_pin_forbidden(self):
        f=self.f; b=deepcopy(f["preview_artifact_manifest"]); b["publication_profile"]["content_digest"]=fill("e"); refresh(b,"content_digest"); self.assertEqual(preview_manifest_error(b,f["manuscript_package"]),"WP-PUBLICATION-PIN-001")
        b=deepcopy(f["preview_artifact_manifest"]); b["outputs"][0]["input_template_digest"]=fill("e"); refresh(b,"content_digest"); self.assertEqual(preview_manifest_error(b,f["manuscript_package"]),"WP-PUBLICATION-PIN-001")

    def test_research_state_mutation_forbidden(self):
        f=self.f; b=deepcopy(f["writing_feedback_package"]); b["research_state_mutation_performed"]=True; refresh(b,"feedback_digest"); self.assertEqual(feedback_error(b,f["research_package"],f["outline_package"]),"WP-RESEARCH-STATE-AUTHORITY-001")

    def test_pr10_routing(self):
        p=self.f["research_package"]; self.assertIsNone(conversation_routing_error(self.route,p)); proposal=self.route["action_proposal"]
        Draft202012Validator(load(WORK),format_checker=FormatChecker()).validate(proposal); self.assertEqual(proposal["route"]["route_type"],"harness_service")
        b=deepcopy(self.route); b["action_proposal"]["route"]={"route_type":"unresolved","reason":"wrong"}; self.assertEqual(conversation_routing_error(b,p),"WP-CONVERSATION-ROUTING-001")

    def test_ambiguous_profile_conflict_is_not_lww(self):
        s=self.sem["profile_revision_semantics"]; self.assertEqual(s["ambiguous_conflict_resolution"],"human_review_required"); self.assertFalse(s["last_write_wins_for_ambiguous_conflicts"])


if __name__ == "__main__": unittest.main()
