from __future__ import annotations

import json
import random
import unittest

import rfc8785
import yaml
from jsonschema import Draft202012Validator

from semantic_oracle import (
    ROOT,
    canonical_compose_constraints,
    canonical_constraint_source_key,
    canonical_json_bytes,
    canonicalize_set_like,
    core_compatibility_error,
    effective_identity_error,
    effective_provenance_error,
    key_of,
    keyver_of,
    load_candidate,
    load_json,
    requested_presence_error,
    resolve_candidates,
    satisfies,
    sha256_bytes,
    strengthening_error,
    constraint_composition_error,
)

PROFILE_SCHEMA_PATH = ROOT / "profiles/contracts/profile-manifest.schema.json"
EFFECTIVE_SCHEMA_PATH = ROOT / "profiles/contracts/effective-profile-set.schema.json"
SEMANTICS_PATH = ROOT / "profiles/contracts/composition-semantics.yaml"
REGISTRY_PATH = ROOT / "profiles/contracts/invariant-strengthening-validators.yaml"


class ProfileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_schema = load_json(PROFILE_SCHEMA_PATH)
        cls.effective_schema = load_json(EFFECTIVE_SCHEMA_PATH)
        cls.profile_validator = Draft202012Validator(cls.profile_schema)
        cls.effective_validator = Draft202012Validator(cls.effective_schema)
        cls.registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.semantics = yaml.safe_load(SEMANTICS_PATH.read_text(encoding="utf-8"))

    def test_schemas_are_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(self.profile_schema)
        Draft202012Validator.check_schema(self.effective_schema)

    def test_contract_yaml_parses_and_registry_covers_all_core_invariants(self):
        self.assertEqual(self.semantics["status"], "CANONICAL")
        core = yaml.safe_load((ROOT / "core/validators/non-overridable-invariants.yaml").read_text(encoding="utf-8"))
        self.assertEqual({x["id"] for x in core["invariants"]}, set(self.registry["invariants"]))

    def test_valid_profile_fixtures_validate(self):
        for path in sorted((ROOT / "profiles/fixtures/valid").glob("*.profile.json")):
            self.assertFalse(list(self.profile_validator.iter_errors(load_json(path))), str(path))

    def test_valid_effective_fixture_validates_and_pins_manifest_bytes(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        self.assertFalse(list(self.effective_validator.iter_errors(eps)))
        self.assertIsNone(effective_identity_error(eps))
        self.assertIsNone(effective_provenance_error(eps))
        self.assertIsNone(requested_presence_error(eps))
        actual = {}
        for path in sorted((ROOT / "profiles/fixtures/valid").glob("*.profile.json")):
            manifest = load_json(path)
            actual[keyver_of(manifest)] = sha256_bytes(path)
        for ref in eps["candidate_universe"] + eps["effective_profiles"]:
            self.assertEqual(actual[keyver_of(ref)], ref["manifest_sha256"])

    def test_required_fields_constraint_rejects_non_string_members(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        required = next(
            item for item in eps["effective_constraints"]
            if item["path"] == "evidence.capture.required_fields"
        )
        required["value"] = [["capture_digest"]]
        self.assertTrue(list(self.effective_validator.iter_errors(eps)))

    def test_schema_invalid_fixtures_fail(self):
        for name in [
            "cross-type-extends.profile.json",
            "core-invariant-weakening.profile.json",
            "merge-strategy-value-type.profile.json",
        ]:
            self.assertTrue(list(self.profile_validator.iter_errors(load_json(ROOT / "profiles/fixtures/invalid" / name))), name)
        for name in ["effective-profile-set-status-provenance.json", "effective-profile-set-invalid-resolution.json"]:
            self.assertTrue(list(self.effective_validator.iter_errors(load_json(ROOT / "profiles/fixtures/invalid" / name))), name)

    def test_semantic_invalid_fixtures_are_schema_valid_then_fail_expected_code(self):
        cases = load_json(ROOT / "profiles/fixtures/contract-cases.json")["semantic_invalid"]
        for case in cases:
            objects = [load_json(ROOT / path) for path in case["fixtures"]]
            if case["kind"] == "profile_core_compatibility":
                self.assertFalse(list(self.profile_validator.iter_errors(objects[0])))
                actual = core_compatibility_error(
                    objects[0], {"research_contract": "0.1.0", "invariant_contract": "0.1.0"}
                )
            elif case["kind"] == "effective_identity":
                self.assertFalse(list(self.effective_validator.iter_errors(objects[0])))
                actual = effective_identity_error(objects[0])
            elif case["kind"] == "constraint_composition":
                for obj in objects:
                    self.assertFalse(list(self.profile_validator.iter_errors(obj)))
                actual = constraint_composition_error(objects)
            elif case["kind"] == "strengthening":
                self.assertFalse(list(self.profile_validator.iter_errors(objects[0])))
                actual = strengthening_error(objects[0], self.registry)
            else:
                self.fail(f"unknown case kind: {case['kind']}")
            self.assertEqual(case["expected_error"], actual, case["id"])

    def test_registered_strengthening_fixture_is_machine_distinguishable(self):
        valid = load_json(ROOT / "profiles/fixtures/valid/research-strict.profile.json")
        invalid = load_json(ROOT / "profiles/fixtures/invalid/unverifiable-core-strengthening.profile.json")
        self.assertIsNone(strengthening_error(valid, self.registry))
        self.assertEqual("PROFILE-CORE-STRENGTHENING-001", strengthening_error(invalid, self.registry))

    def test_version_resolution_intersects_transitive_ranges_and_selects_deterministically(self):
        case_dir = ROOT / "profiles/fixtures/semantic/version-resolution"
        case = load_json(case_dir / "case.json")
        base_candidates = [load_candidate(case_dir / "candidates" / name) for name in case["candidate_files"]]
        expected = [(x["profile_type"], x["profile_id"], x["profile_version"]) for x in case["expected_selected"]]
        expected_output = None
        for seed in range(20):
            candidates = base_candidates[:]
            random.Random(seed).shuffle(candidates)
            output, error = resolve_candidates(candidates, case["requested_profiles"], case["core_contracts"])
            self.assertIsNone(error)
            self.assertEqual(expected, [(x["profile_type"], x["profile_id"], x["profile_version"]) for x in output])
            normalized = canonical_json_bytes(output)
            expected_output = normalized if expected_output is None else expected_output
            self.assertEqual(expected_output, normalized)
        target = next(x for x in output if x["profile_id"] == "fixture.version-target")
        dependencies = [x for x in target["selection_provenance"] if x["relation"] == "requires"]
        self.assertEqual({">=1.5.0 <3.0.0", ">=2.0.0 <2.5.0"}, {x["required_version"] for x in dependencies})
        self.assertEqual({"fixture.version-org", "fixture.version-root"}, {x["introduced_by"]["profile_id"] for x in dependencies})
        root = next(x for x in output if x["profile_id"] == "fixture.version-root")
        self.assertEqual([{"relation": "requested", "required_version": "1.0.0"}], root["selection_provenance"])

    def test_dependency_provenance_in_effective_fixture_is_bidirectionally_lossless(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        self.assertIsNone(effective_provenance_error(eps))
        self.assertIsNone(requested_presence_error(eps))

    def test_constraint_composition_is_input_order_independent_and_serialized(self):
        paths = [
            ROOT / "profiles/fixtures/valid" / name
            for name in [
                "research-base.profile.json",
                "research-strict.profile.json",
                "organization.profile.json",
                "narrative.profile.json",
                "publication.profile.json",
            ]
        ]
        base = [load_candidate(path) for path in paths]
        expected = None
        for seed in range(20):
            items = base[:]
            random.Random(seed).shuffle(items)
            composed = canonical_compose_constraints(items)
            normalized = canonical_json_bytes(composed)
            expected = normalized if expected is None else expected
            self.assertEqual(expected, normalized)
        self.assertEqual(sorted(c["path"] for c in composed), [c["path"] for c in composed])
        union = next(c for c in composed if c["path"] == "evidence.capture.required_fields")
        self.assertEqual(["capture_digest", "locator", "source_id"], union["value"])
        self.assertEqual(sorted(union["provenance"], key=canonical_constraint_source_key), union["provenance"])

    def test_set_like_serialization_uses_rfc8785_for_numbers_objects_and_unicode(self):
        fixture = load_json(ROOT / "profiles/fixtures/semantic/canonical-serialization.json")
        expected = fixture["expected_sorted_rfc8785"]
        for seed in range(20):
            members = fixture["members"][:]
            random.Random(seed).shuffle(members)
            canonical_members = canonicalize_set_like(members)
            actual = [rfc8785.dumps(member).decode("utf-8") for member in canonical_members]
            self.assertEqual(expected, actual)
        self.assertEqual(b"1", rfc8785.dumps(1.0))
        self.assertEqual(b'{"a":1,"b":2}', rfc8785.dumps({"b": 2, "a": 1}))


if __name__ == "__main__":
    unittest.main()
