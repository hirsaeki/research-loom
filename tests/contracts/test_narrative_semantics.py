from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from narrative_semantic_oracle import (
    apply_mutations,
    catalog_cross_reference_errors,
    narrative_composition_error,
    narrative_constraint_error,
    narrative_projection_error,
)
from semantic_oracle import canonical_compose_constraints, load_candidate

ROOT = Path(__file__).resolve().parents[2]
PROFILE_SCHEMA = ROOT / "profiles/contracts/profile-manifest.schema.json"
NARRATIVE_SCHEMA = ROOT / "profiles/contracts/narrative-semantics.schema.json"
NARRATIVE_CATALOG = ROOT / "profiles/contracts/narrative-semantics.yaml"
FIXTURES = ROOT / "profiles/fixtures/narrative"


class NarrativeSemanticsContractTests(unittest.TestCase):
    """Executable specification for canonical Narrative Profile semantics."""

    @classmethod
    def setUpClass(cls):
        cls.profile_schema = json.loads(PROFILE_SCHEMA.read_text(encoding="utf-8"))
        cls.narrative_schema = json.loads(NARRATIVE_SCHEMA.read_text(encoding="utf-8"))
        cls.catalog = yaml.safe_load(NARRATIVE_CATALOG.read_text(encoding="utf-8"))
        cls.profile_validator = Draft202012Validator(cls.profile_schema)
        cls.narrative_validator = Draft202012Validator(cls.narrative_schema)
        cls.generic = json.loads((FIXTURES / "valid/generic-narrative.profile.json").read_text(encoding="utf-8"))

    def test_catalog_schema_and_cross_references(self):
        Draft202012Validator.check_schema(self.narrative_schema)
        self.assertFalse(list(self.narrative_validator.iter_errors(self.catalog)))
        self.assertEqual([], catalog_cross_reference_errors(self.catalog))
        paths = [entry["path"] for entry in self.catalog["constraint_paths"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(path.startswith("narrative.") for path in paths))
        self.assertTrue(self.catalog["principles"]["partial_order_only"])
        self.assertTrue(self.catalog["principles"]["research_state_read_only"])
        self.assertTrue(self.catalog["principles"]["literal_outline_is_projection"])

    def test_generic_narrative_fixture_is_valid_and_closed_namespace_conformant(self):
        self.assertFalse(list(self.profile_validator.iter_errors(self.generic)))
        self.assertIsNone(narrative_constraint_error(self.generic, self.catalog))
        self.assertIsNone(narrative_composition_error([self.generic], self.catalog))
        for constraint in self.generic["constraints"]:
            if constraint["path"] in {"narrative.stages.definitions", "narrative.section_purposes.definitions"}:
                self.assertNotIn("chapter_number", json.dumps(constraint["value"]))
                self.assertNotIn("literal_heading", json.dumps(constraint["value"]))
        self.assertNotIn("MISCO", json.dumps(self.generic))

    def test_namespace_rejects_wrong_owner_path_merge_and_values(self):
        cases = [
            ("PROFILE-NARRATIVE-OWNER-001", {"profile_type": "organization"}),
            ("PROFILE-NARRATIVE-PATH-001", {"constraint": {"path":"narrative.magic.order","merge_strategy":"union","value":[]}}),
            ("PROFILE-NARRATIVE-MERGE-001", {"constraint": {"path":"narrative.preservation.required_content","merge_strategy":"intersection","value":["limitations"]}}),
            ("PROFILE-NARRATIVE-VALUE-001", {"constraint": {"path":"narrative.preservation.required_content","merge_strategy":"union","value":["hide_adverse_results"]}}),
            ("PROFILE-NARRATIVE-VALUE-001", {"constraint": {"path":"narrative.stages.definitions","merge_strategy":"union","value":[{"id":"x","semantic_role":"framing","consumes":[],"requires":[],"produces":["finding"]}]}}),
        ]
        for index, (expected, mutation) in enumerate(cases):
            profile = deepcopy(self.generic)
            profile["profile_id"] = f"fixture.invalid-narrative-{index}"
            if "profile_type" in mutation:
                profile["profile_type"] = mutation["profile_type"]
                profile["constraints"] = [profile["constraints"][0]]
            else:
                profile["constraints"] = [{"id":f"bad-{index}", **mutation["constraint"]}]
            self.assertFalse(list(self.profile_validator.iter_errors(profile)), str(index))
            self.assertEqual(expected, narrative_constraint_error(profile, self.catalog), str(index))

    def test_structured_identity_conflicts_refs_and_cycles_fail_closed(self):
        conflict = deepcopy(self.generic)
        stage_constraint = next(c for c in conflict["constraints"] if c["path"] == "narrative.stages.definitions")
        stage_constraint["value"] = [{"id":"framing","semantic_role":"synthesis","consumes":["finding"],"requires":["finding"],"produces":["contribution_synthesis"]}]
        self.assertEqual("PROFILE-NARRATIVE-IDENTITY-001", narrative_composition_error([self.generic, conflict], self.catalog))

        dangling = deepcopy(self.generic)
        dep_constraint = next(c for c in dangling["constraints"] if c["path"] == "narrative.dependencies.required")
        dep_constraint["value"].append({"from_stage":"missing","to_stage":"synthesis","relation":"semantic_precondition"})
        self.assertEqual("PROFILE-NARRATIVE-REF-001", narrative_composition_error([dangling], self.catalog))

        cyclic = deepcopy(self.generic)
        dep_constraint = next(c for c in cyclic["constraints"] if c["path"] == "narrative.dependencies.required")
        dep_constraint["value"].append({"from_stage":"synthesis","to_stage":"framing","relation":"semantic_precondition"})
        self.assertEqual("NARRATIVE-DEPENDENCY-CYCLE-001", narrative_composition_error([cyclic], self.catalog))

    def test_dependencies_are_minimum_partial_order_not_literal_total_order(self):
        stage_constraint = next(c for c in self.generic["constraints"] if c["path"] == "narrative.stages.definitions")
        dependency_constraint = next(c for c in self.generic["constraints"] if c["path"] == "narrative.dependencies.required")
        stages = {stage["id"] for stage in stage_constraint["value"]}
        edges = {(edge["from_stage"], edge["to_stage"]) for edge in dependency_constraint["value"]}
        self.assertEqual({"framing", "formation", "validation", "synthesis", "implication"}, stages)
        self.assertIn(("validation", "synthesis"), edges)
        self.assertIn(("validation", "implication"), edges)
        self.assertNotIn(("synthesis", "implication"), edges)
        self.assertNotIn(("implication", "synthesis"), edges)

    def test_pr4_union_composition_is_reused_without_lww(self):
        candidate = load_candidate(FIXTURES / "valid/generic-narrative.profile.json")
        composed = {item["path"]: item for item in canonical_compose_constraints([candidate])}
        self.assertEqual("union", composed["narrative.stages.definitions"]["merge_strategy"])
        self.assertEqual("union", composed["narrative.dependencies.required"]["merge_strategy"])
        self.assertEqual("union", composed["narrative.preservation.required_content"]["merge_strategy"])

    def test_projection_regressions_preserve_authority_qualifiers_and_hints(self):
        cases = json.loads((FIXTURES / "semantic/cases.json").read_text(encoding="utf-8"))
        for case in cases["valid"] + cases["semantic_invalid"]:
            state = apply_mutations(cases["base_state"], case["mutations"])
            self.assertEqual(case["expected_error"], narrative_projection_error(state, self.generic), case["id"])

    def test_stage_outputs_are_narrative_products_not_core_research_objects(self):
        stages = next(c["value"] for c in self.generic["constraints"] if c["path"] == "narrative.stages.definitions")
        research_kinds = set(self.catalog["vocabularies"]["research_input_kind"])
        products = set(self.catalog["vocabularies"]["narrative_product"])
        for stage in stages:
            self.assertTrue(set(stage["produces"]).issubset(products))
            self.assertTrue(set(stage["produces"]).isdisjoint(research_kinds))


if __name__ == "__main__":
    unittest.main()
