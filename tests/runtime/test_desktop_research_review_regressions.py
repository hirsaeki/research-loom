from __future__ import annotations

import unittest

from test_desktop_research import Flow


class DesktopResearchReviewRegressionTests(unittest.TestCase):
    def test_inaccessible_sources_preserve_unknown_gap_and_partial_coverage_in_proposal(self):
        flow = Flow(run_id="RUN-DR-INACCESSIBLE-REVIEW")
        try:
            handoff, extension = flow.build_inaccessible()
            result = flow.service.collect_external(
                flow.prepared.run.run_id,
                handoff,
                extension,
            )
            proposal = result.state_delta_proposal
            self.assertIsNotNone(proposal)

            kinds = {
                action.payload["object"]["kind"]
                for action in proposal.proposed_actions
            }
            self.assertNotIn("source", kinds)
            self.assertNotIn("evidence", kinds)

            desktop = proposal.provenance["desktop_research"]
            self.assertEqual(
                desktop["evidence_gap_assessments"][0]["materiality"],
                "unknown",
            )
            self.assertEqual(
                desktop["coverage_assessment"]["remaining_information_value"]
                ["level"],
                "unknown",
            )
            self.assertFalse(
                desktop["coverage_assessment"]["stopping_recommendation"]
                ["stop_recommended"]
            )
            self.assertEqual(
                desktop["handoff_outputs"]["unknowns"][0]["unknown_id"],
                "UNK-1",
            )
        finally:
            flow.close()


if __name__ == "__main__":
    unittest.main()
