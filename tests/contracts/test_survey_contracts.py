from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
SV = PKG / "survey"
FIX = ROOT / "core/fixtures/capabilities/valid"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SurveyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.descriptor_schema = load(PKG / "capability-descriptor.schema.json")
        cls.schema = load(SV / "survey-contract.schema.json")
        cls.design_schema = load(SV / "survey-design.schema.json")
        cls.descriptor = load(FIX / "generic-survey-capability-descriptor.json")
        cls.fixtures = load(FIX / "generic-survey-contract-fixtures.json")

    def test_schemas_and_semantics(self):
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator.check_schema(self.design_schema)
        semantics = yaml.safe_load((SV / "survey-semantics.yaml").read_text(encoding="utf-8"))
        self.assertEqual(semantics["capability"]["research_method_contract"], "research-method@0.1.0")
        self.assertFalse(semantics["capability"]["pr9_context_or_handoff_redefined"])
        self.assertFalse(semantics["instrument"]["questionnaire_is_core_method"])
        self.assertFalse(semantics["instrument"]["generation_is_instrument_approval"])
        self.assertFalse(semantics["execution"]["response_is_verified_evidence"])
        self.assertFalse(semantics["analysis"]["aggregate_or_statistic_is_finding"])
        self.assertFalse(semantics["routing"]["survey_selects_next_method"])
        self.assertFalse(semantics["epistemic_boundary"]["synthetic_respondent_or_persona_generation_defined_here"])
        self.assertEqual(len({e["id"] for e in semantics["errors"]}), len(semantics["errors"]))

    def test_descriptor_binds_pr12_functions_and_pr9_wire_contracts(self):
        self.assertEqual(list(Draft202012Validator(self.descriptor_schema).iter_errors(self.descriptor)), [])
        self.assertEqual(self.descriptor["capability_kind"], "research_method.survey")
        functions = {f["function_id"]: f for f in self.descriptor["declared_functions"]}
        self.assertEqual(set(functions), {"method_design", "instrument_design", "execute", "analyze"})
        for function in functions.values():
            self.assertEqual(function["input_contract"], "capability-context-pack@0.1.0")
            self.assertEqual(function["output_contract"], "capability-handoff@0.1.0")

    def test_questionnaire_fixture_and_stable_traceability(self):
        questionnaire = self.fixtures["questionnaire"]
        self.assertEqual(list(Draft202012Validator(self.schema).iter_errors(questionnaire)), [])
        ids = [q["question_id"] for q in questionnaire["questions"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({q["question_type"] for q in questionnaire["questions"]}, {"single_choice", "scale", "numeric", "free_text"})
        self.assertTrue(all(any(q["traceability"].values()) for q in questionnaire["questions"]))
        self.assertEqual(questionnaire["approval_status"], "approved")
        self.assertIn("approval_decision_id", questionnaire)

    def test_real_execution_keeps_nonresponse_and_sufficiency_boundary(self):
        result = self.fixtures["real"]
        self.assertEqual(list(Draft202012Validator(self.schema).iter_errors(result)), [])
        self.assertEqual(result["sample_disposition"]["nonresponse_count"], 1)
        self.assertTrue(result["target_sample_achieved"])
        self.assertFalse(result["research_sufficiency_claimed"])
        self.assertTrue(all(not r["verified_evidence_claimed"] for r in result["responses"]))

    def test_partial_nonresponse_preserves_missingness_and_duplicate_disposition(self):
        result = self.fixtures["partial_nonresponse"]
        self.assertEqual(list(Draft202012Validator(self.schema).iter_errors(result)), [])
        disposition = result["sample_disposition"]
        self.assertGreater(disposition["partial_count"], 0)
        self.assertGreater(disposition["dropout_count"], 0)
        self.assertGreater(disposition["duplicate_flagged_count"], 0)
        self.assertTrue(result["missing_data_preserved"])
        self.assertTrue(any(r["duplicate_disposition"] == "excluded" for r in result["responses"]))

    def test_synthetic_test_cannot_claim_empirical_or_finding_authority(self):
        result = self.fixtures["synthetic_test"]
        self.assertEqual(list(Draft202012Validator(self.schema).iter_errors(result)), [])
        self.assertTrue(all(r["epistemic_mode"] == "synthetic" for r in result["responses"]))
        self.assertFalse(result["synthetic_responses_may_be_empirical"])
        self.assertFalse(result["aggregate_is_finding"])
        self.assertFalse(result["finding_adoption_performed"])

    def test_analysis_fixture_has_item_denominators_and_provenance(self):
        result = self.fixtures["analysis"]
        self.assertEqual(list(Draft202012Validator(self.schema).iter_errors(result)), [])
        self.assertTrue(result["item_summaries"])
        for item in result["item_summaries"]:
            self.assertEqual(item["denominator_count"], item["answered_count"] + item["missing_count"] + item["excluded_count"])
        self.assertTrue(result["aggregation_provenance_ref"])
        self.assertTrue(result["subgroup_provenance_refs"])
        self.assertTrue(result["free_text_coding_refs"])
        self.assertFalse(result["aggregate_is_finding"])


if __name__ == "__main__":
    unittest.main()
