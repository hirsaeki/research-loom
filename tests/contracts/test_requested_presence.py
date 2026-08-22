import unittest

from jsonschema import Draft202012Validator

from semantic_oracle import ROOT, key_of, load_json, requested_presence_error


def mutate_requested_fixture(spec):
    eps = load_json(ROOT / spec["base"])
    target = next(profile for profile in eps["effective_profiles"] if key_of(profile) == key_of(spec["target_profile"]))
    target["selection_provenance"].append(spec["append_selection_provenance"])
    return eps


class RequestedPresenceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(ROOT / "profiles/contracts/effective-profile-set.schema.json")
        cls.validator = Draft202012Validator(cls.schema)

    def test_valid_effective_set_has_exact_bidirectional_direct_request_provenance(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        self.assertIsNone(requested_presence_error(eps))

    def test_missing_direct_request_fails_with_exact_code(self):
        eps = load_json(ROOT / "profiles/fixtures/invalid/effective-profile-set-missing-requested.json")
        self.assertFalse(list(self.validator.iter_errors(eps)))
        self.assertEqual("PROFILE-EFFECTIVE-REQUEST-001", requested_presence_error(eps))

    def test_fabricated_requested_provenance_fails_with_exact_code(self):
        spec = load_json(ROOT / "profiles/fixtures/semantic/provenance/fabricated-request.json")
        eps = mutate_requested_fixture(spec)
        self.assertFalse(list(self.validator.iter_errors(eps)))
        self.assertEqual(spec["expected_error"], requested_presence_error(eps))


if __name__ == "__main__":
    unittest.main()
