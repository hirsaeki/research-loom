from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills/research-conversation"


def read(relative):
    return " ".join((SKILL_ROOT / relative).read_text(encoding="utf-8").split())


class InitialProgressSemanticsTests(unittest.TestCase):
    """Contract coverage only: these tests do not grade generated host prose."""

    def test_first_artifact_and_diagnosis_contract(self):
        skill = read("SKILL.md")
        for phrase in (
            "On the **first save**", "before internal audit details",
            "Machine-only logs", "what is done and not done",
            "what the stop does and does not establish", "worker's next action",
            "whether a human decision is needed now", "Research-content gap",
            "Writing-input record gap", "Authority or operation constraint",
            "alone does not establish a research-content gap",
            "If the cause is undiagnosed", "not new backend state enums",
            "Skill citations are not a substitute",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_delta_keeps_exact_authority_and_diagnostic_control(self):
        skill = read("SKILL.md")
        for phrase in (
            "already adopted content", "research-content additions or changes",
            "permission for this operation or record", "difference is zero",
            "specific change and its reservations", "zero content difference does not supply missing authority",
            "unissued request", "stale checks", "state.apply_candidate",
            "formal Writer/Publication paths", "explicitly requests diagnostics",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_shared_bootstrap_and_existing_acceptance_dimensions(self):
        bootstrap = read("references/host-bootstrap.md")
        self.assertIn("For both Codex and Work", bootstrap)
        self.assertIn("first saved researcher-readable Markdown", bootstrap)
        self.assertIn("after inspecting the exact issued request", bootstrap)
        rubric = read("acceptance/rubric.md")
        for phrase in ("first save", "Semantic misdiagnosis", "dependence on a user's correction",
                       "not LLM response quality", "Zero delta never bypasses", "S7"):
            self.assertIn(phrase, rubric)
        runbook = (ROOT / "docs/architecture/misco-integrated-acceptance.md").read_text(encoding="utf-8")
        self.assertIn("existing G4/G5 explanation criteria", runbook)
        self.assertIn("maximum two cases", runbook)

    def test_frozen_contrasts_and_bounded_ablation_coverage(self):
        scenarios = read("acceptance/scenarios.md")
        for phrase in (
            "S9-content", "S9-mixed", "S9-unknown", "S10-zero", "S10-change", "S10-unissued",
            "Source sufficiency has not been assessed", "lacks its primary source and supporting inference",
            "small exploratory sample", "Negative control", "Score the first saved bytes",
            "remove each added obligation in turn", "Keep authority requirements in every variant",
            "at most two frozen cases", "never current research", "not model response quality",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, scenarios)


if __name__ == "__main__":
    unittest.main()
