from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import unittest
from pathlib import Path

import rfc8785
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
DR = PKG / "desktop-research"
CONTEXT_PATH = ROOT / "core/fixtures/capabilities/valid/generic-capability-context-pack.json"
ROUTING_PATH = ROOT / "core/fixtures/conversation/valid/desktop-research-routing.json"


def digest(document, field):
    value = deepcopy(document)
    value.pop(field, None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


class DesktopResearchContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.descriptor_schema = json.loads((PKG / "capability-descriptor.schema.json").read_text())
        cls.conversation_schema = json.loads((PKG / "work-conversation.schema.json").read_text())
        cls.context_schema = json.loads((DR / "desktop-research-context-extension.schema.json").read_text())
        cls.result_schema = json.loads((DR / "desktop-research-result-extension.schema.json").read_text())
        cls.descriptor = json.loads((DR / "desktop-research-capability-descriptor.json").read_text())
        cls.context = json.loads(CONTEXT_PATH.read_text())
        cls.routing = json.loads(ROUTING_PATH.read_text())
        cls.semantics = yaml.safe_load((DR / "desktop-research-semantics.yaml").read_text())
        cls.context_extension = {
            "schema_version": "0.1.0", "extension_type": "desktop_research_context",
            "context_binding": {"context_pack_id": cls.context["context_pack_id"], "context_pack_digest": cls.context["context_pack_digest"], "project_id": cls.context["project_id"]},
            "target": {"target_type": "research_question", "question_id": "RQ-1"},
            "retrieval_scope": {"scope_statement": "Bounded contract-fixture retrieval.", "in_scope": ["source discovery and capture"], "out_of_scope": ["Writer and Publication evidence"]},
            "allowed_source_categories": ["peer_reviewed_research", "government_primary", "other"],
            "resource_role_bindings": [{"reference_id": "REF-INPUT-001", "role": "research_context"}, {"reference_id": "REF-SOURCE-001", "role": "candidate_source"}, {"reference_id": "REF-ARTIFACT-001", "role": "research_artifact"}],
            "forbidden_resource_roles": ["writer_material", "publication_material", "publication_feedback", "archive_provenance"],
            "coverage_dimensions": [{"dimension_id": "COV-SUPPORT", "label": "Supporting material", "required": True}, {"dimension_id": "COV-OPPOSE", "label": "Opposing material", "required": True}],
            "budget": {"max_total_resources": 3, "max_candidate_source_resources": 1, "max_artifact_resources": 1, "max_acquired_source_captures": 2, "max_search_trace_entries": 4, "max_text_rendition_bytes": 4096},
            "extension_digest": "sha256:" + "0" * 64,
        }
        cls.context_extension["extension_digest"] = digest(cls.context_extension, "extension_digest")
        text = "Synthetic captured text containing an exact excerpt for citation."
        text_digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        cls.result_extension = {
            "schema_version": "0.1.0", "extension_type": "desktop_research_result",
            "handoff_binding": {"handoff_id": "HND-DR-001", "handoff_digest": "sha256:" + "1" * 64, "invocation_id": "INV-DR-001", "run_id": "RUN-DR-001", "context_pack_id": cls.context["context_pack_id"], "context_pack_digest": cls.context["context_pack_digest"], "capability_id": "desktop-research", "function_id": "investigate"},
            "source_capture_details": [{"capture_id": "CAP-DR-001", "source_category": "other", "exact_locator": "fixture://source#exact", "acquired_at": "2026-08-24T00:00:00Z", "original_capture": {"content_reference": "capture://original", "content_digest": "sha256:" + "2" * 64, "media_type": "application/octet-stream", "byte_length": 64}, "text_rendition": {"content_reference": "capture://text", "content_digest": text_digest, "media_type": "text/plain", "byte_length": len(text.encode()), "encoding": "UTF-8", "inline_text": text}}],
            "citation_details": [{"citation_id": "CIT-DR-001", "handoff_output_kind": "evidence_candidate", "handoff_output_id": "EVC-DR-001", "capture_id": "CAP-DR-001", "excerpt": "exact excerpt", "excerpt_locator": "fixture://source#excerpt", "text_rendition_digest": text_digest, "capture_integrity_verified": True, "excerpt_containment_verified": True, "evidence_adoption_performed": False}],
            "search_trace": {"entries": [{"trace_entry_id": "STR-1", "strategy": "support search", "coverage_dimension_ids": ["COV-SUPPORT"], "outcome": "source_captured", "related_handoff_output_ids": ["EVC-DR-001"], "source_capture_ids": ["CAP-DR-001"]}, {"trace_entry_id": "STR-2", "strategy": "opposing search", "coverage_dimension_ids": ["COV-OPPOSE"], "outcome": "no_relevant_source", "related_handoff_output_ids": ["GAP-DR-001"], "source_capture_ids": []}], "unsuccessful_entry_ids": ["STR-2"]},
            "null_results": [{"null_id": "NULL-DR-001", "statement": "No relevant opposing source was found.", "question_ids": ["RQ-1"], "handoff_projection": {"output_kind": "observation", "output_id": "OBS-DR-NULL"}}],
            "evidence_gap_assessments": [{"gap_id": "GAP-DR-001", "materiality": "material", "coverage_dimension_ids": ["COV-OPPOSE"], "rationale": "Opposing coverage remains missing."}],
            "coverage_assessment": {"dimensions": [{"dimension_id": "COV-SUPPORT", "status": "covered", "trace_entry_ids": ["STR-1"], "rationale": "Captured."}, {"dimension_id": "COV-OPPOSE", "status": "uncovered", "trace_entry_ids": ["STR-2"], "rationale": "Explicit null."}], "saturation": {"level": "medium", "rationale": "Partial saturation only."}, "remaining_information_value": {"level": "high", "rationale": "A material gap remains."}, "stopping_recommendation": {"stop_recommended": False, "basis": ["coverage", "saturation", "evidence_gaps", "remaining_information_value"], "rationale": "Continue retrieval.", "research_completion_claimed": False, "human_decision_performed": False}},
            "candidate_next_method_ids": ["NM-DR-001"], "extension_digest": "sha256:" + "0" * 64,
        }
        cls.result_extension["extension_digest"] = digest(cls.result_extension, "extension_digest")

    def assert_valid(self, schema, document):
        errors = list(Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(document))
        self.assertFalse(errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors))

    def test_descriptor_uses_only_pr9_wire_contracts_and_all_execution_modes(self):
        self.assert_valid(self.descriptor_schema, self.descriptor)
        self.assertEqual(self.descriptor["descriptor_digest"], digest(self.descriptor, "descriptor_digest"))
        function = self.descriptor["declared_functions"][0]
        self.assertEqual(function["input_contract"], "capability-context-pack@0.1.0")
        self.assertEqual(function["output_contract"], "capability-handoff@0.1.0")
        self.assertEqual(set(function["supported_execution_modes"]), {"real", "virtual", "synthetic_test"})
        self.assertTrue(self.semantics["handoff"]["second_desktop_research_handoff_forbidden"])

    def test_context_extension_is_exact_bound_bounded_and_quality_neutral(self):
        self.assert_valid(self.context_schema, self.context_extension)
        self.assertEqual(self.context_extension["extension_digest"], digest(self.context_extension, "extension_digest"))
        self.assertEqual(set(x["reference_id"] for x in self.context_extension["resource_role_bindings"]), set(x["reference_id"] for x in self.context["resources"]))
        self.assertTrue({"writer_material", "publication_material", "publication_feedback", "archive_provenance"}.issubset(self.context_extension["forbidden_resource_roles"]))
        serialized = json.dumps(self.context_schema)
        self.assertNotIn("quality_tier", serialized)
        self.assertNotIn("source_quality", serialized)
        self.assertFalse(self.semantics["quality_boundary"]["source_type_to_quality_tier_matrix_canonicalized"])

    def test_question_candidate_target_is_explicitly_non_authoritative(self):
        candidate = deepcopy(self.context_extension)
        candidate["target"] = {"target_type": "question_candidate", "question_candidate_id": "RQ-SEED-001", "statement": "Candidate only.", "source_attention_id": "ATT-FIXTURE-001", "related_question_ids": ["RQ-1"], "authoritative_question": False}
        candidate["extension_digest"] = digest(candidate, "extension_digest")
        self.assert_valid(self.context_schema, candidate)
        bad = deepcopy(candidate); bad["target"]["authoritative_question"] = True; bad["extension_digest"] = digest(bad, "extension_digest")
        self.assertTrue(list(Draft202012Validator(self.context_schema).iter_errors(bad)))

    def test_result_extension_preserves_provenance_negative_search_gap_and_stopping_boundary(self):
        self.assert_valid(self.result_schema, self.result_extension)
        self.assertEqual(self.result_extension["extension_digest"], digest(self.result_extension, "extension_digest"))
        citation = self.result_extension["citation_details"][0]
        rendition = self.result_extension["source_capture_details"][0]["text_rendition"]
        self.assertIn(citation["excerpt"], rendition["inline_text"])
        self.assertFalse(citation["evidence_adoption_performed"])
        self.assertEqual(self.result_extension["search_trace"]["unsuccessful_entry_ids"], ["STR-2"])
        self.assertEqual(self.result_extension["evidence_gap_assessments"][0]["materiality"], "material")
        stop = self.result_extension["coverage_assessment"]["stopping_recommendation"]
        self.assertFalse(stop["stop_recommended"]); self.assertFalse(stop["research_completion_claimed"]); self.assertFalse(stop["human_decision_performed"])
        self.assertNotEqual(set(stop["basis"]), {"source_count"})

    def test_result_schema_cannot_claim_adoption_completion_or_human_decision(self):
        for path in (("citation_details", 0, "evidence_adoption_performed"), ("coverage_assessment", "stopping_recommendation", "research_completion_claimed"), ("coverage_assessment", "stopping_recommendation", "human_decision_performed")):
            bad = deepcopy(self.result_extension); cursor = bad
            for part in path[:-1]: cursor = cursor[part]
            cursor[path[-1]] = True; bad["extension_digest"] = digest(bad, "extension_digest")
            self.assertTrue(list(Draft202012Validator(self.result_schema).iter_errors(bad)))

    def test_pr10_routing_fixture_targets_pr9_invocation_not_a_desktop_wire_format(self):
        proposal = self.routing["action_proposal"]
        self.assert_valid(self.conversation_schema, proposal)
        self.assertEqual(proposal["proposal_digest"], digest(proposal, "proposal_digest"))
        self.assertEqual(proposal["action"]["payload_digest"], "sha256:" + hashlib.sha256(rfc8785.dumps(proposal["action"]["payload"])).hexdigest())
        self.assertEqual(proposal["route"]["invocation_contract"], "capability-invocation@0.1.0")
        self.assertEqual(proposal["route"]["capability"]["capability_id"], "desktop-research")
        self.assertNotIn("runtime_authorization_evidence", proposal["route"])
        self.assertEqual(proposal["commitment_mode"], "proposal_only")

    def test_legacy_source_quality_matrix_is_not_promoted(self):
        self.assertEqual(self.semantics["quality_boundary"]["source_quality_owned_by"], "research_profile")
        self.assertEqual(self.semantics["quality_boundary"]["causal_support_owned_by"], "research_profile")
        self.assertFalse(self.semantics["quality_boundary"]["writer_publication_material_is_research_evidence"])
        self.assertEqual(self.semantics["quality_boundary"]["execution_mode_epistemic_boundary_owned_by"], "capability-handoff@0.1.0")


if __name__ == "__main__":
    unittest.main()
