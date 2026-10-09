from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = ROOT / "skills/research-conversation"


def read(path):
    return " ".join(path.read_text(encoding="utf-8").split())


class SupportedConclusionContractTests(unittest.TestCase):
    """Rule/contrast coverage, not a semantic grader of generated prose."""

    def test_host_preserves_answer_reasoning_limits_and_authority(self):
        skill = read(CONVERSATION / "SKILL.md")
        for phrase in (
            "best-supported answer", "principal evidence and warrant",
            "observation, comparison, interpretation and value judgement",
            "qualifications that change its truth or strength near the conclusion",
            "overstatement and conclusion-erasure / non-answer",
            "retain the supported central conclusion", "no direction is currently supported",
            "incomplete investigation from genuine equipoise", "fixed template",
            "Mark an unadopted conclusion as a proposal", "exact Decision binding",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_writer_returns_gaps_without_creating_meaning_or_profile_policy(self):
        skill = read(ROOT / "skills/writer/SKILL.md")
        for phrase in (
            "Preserve claim strength in both directions", "principal evidence and warrant",
            "central research judgement, warrant or applicability conditions are missing",
            "section-targeted Writing Feedback", "inspect existing analysis and its links first",
            "does not silently amend approved MISCO Writer rules",
            "exact delivered inventory and pins", "writer-round-trip import-response",
            "Do not create new Evidence", "Human Decision/Confirmation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_semantic_contrasts_cover_both_strength_errors_and_legitimate_non_direction(self):
        scenarios = read(CONVERSATION / "acceptance/scenarios.md")
        for phrase in (
            "## S11 —", "## S12 —", "## S13 —", "## S14 —",
            "overstatement", "conclusion-erasure", "slogan", "supported",
            "FAIL: unsupported UI-only causality", "FAIL: correct caveats replace",
            "100 to 80 minutes (20% reduction)", "S13-balanced", "S13-insufficient",
            "S14-missing", "one at a time", "target-population or market-condition limits",
            "Baseline Skill is that removal control", "baseline that already passes",
            "unchanged initial outputs", "no real research workspace",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, scenarios)

    def test_rubric_rejects_non_answers_without_relaxing_authority(self):
        rubric = read(CONVERSATION / "acceptance/rubric.md")
        for phrase in (
            "Supported answer and reasoning", "Both overstatement and conclusion-erasure / non-answer are FAIL",
            "first output", "without an invented direction", "Writing Feedback",
            "exact Human Decision/Confirmation and Writer round-trip", "not independent human acceptance",
            "Do not use an LLM judge",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, rubric)


if __name__ == "__main__":
    unittest.main()
