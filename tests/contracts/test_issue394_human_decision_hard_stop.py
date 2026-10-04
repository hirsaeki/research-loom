from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


def compact(text: str) -> str:
    return " ".join(text.split())


class HumanDecisionHardStopContractTests(unittest.TestCase):
    def test_skill_requires_hard_stop_and_wait(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in (
            "user-visible hard stop",
            "Then end the visible turn and wait for the human answer",
            "Do not continue progress narration",
            "A human-relevant consequence remains allowed",
            "Then end the visible turn and wait",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_internal_instruction_links_and_rule_quotes_are_forbidden_as_justification(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in (
            "Never cite or link internal instruction/evaluator material",
            "SKILL.md",
            "AGENTS.md",
            "internal architecture/runbook documents",
            "local source paths",
            "Bind a human answer only to that issued request",
            "Internal attribution is evaluator evidence, not user-facing proof",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_bootstrap_enforces_same_hard_stop(self):
        bootstrap = compact((SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8"))
        for phrase in (
            "decision request as a conversational hard stop",
            "end the user-visible turn and wait",
            "Never cite/link `SKILL.md`, `AGENTS.md`",
            "never quote an internal binding rule as proof",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bootstrap)

    def test_uat_records_exact_2f73_failure(self):
        runbook = compact((ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8"))
        for phrase in (
            "ordinary Human Decision request is also a **hard stop**",
            "2f73d96d3bcaf686526d5935ee6e293d5a75744e",
            "research-conversation/SKILL.md",
            "Bind a human answer only to that issued request",
            "blocking G4 FAIL evidence",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, runbook)

    def test_explicit_later_diagnostics_still_allowed(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("If the human later explicitly asks why the confirmation was required", skill)
        self.assertIn("requests diagnostics/mechanics, explain the implementation accurately", skill)


if __name__ == "__main__":
    unittest.main()
