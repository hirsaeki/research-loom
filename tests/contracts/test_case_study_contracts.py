from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from case_study_oracle import CASE_ERROR_CODES, context_error, descriptor_error, design_error, protocol_error, result_error
from research_method_oracle import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
CASE = PKG / "case-study"
FIX = ROOT / "core/fixtures/capabilities/valid"
CONV = ROOT / "core/fixtures/conversation/valid"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixtures():
    merged = {}
    for name in (
        "generic-case-study-design-fixtures.json",
        "generic-case-study-protocol-fixtures.json",
        "generic-case-study-within-case-fixtures.json",
        "generic-case-study-cross-case-fixtures.json",
        "generic-case-study-mode-fixtures.json",
    ):
        merged.update(load(FIX / name))
    return merged


class CaseStudyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.descriptor_schema = load(PKG / "capability-descriptor.schema.json")
        cls.schema = load(CASE / "case-study-contract.schema.json")
        cls.design_schema = load(CASE / "case-study-design.schema.json")
        cls.conversation_schema = load(PKG / "work-conversation.schema.json")
        cls.descriptor = load(FIX / "generic-case-study-capability-descriptor.json")
        cls.fixtures = load_fixtures()
        cls.routing = load(CONV / "case-study-routing.json")
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def test_schemas_semantics_descriptor_and_error_catalog(self):
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator.check_schema(self.design_schema)
        self.assertEqual(list(Draft202012Validator(self.descriptor_schema).iter_errors(self.descriptor)), [])
        self.assertIsNone(descriptor_error(self.descriptor))
        semantics = yaml.safe_load((CASE / "case-study-semantics.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(semantics["errors"]), CASE_ERROR_CODES)
        self.assertFalse(semantics["capability"]["pr9_context_or_handoff_redefined"])
        self.assertFalse(semantics["capability"]["pr12_method_envelopes_redefined"])
        self.assertTrue(semantics["capability"]["harness_is_only_authoritative_write_boundary"])
        self.assertFalse(semantics["analysis_boundary"]["recurring_pattern_is_causal_mechanism"])
        self.assertFalse(semantics["analysis_boundary"]["sequence_consistency_is_causal_proof"])
        self.assertFalse(semantics["analysis_boundary"]["cross_case_similarity_is_generalizability"])
        self.assertFalse(semantics["epistemic_boundary"]["virtual_content_may_be_promoted_to_real_observation"])
        self.assertFalse(semantics["routing"]["case_study_handoff_wire_format_defined"])

    def test_single_and_comparative_designs(self):
        for name in ("single_case_design", "comparative_multi_case_design"):
            design = self.fixtures[name]
            self.assertEqual(list(Draft202012Validator(self.design_schema).iter_errors(design)), [])
            self.assertEqual(design["content_digest"], canonical_digest(design, "content_digest"))
            self.assertEqual(design["case_boundary"]["content_digest"], canonical_digest(design["case_boundary"], "content_digest"))
            self.assertIsNone(design_error(design))
            self.assertFalse(design["selection"]["selected_cases_are_population_sample"])
            self.assertFalse(design["stopping"]["fixed_case_count_alone_is_sufficient"])
        self.assertFalse(self.fixtures["single_case_design"]["analysis_intent"]["cross_case"])
        self.assertTrue(self.fixtures["comparative_multi_case_design"]["analysis_intent"]["cross_case"])

    def test_invalid_boundary_selection_and_representativeness_fail(self):
        design = deepcopy(self.fixtures["single_case_design"])
        design["case_boundary"]["definition"] = "mutated after digest"
        design["content_digest"] = canonical_digest(design, "content_digest")
        self.assertEqual(design_error(design), "CASE-BOUNDARY-001")

        convenience = deepcopy(self.fixtures["single_case_design"])
        convenience["selection"]["strategy"] = "theoretical_purposive"
        convenience["selection"]["convenience_only"] = True
        convenience["content_digest"] = canonical_digest(convenience, "content_digest")
        self.assertEqual(design_error(convenience), "CASE-SELECTION-001")

        representative = deepcopy(self.fixtures["single_case_design"])
        representative["selection"]["selected_cases_are_population_sample"] = True
        representative["content_digest"] = canonical_digest(representative, "content_digest")
        self.assertEqual(design_error(representative), "CASE-REPRESENTATIVENESS-001")

    def test_case_protocol_is_instrument_specialization(self):
        protocol = self.fixtures["case_protocol"]
        self.assertEqual(list(self.validator.iter_errors(protocol)), [])
        self.assertEqual(protocol["content_digest"], canonical_digest(protocol, "content_digest"))
        self.assertIsNone(protocol_error(protocol))
        self.assertEqual(protocol["object_type"], "case_protocol")
        self.assertIn("within_case", protocol["coding_schemes"])
        self.assertIn("cross_case", protocol["coding_schemes"])

        approved_without_decision = deepcopy(protocol)
        approved_without_decision.pop("approval_decision_id")
        self.assertTrue(list(self.validator.iter_errors(approved_without_decision)))

        untraceable = deepcopy(protocol)
        untraceable["fields"][0]["traceability"] = {"research_question_ids": [], "evidence_gap_refs": [], "construct_ids": []}
        untraceable["content_digest"] = canonical_digest(untraceable, "content_digest")
        self.assertEqual(protocol_error(untraceable), "CASE-PROTOCOL-TRACE-001")

    def test_real_context_pins_design_protocol_boundary_and_fails_closed(self):
        context = self.fixtures["execute_context_real"]
        design = self.fixtures["single_case_design"]
        protocol = self.fixtures["case_protocol"]
        self.assertEqual(list(self.validator.iter_errors(context)), [])
        self.assertIsNone(context_error(context, design, protocol))

        missing_auth = deepcopy(context)
        missing_auth["runtime_authorized"] = False
        missing_auth["extension_digest"] = canonical_digest(missing_auth, "extension_digest")
        self.assertEqual(context_error(missing_auth, design, protocol), "CASE-BLOCKED-001")

        boundary_mutation = deepcopy(context)
        boundary_mutation["case_boundary_pins"][0]["boundary_digest"] = "sha256:" + "f" * 64
        boundary_mutation["extension_digest"] = canonical_digest(boundary_mutation, "extension_digest")
        self.assertEqual(context_error(boundary_mutation, design, protocol), "CASE-BOUNDARY-001")

        blocked = self.fixtures["blocked_invalid_boundary"]
        self.assertEqual(list(self.validator.iter_errors(blocked)), [])
        self.assertFalse(blocked["capability_filled_missing_inputs"])
        self.assertFalse(blocked["authoritative_state_changed"])

    def test_real_within_case_preserves_fact_interpretation_boundary(self):
        result = self.fixtures["valid_real_within_case_execution"]
        self.assertEqual(list(self.validator.iter_errors(result)), [])
        self.assertIsNone(result_error(result, self.fixtures["single_case_design"], self.fixtures["case_protocol"]))
        observations = result["case_runs"][0]["observations"]
        interpretation = next(item for item in observations if item["observation_kind"] == "researcher_interpretation")
        self.assertEqual(interpretation["assertion_role"], "researcher_interpretation")
        self.assertTrue(interpretation["source_observation_refs"])
        self.assertFalse(result["raw_observation_is_verified_evidence"])
        self.assertFalse(result["coding_label_is_finding"])
        self.assertFalse(result["finding_adoption_performed"])

    def test_incomplete_case_preserves_access_failure_and_missingness(self):
        result = self.fixtures["incomplete_inaccessible_source_case"]
        self.assertEqual(list(self.validator.iter_errors(result)), [])
        self.assertIsNone(result_error(result, self.fixtures["single_case_design"], self.fixtures["case_protocol"]))
        run = result["case_runs"][0]
        self.assertTrue(run["access_failures"])
        self.assertTrue(run["missingness"])
        self.assertTrue(run["unavailable_sources"])
        self.assertTrue(run["unresolved_ambiguities"])

        erased = deepcopy(result)
        for key in ("access_failures", "missingness", "protocol_deviations", "exclusions", "unavailable_sources", "unresolved_ambiguities"):
            erased["case_runs"][0][key] = []
        erased["extension_digest"] = canonical_digest(erased, "extension_digest")
        self.assertEqual(result_error(erased, self.fixtures["single_case_design"], self.fixtures["case_protocol"]), "CASE-MISSINGNESS-001")

    def test_negative_contradictory_observation_cannot_disappear(self):
        result = self.fixtures["negative_contradictory_observation_case"]
        self.assertEqual(list(self.validator.iter_errors(result)), [])
        self.assertIsNone(result_error(result, self.fixtures["single_case_design"], self.fixtures["case_protocol"]))
        self.assertIn("OBS-A4", result["within_case_analyses"][0]["negative_observation_refs"])
        self.assertFalse(result["triangulation_assessment"]["conflicts"][0]["resolved"])

        erased = deepcopy(result)
        erased["within_case_analyses"][0]["negative_observation_refs"] = []
        erased["extension_digest"] = canonical_digest(erased, "extension_digest")
        self.assertEqual(result_error(erased, self.fixtures["single_case_design"], self.fixtures["case_protocol"]), "CASE-NEGATIVE-DEVIANT-001")

    def test_cross_case_preserves_deviant_case_provenance_and_information_value(self):
        result = self.fixtures["cross_case_comparison"]
        design = self.fixtures["comparative_multi_case_design"]
        self.assertEqual(list(self.validator.iter_errors(result)), [])
        self.assertIsNone(result_error(result, design, self.fixtures["case_protocol"]))
        analysis = result["cross_case_analyses"][0]
        self.assertEqual(set(analysis["case_ids"]), {"CASE-A", "CASE-B", "CASE-C"})
        self.assertIn("CASE-C", analysis["negative_deviant_case_ids"])
        self.assertTrue(all(item["observation_refs"] for item in analysis["case_values"]))
        self.assertTrue(analysis["missing_incomparable_dimensions"])
        self.assertTrue(result["stopping_assessment"]["remaining_information_value"])
        self.assertEqual(self.fixtures["deviant_negative_case_preservation_ref"], "cross_case_comparison")

        dropped = deepcopy(result)
        dropped["cross_case_analyses"][0]["negative_deviant_case_ids"] = []
        dropped["extension_digest"] = canonical_digest(dropped, "extension_digest")
        self.assertEqual(result_error(dropped, design, self.fixtures["case_protocol"]), "CASE-NEGATIVE-DEVIANT-001")

    def test_triangulation_does_not_inflate_same_primary_source(self):
        result = deepcopy(self.fixtures["valid_real_within_case_execution"])
        duplicate = deepcopy(result["case_runs"][0]["observations"][0])
        duplicate["observation_id"] = "OBS-A1-B"
        duplicate["locator"] = "p.13"
        result["case_runs"][0]["observations"].append(duplicate)
        result["extension_digest"] = canonical_digest(result, "extension_digest")
        self.assertIsNone(result_error(result, self.fixtures["single_case_design"], self.fixtures["case_protocol"]))

        inflated = deepcopy(result)
        inflated["triangulation_assessment"]["claimed_independent_source_count"] = 3
        inflated["extension_digest"] = canonical_digest(inflated, "extension_digest")
        self.assertEqual(result_error(inflated, self.fixtures["single_case_design"], self.fixtures["case_protocol"]), "CASE-TRIANGULATION-001")

    def test_virtual_and_synthetic_test_never_become_empirical(self):
        for name, mode in (("virtual_execution", "virtual"), ("synthetic_test", "synthetic_test")):
            result = self.fixtures[name]
            self.assertEqual(list(self.validator.iter_errors(result)), [])
            self.assertIsNone(result_error(result, self.fixtures["single_case_design"], self.fixtures["case_protocol"]))
            self.assertEqual(result["execution_mode"], mode)
            self.assertFalse(result["virtual_content_may_be_empirical"])

        promoted = deepcopy(self.fixtures["virtual_execution"])
        promoted["case_runs"][0]["observations"][0]["epistemic_mode"] = "empirical"
        promoted["extension_digest"] = canonical_digest(promoted, "extension_digest")
        self.assertEqual(result_error(promoted, self.fixtures["single_case_design"], self.fixtures["case_protocol"]), "CASE-EPISTEMIC-MODE-001")

    def test_pattern_sequence_similarity_do_not_become_causal_or_generalizable(self):
        result = deepcopy(self.fixtures["valid_real_within_case_execution"])
        result["recurring_pattern_is_causal_mechanism"] = True
        result["extension_digest"] = canonical_digest(result, "extension_digest")
        self.assertEqual(result_error(result, self.fixtures["single_case_design"], self.fixtures["case_protocol"]), "CASE-CAUSAL-BOUNDARY-001")

        cross = deepcopy(self.fixtures["cross_case_comparison"])
        cross["cross_case_analyses"][0]["similarity_difference_candidates"][0]["generalizability_claimed"] = True
        cross["extension_digest"] = canonical_digest(cross, "extension_digest")
        self.assertEqual(result_error(cross, self.fixtures["comparative_multi_case_design"], self.fixtures["case_protocol"]), "CASE-CAUSAL-BOUNDARY-001")

    def test_stopping_is_candidate_not_research_completion(self):
        result = self.fixtures["cross_case_comparison"]
        stop = result["stopping_assessment"]
        self.assertTrue(stop["additional_case_recommendation"]["recommended"])
        self.assertTrue(stop["remaining_information_value"])
        self.assertFalse(stop["research_completion_claimed"])
        self.assertFalse(stop["human_decision_performed"])

        invalid = deepcopy(result)
        invalid["stopping_assessment"]["remaining_information_value"] = []
        invalid["extension_digest"] = canonical_digest(invalid, "extension_digest")
        self.assertEqual(result_error(invalid, self.fixtures["comparative_multi_case_design"], self.fixtures["case_protocol"]), "CASE-STOPPING-001")

    def test_pr10_routing_preserves_pr9_pr12_and_human_decision_boundary(self):
        proposal = self.routing["action_proposal"]
        validator = Draft202012Validator(self.conversation_schema, format_checker=FormatChecker())
        self.assertEqual(list(validator.iter_errors(proposal)), [])
        self.assertEqual(proposal["commitment_mode"], "proposal_only")
        self.assertEqual(proposal["route"]["invocation_contract"], "capability-invocation@0.1.0")
        self.assertEqual(proposal["route"]["capability"]["descriptor_digest"], self.descriptor["descriptor_digest"])
        self.assertEqual(proposal["route"]["capability"]["function_id"], "execute")
        self.assertFalse(proposal["human_decision_boundary"]["confirmation_is_human_decision"])
        self.assertIn("DEC-PROT-1", proposal["human_decision_boundary"]["decision_reference_ids"])


if __name__ == "__main__":
    unittest.main()
