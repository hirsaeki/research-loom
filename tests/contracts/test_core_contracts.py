from __future__ import annotations

import json
import random
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from core_semantic_oracle import canonical_state_bytes, evaluate_core_invariants

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "core/models/research-object.schema.json"
CATALOG_PATH = ROOT / "core/validators/non-overridable-invariants.yaml"
VALID_FIXTURE_PATH = ROOT / "core/fixtures/research-objects/valid.json"
INVALID_FIXTURE_PATH = ROOT / "core/fixtures/research-objects/invalid.json"
SEMANTIC_FIXTURE_PATH = ROOT / "core/fixtures/research-objects/semantic-cases.json"
REGISTRY_PATH = ROOT / "profiles/contracts/invariant-strengthening-validators.yaml"
PROFILE_SEMANTICS_PATH = ROOT / "profiles/contracts/composition-semantics.yaml"
PROFILE_FIXTURES = ROOT / "profiles/fixtures"


def load_json(path: Path) -> dict:
    """Load one UTF-8 JSON contract fixture from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_validation_errors(errors):
    """Yield validation errors recursively, including nested oneOf/anyOf contexts."""
    for error in errors:
        yield error
        yield from flatten_validation_errors(error.context)


class CoreContractTests(unittest.TestCase):
    """Executable specification for canonical Core and Core/Profile contracts."""

    @classmethod
    def setUpClass(cls):
        """Load canonical schemas, catalogs, registries, and fixture bundles once."""
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)
        cls.catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.profile_semantics = yaml.safe_load(PROFILE_SEMANTICS_PATH.read_text(encoding="utf-8"))
        cls.valid_fixture = load_json(VALID_FIXTURE_PATH)
        cls.invalid_fixture = load_json(INVALID_FIXTURE_PATH)
        cls.semantic_fixture = load_json(SEMANTIC_FIXTURE_PATH)

    def test_research_object_schema_is_valid_draft_2020_12(self):
        """Require the canonical research-object schema itself to be valid Draft 2020-12."""
        Draft202012Validator.check_schema(self.schema)

    def test_valid_fixture_covers_every_canonical_object_kind(self):
        """Require one schema-valid fixture for each canonical research-object kind."""
        objects = self.valid_fixture["objects"]
        expected_kinds = {
            "project", "research_question", "claim", "method", "source", "evidence",
            "analysis", "finding", "counter_review", "argument", "contribution",
            "recommendation", "next_action", "decision", "artifact", "snapshot", "audit_event",
        }
        self.assertEqual(expected_kinds, {obj["kind"] for obj in objects})
        self.assertEqual(len(expected_kinds), len(objects))
        for obj in objects:
            errors = list(self.validator.iter_errors(obj))
            self.assertFalse(errors, f"{obj['kind']}:{obj['id']}: {errors}")

    def test_schema_invalid_fixtures_each_fail_for_declared_reason(self):
        """Require every structural invalid fixture to fail for its declared schema reason."""
        for case in self.invalid_fixture["cases"]:
            errors = list(flatten_validation_errors(self.validator.iter_errors(case["object"])))
            self.assertTrue(errors, case["id"])
            expected = case["expected_error"]
            matches = [
                error
                for error in errors
                if error.validator == expected["validator"]
                and list(error.path) == expected["path"]
                and expected.get("message_contains", "") in error.message
            ]
            self.assertTrue(
                matches,
                f"{case['id']}: expected {expected}, got "
                f"{[(error.validator, list(error.path), error.message) for error in errors]}",
            )

    def test_semantic_fixtures_remain_schema_valid(self):
        """Keep semantic-invalid fixtures structurally valid so layers remain distinct."""
        for case in self.semantic_fixture["cases"]:
            for lane in ("prior_objects", "objects"):
                for obj in case.get(lane, []):
                    errors = list(self.validator.iter_errors(obj))
                    self.assertFalse(errors, f"{case['id']}:{lane}:{obj['kind']}:{obj['id']}: {errors}")

    def test_semantic_fixtures_exercise_exact_invariant_outcomes(self):
        """Require every semantic fixture to produce exactly its declared invariant set."""
        for case in self.semantic_fixture["cases"]:
            prior = case.get("prior_objects")
            actual = evaluate_core_invariants(case["objects"], prior)
            self.assertEqual(set(case["expected_invariants"]), actual, case["id"])

    def test_snapshot_revision_bump_is_still_snapshot_mutation(self):
        """Require a reused snapshot id with a revision bump to violate immutability."""
        prior = {
            "schema_version": "0.1.0",
            "id": "SNP-REV",
            "kind": "snapshot",
            "revision": 0,
            "project_id": "PRJ-1",
            "snapshot_type": "research",
            "created_at": "2026-01-01T00:00:00Z",
            "mode": "real",
            "members": [],
        }
        current = {
            "schema_version": "0.1.0",
            "id": "SNP-REV",
            "kind": "snapshot",
            "revision": 1,
            "project_id": "PRJ-1",
            "snapshot_type": "research",
            "created_at": "2026-01-01T00:00:00Z",
            "mode": "real",
            "members": [{"kind": "finding", "id": "FND-1", "revision": 0}],
        }
        self.assertFalse(list(self.validator.iter_errors(prior)))
        self.assertFalse(list(self.validator.iter_errors(current)))
        self.assertEqual({"CORE-PROV-002"}, evaluate_core_invariants([current], [prior]))

    def test_every_core_invariant_has_executable_semantic_fixture_coverage(self):
        """Require executable semantic fixture coverage for every cataloged Core invariant."""
        catalog_ids = {entry["id"] for entry in self.catalog["invariants"]}
        covered = {
            invariant_id
            for case in self.semantic_fixture["cases"]
            for invariant_id in case["expected_invariants"]
        }
        self.assertEqual(catalog_ids, covered)

    def test_semantic_results_and_state_serialization_are_input_order_independent(self):
        """Require shuffled object order to preserve outcomes and canonical serialization."""
        for case in self.semantic_fixture["cases"]:
            expected_invariants = set(case["expected_invariants"])
            baseline_bytes = canonical_state_bytes(case["objects"])
            for seed in range(20):
                objects = list(case["objects"])
                random.Random(seed).shuffle(objects)
                prior = list(case.get("prior_objects", []))
                random.Random(seed + 1000).shuffle(prior)
                actual = evaluate_core_invariants(objects, prior if "prior_objects" in case else None)
                self.assertEqual(expected_invariants, actual, f"{case['id']} seed={seed}")
                self.assertEqual(baseline_bytes, canonical_state_bytes(objects), f"{case['id']} seed={seed}")

    def test_invariant_catalog_and_profile_strengthening_registry_are_one_to_one(self):
        """Require the Profile strengthening registry to match the active Core catalog exactly."""
        catalog_ids = [entry["id"] for entry in self.catalog["invariants"]]
        registry_ids = list(self.registry["invariants"])
        self.assertEqual(len(catalog_ids), len(set(catalog_ids)))
        self.assertEqual(set(catalog_ids), set(registry_ids))
        self.assertEqual(self.catalog["contract_version"], self.registry["authoritative_for_invariant_contract"])
        self.assertEqual(self.catalog["contract_version"], self.profile_semantics["semantic_floor"]["invariant_contract"])

        allowed_policies = {"registered_forms", "no_registered_forms"}
        for invariant_id, entry in self.registry["invariants"].items():
            policy = entry["strengthening_policy"]
            self.assertIn(policy, allowed_policies, invariant_id)
            validators = entry.get("validators", [])
            if policy == "registered_forms":
                self.assertTrue(validators, invariant_id)
                bindings = set()
                for validator in validators:
                    self.assertTrue(validator.get("approved_forms"), invariant_id)
                    for form in validator["approved_forms"]:
                        binding = (validator["validator_id"], validator["validator_version"], form["form_id"])
                        self.assertNotIn(binding, bindings, invariant_id)
                        bindings.add(binding)
            else:
                self.assertFalse(validators, invariant_id)

    def test_all_profile_strengthening_declarations_reference_cataloged_invariants(self):
        """Require fixture strengthening declarations to target existing Core invariants."""
        catalog_ids = {entry["id"] for entry in self.catalog["invariants"]}
        manifests = list((PROFILE_FIXTURES / "valid").glob("*.profile.json")) + list((PROFILE_FIXTURES / "invalid").glob("*.profile.json"))
        self.assertTrue(manifests, f"no profile manifests found under {PROFILE_FIXTURES}")
        for path in manifests:
            profile = load_json(path)
            for strengthening in profile.get("core_invariant_strengthenings", []):
                self.assertIn(strengthening["invariant_id"], catalog_ids, str(path))


if __name__ == "__main__":
    unittest.main()
