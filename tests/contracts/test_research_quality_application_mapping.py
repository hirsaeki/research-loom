from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "profiles/contracts/research-quality-policy.yaml"
MAPPING = ROOT / "profiles/contracts/research-quality-application.yaml"


class ResearchQualityApplicationMappingTests(unittest.TestCase):
    def test_all_closed_research_quality_paths_have_one_application_mapping(self):
        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
        mapping = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
        expected = [row["path"] for row in policy["constraint_paths"]]
        actual = [row["path"] for row in mapping["constraints"]]
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(len(actual), 22)
        allowed_modes = {
            "machine_check_on_core_state",
            "machine_check_on_explicit_assessment",
            "machine_check_on_explicit_assessment_and_core_state",
            "aggregate_of_configured_quality_checks",
        }
        self.assertTrue(all(row["evaluation_mode"] in allowed_modes for row in mapping["constraints"]))

    def test_mapping_keeps_semantic_truth_and_authority_outside_machine_pass(self):
        mapping = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
        self.assertFalse(mapping["semantic_assessment_boundary"]["classification_truth_verified"])
        self.assertEqual(mapping["semantic_assessment_boundary"]["missing_assessment_status"], "unevaluated")
        self.assertEqual(
            mapping["consumer"],
            "plugins.local_application.research_quality_evaluation.evaluate",
        )
        self.assertEqual(mapping["result_record"]["kind"], "research_exhibit")
        self.assertEqual(mapping["result_record"]["authority_effect"], "none")
        self.assertEqual(mapping["organization_constraints"]["evaluation_mode"], "host_or_human_assessment")
        self.assertEqual(mapping["organization_constraints"]["missing_assessment_status"], "unevaluated")
        self.assertEqual(mapping["organization_constraints"]["authority_effect"], "none")


if __name__ == "__main__":
    unittest.main()
