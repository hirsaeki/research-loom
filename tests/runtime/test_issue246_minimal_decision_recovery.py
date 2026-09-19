from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from test_local_workspace_application_cli import run_cli
from test_research_question_adoption import _init_workspace, _proposal_input


T1 = "2026-09-20T01:00:00Z"
T2 = "2026-09-20T02:00:00Z"


class MinimalDecisionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = _init_workspace(Path(self.temp.name))
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            proposed = facade.submit_action(_proposal_input())
            confirmation = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                "actor_id": "HUMAN-RQ",
            })
            request = facade.submit_confirmation({
                "confirmation_request_id": confirmation["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-RQ",
            })["decision_request"]
            self.intent = {
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-RQ",
            }
            self.before = facade.status()["snapshot"]

    def _fail(self, stage):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            app = facade._application
            original = app.decision_store.finalize

            def fail_finalize(*args, **kwargs):
                if stage == "after_finalize":
                    original(*args, **kwargs)
                raise OSError("injected interruption")

            target = app.state_transition_service if stage == "before_commit" else app.decision_store
            method = "apply" if stage == "before_commit" else "finalize"
            failure = OSError("injected interruption") if stage == "before_commit" else fail_finalize
            with patch.object(app.clock, "now", return_value=T1), patch.object(target, method, side_effect=failure):
                with self.assertRaisesRegex(OSError, "injected interruption"):
                    facade.resolve_human_decision(self.intent)
            return facade.status()["snapshot"]

    def _assert_recovered(self, stage):
        interrupted_snapshot = self._fail(stage)
        self.assertEqual(interrupted_snapshot == self.before, stage == "before_commit")
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            with patch.object(facade._application.clock, "now", return_value=T2):
                recovered = facade.resolve_human_decision(self.intent)
            self.assertEqual(recovered["status"], "RESOLVED")
            self.assertEqual(recovered["response"]["responded_at"], T1)
            after = facade.status()["snapshot"]
            self.assertNotEqual(after, self.before)
            repo = facade._application.state_repository
            state = repo.load_state_view(facade.project_id, repo.load_active_lineage_ref(facade.project_id))
            decisions = deepcopy(state.decisions)
            if stage != "before_commit":
                self.assertEqual(after, interrupted_snapshot)
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            # A second later replay must return the identical response and receipt,
            # not a second Snapshot, Decision, or approval timestamp.
            with patch.object(facade._application.clock, "now", return_value="2026-09-21T01:00:00Z"):
                reused = facade.resolve_human_decision(self.intent)
            self.assertEqual(reused["response"], recovered["response"])
            self.assertEqual(reused["commit_receipt"], recovered["commit_receipt"])
            self.assertEqual(facade.status()["snapshot"], after)
            repo = facade._application.state_repository
            state = repo.load_state_view(facade.project_id, repo.load_active_lineage_ref(facade.project_id))
            self.assertEqual(state.decisions, decisions)
            # The original full-response public path remains supported.
            exact = facade.resolve_human_decision(recovered["response"])
            self.assertEqual(exact["commit_receipt"], recovered["commit_receipt"])

    def test_before_state_commit(self):
        self._assert_recovered("before_commit")

    def test_after_state_commit_before_finalize(self):
        self._assert_recovered("before_finalize")

    def test_after_finalize_before_reply(self):
        self._assert_recovered("after_finalize")

    def test_cli_retry_needs_only_original_minimal_intent(self):
        self._fail("before_finalize")
        code, _raw, recovered = run_cli(
            ["decision", "resolve", "--workspace", str(self.workspace), "--json", "-"],
            stdin_text=json.dumps(self.intent),
        )
        self.assertEqual(code, 0, recovered)
        self.assertEqual(recovered["status"], "RESOLVED")
        self.assertEqual(recovered["response"]["responded_at"], T1)

    def test_changed_intent_cannot_take_over_claim(self):
        self._fail("before_finalize")
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            before = facade.status()["snapshot"]
            for field, value in (
                ("actor_id", "ANOTHER-HUMAN"),
                ("disposition", "decline"),
                ("request_digest", "sha256:" + "0" * 64),
            ):
                with self.subTest(field=field):
                    with self.assertRaises(LocalApplicationError) as raised:
                        facade.resolve_human_decision({**self.intent, field: value})
                    self.assertEqual(raised.exception.code, "APPLICATION-DECISION-BINDING-001")
                    self.assertEqual(facade.status()["snapshot"], before)
            self.assertEqual(facade.resolve_human_decision(self.intent)["status"], "RESOLVED")

    def test_claimed_response_missing_or_corrupt_is_not_recreated(self):
        self._fail("before_finalize")
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            store = facade._application.decision_store
            request_id = self.intent["request_id"]
            saved = store._db.execute(
                "SELECT payload_json FROM decision_responses WHERE request_id=?", (request_id,)
            ).fetchone()[0]
            before = facade.status()["snapshot"]
            for corrupt in ("{", "null", "{}", saved.replace(T1, T2)):
                with self.subTest(corrupt=corrupt[:40]):
                    store._db.execute("UPDATE decision_responses SET payload_json=? WHERE request_id=?", (corrupt, request_id))
                    with self.assertRaises(LocalApplicationError) as raised:
                        facade.resolve_human_decision(self.intent)
                    self.assertEqual(raised.exception.code, "APPLICATION-DECISION-RECOVERY-001")
                    self.assertEqual(facade.status()["snapshot"], before)
            store._db.execute("DELETE FROM decision_responses WHERE request_id=?", (request_id,))
            with self.assertRaises(LocalApplicationError) as raised:
                facade.resolve_human_decision(self.intent)
            self.assertEqual(raised.exception.code, "APPLICATION-DECISION-RECOVERY-001")
            self.assertEqual(facade.status()["snapshot"], before)

    def test_terminal_decline_and_revision_request_reuse_claimed_response(self):
        for disposition, status in (("decline", "DECLINED"), ("request_revision", "REVISION_REQUESTED")):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as temp:
                workspace = _init_workspace(Path(temp))
                with LocalApplicationFacade.open_workspace(workspace) as facade:
                    candidate = facade.submit_action(_proposal_input())
                    proposal = facade.submit_action({
                        "action_type": "state.apply_candidate",
                        "payload": {"state_delta_proposal_id": candidate["data"]["state_delta_proposal_id"]},
                        "actor_id": "HUMAN-RQ",
                    })
                    request = facade.submit_confirmation({
                        "confirmation_request_id": proposal["confirmation_request"]["confirmation_request_id"],
                        "actor_id": "HUMAN-RQ",
                    })["decision_request"]
                    intent = {**self.intent, "request_id": request["request_id"], "request_digest": request["request_digest"], "disposition": disposition}
                    before = facade.status()["snapshot"]
                    with patch.object(facade._application.clock, "now", return_value=T1):
                        first = facade.resolve_human_decision(intent)
                with LocalApplicationFacade.open_workspace(workspace) as facade:
                    with patch.object(facade._application.clock, "now", return_value=T2):
                        reused = facade.resolve_human_decision(intent)
                    self.assertEqual(reused["status"], status)
                    self.assertEqual(reused["response"], first["response"])
                    self.assertEqual(facade.status()["snapshot"], before)


if __name__ == "__main__":
    unittest.main()
