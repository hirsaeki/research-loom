from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade
from test_research_question_adoption import _init_workspace, _proposal_input


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


class Issue324ResearchConversationMutationContractTests(unittest.TestCase):
    def test_canonical_reference_exposes_minimal_adoption_inputs(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        surfaces = (SKILL_ROOT / "references" / "public-surfaces.md").read_text(encoding="utf-8")

        self.assertIn("minimal transport inputs documented in `references/public-surfaces.md`", skill)
        self.assertIn('"action_type": "state.apply_candidate"', surfaces)
        self.assertIn('"state_delta_proposal_id": "<exact saved candidate_id>"', surfaces)
        self.assertIn('"confirmation_request_id": "<exact issued confirmation_request_id>"', surfaces)
        self.assertIn('"request_id": "<exact issued request_id>"', surfaces)
        self.assertIn('"request_digest": "<exact issued request_digest>"', surfaces)
        self.assertIn('"actor_id": "<exact request human_actor_id>"', surfaces)
        for disposition in ("approve_exact", "decline", "request_revision"):
            self.assertIn(disposition, surfaces)
        for unsupported in ("`approve`", "`APPROVE`", "`adopt`"):
            self.assertIn(unsupported, surfaces)
        self.assertIn("do not guess field names", surfaces)
        self.assertIn("ordinary human-facing progress", surfaces)

    def test_documented_happy_path_matches_public_facade_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                candidate = facade.submit_action(
                    _proposal_input(),
                    view="conversation",
                )["candidate"]

                applied = facade.submit_action(
                    {
                        "action_type": "state.apply_candidate",
                        "payload": {
                            "state_delta_proposal_id": candidate["candidate_id"],
                        },
                        "actor_id": "HUMAN-RQ",
                    },
                    view="conversation",
                )
                self.assertEqual(applied["status"], "CONFIRMATION_REQUIRED")

                confirmed = facade.submit_confirmation(
                    {
                        "confirmation_request_id": applied["confirmation_required"][
                            "confirmation_request_id"
                        ],
                        "actor_id": "HUMAN-RQ",
                    },
                    view="conversation",
                )
                self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")

                decision_ref = confirmed["human_decision_required"]
                exact = facade.show_human_decision_request(decision_ref["request_id"])
                request = exact["request"]
                self.assertEqual(request["request_digest"], decision_ref["request_digest"])
                self.assertEqual(request["human_actor_id"], "HUMAN-RQ")

                resolved = facade.resolve_human_decision(
                    {
                        "request_id": request["request_id"],
                        "request_digest": request["request_digest"],
                        "disposition": "approve_exact",
                        "actor_id": request["human_actor_id"],
                    },
                    view="conversation",
                )
                self.assertEqual(resolved["status"], "RESOLVED")

                resumed = facade.resume_context(view="conversation")
                authoritative = resumed["research_questions"]["authoritative"]
                self.assertTrue(authoritative)
                self.assertEqual(
                    authoritative[0]["text"],
                    _proposal_input()["payload"]["text"],
                )


if __name__ == "__main__":
    unittest.main()
