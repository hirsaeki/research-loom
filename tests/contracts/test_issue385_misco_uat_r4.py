from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md"


class MiscoUatR4ContractTests(unittest.TestCase):
    def test_r4_is_canonical_and_changes_u2_only(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("#337 UAT-02R4", text)
        self.assertIn("UAT-02R4 changes **U2 only relative to R3**", text)
        self.assertIn("U1 and U3-U8 are unchanged from R3", text)
        self.assertNotIn("U2.5", text)

    def test_u2_explicitly_requires_actual_source_inspection(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn(
            "この3資料を実際に確認して、今回の問いに関係する根拠・適用上の限界・まだ分からない点を整理してください。",
            text,
        )
        self.assertIn("retrieve/capture and actually inspect/read the fixed material", text)
        self.assertIn("merely registering the source", text)
        self.assertIn("scope or confirming official landing pages does not satisfy U2", text)

    def test_rq_authority_precedes_source_analysis_without_internal_human_interface(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("research question is not yet authoritative", text)
        self.assertIn("first asks the meaningful research decision in ordinary", text)
        self.assertIn("without exposing internal", text)
        self.assertIn("making the human prescribe the operation", text)

    def test_r3_u2_cannot_be_reused_as_r4_prefix(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("already executed R3 U2 cannot continue as R4", text)
        self.assertIn("final Codex and", text)
        self.assertIn("ChatGPT Work records start fresh from U1", text)


if __name__ == "__main__":
    unittest.main()
