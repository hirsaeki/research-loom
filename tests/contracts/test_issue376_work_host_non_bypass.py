from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


class WorkHostNonBypassContractTests(unittest.TestCase):
    def test_research_conversation_skill_blocks_host_native_stage_substitution(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "not alternate persistence, provenance, Writer, or Publication paths",
            "Before an external research source informs analysis, synthesis, or prose",
            "Before manuscript drafting or revision",
            "Before telling the human that a pre-submission/appearance-check document is ready",
            "Do not silently substitute a host-native Markdown, DOCX, PDF, or image workflow",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_work_bootstrap_routes_each_stage_through_existing_public_operations(self):
        bootstrap = (SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8")
        for phrase in (
            "### Work non-bypass route",
            "external materials list --json",
            "research-package build/show",
            "writer-composition capture/select",
            "writer-round-trip export-input/import-response/inspect",
            "publication preview",
            "publication show",
            "downstream presentation helpers, not a substitute Publication path",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bootstrap)

    def test_public_surface_reference_names_stage_boundaries_and_failure_semantics(self):
        surfaces = (SKILL_ROOT / "references" / "public-surfaces.md").read_text(encoding="utf-8")
        for operation in (
            "research-package build --workspace PATH --json INPUT.json",
            "research-package show --workspace PATH --package-id ... --json",
            "writer-composition capture --workspace PATH --package-id ... --json INPUT.json",
            "writer-round-trip export-input",
            "writer-round-trip import-response",
            "writer-round-trip inspect",
            "publication preview --workspace PATH --composition-id ... [--revision-id ...] --json",
            "publication show --workspace PATH --build-id ... --json",
        ):
            with self.subTest(operation=operation):
                self.assertIn(operation, surfaces)
        self.assertIn("host-generated Markdown, DOCX, PDF, or image", surfaces)
        self.assertIn("must not be reported as successful completion", surfaces)

    def test_misco_live_uat_treats_host_native_bypass_as_blocking(self):
        runbook = (ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8")
        self.assertIn("blocking bypass", runbook)
        self.assertIn("external research material must be captured", runbook)
        self.assertIn("Research Package /", runbook)
        self.assertIn("Writer round-trip", runbook)
        self.assertIn("canonical Publication preview", runbook)
        self.assertIn("polished Markdown/PDF result does not repair", runbook)


if __name__ == "__main__":
    unittest.main()
