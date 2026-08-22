from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from research_quality_oracle import (
    apply_mutations,
    catalog_index,
    research_quality_constraint_error,
    research_quality_state_error,
)
from semantic_oracle import canonical_compose_constraints, load_candidate

ROOT = Path(__file__).resolve().parents[2]
PROFILE_SCHEMA = ROOT / "profiles/contracts/profile-manifest.schema.json"
CORE_SCHEMA = ROOT / "core/models/research-object.schema.json"
QUALITY_SCHEMA = ROOT / "profiles/contracts/research-quality-policy.schema.json"
QUALITY_CATALOG = ROOT / "profiles/contracts/research-quality-policy.yaml"
FIXTURES = ROOT / "profiles/fixtures/research-quality"


class ResearchQualityPolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_schema = json.loads(PROFILE_SCHEMA.read_text(encoding="utf-8"))
        cls.core_schema = json.loads(CORE_SCHEMA.read_text(encoding="utf-8"))
        cls.quality_schema = json.loads(QUALITY_SCHEMA.read_text(encoding="utf-8"))
        cls.catalog = yaml.safe_load(QUALITY_CATALOG.read_text(encoding="utf-8"))
        cls.profile_validator = Draft202012Validator(cls.profile_schema)
        cls.core_validator = Draft202012Validator(cls.core_schema)
        cls.quality_validator = Draft202012Validator(cls.quality_schema)
        cls.generic = json.loads((FIXTURES / "valid/generic-research-quality.profile.json").read_text(encoding="utf-8"))

    def test_quality_catalog_schema_is_valid_and_catalog_conforms(self):
        Draft202012Validator.check_schema(self.quality_schema)
        self.assertFalse(list(self.quality_validator.iter_errors(self.catalog)))
        paths = [entry["path"] for entry in self.catalog["constraint_paths"]]
        self.assertEqual(len(paths), len(set(paths)))
        index = catalog_index(self.catalog)
        self.assertEqual(set(paths), set(index))
        for entry in self.catalog["constraint_paths"]:
            if entry["class"] == "threshold":
                self.assertTrue(entry["path"].startswith("research_quality.thresholds."))
                self.assertEqual("integer", entry["value_shape"])
                self.assertIn(entry["merge_strategy"], {"max", "min"})
            else:
                self.assertFalse(entry["path"].startswith("research_quality.thresholds."))
                self.assertEqual("enum_set", entry["value_shape"])
                self.assertIn(entry["merge_strategy"], {"union", "intersection"})

    def test_generic_and_strict_research_quality_fixtures_are_valid_manifests(self):
        for path in sorted((FIXTURES / "valid").glob("*.profile.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(list(self.profile_validator.iter_errors(manifest)), str(path))
            self.assertIsNone(research_quality_constraint_error(manifest, self.catalog), str(path))

    def test_quality_namespace_rejects_wrong_owner_path_merge_and_values(self):
        cases = [
            ("PROFILE-RESEARCH-QUALITY-OWNER-001", {"profile_type": "organization"}),
            ("PROFILE-RESEARCH-QUALITY-PATH-001", {"constraint": {"path": "research_quality.evidence.magic_score", "merge_strategy": "max", "value": 5}}),
            ("PROFILE-RESEARCH-QUALITY-MERGE-001", {"constraint": {"path": "research_quality.counter_review.required_lenses", "merge_strategy": "intersection", "value": ["contradictory_evidence"]}}),
            ("PROFILE-RESEARCH-QUALITY-VALUE-001", {"constraint": {"path": "research_quality.evidence.claim_support.allowed_directness", "merge_strategy": "intersection", "value": ["very_direct"]}}),
            ("PROFILE-RESEARCH-QUALITY-VALUE-001", {"constraint": {"path": "research_quality.thresholds.material_finding.min_supporting_evidence_count", "merge_strategy": "max", "value": -1}}),
        ]
        for index, (code, mutation) in enumerate(cases):
            manifest = json.loads(json.dumps(self.generic))
            manifest["profile_id"] = f"fixture.invalid-quality-{index}"
            if "profile_type" in mutation:
                manifest["profile_type"] = mutation["profile_type"]
                manifest["constraints"] = [manifest["constraints"][0]]
            else:
                manifest["constraints"] = [{"id": f"bad-{index}", **mutation["constraint"]}]
            self.assertFalse(list(self.profile_validator.iter_errors(manifest)), str(index))
            self.assertEqual(code, research_quality_constraint_error(manifest, self.catalog), str(index))

    def test_quality_composition_is_monotone_and_reuses_profile_merge_semantics(self):
        generic = load_candidate(FIXTURES / "valid/generic-research-quality.profile.json")
        strict = load_candidate(FIXTURES / "valid/strict-research-quality.profile.json")
        composed = {item["path"]: item["value"] for item in canonical_compose_constraints([strict, generic])}
        self.assertEqual(["descriptive_context"], composed["research_quality.source.low_confidence.allowed_support_scopes"])
        self.assertEqual(
            ["alternative_explanation", "contradictory_evidence", "methodological_weakness"],
            composed["research_quality.counter_review.required_lenses"],
        )
        self.assertEqual(3, composed["research_quality.thresholds.material_finding.min_supporting_evidence_count"])
        self.assertEqual(3, composed["research_quality.thresholds.material_finding.min_independent_evidence_groups"])
        self.assertIn("research_freeze", composed["research_quality.gates.required"])

    def test_semantic_quality_fixtures_use_schema_valid_core_objects_and_expected_outcomes(self):
        cases = json.loads((FIXTURES / "semantic/cases.json").read_text(encoding="utf-8"))
        base = cases["base_state"]
        for case in cases["valid"] + cases["semantic_invalid"]:
            state = apply_mutations(base, case["mutations"])
            for object_id, obj in state["objects"].items():
                errors = list(self.core_validator.iter_errors(obj))
                self.assertFalse(errors, f"{case['id']}:{object_id}:{errors}")
            self.assertEqual(case["expected_error"], research_quality_state_error(state, self.generic), case["id"])

    def test_policy_keeps_numeric_thresholds_distinct_from_semantic_sufficiency(self):
        paths = catalog_index(self.catalog)
        count_path = paths["research_quality.thresholds.material_finding.min_supporting_evidence_count"]
        sufficiency_path = paths["research_quality.evidence_sufficiency.required_checks"]
        self.assertEqual(("threshold", "integer", "max"), (count_path["class"], count_path["value_shape"], count_path["merge_strategy"]))
        self.assertEqual(("semantic", "enum_set", "union"), (sufficiency_path["class"], sufficiency_path["value_shape"], sufficiency_path["merge_strategy"]))
        self.assertTrue(self.catalog["principles"]["no_fixed_source_count_stopping"])


if __name__ == "__main__":
    unittest.main()
