from __future__ import annotations

from copy import deepcopy
import io
from pathlib import Path
from contextlib import redirect_stdout
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade, LocalApplicationError
from plugins.local_application.cli import main as cli_main
from plugins.local_application.conversation_view import ConversationViewError
import test_issue92_external_submission_preflight as external_tests
import test_issue293_synthesis_candidate_discovery as synthesis_tests
import test_issue134_argument_proposal as argument_tests
import test_issue135_recommendation_proposal as recommendation_tests
from test_research_question_adoption import _init_workspace, _proposal_input
from test_research_question_batch_adoption import (
    _apply_to_decision,
    _batch_input,
    _five_questions,
    _question,
    _resolve,
)
from test_research_question_review import _adopt_question, _workspace


_RAW_TARGET_KEYS = {
    "proposal",
    "data",
    "state_delta_proposal",
    "candidate_projection",
    "current_value",
    "candidate_value",
    "target_actions",
    "proposed_actions",
    "adoption_state",
    "research_question_candidate",
    "recommendation_candidate",
    "argument_candidate",
    "execution_result",
    "presentations",
}


def _keys(value):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.append(key)
            found.extend(_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_keys(item))
    return found


def _assert_no_raw_target(test: unittest.TestCase, value) -> None:
    leaked = sorted(set(_keys(value)) & _RAW_TARGET_KEYS)
    test.assertEqual(leaked, [], f"raw target keys leaked: {leaked}")


def _run_cli(argv: list[str]):
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli_main(argv)
    import json
    return code, json.loads(output.getvalue())


class Issue306ConversationViewTests(unittest.TestCase):
    def test_default_and_explicit_detail_preserve_existing_read_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                self.assertEqual(facade.status(), facade.status(view="detail"))
                self.assertEqual(facade.resume_context(), facade.resume_context(view="detail"))

                helper = recommendation_tests.Issue135RecommendationProposalTests()
            # Synthesis detail contract is covered with a purpose-built workspace.
            facade = helper.make_facade(temp)
            try:
                result = facade.submit_action(helper.proposal_input())
                synth_id = result["data"]["state_delta_proposal_id"]
                self.assertEqual(
                    facade.list_synthesis_candidates(),
                    facade.list_synthesis_candidates(view="detail"),
                )
                self.assertEqual(
                    facade.show_synthesis_candidate(synth_id),
                    facade.show_synthesis_candidate(synth_id, view="detail"),
                )
            finally:
                facade.close()

            # #305 exact detail reads stay exact-only and are unaffected by view support.
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                self.assertEqual(
                    facade.show_candidate(candidate_id)["candidate"],
                    proposed["data"]["state_delta_proposal"],
                )

    def test_rq_single_batch_and_review_views_preserve_semantics_without_raw_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                single = facade.submit_action(
                    _proposal_input(text="approved is legitimate research text"),
                    view="conversation",
                )
                _assert_no_raw_target(self, single)
                self.assertEqual(
                    single["candidate"]["content"][0]["content"]["text"],
                    "approved is legitimate research text",
                )
                self.assertFalse(
                    single["candidate"]["current_relation"]["subjects"][0]["current_value_present"]
                )

                batch = facade.submit_action(
                    _batch_input(_question("Batch A"), _question("Batch B")),
                    view="conversation",
                )
                _assert_no_raw_target(self, batch)
                self.assertEqual(len(batch["candidate"]["content"]), 2)

        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                q1 = _adopt_question(facade, "Q1")
                q2 = _adopt_question(facade, "Q2")
                keep = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {"operation": "KEEP", "question_ids": [q1], "rationale": "still valid"},
                    "actor_id": "H",
                }, view="conversation")
                _assert_no_raw_target(self, keep)
                self.assertNotIn("candidate", keep)
                self.assertEqual(keep["question_review"]["operation"], "KEEP")
                self.assertFalse(keep["question_review"]["material_change"])

                payloads = [
                    {"operation": "REFINE", "question_ids": [q1], "rationale": "narrow", "text": "approved stays in text"},
                    {"operation": "CLOSE", "question_ids": [q2], "rationale": "answered"},
                    {"operation": "SPLIT", "question_ids": [q1], "rationale": "two decisions", "questions": [{"text": "Q1a"}, {"text": "Q1b"}]},
                    {"operation": "MERGE", "question_ids": [q1, q2], "rationale": "same decision", "text": "Merged"},
                ]
                for payload in payloads:
                    with self.subTest(operation=payload["operation"]):
                        result = facade.submit_action({
                            "action_type": "research_question.review",
                            "payload": payload,
                            "actor_id": "H",
                        }, view="conversation")
                        _assert_no_raw_target(self, result)
                        self.assertEqual(
                            result["candidate"]["question_review_operation"], payload["operation"]
                        )
                        self.assertTrue(
                            all("current_status" not in item["content"] for item in result["candidate"]["content"])
                        )
                refine = next(
                    item for item in facade.resume_context(view="conversation")["research_questions"]["candidates"]
                    if item.get("question_review_operation") == "REFINE"
                )
                _assert_no_raw_target(self, refine)
                self.assertEqual(refine["content"][0]["text"], "approved stays in text")

    def test_recommendation_argument_and_synthesis_views_are_semantic_and_detail_reachable(self):
        helper = recommendation_tests.Issue135RecommendationProposalTests()
        with tempfile.TemporaryDirectory() as temp:
            facade = helper.make_facade(temp)
            try:
                result = facade.submit_action(helper.proposal_input(), view="conversation")
                _assert_no_raw_target(self, result)
                candidate_id = result["candidate"]["candidate_id"]
                exact = facade.show_candidate(candidate_id)["candidate"]
                self.assertEqual(exact["proposal_id"], candidate_id)
                listing = facade.list_synthesis_candidates(view="conversation")
                shown = facade.show_synthesis_candidate(candidate_id, view="conversation")
                _assert_no_raw_target(self, listing)
                _assert_no_raw_target(self, shown)
                self.assertEqual(shown["content"]["statement"], result["candidate"]["content"][0]["content"]["statement"])
            finally:
                facade.close()

        helper = argument_tests.Issue134ArgumentProposalTests()
        with tempfile.TemporaryDirectory() as temp:
            facade = helper.make_facade(temp)
            try:
                result = facade.submit_action(helper.proposal_input(), view="conversation")
                _assert_no_raw_target(self, result)
                argument = result["candidate"]["content"][0]["content"]
                self.assertIn("conclusion", argument)
                self.assertIn("warrant", argument)
                self.assertNotIn("current_status", argument)
            finally:
                facade.close()

    def test_confirmation_decision_status_and_exact_detail_keep_authority_binding_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                candidate = facade.submit_action(_proposal_input(), view="conversation")["candidate"]
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": candidate["candidate_id"]},
                    "actor_id": "HUMAN-RQ",
                }, view="conversation")
                _assert_no_raw_target(self, apply)
                self.assertEqual(apply["status"], "CONFIRMATION_REQUIRED")

                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_required"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                }, view="conversation")
                _assert_no_raw_target(self, confirmed)
                decision = confirmed["human_decision_required"]
                self.assertEqual(decision["issued_status"], "PENDING")
                self.assertEqual(decision["operational_status"], "PENDING")
                exact = facade.show_human_decision_request(decision["request_id"])
                self.assertEqual(exact["request"]["request_digest"], decision["request_digest"])
                self.assertEqual(
                    exact["request"]["source_state_delta_proposal"]["proposal_id"],
                    decision["source_candidate"]["candidate_id"],
                )

                status = facade.status(view="conversation")
                _assert_no_raw_target(self, status)
                pending = next(item for item in status["pending_human_decisions"] if item["request_id"] == decision["request_id"])
                self.assertEqual(pending["operational_status"], "PENDING")

                resolved = facade.resolve_human_decision({
                    "request_id": decision["request_id"],
                    "request_digest": decision["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-RQ",
                }, view="conversation")
                _assert_no_raw_target(self, resolved)
                self.assertEqual(resolved["status"], "RESOLVED")
                self.assertEqual(resolved["request"]["issued_status"], "PENDING")
                self.assertIn("commit_id", resolved["commit"])

    def test_historical_and_new_revision_relations_are_observations_not_adoption_claims(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_batch_input(*_five_questions()))
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                _, confirmed = _apply_to_decision(facade, candidate_id)
                _resolve(facade, confirmed["decision_request"], "approve_exact")
                row = next(
                    item for item in facade.resume_context(view="conversation")["research_questions"]["candidates"]
                    if item["candidate_id"] == candidate_id
                )
                self.assertFalse(row["current_relation"]["bound_to_current_snapshot"])
                self.assertTrue(all(item["current_value_present"] for item in row["current_relation"]["subjects"]))
                self.assertNotIn("adopted", row)
                self.assertNotIn("approved", row)

        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                qid = _adopt_question(facade)
                refined = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {"operation": "REFINE", "question_ids": [qid], "rationale": "r", "text": "new revision"},
                    "actor_id": "H",
                }, view="conversation")
                relation = refined["candidate"]["current_relation"]["subjects"][0]
                self.assertTrue(relation["current_value_present"])
                self.assertFalse(relation["candidate_value_matches_current"])

    def test_desktop_research_collect_and_run_views_preserve_research_gaps_without_raw_candidate(self):
        helper = external_tests.Issue92ExternalSubmissionPreflightTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _app, facade = helper.make_facade(root)
            try:
                run_id, result_input, _capture = helper.prepared(root, facade)
                before = facade.show_run(run_id, view="conversation")
                _assert_no_raw_target(self, before)
                self.assertEqual(before["run"]["execution_mode"], "real")
                collected = facade.collect_external(run_id, {"research_result": result_input}, view="conversation")
                _assert_no_raw_target(self, collected)
                self.assertTrue(collected["normalized_candidate_available"])
                self.assertEqual(collected["research_context"]["coverage_assessment"]["stopping_recommendation"]["research_completion_claimed"], False)
                self.assertTrue(collected["research_outputs"]["evidence_gaps"])
                after = facade.show_run(run_id, view="conversation")
                _assert_no_raw_target(self, after)
                self.assertEqual(after["run"]["status"], "COMPLETED")
                self.assertEqual(after["finding_recovery"]["status"], "NOT_RECOVERABLE")
            finally:
                facade.close()


    def test_rejected_or_correctable_external_result_does_not_invent_candidate_or_success(self):
        helper = external_tests.Issue92ExternalSubmissionPreflightTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _app, facade = helper.make_facade(root)
            try:
                run_id, valid, _capture = helper.prepared(root, facade)
                rejected = deepcopy(valid)
                rejected["validation"] = {"status": "rejected", "issues": [{
                    "code": "SOURCE-QUALITY", "severity": "error", "message": "Formal research rejection."
                }]}
                result = facade.collect_external(run_id, {"research_result": rejected}, view="conversation")
                _assert_no_raw_target(self, result)
                self.assertEqual(result["run"]["status"], "COMPLETED")
                self.assertEqual(result["handoff_status"], "rejected")
                self.assertFalse(result["normalized_candidate_available"])
                self.assertNotIn("candidate", result)
            finally:
                facade.close()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _app, facade = helper.make_facade(root)
            try:
                run_id, valid, _capture = helper.prepared(root, facade)
                broken = deepcopy(valid)
                broken["outputs"] = []
                result = facade.collect_external(run_id, {"research_result": broken}, view="conversation")
                _assert_no_raw_target(self, result)
                self.assertEqual(result["run"]["status"], "RUNNING")
                self.assertFalse(result["normalized_candidate_available"])
                self.assertTrue(result["issues"])
                self.assertNotIn("candidate", result)
            finally:
                facade.close()

    def test_conversation_synthesis_listing_preserves_corruption_and_incomplete_collection_signals(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            facade = synthesis_tests._make_facade(temp)
            try:
                healthy = facade.submit_action(synthesis_tests._recommendation_input("Healthy"))
                corrupt = facade.submit_action(synthesis_tests._recommendation_input("Corrupt"))
                healthy_id = healthy["data"]["state_delta_proposal_id"]
                corrupt_id = corrupt["data"]["state_delta_proposal_id"]
                store = facade._application.conversation_store
                raw = store.load_state_delta_proposal(corrupt_id)
                raw["rationale"] = "tampered without refreshing digest"
                store._db.execute(
                    "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                    (json.dumps(raw, ensure_ascii=False), corrupt_id),
                )
                store._db.execute(
                    "INSERT INTO state_delta_proposals(proposal_id,payload_json) VALUES(?,?)",
                    ("SDP-UNATTRIBUTABLE", "not-json"),
                )
                listing = facade.list_synthesis_candidates(kind="recommendation", view="conversation")
                _assert_no_raw_target(self, listing)
                by_id = {item["candidate_id"]: item for item in listing["items"]}
                self.assertEqual(listing["status"], "DEGRADED")
                self.assertEqual(by_id[healthy_id]["availability"], "AVAILABLE")
                self.assertEqual(by_id[corrupt_id]["availability"], "UNAVAILABLE")
                self.assertTrue(by_id[corrupt_id]["issues"])
                self.assertTrue(listing["issues"])
            finally:
                facade.close()

    def test_unknown_action_has_no_raw_fallback_and_invalid_view_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                result = facade.submit_action({
                    "action_type": "research_attention.status", "payload": {}
                }, view="conversation")
                _assert_no_raw_target(self, result)
                self.assertEqual(result["interpretation"]["status"], "UNSUPPORTED")

                before = facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM proposals"
                ).fetchone()[0]
                with self.assertRaises(LocalApplicationError) as invalid:
                    facade.submit_action(_proposal_input(), view="future")
                self.assertEqual(invalid.exception.code, "APPLICATION-VIEW-001")
                after = facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM proposals"
                ).fetchone()[0]
                self.assertEqual(before, after)

    def test_projection_failure_after_operation_returns_safe_unavailable_without_reexecution(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                before = facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM state_delta_proposals"
                ).fetchone()[0]
                with patch(
                    "plugins.local_application.synthesis_candidate_facade.project_action_result",
                    side_effect=ConversationViewError("fixture projection failure"),
                ):
                    result = facade.submit_action(_proposal_input(), view="conversation")
                _assert_no_raw_target(self, result)
                self.assertEqual(result["conversation_projection"]["status"], "UNAVAILABLE")
                self.assertTrue(result["exact_references"]["result_reference"].startswith("SDP-"))
                after = facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM state_delta_proposals"
                ).fetchone()[0]
                self.assertEqual(after, before + 1)

    def test_cli_conversation_view_matches_python_and_default_cli_stays_detail(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            payload = _proposal_input(text="CLI approved literal")
            import json
            input_file = Path(temp) / "action.json"
            input_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            code, conversation = _run_cli([
                "action", "submit", "--workspace", str(workspace), "--view", "conversation", "--json", str(input_file)
            ])
            self.assertEqual(code, 0)
            _assert_no_raw_target(self, conversation)
            self.assertEqual(conversation["candidate"]["content"][0]["content"]["text"], "CLI approved literal")

            code, detail = _run_cli([
                "resume", "--workspace", str(workspace), "--json"
            ])
            self.assertEqual(code, 0)
            self.assertIn("candidate_projection", detail["research_questions"]["candidates"][0])
            code, conversation_resume = _run_cli([
                "resume", "--workspace", str(workspace), "--view", "conversation", "--json"
            ])
            self.assertEqual(code, 0)
            _assert_no_raw_target(self, conversation_resume)

    def test_b0_b1_b2_controls_leak_and_b3_conversation_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                raw = facade.submit_action(_proposal_input())
                b0 = deepcopy(raw)
                b1 = {"summary": "candidate saved", "raw": deepcopy(raw)}
                b2 = deepcopy(raw)
                b2.get("data", {}).pop("candidate_projection", None)
                b3 = facade.submit_action(_proposal_input(text="B3"), view="conversation")
                self.assertTrue(set(_keys(b0)) & _RAW_TARGET_KEYS)
                self.assertTrue(set(_keys(b1)) & _RAW_TARGET_KEYS)
                self.assertTrue(set(_keys(b2)) & _RAW_TARGET_KEYS)
                _assert_no_raw_target(self, b3)


if __name__ == "__main__":
    unittest.main()
