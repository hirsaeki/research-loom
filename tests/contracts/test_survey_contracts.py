from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from research_method_oracle import canonical_digest
from survey_oracle import context_error, descriptor_error, questionnaire_error, result_error

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
SV = PKG / "survey"
FIX = ROOT / "core/fixtures/capabilities/valid"
CONV = ROOT / "core/fixtures/conversation/valid"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def refresh(document, digest_field):
    document[digest_field] = canonical_digest(document, digest_field)


class SurveyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.descriptor_schema = load(PKG / "capability-descriptor.schema.json")
        cls.schema = load(SV / "survey-contract.schema.json")
        cls.design_schema = load(SV / "survey-design.schema.json")
        cls.conversation_schema = load(PKG / "work-conversation.schema.json")
        cls.descriptor = load(FIX / "generic-survey-capability-descriptor.json")
        cls.fixtures = load(FIX / "generic-survey-contract-fixtures.json")
        cls.routing = load(CONV / "survey-routing.json")
        cls.format_checker = FormatChecker()

    def _validator(self):
        return Draft202012Validator(self.schema, format_checker=self.format_checker)

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

    def test_descriptor_binds_pr12_functions_pr9_wire_and_digest(self):
        self.assertEqual(list(Draft202012Validator(self.descriptor_schema).iter_errors(self.descriptor)), [])
        self.assertEqual(descriptor_error(self.descriptor), None)
        self.assertEqual(self.descriptor["descriptor_digest"], canonical_digest(self.descriptor, "descriptor_digest"))
        functions = {f["function_id"]: f for f in self.descriptor["declared_functions"]}
        self.assertEqual(set(functions), {"method_design", "instrument_design", "execute", "analyze"})
        for function in functions.values():
            self.assertEqual(function["input_contract"], "capability-context-pack@0.1.0")
            self.assertEqual(function["output_contract"], "capability-handoff@0.1.0")
        stale = deepcopy(self.descriptor)
        stale["declared_functions"][0]["description"] = "Mutated after digest calculation."
        self.assertEqual(descriptor_error(stale), "SV-DESCRIPTOR-001")

    def test_minimal_survey_design_fixture_is_candidate_only_and_digest_bound(self):
        design = self.fixtures["design"]
        self.assertEqual(list(Draft202012Validator(self.design_schema).iter_errors(design)), [])
        self.assertTrue(design["candidate_only"])
        self.assertFalse(design["target_sample"]["target_count_is_research_sufficiency"])
        self.assertEqual(design["content_digest"], canonical_digest(design, "content_digest"))

    def test_questionnaire_fixture_stable_traceability_approval_and_digest(self):
        questionnaire = self.fixtures["questionnaire"]
        self.assertEqual(list(self._validator().iter_errors(questionnaire)), [])
        self.assertEqual(questionnaire_error(questionnaire), None)
        self.assertEqual(questionnaire["content_digest"], canonical_digest(questionnaire, "content_digest"))
        ids = [q["question_id"] for q in questionnaire["questions"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({q["question_type"] for q in questionnaire["questions"]}, {"single_choice", "scale", "numeric", "free_text"})
        self.assertTrue(all(any(q["traceability"].values()) for q in questionnaire["questions"]))
        self.assertEqual(questionnaire["approval_status"], "approved")
        self.assertIn("approval_decision_id", questionnaire)
        stale = deepcopy(questionnaire)
        stale["questions"][0]["text"] = "Changed without digest update."
        self.assertEqual(questionnaire_error(stale), "SV-QUESTIONNAIRE-DIGEST-001")

    def test_real_execute_requires_exact_design_questionnaire_and_human_decision(self):
        design = self.fixtures["design"]
        questionnaire = self.fixtures["questionnaire"]
        context = self.fixtures["context"]
        self.assertEqual(list(self._validator().iter_errors(context)), [])
        self.assertEqual(context_error(context, design, questionnaire, "real"), None)

        changed_design = deepcopy(design)
        changed_design["target_population"]["definition"] = "Changed design after context pinning."
        refresh(changed_design, "content_digest")
        self.assertEqual(context_error(context, changed_design, questionnaire, "real"), "SV-CONTEXT-BINDING-001")

        candidate = deepcopy(questionnaire)
        candidate["approval_status"] = "candidate"
        candidate.pop("approval_decision_id", None)
        refresh(candidate, "content_digest")
        candidate_context = deepcopy(context)
        candidate_context["questionnaire_ref"]["content_digest"] = candidate["content_digest"]
        candidate_context["questionnaire_decision_ids"] = []
        refresh(candidate_context, "extension_digest")
        self.assertEqual(context_error(candidate_context, design, candidate, "real"), "SV-REAL-EXECUTION-001")
        missing_decision = deepcopy(context)
        missing_decision["questionnaire_decision_ids"] = []
        refresh(missing_decision, "extension_digest")
        self.assertEqual(context_error(missing_decision, design, questionnaire, "real"), "SV-REAL-EXECUTION-001")
        stale = deepcopy(context)
        stale["duplicate_response_policy"] = "manual_review"
        self.assertEqual(context_error(stale, design, questionnaire, "real"), "SV-CONTEXT-DIGEST-001")

    def test_real_execution_keeps_nonresponse_sufficiency_and_datetime_boundary(self):
        result = self.fixtures["real"]
        self.assertEqual(list(self._validator().iter_errors(result)), [])
        self.assertEqual(result_error(result, "real"), None)
        self.assertEqual(result["extension_digest"], canonical_digest(result, "extension_digest"))
        self.assertEqual(result["sample_disposition"]["nonresponse_count"], 1)
        self.assertFalse(result["target_sample_achieved"])
        self.assertFalse(result["research_sufficiency_claimed"])
        self.assertTrue(all(not r["verified_evidence_claimed"] for r in result["responses"]))
        invalid_time = deepcopy(result)
        invalid_time["responses"][0]["response_timestamp"] = "not-a-date-time"
        refresh(invalid_time, "extension_digest")
        errors = list(self._validator().iter_errors(invalid_time))

        def contains_format(error):
            return error.validator == "format" or any(contains_format(child) for child in error.context)

        self.assertTrue(any(contains_format(error) for error in errors), errors)
        stale = deepcopy(result)
        stale["limitations"].append("Changed without digest update.")
        self.assertEqual(result_error(stale, "real"), "SV-RESULT-DIGEST-001")

    def test_partial_nonresponse_preserves_missingness_and_duplicate_disposition(self):
        result = self.fixtures["partial_nonresponse"]
        self.assertEqual(list(self._validator().iter_errors(result)), [])
        self.assertEqual(result_error(result, "real"), None)
        disposition = result["sample_disposition"]
        self.assertGreater(disposition["partial_count"], 0)
        self.assertGreater(disposition["dropout_count"], 0)
        self.assertGreater(disposition["duplicate_flagged_count"], 0)
        self.assertTrue(result["missing_data_preserved"])
        self.assertTrue(any(r["duplicate_disposition"] == "excluded" for r in result["responses"]))

    def test_execution_mode_requires_matching_epistemic_mode(self):
        real = self.fixtures["real"]
        self.assertEqual(result_error(real, "real"), None)
        wrong_real = deepcopy(real)
        wrong_real["responses"][0]["epistemic_mode"] = "synthetic"
        refresh(wrong_real, "extension_digest")
        self.assertEqual(result_error(wrong_real, "real"), "SV-EPISTEMIC-MODE-001")

        synthetic = self.fixtures["synthetic_test"]
        self.assertEqual(result_error(synthetic, "synthetic_test"), None)
        wrong_synthetic = deepcopy(synthetic)
        wrong_synthetic["responses"][0]["epistemic_mode"] = "empirical"
        refresh(wrong_synthetic, "extension_digest")
        self.assertEqual(result_error(wrong_synthetic, "synthetic_test"), "SV-EPISTEMIC-MODE-001")

        virtual = deepcopy(synthetic)
        virtual["responses"][0]["epistemic_mode"] = "virtual"
        refresh(virtual, "extension_digest")
        self.assertEqual(list(self._validator().iter_errors(virtual)), [])
        self.assertEqual(result_error(virtual, "virtual"), None)
        wrong_virtual = deepcopy(virtual)
        wrong_virtual["responses"][0]["epistemic_mode"] = "synthetic"
        refresh(wrong_virtual, "extension_digest")
        self.assertEqual(result_error(wrong_virtual, "virtual"), "SV-EPISTEMIC-MODE-001")

    def test_synthetic_test_cannot_claim_empirical_or_finding_authority(self):
        result = self.fixtures["synthetic_test"]
        self.assertEqual(list(self._validator().iter_errors(result)), [])
        self.assertEqual(result_error(result, "synthetic_test"), None)
        self.assertTrue(all(r["epistemic_mode"] == "synthetic" for r in result["responses"]))
        empirical = deepcopy(result)
        empirical["responses"][0]["epistemic_mode"] = "empirical"
        refresh(empirical, "extension_digest")
        self.assertEqual(result_error(empirical, "synthetic_test"), "SV-EPISTEMIC-MODE-001")

    def test_analysis_fixture_has_item_denominators_provenance_and_candidate_authority(self):
        result = self.fixtures["analysis"]
        self.assertEqual(list(self._validator().iter_errors(result)), [])
        self.assertEqual(result_error(result, "real"), None)
        self.assertTrue(result["item_summaries"])
        for item in result["item_summaries"]:
            self.assertEqual(item["denominator_count"], item["answered_count"] + item["missing_count"] + item["excluded_count"])
        self.assertTrue(result["aggregation_provenance_ref"])
        self.assertTrue(result["subgroup_provenance_refs"])
        self.assertTrue(result["free_text_coding_refs"])
        self.assertFalse(result["aggregate_is_finding"])
        bad_denominator = deepcopy(result)
        bad_denominator["item_summaries"][0]["denominator_count"] += 1
        refresh(bad_denominator, "extension_digest")
        self.assertEqual(result_error(bad_denominator, "real"), "SV-ANALYSIS-DENOMINATOR-001")

    def test_pr10_routing_keeps_pr9_invocation_and_human_decision_boundary(self):
        proposal = self.routing["action_proposal"]
        validator = Draft202012Validator(self.conversation_schema, format_checker=self.format_checker)
        self.assertEqual(list(validator.iter_errors(proposal)), [])
        self.assertEqual(proposal["route"]["invocation_contract"], "capability-invocation@0.1.0")
        self.assertEqual(proposal["route"]["capability"]["function_id"], "execute")
        self.assertEqual(proposal["route"]["capability"]["descriptor_digest"], self.descriptor["descriptor_digest"])
        self.assertEqual(proposal["route"]["execution_mode"], "real")
        self.assertTrue(proposal["human_decision_boundary"]["required"])
        self.assertFalse(proposal["human_decision_boundary"]["confirmation_is_human_decision"])
        self.assertIn("DEC-QNR-1", proposal["human_decision_boundary"]["decision_reference_ids"])


if __name__ == "__main__":
    unittest.main()
