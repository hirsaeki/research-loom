from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from delphi_oracle import design_error
from research_method_oracle import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
DLP = PKG / "delphi"
FIX = ROOT / "core/fixtures/capabilities/valid"
CONV = ROOT / "core/fixtures/conversation/valid"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class DelphiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.descriptor_schema = load(PKG / "capability-descriptor.schema.json")
        cls.schema = load(DLP / "delphi-contract.schema.json")
        cls.design_schema = load(DLP / "delphi-design.schema.json")
        cls.conversation_schema = load(PKG / "work-conversation.schema.json")
        cls.descriptor = load(FIX / "generic-delphi-capability-descriptor.json")
        cls.fixtures = load(FIX / "generic-delphi-contract-fixtures.json")
        cls.routing = load(CONV / "delphi-routing.json")

    def test_schemas_semantics_and_descriptor(self):
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator.check_schema(self.design_schema)
        self.assertEqual(list(Draft202012Validator(self.descriptor_schema).iter_errors(self.descriptor)), [])
        self.assertEqual(self.descriptor["descriptor_digest"], canonical_digest(self.descriptor, "descriptor_digest"))
        self.assertEqual({f["function_id"] for f in self.descriptor["declared_functions"]}, {"method_design", "instrument_design", "execute", "analyze"})
        semantics = yaml.safe_load((DLP / "delphi-semantics.yaml").read_text(encoding="utf-8"))
        self.assertFalse(semantics["capability"]["pr9_context_or_handoff_redefined"])
        self.assertFalse(semantics["capability"]["pr12_method_envelopes_redefined"])
        self.assertFalse(semantics["analysis"]["universal_numeric_threshold_defined_here"])
        self.assertFalse(semantics["analysis"]["consensus_threshold_satisfaction_is_finding"])
        self.assertTrue(semantics["analysis"]["lack_of_consensus_is_valid_result"])
        self.assertFalse(semantics["stopping"]["recommendation_is_research_completion"])
        self.assertFalse(semantics["routing"]["delphi_selects_next_method"])

    def test_design_instrument_and_multi_round_fixtures(self):
        design = self.fixtures["design"]
        self.assertEqual(list(Draft202012Validator(self.design_schema).iter_errors(design)), [])
        self.assertEqual(design_error(design), None)
        validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        for name in ("round1_instrument", "round2_revised_instrument", "real_multi_round", "no_consensus"):
            self.assertEqual(list(validator.iter_errors(self.fixtures[name])), [])
        self.assertEqual(design["content_digest"], canonical_digest(design, "content_digest"))
        for name in ("round1_instrument", "round2_revised_instrument"):
            instrument = self.fixtures[name]
            self.assertEqual(instrument["content_digest"], canonical_digest(instrument, "content_digest"))
        for name in ("real_multi_round", "no_consensus"):
            result = self.fixtures[name]
            self.assertEqual(result["extension_digest"], canonical_digest(result, "extension_digest"))
        self.assertTrue(design["candidate_only"])
        self.assertFalse(design["participation_targets"]["target_is_research_sufficiency"])
        self.assertTrue(design["stopping"]["no_universal_numeric_threshold"])
        round2 = self.fixtures["round2_revised_instrument"]
        self.assertTrue(round2["material_revision"])
        self.assertIn("material_revision_decision_id", round2)
        self.assertEqual(round2["items"][0]["lineage"]["predecessor_item_id"], "ITEM-1")
        real = self.fixtures["real_multi_round"]
        self.assertEqual(real["rounds"][1]["participation"]["dropout"], 1)
        self.assertTrue(real["rounds"][1]["controlled_feedback"]["delivered"])
        self.assertTrue(real["missing_data_preserved"])
        self.assertTrue(real["minority_positions_preserved"])
        no_consensus = self.fixtures["no_consensus"]
        self.assertFalse(no_consensus["item_analyses"][0]["consensus"]["threshold_satisfied"])
        self.assertTrue(no_consensus["item_analyses"][0]["minority_dissent_refs"])
        self.assertFalse(no_consensus["consensus_is_truth"])
        self.assertFalse(no_consensus["analysis_is_finding"])

    def test_instrument_human_decision_evidence_is_required(self):
        validator = Draft202012Validator(self.schema)
        approved_without_decision = deepcopy(self.fixtures["round1_instrument"])
        approved_without_decision.pop("approval_decision_id")
        self.assertTrue(list(validator.iter_errors(approved_without_decision)))

        material_without_decision = deepcopy(self.fixtures["round2_revised_instrument"])
        material_without_decision.pop("material_revision_decision_id")
        self.assertTrue(list(validator.iter_errors(material_without_decision)))

    def test_planned_rounds_are_executable(self):
        validator = Draft202012Validator(self.design_schema)
        null_plan = deepcopy(self.fixtures["design"])
        null_plan["planned_rounds"]["round_plan"] = None
        self.assertTrue(list(validator.iter_errors(null_plan)))

        invalid_minimum = deepcopy(self.fixtures["design"])
        invalid_minimum["planned_rounds"]["minimum_rounds"] = 0
        self.assertTrue(list(validator.iter_errors(invalid_minimum)))

        inverted = deepcopy(self.fixtures["design"])
        inverted["planned_rounds"]["minimum_rounds"] = 4
        inverted["planned_rounds"]["maximum_approved_rounds"] = 3
        self.assertEqual(design_error(inverted), "DLP-DESIGN-ROUNDS-001")

        below_minimum = deepcopy(self.fixtures["design"])
        below_minimum["planned_rounds"]["minimum_rounds"] = 3
        below_minimum["planned_rounds"]["maximum_approved_rounds"] = 3
        below_minimum["planned_rounds"]["round_plan"] = [{"sequence": 1}, {"sequence": 2}]
        self.assertEqual(design_error(below_minimum), "DLP-DESIGN-ROUNDS-001")

        above_maximum = deepcopy(self.fixtures["design"])
        above_maximum["planned_rounds"]["minimum_rounds"] = 2
        above_maximum["planned_rounds"]["maximum_approved_rounds"] = 2
        above_maximum["planned_rounds"]["round_plan"] = [{"sequence": 1}, {"sequence": 2}, {"sequence": 3}]
        self.assertEqual(design_error(above_maximum), "DLP-DESIGN-ROUNDS-001")

        exact_bounds = deepcopy(self.fixtures["design"])
        exact_bounds["planned_rounds"]["minimum_rounds"] = 2
        exact_bounds["planned_rounds"]["maximum_approved_rounds"] = 2
        exact_bounds["planned_rounds"]["round_plan"] = [{"sequence": 1}, {"sequence": 2}]
        self.assertEqual(design_error(exact_bounds), None)

    def test_pr10_routing_preserves_pr9_and_human_decision_boundary(self):
        proposal = self.routing["action_proposal"]
        validator = Draft202012Validator(self.conversation_schema, format_checker=FormatChecker())
        self.assertEqual(list(validator.iter_errors(proposal)), [])
        self.assertEqual(proposal["route"]["invocation_contract"], "capability-invocation@0.1.0")
        self.assertEqual(proposal["route"]["capability"]["descriptor_digest"], self.descriptor["descriptor_digest"])
        self.assertFalse(proposal["human_decision_boundary"]["confirmation_is_human_decision"])
        self.assertIn("DEC-MAT-2", proposal["human_decision_boundary"]["decision_reference_ids"])


if __name__ == "__main__":
    unittest.main()
