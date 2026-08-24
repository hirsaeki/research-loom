from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages/survey"
FIX = ROOT / "core/fixtures/capabilities/valid/generic-survey-contract-fixtures.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SurveyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design_schema = load(PKG / "survey-design.schema.json")
        cls.contract_schema = load(PKG / "survey-contract.schema.json")
        cls.fixtures = load(FIX)
        cls.semantics = yaml.safe_load((PKG / "survey-semantics.yaml").read_text(encoding="utf-8"))

    def test_schemas_are_draft_2020_12(self):
        Draft202012Validator.check_schema(self.design_schema)
        Draft202012Validator.check_schema(self.contract_schema)

    def test_questionnaire_fixture_and_item_types(self):
        questionnaire = self.fixtures["questionnaire"]
        errors = list(Draft202012Validator(self.contract_schema, format_checker=FormatChecker()).iter_errors(questionnaire))
        self.assertEqual(errors, [])
        self.assertEqual(
            {item["question_type"] for item in questionnaire["questions"]},
            {"single_choice", "multiple_choice", "scale", "numeric", "free_text"},
        )
        self.assertEqual(len({item["question_id"] for item in questionnaire["questions"]}), len(questionnaire["questions"]))
        self.assertTrue(all(any(item["traceability"].values()) for item in questionnaire["questions"]))
        self.assertEqual(questionnaire["approval_status"], "approved")
        self.assertIn("approval_decision_id", questionnaire)

    def test_real_partial_synthetic_and_analysis_fixtures_validate(self):
        validator = Draft202012Validator(self.contract_schema, format_checker=FormatChecker())
        for name in ("real", "partial_nonresponse", "synthetic_test", "analysis"):
            self.assertEqual(list(validator.iter_errors(self.fixtures[name])), [], name)

    def test_response_and_sufficiency_boundaries(self):
        real = self.fixtures["real"]
        self.assertTrue(all(item["verified_evidence_claimed"] is False for item in real["responses"]))
        self.assertFalse(real["research_sufficiency_claimed"])
        partial = self.fixtures["partial_nonresponse"]
        self.assertTrue(partial["missing_data_preserved"])
        self.assertGreater(partial["sample_disposition"]["nonresponse_count"], 0)
        self.assertGreater(partial["sample_disposition"]["dropout_count"], 0)
        self.assertGreater(partial["sample_disposition"]["excluded_response_count"], 0)
        self.assertGreater(partial["sample_disposition"]["duplicate_flagged_count"], 0)

    def test_synthetic_test_never_claims_empirical_response(self):
        synthetic = self.fixtures["synthetic_test"]
        self.assertEqual(synthetic["execution_mode"], "synthetic_test")
        self.assertTrue(all(item["epistemic_mode"] == "synthetic" for item in synthetic["responses"]))
        self.assertFalse(synthetic["synthetic_responses_may_be_empirical"])
        self.assertFalse(synthetic["synthetic_respondent_semantics_defined_here"])

    def test_analysis_preserves_denominators_and_candidate_authority(self):
        analysis = self.fixtures["analysis"]
        for item in analysis["item_summaries"]:
            self.assertEqual(
                item["denominator_count"],
                item["answered_count"] + item["missing_count"] + item["excluded_count"],
            )
        self.assertTrue(analysis["aggregation_provenance"])
        self.assertTrue(analysis["subgroup_provenance"])
        self.assertTrue(analysis["free_text_coding_refs"])
        self.assertFalse(analysis["aggregate_is_finding"])
        self.assertFalse(analysis["core_analysis_adoption_performed"])
        self.assertFalse(analysis["finding_adoption_performed"])

    def test_semantic_boundaries_are_explicit(self):
        self.assertEqual(self.semantics["capability"]["research_method_contract"], "research-method@0.1.0")
        self.assertFalse(self.semantics["capability"]["pr9_context_or_handoff_redefined"])
        self.assertFalse(self.semantics["capability"]["pr12_method_envelopes_redefined"])
        self.assertFalse(self.semantics["instrument"]["questionnaire_is_core_method"])
        self.assertFalse(self.semantics["instrument"]["generation_is_instrument_approval"])
        self.assertTrue(self.semantics["instrument"]["material_questionnaire_revision_requires_human_decision"])
        self.assertFalse(self.semantics["execution"]["response_is_verified_evidence"])
        self.assertFalse(self.semantics["analysis"]["aggregate_or_statistic_is_finding"])
        self.assertFalse(self.semantics["routing"]["survey_selects_next_method"])
        self.assertFalse(self.semantics["conversation_boundary"]["confirmation_is_human_decision"])
        errors = self.semantics["errors"]
        self.assertEqual(len(errors), len({item["id"] for item in errors}))


if __name__ == "__main__":
    unittest.main()
