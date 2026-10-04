from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


def compact(text: str) -> str:
    return " ".join(text.split())


class OrdinaryTurnDomainLanguageContractTests(unittest.TestCase):
    def test_skill_applies_firewall_to_all_ordinary_user_visible_turns(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in (
            "### Ordinary user-visible turns are domain-language only",
            "every ordinary user-visible research, writing, progress, and output-check turn",
            "Do **not** volunteer implementation narration",
            "which Skill, Skill path, plugin, CLI command, or host capability will be used",
            "This applies to preambles, progress updates, completion summaries",
            "I will use the Writer Skill",
            "I will use the Documents/PDF Skill",
            "I will draft the requested sections from the saved material",
            "I will create an appearance-check document and inspect its pages",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_bootstrap_keeps_internal_route_out_of_progress_narration(self):
        bootstrap = compact((SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8"))
        for phrase in (
            "Do not narrate this route to the human",
            "checking the specified sources",
            "drafting the requested sections",
            "preparing an appearance-check document",
            "not the Skill, plugin, CLI command, capability",
            "This applies to preambles, progress updates, and completion summaries",
            "unless the human explicitly asks for diagnostics or implementation details",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bootstrap)

    def test_uat_marks_general_skill_narration_as_blocking(self):
        runbook = compact((ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8"))
        for phrase in (
            "all ordinary user-visible progress and completion narration",
            "A host fails G4 if it volunteers which Skill",
            "Say what research/writing/document-check action is happening instead",
            "research-conversation, Writer, Documents/PDF Skills",
            "blocking diagnostic evidence",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, runbook)

    def test_explicit_diagnostics_remain_available(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        runbook = compact((ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8"))
        self.assertIn("If the human explicitly asks how the system works", skill)
        self.assertIn("explicitly asks for diagnostics/mechanics", runbook)


if __name__ == "__main__":
    unittest.main()
