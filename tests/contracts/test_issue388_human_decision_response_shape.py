from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


def compact(text: str) -> str:
    return " ".join(text.split())


class HumanDecisionResponseShapeContractTests(unittest.TestCase):
    def test_skill_applies_content_only_rule_to_entire_decision_turn(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in (
            "### Ordinary Human Decision response shape",
            "entire user-visible turn",
            "any preamble before the question",
            "any follow-up explanation after the choices",
            "research content being decided",
            "meaningful choices available to the human",
            "human-relevant consequences",
            "do not name or link a Skill",
            "A natural question followed by an implementation preamble or postscript still violates this boundary",
            "only after the human explicitly asks for diagnostics",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_work_bootstrap_forbids_diagnostic_preamble_and_postscript(self):
        bootstrap = compact((SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8"))
        for phrase in (
            "whole user-visible response",
            "Do not prepend or append a diagnostic rationale",
            "Research Conversation Skill requires this",
            "internal exact-binding quotation",
            "research meaning, meaningful choices",
            "Only a later explicit human request for diagnostics/mechanics unlocks that explanation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bootstrap)

    def test_uat_marks_observed_skill_rationale_leak_as_blocking(self):
        runbook = compact((ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8"))
        for phrase in (
            "covers the entire ordinary decision response",
            "semantically good decision prompt is still a blocking failure",
            "Skill name/link",
            "quotes an internal binding rule",
            "research meaning + meaningful choices",
            "2026-10-04 R4 Codex run",
            "diagnostic G4 FAIL evidence",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, runbook)

    def test_explicit_diagnostics_remain_allowed(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        bootstrap = compact((SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8"))
        self.assertIn("explicitly asks for diagnostics, implementation details, or why the system is asking", skill)
        self.assertIn("Only a later explicit human request for diagnostics/mechanics", bootstrap)


if __name__ == "__main__":
    unittest.main()
