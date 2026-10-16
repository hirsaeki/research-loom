import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WriterParagraphRoleContractTests(unittest.TestCase):
    """Check instruction coverage, not the semantic quality of generated prose."""

    def test_writer_and_host_require_targeted_edits_without_runtime_gate(self):
        writer = (ROOT / "skills/writer/SKILL.md").read_text(encoding="utf-8")
        host = (ROOT / "skills/research-conversation/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Each paragraph must advance one question, claim or contrast", writer)
        self.assertIn(
            "Coexistence of an argument and a qualification is not itself a violation", writer
        )
        self.assertIn("not a new Profile rule ID or a runtime gate", writer)
        self.assertIn("request a concrete edit", host)
        self.assertIn("necessary qualifications and supplied contrasts", host)
        self.assertIn("not a runtime gate on draft storage or Research", host)

    def test_placement_and_contrasts_preserve_the_argument(self):
        flow = (ROOT / "skills/writer/references/reader-flow.md").read_text(encoding="utf-8")
        for phrase in (
            "rather than defaulting to notes",
            "counterresults, counterarguments and alternative explanations in the body",
            "consolidate shared method limits",
            "Delete or consolidate repetition",
            "the exact paragraph, the competing jobs and the edit",
            "not detect the problem merely by counting caveat words",
            "Allowed qualification:",
            "Allowed contrast:",
            "Revise competing roles:",
            "not complete manuscripts or evidence of reader",
            "Do not force an argument/counterargument chapter order",
            "new Profile IDs, automatic prose classifier or semantic PASS",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flow)
