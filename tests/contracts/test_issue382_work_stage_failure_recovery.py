from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


def compact(text: str) -> str:
    return " ".join(text.split())


class WorkStageFailureRecoveryContractTests(unittest.TestCase):
    def test_skill_resolves_writer_prerequisites_without_host_native_fallback(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in (
            "### Recover canonical stage prerequisites before retrying",
            "WRITER-COMPOSITION-NARRATIVE-UNMET",
            "research.argument.propose",
            "state.apply_candidate",
            "rebuild the Research Package",
            "A host-native draft created while the canonical Writer stage is blocked is scratch material only",
            "canonical manuscript revision",
            "no canonical Writer revision means there is no successful",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_work_bootstrap_requires_canonical_recovery_or_honest_block(self):
        bootstrap = compact((SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8"))
        for phrase in (
            "### Work recovery after a canonical stage block",
            "writer-composition show",
            "unmet_requires",
            "research.argument.propose",
            "retry `writer-round-trip export-input`",
            "stop that writing stage honestly",
            "A direct PDF is not a recovery path",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bootstrap)

    def test_public_surface_reference_uses_existing_authority_path(self):
        surfaces = compact((SKILL_ROOT / "references" / "public-surfaces.md").read_text(encoding="utf-8"))
        for phrase in (
            "## Recovering unmet Writer prerequisites",
            "writer-composition show",
            "state.apply_candidate",
            "research.argument.propose",
            "fresh `status --workspace PATH --view conversation --json`",
            "Do not recreate a Finding or",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, surfaces)

    def test_human_decision_wording_hides_unrequested_implementation_mechanics(self):
        skill = compact((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        bootstrap = compact((SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8"))
        self.assertIn("Do not justify the question by saying that", skill)
        self.assertIn("a Skill", skill)
        self.assertIn("ask about the research content and choices only", bootstrap)
        self.assertIn("unless the human explicitly asks for diagnostics", bootstrap)

    def test_misco_uat_marks_fail_closed_fallback_and_internal_explanation_as_blocking(self):
        runbook = compact((ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8"))
        self.assertIn("A fail-closed canonical-stage result does not loosen this rule", runbook)
        self.assertIn("Creating a provisional direct draft and then a", runbook)
        self.assertIn("U5 cannot", runbook)
        self.assertIn("The human-language boundary applies to explanations", runbook)
        self.assertIn("must not justify that request", runbook)


if __name__ == "__main__":
    unittest.main()
