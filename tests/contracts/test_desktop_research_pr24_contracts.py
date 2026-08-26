from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DR = ROOT / "core/packages/desktop-research"


class DesktopResearchPR24ContractExtensions(unittest.TestCase):
    def test_attempt_failure_outcome_and_actual_capture_budget_fields_are_canonical(self):
        context = json.loads((DR / "desktop-research-context-extension.schema.json").read_text())
        result = json.loads((DR / "desktop-research-result-extension.schema.json").read_text())
        Draft202012Validator.check_schema(context); Draft202012Validator.check_schema(result)
        budget = context["$defs"]["budget"]["properties"]
        self.assertIn("max_original_capture_bytes", budget)
        self.assertIn("max_capture_artifacts", budget)
        outcomes = set(result["$defs"]["search_entry"]["properties"]["outcome"]["enum"])
        self.assertIn("failed", outcomes)

    def test_semantics_keep_attempt_ledger_operational_and_quality_external(self):
        import yaml
        semantics = yaml.safe_load((DR / "desktop-research-semantics.yaml").read_text())
        self.assertTrue(semantics["search_trace"]["production_attempt_ledger_required"])
        self.assertFalse(semantics["search_trace"]["acquisition_failure_is_absence_evidence"])
        self.assertFalse(semantics["coverage_and_stopping"]["operational_termination_is_research_stopping"])
        self.assertEqual(semantics["quality_boundary"]["source_quality_owned_by"], "research_profile")


if __name__ == "__main__": unittest.main()
