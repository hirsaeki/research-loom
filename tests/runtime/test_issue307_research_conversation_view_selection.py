from __future__ import annotations

from pathlib import Path
import inspect
import tempfile
import unittest

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.cli import build_parser
from test_research_question_adoption import _init_workspace, _proposal_input


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "research-conversation"


class Issue307ResearchConversationViewSelectionTests(unittest.TestCase):
    def test_canonical_docs_select_conversation_for_normal_and_exact_detail_for_authority(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        surfaces = (SKILL_ROOT / "references" / "public-surfaces.md").read_text(encoding="utf-8")
        bootstrap = (SKILL_ROOT / "references" / "host-bootstrap.md").read_text(encoding="utf-8")
        semantics = (SKILL_ROOT / "references" / "interaction-semantics.md").read_text(encoding="utf-8")
        scenarios = (SKILL_ROOT / "acceptance" / "scenarios.md").read_text(encoding="utf-8")
        rubric = (SKILL_ROOT / "acceptance" / "rubric.md").read_text(encoding="utf-8")

        for text in (skill, surfaces, bootstrap, semantics):
            self.assertIn("conversation", text)
        self.assertIn("--view conversation", skill)
        self.assertIn("--view conversation", surfaces)
        self.assertIn("decision show --request-id", skill)
        self.assertIn("candidate show --candidate-id", skill)
        self.assertIn("decision show --request-id", surfaces)
        self.assertIn("candidate show --candidate-id", surfaces)
        self.assertIn("request_id + request_digest + actor_id + disposition", surfaces)
        self.assertIn("do not invent view arguments", surfaces)
        self.assertIn("same session", semantics)
        self.assertIn("adoption_state=approved", scenarios)
        self.assertIn("silently falls back", rubric)

    def test_documented_cli_routes_are_real_and_view_scope_is_not_invented(self):
        parser = build_parser()
        commands = (
            ["resume", "--workspace", "W", "--view", "conversation", "--json"],
            ["status", "--workspace", "W", "--view", "conversation", "--json"],
            ["synthesis-candidate", "list", "--workspace", "W", "--view", "conversation", "--json"],
            ["synthesis-candidate", "show", "--workspace", "W", "--candidate-id", "SDP-1", "--view", "conversation", "--json"],
            ["run", "show", "--workspace", "W", "--run-id", "RUN-1", "--view", "conversation", "--json"],
            ["run", "replay", "--workspace", "W", "--run-id", "RUN-1", "--view", "conversation", "--json"],
            ["action", "submit", "--workspace", "W", "--view", "conversation", "--json", "input.json"],
            ["confirmation", "submit", "--workspace", "W", "--view", "conversation", "--json", "input.json"],
            ["decision", "resolve", "--workspace", "W", "--view", "conversation", "--json", "input.json"],
            ["external", "collect", "--workspace", "W", "--run-id", "RUN-1", "--view", "conversation", "--json", "input.json"],
            ["candidate", "show", "--workspace", "W", "--candidate-id", "SDP-1", "--json"],
            ["decision", "show", "--workspace", "W", "--request-id", "HDR-1", "--json"],
        )
        for argv in commands:
            with self.subTest(argv=argv):
                parser.parse_args(argv)

        # Public contracts that did not add a view must stay view-free.
        for argv in (
            ["actions", "--workspace", "W", "--view", "conversation", "--json"],
            ["external", "materials", "list", "--workspace", "W", "--view", "conversation", "--json"],
        ):
            with self.subTest(rejected=argv), self.assertRaises(Exception):
                parser.parse_args(argv)

    def test_python_public_methods_match_the_documented_view_contract(self):
        for name in (
            "resume_context",
            "status",
            "list_synthesis_candidates",
            "show_synthesis_candidate",
            "show_run",
            "replay_completed_desktop_research_run",
            "submit_action",
            "submit_confirmation",
            "resolve_human_decision",
            "collect_external",
        ):
            with self.subTest(name=name):
                self.assertIn("view", inspect.signature(getattr(LocalApplicationFacade, name)).parameters)
        self.assertNotIn("view", inspect.signature(LocalApplicationFacade.show_candidate).parameters)
        self.assertNotIn("view", inspect.signature(LocalApplicationFacade.show_human_decision_request).parameters)

    def test_live_candidate_flow_uses_conversation_then_exact_detail_without_changing_canonical_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                normal = facade.submit_action(
                    _proposal_input(text="approved remains canonical target text"),
                    view="conversation",
                )
                candidate_id = normal["candidate"]["candidate_id"]
                self.assertNotIn("data", normal)
                self.assertNotIn("state_delta_proposal", normal)
                self.assertEqual(
                    normal["candidate"]["content"][0]["content"]["text"],
                    "approved remains canonical target text",
                )

                exact = facade.show_candidate(candidate_id)["candidate"]
                self.assertEqual(exact["proposal_id"], candidate_id)
                self.assertEqual(exact["candidate_only"], True)
                target = exact["proposed_actions"][0]["payload"]["object"]
                self.assertEqual(target["adoption_state"], "approved")
                self.assertEqual(target["text"], "approved remains canonical target text")
                unsigned = dict(exact)
                digest = unsigned.pop("proposal_digest")
                self.assertEqual(canonical_digest(unsigned), digest)

                # Reading exact detail in-session does not change the later normal read model.
                resumed = facade.resume_context(view="conversation")
                serialized = repr(resumed)
                self.assertNotIn("'adoption_state'", serialized)
                self.assertNotIn("'proposed_actions'", serialized)
                self.assertNotIn("'candidate_value'", serialized)

    def test_decision_boundary_uses_conversation_reference_then_exact_issued_request(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                candidate = facade.submit_action(_proposal_input(), view="conversation")["candidate"]
                apply = facade.submit_action(
                    {
                        "action_type": "state.apply_candidate",
                        "payload": {"state_delta_proposal_id": candidate["candidate_id"]},
                        "actor_id": "HUMAN-RQ",
                    },
                    view="conversation",
                )
                self.assertEqual(apply["status"], "CONFIRMATION_REQUIRED")
                confirmed = facade.submit_confirmation(
                    {
                        "confirmation_request_id": apply["confirmation_required"]["confirmation_request_id"],
                        "actor_id": "HUMAN-RQ",
                    },
                    view="conversation",
                )
                decision_ref = confirmed["human_decision_required"]
                exact = facade.show_human_decision_request(decision_ref["request_id"])
                self.assertEqual(exact["request"]["request_id"], decision_ref["request_id"])
                self.assertEqual(exact["request"]["request_digest"], decision_ref["request_digest"])
                self.assertEqual(
                    exact["request"]["source_state_delta_proposal"]["proposal_id"],
                    candidate["candidate_id"],
                )
                self.assertEqual(exact["request"]["status"], "PENDING")
                self.assertEqual(exact["operational"]["status"], "PENDING")

                # The human-facing pending view remains semantic even after exact inspection.
                status = facade.status(view="conversation")
                pending = next(
                    item for item in status["pending_human_decisions"]
                    if item["request_id"] == decision_ref["request_id"]
                )
                self.assertEqual(pending["operational_status"], "PENDING")
                self.assertNotIn("target_actions", repr(status))
                self.assertNotIn("candidate_value", repr(status))


if __name__ == "__main__":
    unittest.main()
