from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

import unittest

from core.conversation import ConversationRuntimeError
from core.decision import request_digest
from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade
import test_issue134_argument_proposal as argument_tests
import test_issue135_recommendation_proposal as recommendation_tests
import test_issue92_external_submission_preflight as external_tests
from test_research_question_adoption import _init_workspace, _proposal_input, _run_cli
from test_research_question_batch_adoption import _batch_input, _question
from test_research_question_review import _adopt_question, _workspace


def _canonical_request(value: dict) -> dict:
    result = deepcopy(value)
    result.pop("operational_status", None)
    result.pop("commit_id", None)
    result.pop("status_detail", None)
    return result


def _synthetic_candidate(facade, proposal_id: str, *, producer: str, action_kind: str = "CREATE_OBJECT") -> dict:
    state = facade._current_state_view()
    object_id = "OBJ-" + proposal_id
    obj = {
        "schema_version": "0.1.0",
        "id": object_id,
        "kind": "finding",
        "revision": 0,
        "project_id": facade.project_id,
        "statement": proposal_id,
        "adoption_state": "approved",
    }
    candidate = {
        "proposal_id": proposal_id,
        "project_ref": facade.project_id,
        "lineage_ref": state.lineage_ref,
        "source_refs": ["HND-RUN-1"] if producer.startswith("desktop-research") else [],
        "proposed_actions": [{
            "kind": action_kind,
            "payload": {"object": obj},
            "decision_refs": [],
            "source_refs": ["HND-RUN-1"] if producer.startswith("desktop-research") else [],
        }],
        "affected_refs": [{"kind": "finding", "id": object_id}],
        "rationale": "exact detail fixture",
        "required_human_decision_kinds": ["research_adoption"],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {"producer": producer, "run_id": "RUN-1"},
        "candidate_only": True,
    }
    candidate["proposal_digest"] = canonical_digest(candidate)
    return candidate


class Issue305PublicDetailReadTests(unittest.TestCase):
    def test_candidate_show_round_trips_exact_documents_after_reopen_and_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                single = facade.submit_action(_proposal_input())
                batch = facade.submit_action(_batch_input(_question("Batch A"), _question("Batch B")))
                expected = {
                    single["data"]["state_delta_proposal_id"]: deepcopy(single["data"]["state_delta_proposal"]),
                    batch["data"]["state_delta_proposal_id"]: deepcopy(batch["data"]["state_delta_proposal"]),
                }
                before_count = facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM state_delta_proposals"
                ).fetchone()[0]
                before_snapshot = deepcopy(facade._current_state_view().current_snapshot)

            with LocalApplicationFacade.open_workspace(workspace) as reopened:
                for candidate_id, document in expected.items():
                    shown = reopened.show_candidate(candidate_id)
                    assert shown == {
                        "status": "OK",
                        "project_id": reopened.project_id,
                        "candidate_id": candidate_id,
                        "candidate": document,
                    }
                    code, cli = _run_cli([
                        "candidate", "show", "--workspace", str(workspace),
                        "--candidate-id", candidate_id, "--json",
                    ])
                    assert code == 0
                    assert cli == shown
                assert reopened._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM state_delta_proposals"
                ).fetchone()[0] == before_count
                assert reopened._current_state_view().current_snapshot == before_snapshot


    def test_candidate_show_covers_review_recommendation_argument_and_run_candidates(self):
        # Material Research Question review candidate.
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                question_id = _adopt_question(facade)
                review = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "REFINE",
                        "question_ids": [question_id],
                        "rationale": "tighten scope",
                        "text": "Refined exact-detail question",
                    },
                    "actor_id": "H",
                })
                candidate = review["data"]["state_delta_proposal"]
                assert facade.show_candidate(candidate["proposal_id"])["candidate"] == candidate

        # Recommendation candidate.
        helper = recommendation_tests.Issue135RecommendationProposalTests()
        with tempfile.TemporaryDirectory() as temp:
            facade = helper.make_facade(temp)
            try:
                result = facade.submit_action(helper.proposal_input())
                candidate = result["data"]["state_delta_proposal"]
                assert facade.show_candidate(candidate["proposal_id"])["candidate"] == candidate
            finally:
                facade.close()

        # Argument candidate.
        helper = argument_tests.Issue134ArgumentProposalTests()
        with tempfile.TemporaryDirectory() as temp:
            facade = helper.make_facade(temp)
            try:
                result = facade.submit_action(helper.proposal_input())
                candidate = result["data"]["state_delta_proposal"]
                assert facade.show_candidate(candidate["proposal_id"])["candidate"] == candidate
            finally:
                facade.close()

        # Desktop Research Run-derived candidate.
        helper = external_tests.Issue92ExternalSubmissionPreflightTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _app, facade = helper.make_facade(root)
            try:
                run_id, result_input, _capture = helper.prepared(root, facade)
                collected = facade.collect_external(run_id, {"research_result": result_input})
                candidate = collected["execution_result"]["state_delta_proposal"]
                assert facade.show_candidate(candidate["proposal_id"])["candidate"] == candidate
            finally:
                facade.close()


    def test_decision_show_preserves_immutable_request_and_separates_operational_state(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": candidate_id},
                    "actor_id": "HUMAN-RQ",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })
                issued = _canonical_request(confirmed["decision_request"])
                request_id = issued["request_id"]
                assert request_digest(issued) == issued["request_digest"]

                before_candidate_count = facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM state_delta_proposals"
                ).fetchone()[0]
                before_request_count = facade._application.decision_store._db.execute(
                    "SELECT COUNT(*) FROM decision_requests"
                ).fetchone()[0]

                detail = facade.show_human_decision_request(request_id)
                assert detail["request"] == issued
                assert "operational_status" not in detail["request"]
                assert detail["request"]["status"] == "PENDING"
                assert detail["operational"] == {
                    "status": "PENDING",
                    "commit_id": None,
                    "detail": None,
                }

                resolved = facade.resolve_human_decision({
                    "request_id": request_id,
                    "request_digest": issued["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-RQ",
                })
                assert resolved["status"] == "RESOLVED"

                after = facade.show_human_decision_request(request_id)
                assert after["request"] == issued
                assert after["operational"]["status"] == "RESOLVED"
                assert after["operational"]["commit_id"] == resolved["commit_receipt"]["commit_id"]
                assert facade.show_candidate(candidate_id)["candidate"] == proposed["data"]["state_delta_proposal"]

                code, cli = _run_cli([
                    "decision", "show", "--workspace", str(workspace),
                    "--request-id", request_id, "--json",
                ])
                assert code == 0
                assert cli == after
                assert facade._application.conversation_store._db.execute(
                    "SELECT COUNT(*) FROM state_delta_proposals"
                ).fetchone()[0] == before_candidate_count
                assert facade._application.decision_store._db.execute(
                    "SELECT COUNT(*) FROM decision_requests"
                ).fetchone()[0] == before_request_count


    def test_candidate_and_decision_show_fail_closed_on_missing_foreign_or_corrupt_records(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                with self.assertRaises(ConversationRuntimeError) as missing:
                    facade.show_candidate("SDP-MISSING")
                assert missing.exception.code == "APPLICATION-CANDIDATE-DETAIL-001"
                with self.assertRaises(ConversationRuntimeError) as missing_request:
                    facade.show_human_decision_request("HDREQ-MISSING")
                assert missing_request.exception.code == "APPLICATION-DECISION-DETAIL-001"

                foreign = _synthetic_candidate(facade, "SDP-FOREIGN", producer="test")
                foreign["project_ref"] = "PRJ-FOREIGN"
                foreign["proposed_actions"][0]["payload"]["object"]["project_id"] = "PRJ-FOREIGN"
                foreign.pop("proposal_digest")
                foreign["proposal_digest"] = canonical_digest(foreign)
                facade._application.conversation_store.store_state_delta_proposal(
                    foreign["proposal_id"], foreign
                )
                with self.assertRaises(ConversationRuntimeError) as foreign_error:
                    facade.show_candidate(foreign["proposal_id"])
                assert foreign_error.exception.code == "RESUME-CANDIDATE-001"

                proposed = facade.submit_action(_proposal_input(text="corruption target"))
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                raw = deepcopy(proposed["data"]["state_delta_proposal"])
                raw["proposed_actions"] = "not-a-list"
                raw.pop("proposal_digest")
                raw["proposal_digest"] = canonical_digest(raw)
                facade._application.conversation_store._db.execute(
                    "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                    (json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")), candidate_id),
                )
                with self.assertRaises(ConversationRuntimeError) as malformed:
                    facade.show_candidate(candidate_id)
                assert malformed.exception.code == "RESUME-CANDIDATE-001"

            # Use a clean workspace for request corruption so candidate damage cannot mask it.
            decision_root = Path(temp) / "decision-corrupt"
            decision_root.mkdir()
            clean = _init_workspace(decision_root)
            with LocalApplicationFacade.open_workspace(clean) as facade:
                proposed = facade.submit_action(_proposal_input())
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-RQ",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })
                request_id = confirmed["decision_request"]["request_id"]
                row = facade._application.decision_store._db.execute(
                    "SELECT payload_json FROM decision_requests WHERE request_id=?", (request_id,)
                ).fetchone()
                request = json.loads(row["payload_json"])
                request["human_actor_id"] = "TAMPERED"
                facade._application.decision_store._db.execute(
                    "UPDATE decision_requests SET payload_json=? WHERE request_id=?",
                    (json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")), request_id),
                )
                with self.assertRaises(ConversationRuntimeError) as corrupt_request:
                    facade.show_human_decision_request(request_id)
                assert corrupt_request.exception.code == "RESUME-DECISION-001"

    def test_decision_show_rejects_row_project_binding_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-RQ",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })
                request_id = confirmed["decision_request"]["request_id"]
                facade._application.decision_store._db.execute(
                    "UPDATE decision_requests SET project_ref=? WHERE request_id=?",
                    ("PRJ-FOREIGN", request_id),
                )
                with self.assertRaises(ConversationRuntimeError) as corrupt_request:
                    facade.show_human_decision_request(request_id)
                assert corrupt_request.exception.code == "RESUME-DECISION-001"

    def test_decision_show_rejects_operational_fields_inside_immutable_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-RQ",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })
                request_id = confirmed["decision_request"]["request_id"]
                row = facade._application.decision_store._db.execute(
                    "SELECT payload_json FROM decision_requests WHERE request_id=?", (request_id,)
                ).fetchone()
                request = json.loads(row["payload_json"])
                request["operational_status"] = "RESOLVED"
                request["commit_id"] = "COM-FAKE"
                request["status_detail"] = "tampered operational projection"
                # request_digest deliberately remains valid because these fields are excluded
                # from the canonical digest contract. The persisted immutable payload must
                # therefore reject them explicitly.
                assert request_digest(request) == request["request_digest"]
                facade._application.decision_store._db.execute(
                    "UPDATE decision_requests SET payload_json=? WHERE request_id=?",
                    (json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")), request_id),
                )
                with self.assertRaises(ConversationRuntimeError) as corrupt_request:
                    facade.show_human_decision_request(request_id)
                assert corrupt_request.exception.code == "RESUME-DECISION-001"
