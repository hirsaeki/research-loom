from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade

ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


def _configuration_digest(config: dict) -> str:
    value = deepcopy(config); value.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _workspace(root: Path) -> Path:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = _configuration_digest(config)
    c = root / "config.json"; p = root / "profiles.json"; w = root / "ws"
    c.write_text(json.dumps(config), encoding="utf-8")
    p.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    LocalApplicationFacade.initialize_workspace(w, c, p)
    return w


def _adopt_question(facade, text="Initial question") -> str:
    proposed = facade.submit_action({
        "action_type": "research_question.propose", "payload": {"text": text}, "actor_id": "H",
    })
    _apply(facade, proposed["data"]["state_delta_proposal_id"])
    return proposed["data"]["research_question_candidate"]["id"]


def _apply(facade, candidate_id: str):
    apply = facade.submit_action({
        "action_type": "state.apply_candidate",
        "payload": {"state_delta_proposal_id": candidate_id}, "actor_id": "H",
    })
    confirmed = facade.submit_confirmation({
        "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
        "actor_id": "H",
    })
    if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
        req = confirmed["decision_request"]
        return facade.resolve_human_decision({
            "request_id": req["request_id"], "request_digest": req["request_digest"],
            "disposition": "approve_exact", "actor_id": "H",
        })
    return confirmed


def _state_delta(state, proposal_id: str, action: dict) -> dict:
    value = {
        "proposal_id": proposal_id, "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref, "source_refs": [], "proposed_actions": [action],
        "affected_refs": [], "rationale": "advance", "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {"producer": "test"}, "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


class ResearchQuestionReviewTests(unittest.TestCase):
    def test_keep_is_no_change_and_refine_creates_immutable_next_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                qid = _adopt_question(facade)
                before = facade.status()["snapshot"]
                keep = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {"operation": "KEEP", "question_ids": [qid], "rationale": "still valid"},
                    "actor_id": "H",
                })
                self.assertEqual(keep["status"], "SUCCEEDED")
                self.assertFalse(keep["data"]["question_review"]["material_change"])
                self.assertEqual(facade.status()["snapshot"], before)

                refine = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "REFINE", "question_ids": [qid], "rationale": "narrow scope",
                        "text": "Refined question", "scope_limits": ["one scope"],
                        "review_inputs": {"evidence_gap_ids": ["GAP-1"]},
                    }, "actor_id": "H",
                })
                self.assertEqual(refine["status"], "SUCCEEDED")
                delta = refine["data"]["question_delta"]
                self.assertEqual(delta["operation"], "REFINE")
                self.assertEqual(delta["questions"][0]["revision"], 1)
                self.assertEqual(delta["questions"][0]["derived_from_question_revisions"], [{"id": qid, "revision": 0}])
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": refine["data"]["state_delta_proposal_id"]},
                    "actor_id": "H",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "H",
                })
                self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
                decision_kinds = {
                    unit["required_decision_kind"] for unit in confirmed["decision_request"]["decision_units"]
                }
                self.assertIn("research_revision", decision_kinds)
                resolved = facade.resolve_human_decision({
                    "request_id": confirmed["decision_request"]["request_id"],
                    "request_digest": confirmed["decision_request"]["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "H",
                })
                self.assertEqual(resolved["status"], "RESOLVED")
                state = facade._application.state_repository.load_state_view(
                    facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id)
                )
                self.assertEqual(state.exact_object("research_question", qid, 0)["text"], "Initial question")
                self.assertIsNotNone(state.latest_object("snapshot", before["snapshot_id"]))
                self.assertEqual(state.latest_object("research_question", qid)["text"], "Refined question")
                self.assertEqual(state.latest_object("research_question", qid)["question_lineage_id"], qid)
                resumed = facade.resume_context()
                active = next(item for item in resumed["research_questions"]["authoritative"] if item["id"] == qid)
                self.assertEqual(active["revision"], 1)
                self.assertEqual(active["question_lineage_id"], qid)
                self.assertEqual(active["derived_from_question_revisions"], [{"id": qid, "revision": 0}])

                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": qid, "purpose": "Verify the active RQ revision pin."},
                    "actor_id": "H",
                })
                self.assertEqual(prepared["status"], "CAPABILITY_EXECUTION_PREPARED")
                materialization = facade._application.conversation_store.load_materialization(
                    prepared["proposal"]["proposal_id"]
                )
                self.assertIn(
                    {"kind": "research_question", "id": qid, "revision": 1},
                    materialization["context_pack"]["research_object_references"],
                )

    def test_split_merge_close_and_downstream_review_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                q1 = _adopt_question(facade, "Q1")
                # Add a downstream claim through the authoritative transition path.
                state = facade._application.state_repository.load_state_view(
                    facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id)
                )
                claim = {"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":facade.project_id,"question_id":q1,"statement":"claim"}
                candidate = _state_delta(state, "SDP-CLAIM", {"kind":"CREATE_OBJECT","payload":{"object":claim},"decision_refs":[],"source_refs":[]})
                facade._application.conversation_store.store_state_delta_proposal("SDP-CLAIM", candidate)
                _apply(facade, "SDP-CLAIM")

                split = facade.submit_action({
                    "action_type":"research_question.review","actor_id":"H",
                    "payload":{"operation":"SPLIT","question_ids":[q1],"rationale":"two decisions","questions":[{"text":"Q1a"},{"text":"Q1b"}]},
                })
                self.assertIn({"kind":"claim","id":"CLM-1"}, split["data"]["question_delta"]["downstream_review_required_refs"])
                _apply(facade, split["data"]["state_delta_proposal_id"])
                state = facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
                self.assertEqual(state.latest_object("research_question", q1)["adoption_state"], "closed")
                children = [x for x in state.effective_objects() if x.get("kind") == "research_question" and x.get("id") != q1]
                self.assertEqual(len(children), 2)

                merge = facade.submit_action({
                    "action_type":"research_question.review","actor_id":"H",
                    "payload":{"operation":"MERGE","question_ids":[x["id"] for x in children],"rationale":"same decision","text":"Merged"},
                })
                _apply(facade, merge["data"]["state_delta_proposal_id"])
                state = facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
                merged = next(x for x in state.effective_objects() if x.get("kind") == "research_question" and x.get("text") == "Merged")
                self.assertEqual(len(merged["derived_from_question_revisions"]), 2)

                close = facade.submit_action({
                    "action_type":"research_question.review","actor_id":"H",
                    "payload":{"operation":"CLOSE","question_ids":[merged["id"]],"rationale":"answered"},
                })
                _apply(facade, close["data"]["state_delta_proposal_id"])
                state = facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
                self.assertEqual(state.latest_object("research_question", merged["id"])["adoption_state"], "closed")


    def test_child_research_question_is_marked_for_downstream_review(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                parent_id = _adopt_question(facade, "Parent")
                child = facade.submit_action({
                    "action_type": "research_question.propose",
                    "payload": {"text": "Child", "parent_question_id": parent_id},
                    "actor_id": "H",
                })
                _apply(facade, child["data"]["state_delta_proposal_id"])
                child_id = child["data"]["research_question_candidate"]["id"]

                split = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "SPLIT",
                        "question_ids": [parent_id],
                        "rationale": "separate decisions",
                        "questions": [{"text": "Parent A"}, {"text": "Parent B"}],
                    },
                    "actor_id": "H",
                })
                self.assertIn(
                    {"kind": "research_question", "id": child_id},
                    split["data"]["question_delta"]["downstream_review_required_refs"],
                )

    def test_material_review_candidates_remain_visible_in_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                q1 = _adopt_question(facade, "Q1")
                q2 = _adopt_question(facade, "Q2")
                candidates = [
                    facade.submit_action({
                        "action_type": "research_question.review",
                        "payload": {
                            "operation": "REFINE", "question_ids": [q1],
                            "rationale": "narrow", "text": "Q1 refined",
                        },
                        "actor_id": "H",
                    }),
                    facade.submit_action({
                        "action_type": "research_question.review",
                        "payload": {
                            "operation": "CLOSE", "question_ids": [q2],
                            "rationale": "answered",
                        },
                        "actor_id": "H",
                    }),
                    facade.submit_action({
                        "action_type": "research_question.review",
                        "payload": {
                            "operation": "SPLIT", "question_ids": [q1],
                            "rationale": "two decisions",
                            "questions": [{"text": "Q1a"}, {"text": "Q1b"}],
                        },
                        "actor_id": "H",
                    }),
                    facade.submit_action({
                        "action_type": "research_question.review",
                        "payload": {
                            "operation": "MERGE", "question_ids": [q1, q2],
                            "rationale": "same decision", "text": "Merged",
                        },
                        "actor_id": "H",
                    }),
                ]
                expected_ids = {item["data"]["state_delta_proposal_id"] for item in candidates}
                resumed = facade.resume_context()
                rows = {
                    row["state_delta_proposal_id"]: row
                    for row in resumed["research_questions"]["candidates"]
                    if row["state_delta_proposal_id"] in expected_ids
                }
                self.assertEqual(set(rows), expected_ids)
                by_delta = {row["question_delta"]: row for row in rows.values()}
                self.assertEqual(len(by_delta["REFINE"]["questions"]), 1)
                self.assertEqual(by_delta["REFINE"]["questions"][0]["revision"], 1)
                self.assertEqual(by_delta["REFINE"]["questions"][0]["question_lineage_id"], q1)
                self.assertEqual(by_delta["CLOSE"]["questions"][0]["adoption_state"], "closed")
                self.assertEqual(len(by_delta["SPLIT"]["questions"]), 3)
                self.assertEqual(len(by_delta["MERGE"]["questions"]), 3)
                self.assertEqual(
                    by_delta["MERGE"]["source_question_revisions"],
                    [{"id": q1, "revision": 0}, {"id": q2, "revision": 0}],
                )
                self.assertTrue(all(row["bound_to_current_snapshot"] for row in rows.values()))

    def test_closed_question_is_not_reported_as_authoritative_for_stale_review_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                qid = _adopt_question(facade, "Q1")
                close = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "CLOSE",
                        "question_ids": [qid],
                        "rationale": "answered",
                    },
                    "actor_id": "H",
                })
                candidate_id = close["data"]["state_delta_proposal_id"]
                _apply(facade, candidate_id)

                resumed = facade.resume_context()
                row = next(
                    item
                    for item in resumed["research_questions"]["candidates"]
                    if item["state_delta_proposal_id"] == candidate_id
                )
                self.assertFalse(row["bound_to_current_snapshot"])
                self.assertEqual(row["authoritative_same_ids"], [])

    def test_question_review_payload_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                qid = _adopt_question(facade)
                invalid_payloads = [
                    {
                        "operation": "SPLIT", "question_ids": [qid], "rationale": "split",
                        "questions": [{"text": f"Q{i}"} for i in range(17)],
                    },
                    {
                        "operation": "MERGE",
                        "question_ids": [f"RQ-{i}" for i in range(17)],
                        "rationale": "merge", "text": "Merged",
                    },
                    {
                        "operation": "REFINE", "question_ids": [qid],
                        "rationale": "r", "text": "x" * 8_193,
                    },
                ]
                for payload in invalid_payloads:
                    with self.subTest(operation=payload["operation"]), self.assertRaises(LocalApplicationError):
                        facade.submit_action({
                            "action_type": "research_question.review",
                            "payload": payload,
                            "actor_id": "H",
                        })

    def test_material_delta_goes_stale_when_head_advances(self):
        with tempfile.TemporaryDirectory() as temp:
            with LocalApplicationFacade.open_workspace(_workspace(Path(temp))) as facade:
                qid = _adopt_question(facade)
                refine = facade.submit_action({
                    "action_type":"research_question.review","actor_id":"H",
                    "payload":{"operation":"REFINE","question_ids":[qid],"rationale":"r","text":"Refined"},
                })
                state = facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
                source = {"schema_version":"0.1.0","id":"SRC-ADV","kind":"source","revision":0,"project_id":facade.project_id,"source_type":"report","canonical_locator":"fixture://advance"}
                advance = _state_delta(state, "SDP-ADV", {"kind":"CREATE_OBJECT","payload":{"object":source},"decision_refs":[],"source_refs":[]})
                facade._application.conversation_store.store_state_delta_proposal("SDP-ADV", advance)
                _apply(facade, "SDP-ADV")
                apply = facade.submit_action({"action_type":"state.apply_candidate","payload":{"state_delta_proposal_id":refine["data"]["state_delta_proposal_id"]},"actor_id":"H"})
                confirmed = facade.submit_confirmation({"confirmation_request_id":apply["confirmation_request"]["confirmation_request_id"],"actor_id":"H"})
                self.assertEqual(confirmed["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
