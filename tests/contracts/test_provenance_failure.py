import unittest

from jsonschema import Draft202012Validator

from test_profile_contracts import ROOT, effective_provenance_error, load_json


class ProvenanceFailureContractTest(unittest.TestCase):
    def test_dependency_edge_with_wrong_manifest_pin_fails_semantically(self):
        eps = load_json(ROOT / "profiles/fixtures/invalid/effective-profile-set-bad-provenance.json")
        schema = load_json(ROOT / "profiles/contracts/effective-profile-set.schema.json")
        self.assertFalse(list(Draft202012Validator(schema).iter_errors(eps)))
        self.assertEqual("PROFILE-EFFECTIVE-PROVENANCE-001", effective_provenance_error(eps))


if __name__ == "__main__":
    unittest.main()
