import unittest

from jsonschema import Draft202012Validator

from test_profile_contracts import ROOT, key_of, load_json, satisfies


def requested_presence_error(eps):
    for req in eps["requested_profiles"]:
        matches = [p for p in eps["effective_profiles"] if key_of(p) == key_of(req) and satisfies(p["profile_version"], req["version"])]
        if len(matches) != 1:
            return "PROFILE-EFFECTIVE-REQUEST-001"
        requested_edges = [s for s in matches[0]["selection_provenance"] if s["relation"] == "requested" and s["required_version"] == req["version"]]
        if len(requested_edges) != 1:
            return "PROFILE-EFFECTIVE-REQUEST-001"
    return None


class RequestedPresenceContractTest(unittest.TestCase):
    def test_valid_effective_set_has_each_direct_request(self):
        eps = load_json(ROOT / "profiles/fixtures/valid/effective-profile-set.json")
        self.assertIsNone(requested_presence_error(eps))

    def test_missing_direct_request_fails_with_exact_code(self):
        eps = load_json(ROOT / "profiles/fixtures/invalid/effective-profile-set-missing-requested.json")
        schema = load_json(ROOT / "profiles/contracts/effective-profile-set.schema.json")
        self.assertFalse(list(Draft202012Validator(schema).iter_errors(eps)))
        self.assertEqual("PROFILE-EFFECTIVE-REQUEST-001", requested_presence_error(eps))


if __name__ == "__main__":
    unittest.main()
