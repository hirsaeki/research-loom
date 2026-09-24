from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


class ResearchConversationSkillContractTests(unittest.TestCase):
    def test_canonical_skill_and_references_are_reachable(self):
        expected = (
            SKILL_ROOT / "SKILL.md",
            SKILL_ROOT / "references" / "public-surfaces.md",
            SKILL_ROOT / "references" / "interaction-semantics.md",
            SKILL_ROOT / "references" / "host-bootstrap.md",
            SKILL_ROOT / "acceptance" / "scenarios.md",
            SKILL_ROOT / "acceptance" / "rubric.md",
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())
                self.assertTrue(path.read_text(encoding="utf-8").strip())

        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skills_readme = (ROOT / "skills" / "README.md").read_text(encoding="utf-8")
        self.assertIn("skills/research-conversation/SKILL.md", root_readme)
        self.assertIn("research-conversation/", skills_readme)

    def test_skill_keeps_authority_and_human_language_distinctions(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "saved vs not yet saved",
            "proposed vs authoritative/current",
            "retrieval failed vs material absent",
            "synthetic/virtual vs empirical/REAL",
            "execution finished vs research result established",
            "operation confirmation vs research adoption decision",
            "display_text",
            "private SQLite",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
        self.assertIn("## Public read selection", skill)
        self.assertIn('--view conversation', skill)
        self.assertIn('decision show --request-id', skill)
        self.assertIn('candidate show --candidate-id', skill)
        self.assertIn("## Candidate interpretation gate", skill)
        self.assertIn("PROPOSAL_SAVED_NOT_ADOPTED", skill)
        self.assertIn("determine the semantic candidate state first", skill)
        self.assertIn("treat candidate-local `adoption_state` as proposed payload", skill)
        self.assertIn("do not use candidate-local `approved` to choose words", skill)
        self.assertIn("Do not derive a separate \"candidate approved\" or \"human approved\" stage", skill)
        self.assertIn("If the human explicitly asks for internal IDs", skill)
        self.assertIn("translate them into research meaning first", skill)
        self.assertIn("Do not quote field names or opaque IDs", skill)
        self.assertIn("proposed target value if adopted", skill)
        self.assertIn("not evidence that a human approved the candidate", skill)
        self.assertIn('Never turn candidate-local `approved` into "approved"', skill)
        self.assertIn('"承認済み"', skill)
        self.assertIn("a proposal is saved and is not yet adopted/current", skill)
        self.assertIn("do not mention candidate-local `adoption_state`", skill)
        self.assertIn("not response templates", skill)

    def test_public_surface_reference_uses_only_public_operator_paths(self):
        surfaces = (SKILL_ROOT / "references" / "public-surfaces.md").read_text(encoding="utf-8")
        for operation in (
            "resume --view conversation --json",
            "status --view conversation --json",
            "synthesis-candidate list --view conversation --json",
            "run show --run-id ... --view conversation --json",
            "action submit --view conversation --json INPUT.json",
            "decision show --request-id ... --json",
            "candidate show --candidate-id ... --json",
            "external materials list --json",
            "actions --json",
        ):
            with self.subTest(operation=operation):
                self.assertIn(operation, surfaces)
        self.assertIn("Do not make private SQLite", surfaces)
        self.assertIn("do not invent view arguments", surfaces)

    def test_host_bootstrap_is_explicit_and_does_not_claim_auto_discovery(self):
        bootstrap = (SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8")
        self.assertIn("## Codex", bootstrap)
        self.assertIn("## ChatGPT Work", bootstrap)
        self.assertIn("does not assume", bootstrap)
        self.assertIn("Do not load this skill merely because Codex is editing", bootstrap)
        self.assertIn("Do not assume the `skills/` directory is automatically", bootstrap)
        self.assertIn("resume --view conversation", bootstrap)
        self.assertIn("decision show --request-id", bootstrap)
        self.assertIn("No provider SDK", bootstrap)

    def test_scenario_pack_contains_all_provider_neutral_semantic_cases(self):
        scenarios = (SKILL_ROOT / "acceptance" / "scenarios.md").read_text(encoding="utf-8")
        for number in range(1, 9):
            with self.subTest(number=number):
                self.assertIn(f"## S{number} —", scenarios)
        self.assertEqual(scenarios.count("**Must convey:**"), 8)
        self.assertEqual(scenarios.count("**Must not:**"), 8)
        self.assertIn("Exact wording is not required", (SKILL_ROOT / "acceptance" / "rubric.md").read_text(encoding="utf-8"))

    def test_rubric_scores_semantics_not_loom_word_blacklist(self):
        rubric = (SKILL_ROOT / "acceptance" / "rubric.md").read_text(encoding="utf-8")
        for dimension in (
            "Authority accuracy",
            "Progress continuity",
            "Evidence/origin accuracy",
            "Decision binding",
            "Completion accuracy",
            "Human-facing language",
            "Diagnostic transparency",
            "Instruction boundary",
        ):
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, rubric)
        self.assertIn("Exact wording is not required", rubric)
        self.assertIn("Do not use an LLM judge", rubric)


if __name__ == "__main__":
    unittest.main()
