import unittest

from test_profile_contracts import ROOT, load_candidate, load_json, resolve_candidates


class VersionConflictContractTest(unittest.TestCase):
    def test_unsatisfied_transitive_ranges_return_profile_version_error(self):
        case_dir = ROOT / "profiles/fixtures/semantic/version-resolution"
        case = load_json(case_dir / "conflict-case.json")
        candidates = [load_candidate(case_dir / "candidates" / name) for name in case["candidate_files"]]
        output, error = resolve_candidates(candidates, case["requested_profiles"], case["core_contracts"])
        self.assertIsNone(output)
        self.assertEqual(case["expected_error"], error)


if __name__ == "__main__":
    unittest.main()
