from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade

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
