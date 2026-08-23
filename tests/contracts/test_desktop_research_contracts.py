from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import unittest
from pathlib import Path

import rfc8785
import yaml
from jsonschema import Draft202012Validator

from desktop_research_oracle import (
    canonical_digest,
    context_semantic_error,
    expected_context_extension_digest,
    expected_result_extension_digest,
    result_semantic_error,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = ROOT / "tests/contracts/desktop_research_oracle.py"
PKG = ROOT / "core/packages"
DR = PKG / "desktop-research"
CONTEXT_PATH = (
    ROOT
    / "core/fixtures/capabilities/valid/generic-capability-context-pack.json"
)
HANDOFF_PATH = ROOT / "core/fixtures/capabilities/valid/generic-capability-handoff.json"
ROUTING_PATH = (
    ROOT / "core/fixtures/conversation/valid/desktop-research-routing.json"
)


def refresh_extension_digest(document):
    """Refresh one Desktop Research extension digest in place."""
    document["extension_digest"] = canonical_digest(document, "extension_digest")


def build_context_extension(context):
    """Build the valid synthetic Desktop Research Context extension fixture."""
    extension = {
        "schema_version": "0.1.0",
        "extension_type": "desktop_research_context",
        "context_binding": {
            "context_pack_id": context["context_pack_id"],
            "context_pack_digest": context["context_pack_digest"],
            "project_id": context["project_id"],
        },
        "target": {
            "target_type": "research_question",
            "question_id": "RQ-1",
        },
        "retrieval_scope": {
            "scope_statement": "Bounded contract-fixture retrieval.",
            "in_scope": ["source discovery and capture"],
            "out_of_scope": ["Writer and Publication evidence"],
        },
        "allowed_source_categories": [
            "peer_reviewed_research",
            "government_primary",
            "other",
        ],
        "resource_role_bindings": [
            {
                "reference_id": "REF-INPUT-001",
                "role": "research_context",
            },
            {
                "reference_id": "REF-SOURCE-001",
                "role": "candidate_source",
            },
            {
                "reference_id": "REF-ARTIFACT-001",
                "role": "research_artifact",
            },
        ],
        "forbidden_resource_roles": [
            "writer_material",
            "publication_material",
            "publication_feedback",
            "archive_provenance",
        ],
        "coverage_dimensions": [
            {
                "dimension_id": "COV-SUPPORT",
                "label": "Supporting material",
                "required": True,
            },
            {
                "dimension_id": "COV-OPPOSE",
                "label": "Opposing material",
                "required": True,
            },
        ],
        "budget": {
            "max_total_resources": 3,
            "max_candidate_source_resources": 1,
            "max_artifact_resources": 1,
            "max_acquired_source_captures": 2,
            "max_search_trace_entries": 4,
            "max_text_rendition_bytes": 4096,
        },
        "extension_digest": "sha256:" + "0" * 64,
    }
    refresh_extension_digest(extension)
    return extension


def build_desktop_handoff(generic_handoff, descriptor, context):
    """Build a schema-valid PR9 Handoff for Desktop Research regression tests."""
    handoff = deepcopy(generic_handoff)
    original_digest = "sha256:" + "2" * 64
    invocation_digest = "sha256:" + "3" * 64
    handoff["handoff_id"] = "HND-DR-001"
    handoff["invocation_id"] = "INV-DR-001"
    handoff["run_id"] = "RUN-DR-001"
    handoff["project_id"] = context["project_id"]
    handoff["capability"] = {
        "capability_id": descriptor["capability_id"],
        "capability_version": descriptor["capability_version"],
        "descriptor_digest": descriptor["descriptor_digest"],
        "function_id": "investigate",
    }
    handoff["execution_mode"] = "synthetic_test"
    handoff["input_pins"]["invocation_digest"] = invocation_digest
    handoff["input_pins"]["context_pack_digest"] = context["context_pack_digest"]
    handoff["outputs"] = {
        "observations": [
            {
                "observation_id": "OBS-DR-NULL",
                "statement": "No relevant opposing source was found.",
                "epistemic_mode": "synthetic",
            }
        ],
        "source_captures": [
            {
                "capture_id": "CAP-DR-001",
                "origin": {
                    "origin_type": "acquired_source",
                    "acquisition_locator": "fixture://source",
                },
                "locator": "fixture://source#exact",
                "content_digest": original_digest,
            }
        ],
        "evidence_candidates": [
            {
                "evidence_candidate_id": "EVC-DR-001",
                "statement": "Synthetic candidate from the captured source.",
                "source_basis": {
                    "basis_type": "source_capture",
                    "capture_id": "CAP-DR-001",
                },
                "locator": "fixture://source#excerpt",
                "epistemic_mode": "synthetic",
                "limitations": ["Synthetic test material only."],
            }
        ],
        "candidate_findings": [],
        "counterevidence": [],
        "conflicts": [],
        "unknowns": [],
        "evidence_gaps": [
            {
                "gap_id": "GAP-DR-001",
                "statement": "Opposing coverage remains missing.",
                "question_ids": ["RQ-1"],
            }
        ],
        "candidate_next_actions": [],
        "candidate_next_methods": [
            {
                "proposal_id": "NM-DR-001",
                "method_family": "fixture-follow-up",
                "rationale": "A later method may address the material gap.",
                "status": "candidate",
            }
        ],
    }
    handoff["provenance"] = {
        "trace_id": "TRACE-DR-001",
        "produced_at": "2026-08-24T00:00:01Z",
        "implementation_id": "plugin.fixture.desktop-research",
        "implementation_version": "0.1.0",
        "input_content_digests": [
            descriptor["descriptor_digest"],
            context["context_pack_digest"],
            invocation_digest,
        ],
    }
    handoff["handoff_digest"] = canonical_digest(handoff, "handoff_digest")
    return handoff


def build_result_extension(context, handoff):
    """Build the valid synthetic Desktop Research result extension fixture."""
    text = "Synthetic captured text containing an exact excerpt for citation."
    encoded_text = text.encode("utf-8")
    text_digest = "sha256:" + hashlib.sha256(encoded_text).hexdigest()
    extension = {
        "schema_version": "0.1.0",
        "extension_type": "desktop_research_result",
        "handoff_binding": {
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff["handoff_digest"],
            "invocation_id": handoff["invocation_id"],
            "run_id": handoff["run_id"],
            "context_pack_id": context["context_pack_id"],
            "context_pack_digest": context["context_pack_digest"],
            "capability_id": handoff["capability"]["capability_id"],
            "function_id": handoff["capability"]["function_id"],
        },
        "source_capture_details": [
            {
                "capture_id": "CAP-DR-001",
                "source_category": "other",
                "exact_locator": "fixture://source#exact",
                "acquired_at": "2026-08-24T00:00:00Z",
                "original_capture": {
                    "content_reference": "capture://original",
                    "content_digest": "sha256:" + "2" * 64,
                    "media_type": "application/octet-stream",
                    "byte_length": 64,
                },
                "text_rendition": {
                    "content_reference": "capture://text",
                    "content_digest": text_digest,
                    "media_type": "text/plain",
                    "byte_length": len(encoded_text),
                    "encoding": "UTF-8",
                    "inline_text": text,
                },
            }
        ],
        "citation_details": [
            {
                "citation_id": "CIT-DR-001",
                "handoff_output_kind": "evidence_candidate",
                "handoff_output_id": "EVC-DR-001",
                "capture_id": "CAP-DR-001",
                "excerpt": "exact excerpt",
                "excerpt_locator": "fixture://source#excerpt",
                "text_rendition_digest": text_digest,
                "capture_integrity_verified": True,
                "excerpt_containment_verified": True,
                "evidence_adoption_performed": False,
            }
        ],
        "search_trace": {
            "entries": [
                {
                    "trace_entry_id": "STR-1",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "outcome": "source_captured",
                    "related_handoff_output_ids": ["EVC-DR-001"],
                    "source_capture_ids": ["CAP-DR-001"],
                },
                {
                    "trace_entry_id": "STR-2",
                    "strategy": "opposing search",
                    "coverage_dimension_ids": ["COV-OPPOSE"],
                    "outcome": "no_relevant_source",
                    "related_handoff_output_ids": ["GAP-DR-001"],
                    "source_capture_ids": [],
                },
            ],
            "unsuccessful_entry_ids": ["STR-2"],
        },
        "null_results": [
            {
                "null_id": "NULL-DR-001",
                "statement": "No relevant opposing source was found.",
                "question_ids": ["RQ-1"],
                "handoff_projection": {
                    "output_kind": "observation",
                    "output_id": "OBS-DR-NULL",
                },
            }
        ],
        "evidence_gap_assessments": [
            {
                "gap_id": "GAP-DR-001",
                "materiality": "material",
                "coverage_dimension_ids": ["COV-OPPOSE"],
                "rationale": "Opposing coverage remains missing.",
            }
        ],
        "coverage_assessment": {
            "dimensions": [
                {
                    "dimension_id": "COV-SUPPORT",
                    "status": "covered",
                    "trace_entry_ids": ["STR-1"],
                    "rationale": "Captured.",
                },
                {
                    "dimension_id": "COV-OPPOSE",
                    "status": "uncovered",
                    "trace_entry_ids": ["STR-2"],
                    "rationale": "Explicit null.",
                },
            ],
            "saturation": {
                "level": "medium",
                "rationale": "Partial saturation only.",
            },
            "remaining_information_value": {
                "level": "high",
                "rationale": "A material gap remains.",
            },
            "stopping_recommendation": {
                "stop_recommended": False,
                "basis": [
                    "coverage",
                    "saturation",
                    "evidence_gaps",
                    "remaining_information_value",
                ],
                "rationale": "Continue retrieval.",
                "research_completion_claimed": False,
                "human_decision_performed": False,
            },
        },
        "candidate_next_method_ids": ["NM-DR-001"],
        "extension_digest": "sha256:" + "0" * 64,
    }
    refresh_extension_digest(extension)
    return extension


class DesktopResearchContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load canonical contracts and construct one cross-document valid chain."""
        cls.descriptor_schema = json.loads(
            (PKG / "capability-descriptor.schema.json").read_text()
        )
        cls.handoff_schema = json.loads(
            (PKG / "capability-handoff.schema.json").read_text()
        )
        cls.conversation_schema = json.loads(
            (PKG / "work-conversation.schema.json").read_text()
        )
        cls.context_schema = json.loads(
            (DR / "desktop-research-context-extension.schema.json").read_text()
        )
        cls.result_schema = json.loads(
            (DR / "desktop-research-result-extension.schema.json").read_text()
        )
        cls.descriptor = json.loads(
            (DR / "desktop-research-capability-descriptor.json").read_text()
        )
        cls.context = json.loads(CONTEXT_PATH.read_text())
        cls.generic_handoff = json.loads(HANDOFF_PATH.read_text())
        cls.routing = json.loads(ROUTING_PATH.read_text())
        cls.semantics = yaml.safe_load(
            (DR / "desktop-research-semantics.yaml").read_text()
        )
        cls.context_extension = build_context_extension(cls.context)
        cls.handoff = build_desktop_handoff(
            cls.generic_handoff,
            cls.descriptor,
            cls.context,
        )
        cls.result_extension = build_result_extension(cls.context, cls.handoff)

    def assert_valid(self, schema, document):
        """Assert Draft 2020-12 structural validity with format checks."""
        validator = Draft202012Validator(
            schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = list(validator.iter_errors(document))
        self.assertFalse(
            errors,
            "\n".join(f"{list(error.path)}: {error.message}" for error in errors),
        )

    def assert_context_semantic_error(self, document, expected):
        """Assert a schema-valid Context mutation fails with one stable code."""
        refresh_extension_digest(document)
        self.assert_valid(self.context_schema, document)
        self.assertEqual(
            expected,
            context_semantic_error(document, self.context),
        )

    def assert_result_semantic_error(self, document, expected):
        """Assert a schema-valid result mutation fails with one stable code."""
        refresh_extension_digest(document)
        self.assert_valid(self.result_schema, document)
        self.assertEqual(
            expected,
            result_semantic_error(
                document,
                self.context_extension,
                self.context,
                self.handoff,
            ),
        )

    def test_schemas_and_cross_document_fixture_are_valid(self):
        """Validate the structural schemas and the semantic fixture chain."""
        for schema in (
            self.descriptor_schema,
            self.handoff_schema,
            self.conversation_schema,
            self.context_schema,
            self.result_schema,
        ):
            Draft202012Validator.check_schema(schema)
        self.assert_valid(self.descriptor_schema, self.descriptor)
        self.assert_valid(self.handoff_schema, self.handoff)
        self.assert_valid(self.context_schema, self.context_extension)
        self.assert_valid(self.result_schema, self.result_extension)
        self.assertEqual(
            self.context_extension["extension_digest"],
            expected_context_extension_digest(self.context_extension),
        )
        self.assertEqual(
            self.result_extension["extension_digest"],
            expected_result_extension_digest(self.result_extension),
        )
        self.assertIsNone(
            context_semantic_error(self.context_extension, self.context)
        )
        self.assertIsNone(
            result_semantic_error(
                self.result_extension,
                self.context_extension,
                self.context,
                self.handoff,
            )
        )

    def test_descriptor_uses_only_pr9_wire_contracts_and_all_execution_modes(self):
        """Keep the Desktop descriptor on the unmodified PR9 wire ABI."""
        function = self.descriptor["declared_functions"][0]
        self.assertEqual(
            self.descriptor["descriptor_digest"],
            canonical_digest(self.descriptor, "descriptor_digest"),
        )
        self.assertEqual(
            function["input_contract"],
            "capability-context-pack@0.1.0",
        )
        self.assertEqual(
            function["output_contract"],
            "capability-handoff@0.1.0",
        )
        self.assertEqual(
            set(function["supported_execution_modes"]),
            {"real", "virtual", "synthetic_test"},
        )
        self.assertTrue(
            self.semantics["handoff"]["second_desktop_research_handoff_forbidden"]
        )

    def test_context_extension_is_exact_bound_bounded_and_quality_neutral(self):
        """Keep Desktop context bounded without owning PR6 quality policy."""
        bound_ids = {
            item["reference_id"]
            for item in self.context_extension["resource_role_bindings"]
        }
        context_ids = {
            item["reference_id"] for item in self.context["resources"]
        }
        self.assertEqual(bound_ids, context_ids)
        self.assertTrue(
            {
                "writer_material",
                "publication_material",
                "publication_feedback",
                "archive_provenance",
            }.issubset(self.context_extension["forbidden_resource_roles"])
        )
        serialized = json.dumps(self.context_schema)
        self.assertNotIn("quality_tier", serialized)
        self.assertNotIn("source_quality", serialized)
        self.assertFalse(
            self.semantics["quality_boundary"][
                "source_type_to_quality_tier_matrix_canonicalized"
            ]
        )

    def test_question_candidate_target_is_explicitly_non_authoritative(self):
        """Allow candidate targets without giving them Question authority."""
        candidate = deepcopy(self.context_extension)
        candidate["target"] = {
            "target_type": "question_candidate",
            "question_candidate_id": "RQ-SEED-001",
            "statement": "Candidate only.",
            "source_attention_id": "ATT-FIXTURE-001",
            "related_question_ids": ["RQ-1"],
            "authoritative_question": False,
        }
        refresh_extension_digest(candidate)
        self.assert_valid(self.context_schema, candidate)
        self.assertIsNone(context_semantic_error(candidate, self.context))

        bad = deepcopy(candidate)
        bad["target"]["authoritative_question"] = True
        refresh_extension_digest(bad)
        validator = Draft202012Validator(self.context_schema)
        self.assertTrue(list(validator.iter_errors(bad)))

    def test_context_semantics_fail_closed_on_identity_and_resource_roles(self):
        """Reject duplicate identities, missing bindings, and forbidden roles."""
        duplicate_binding = deepcopy(self.context_extension)
        duplicate_binding["resource_role_bindings"].append(
            deepcopy(duplicate_binding["resource_role_bindings"][0])
        )
        self.assert_context_semantic_error(
            duplicate_binding,
            "DR-CONTEXT-IDENTITY-001",
        )

        duplicate_dimension = deepcopy(self.context_extension)
        duplicate_dimension["coverage_dimensions"].append(
            deepcopy(duplicate_dimension["coverage_dimensions"][0])
        )
        self.assert_context_semantic_error(
            duplicate_dimension,
            "DR-CONTEXT-IDENTITY-001",
        )

        forbidden = deepcopy(self.context_extension)
        forbidden["resource_role_bindings"][0]["role"] = "writer_material"
        self.assert_context_semantic_error(
            forbidden,
            "DR-CONTEXT-RESOURCE-ROLE-001",
        )

        missing = deepcopy(self.context_extension)
        missing["resource_role_bindings"].pop()
        self.assert_context_semantic_error(
            missing,
            "DR-CONTEXT-RESOURCE-ROLE-001",
        )

    def test_context_semantics_enforce_desktop_budget(self):
        """Reject a Desktop budget smaller than the bound PR9 resources."""
        bad = deepcopy(self.context_extension)
        bad["budget"]["max_total_resources"] = 2
        self.assert_context_semantic_error(
            bad,
            "DR-CONTEXT-BUDGET-001",
        )

    def test_result_preserves_provenance_negative_search_gap_and_stopping(self):
        """Preserve capture provenance, unsuccessful search, and stop boundaries."""
        citation = self.result_extension["citation_details"][0]
        rendition = self.result_extension["source_capture_details"][0][
            "text_rendition"
        ]
        self.assertIn(citation["excerpt"], rendition["inline_text"])
        self.assertFalse(citation["evidence_adoption_performed"])
        self.assertEqual(
            self.result_extension["search_trace"]["unsuccessful_entry_ids"],
            ["STR-2"],
        )
        self.assertEqual(
            self.result_extension["evidence_gap_assessments"][0]["materiality"],
            "material",
        )
        stop = self.result_extension["coverage_assessment"][
            "stopping_recommendation"
        ]
        self.assertFalse(stop["stop_recommended"])
        self.assertFalse(stop["research_completion_claimed"])
        self.assertFalse(stop["human_decision_performed"])
        self.assertNotEqual(set(stop["basis"]), {"source_count"})

    def test_result_semantics_reject_invalid_cross_document_references(self):
        """Reject invalid capture, output, trace, coverage, and method references."""
        bad_binding = deepcopy(self.result_extension)
        bad_binding["handoff_binding"]["handoff_id"] = "HND-MISSING"
        self.assert_result_semantic_error(
            bad_binding,
            "DR-RESULT-BINDING-001",
        )

        missing_capture = deepcopy(self.result_extension)
        missing_capture["citation_details"][0]["capture_id"] = "CAP-MISSING"
        self.assert_result_semantic_error(
            missing_capture,
            "DR-CITATION-001",
        )

        missing_output = deepcopy(self.result_extension)
        missing_output["citation_details"][0][
            "handoff_output_id"
        ] = "EVC-MISSING"
        self.assert_result_semantic_error(
            missing_output,
            "DR-CITATION-001",
        )

        bad_unsuccessful = deepcopy(self.result_extension)
        bad_unsuccessful["search_trace"]["unsuccessful_entry_ids"] = [
            "STR-MISSING"
        ]
        self.assert_result_semantic_error(
            bad_unsuccessful,
            "DR-SEARCH-TRACE-001",
        )

        bad_search_dimension = deepcopy(self.result_extension)
        bad_search_dimension["search_trace"]["entries"][0][
            "coverage_dimension_ids"
        ] = ["COV-MISSING"]
        self.assert_result_semantic_error(
            bad_search_dimension,
            "DR-SEARCH-TRACE-001",
        )

        bad_coverage_trace = deepcopy(self.result_extension)
        bad_coverage_trace["coverage_assessment"]["dimensions"][0][
            "trace_entry_ids"
        ] = ["STR-MISSING"]
        self.assert_result_semantic_error(
            bad_coverage_trace,
            "DR-COVERAGE-001",
        )

        bad_method = deepcopy(self.result_extension)
        bad_method["candidate_next_method_ids"] = ["NM-MISSING"]
        self.assert_result_semantic_error(
            bad_method,
            "DR-NEXT-METHOD-001",
        )

    def test_result_semantics_reject_contradictory_stopping_recommendations(self):
        """Reject stop recommendations blocked by gaps or information value."""
        material_gap = deepcopy(self.result_extension)
        material_gap["coverage_assessment"]["stopping_recommendation"][
            "stop_recommended"
        ] = True
        self.assert_result_semantic_error(
            material_gap,
            "DR-STOP-GAP-001",
        )

        high_riv = deepcopy(self.result_extension)
        high_riv["evidence_gap_assessments"][0]["materiality"] = "non_material"
        high_riv["coverage_assessment"]["stopping_recommendation"][
            "stop_recommended"
        ] = True
        self.assert_result_semantic_error(
            high_riv,
            "DR-STOP-RIV-001",
        )

        source_count_only = deepcopy(self.result_extension)
        source_count_only["coverage_assessment"]["stopping_recommendation"][
            "basis"
        ] = ["source_count"]
        self.assert_result_semantic_error(
            source_count_only,
            "DR-STOP-BASIS-001",
        )

    def test_result_schema_cannot_claim_adoption_completion_or_human_decision(self):
        """Keep Evidence adoption, completion, and Human Decision out of extension."""
        paths = (
            ("citation_details", 0, "evidence_adoption_performed"),
            (
                "coverage_assessment",
                "stopping_recommendation",
                "research_completion_claimed",
            ),
            (
                "coverage_assessment",
                "stopping_recommendation",
                "human_decision_performed",
            ),
        )
        validator = Draft202012Validator(self.result_schema)
        for path in paths:
            bad = deepcopy(self.result_extension)
            cursor = bad
            for part in path[:-1]:
                cursor = cursor[part]
            cursor[path[-1]] = True
            refresh_extension_digest(bad)
            self.assertTrue(list(validator.iter_errors(bad)))

    def test_pr10_routing_fixture_targets_pr9_invocation_not_desktop_wire_format(self):
        """Keep Conversation routing on the PR9 Invocation contract."""
        proposal = self.routing["action_proposal"]
        self.assert_valid(self.conversation_schema, proposal)
        self.assertEqual(
            proposal["proposal_digest"],
            canonical_digest(proposal, "proposal_digest"),
        )
        expected_payload_digest = "sha256:" + hashlib.sha256(
            rfc8785.dumps(proposal["action"]["payload"])
        ).hexdigest()
        self.assertEqual(
            proposal["action"]["payload_digest"],
            expected_payload_digest,
        )
        self.assertEqual(
            proposal["route"]["invocation_contract"],
            "capability-invocation@0.1.0",
        )
        self.assertEqual(
            proposal["route"]["capability"]["capability_id"],
            "desktop-research",
        )
        self.assertNotIn(
            "runtime_authorization_evidence",
            proposal["route"],
        )
        self.assertEqual(proposal["commitment_mode"], "proposal_only")

    def test_legacy_source_quality_matrix_is_not_promoted(self):
        """Leave source quality and causal support in the PR6 Research Profile."""
        quality = self.semantics["quality_boundary"]
        self.assertEqual(quality["source_quality_owned_by"], "research_profile")
        self.assertEqual(quality["causal_support_owned_by"], "research_profile")
        self.assertFalse(
            quality["writer_publication_material_is_research_evidence"]
        )
        self.assertEqual(
            quality["execution_mode_epistemic_boundary_owned_by"],
            "capability-handoff@0.1.0",
        )

    def test_oracle_error_codes_match_semantics_catalog(self):
        """Keep executable Desktop error IDs synchronized with the catalog."""
        tree = ast.parse(ORACLE_PATH.read_text())
        oracle_codes = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("DR-")
        }
        catalog_codes = {item["id"] for item in self.semantics["errors"]}
        self.assertEqual(oracle_codes, catalog_codes)


if __name__ == "__main__":
    unittest.main()
