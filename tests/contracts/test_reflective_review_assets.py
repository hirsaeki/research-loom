"""Reflective Review comparison assets stay complete and consistent (#590)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "skills" / "research-conversation" / "acceptance"


def _read(name: str) -> str:
    return (ACCEPTANCE / name).read_text(encoding="utf-8")


class ReflectiveReviewAssetTests(unittest.TestCase):
    def test_every_case_has_an_expectation_and_the_reverse(self):
        cases = set(re.findall(r"^## (RR\d+) —", _read("reflective-review-cases.md"), re.M))
        expected = set(
            re.findall(r"^\| (RR\d+) \|", _read("reflective-review-expectations.md"), re.M)
        )
        self.assertEqual(cases, expected)
        self.assertTrue(6 <= len(cases) <= 8, sorted(cases))

    def test_cases_freeze_the_inputs_a_reviewer_needs(self):
        sections = re.split(r"^## RR\d+ —", _read("reflective-review-cases.md"), flags=re.M)[1:]
        for index, section in enumerate(sections, start=1):
            for field in ("**Request**", "**Target**", "**Facts**", "**State**"):
                with self.subTest(case=index, field=field):
                    self.assertIn(field, section)

    def test_expected_findings_stay_out_of_the_case_inputs(self):
        sections = re.split(r"^## RR\d+ —", _read("reflective-review-cases.md"), flags=re.M)[1:]
        for index, section in enumerate(sections, start=1):
            for leak in ("Expected", "Must not", "Cross-check", "PASS", "FAIL"):
                with self.subTest(case=index, leak=leak):
                    self.assertNotIn(leak, section)

    def test_rubric_scores_the_two_lenses_separately(self):
        rubric = _read("rubric.md")
        self.assertIn("## Reflective review lenses (#590)", rubric)
        self.assertIn("**Purpose fit**", rubric)
        self.assertIn("**Meaning fidelity**", rubric)
        self.assertIn("Never add them into one total", rubric)

    def test_protocol_defines_conditions_budget_and_a_no_adoption_path(self):
        protocol = _read("reflective-review.md")
        for phrase in (
            "**A, no review.**",
            "**B, review with the long working context.**",
            "**C, review with a narrowed, separate context.**",
            "at most two review calls and at most one revision",
            "never counts as a pass",
            "do not introduce a standing review loop",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, protocol)


if __name__ == "__main__":
    unittest.main()
