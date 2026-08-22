import unittest

from jsonschema import Draft202012Validator

from semantic_oracle import ROOT, effective_provenance_error, key_of, load_json


def mutate_dependency_fixture(spec):
    eps = load_json(ROOT / spec["base"])
    target = next(profile for profile in eps["effective_profiles"] if key_of(profile) == key_of(spec["target_profile"]))
    target["selection_provenance"][spec["selection_index"]].update(spec["set"])
    return eps


class ProvenanceFailureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(ROOT / "profiles/contracts/effective-profile-set.schema.json")
        cls.validator = Draft202012Validator(cls.schema)

    def test_dependency_edge_with_wrong_manifest_pin_fails_semantically(self):
        eps = load_json(ROOT / "profiles/fixtures/invalid/effective-profile-set-bad-provenance.json")
        self.assertFalse(list(self.validator.iter_errors(eps)))
        self.assertEqual("PROFILE-EFFECTIVE-PROVENANCE-001", effective_provenance_error(eps))

    def test_forged_dependency_relation_and_range_fail_exact_code(self):
        fixture_dir = ROOT / "profiles/fixtures/semantic/provenance"
        for name in ["forged-dependency-relation.json", "forged-dependency-range.json"]:
            spec = load_json(fixture_dir / name)
            eps = mutate_dependency_fixture(spec)
            self.assertFalse(list(self.validator.iter_errors(eps)), name)
            self.assertEqual(spec["expected_error"], effective_provenance_error(eps), name)


if __name__ == "__main__":
    unittest.main()
