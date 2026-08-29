from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import rfc8785

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationFacade


ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


def _configuration_digest(config: dict) -> str:
    value = deepcopy(config)
    value.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _bootstrap_config() -> dict:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = _configuration_digest(config)
    return config


def _init_workspace(root: Path) -> Path:
    config = root / "project-config.json"
    profiles = root / "effective-profile-set.json"
    config.write_text(json.dumps(_bootstrap_config()), encoding="utf-8")
    profiles.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    workspace = root / "workspace"
    result = LocalApplicationFacade.initialize_workspace(workspace, config, profiles)
    assert result["status"] == "INITIALIZED"
    return workspace


def _rq_input(text="企業はどの条件でAIへ意思決定を委ねるべきか"):
    return {
        "action_type": "research_question.propose",
        "payload": {
            "text": text,
            "rationale": "再開可能性を検証する問い候補。",
            "acceptance_criteria": ["条件を比較可能に説明できる"],
            "scope_limits": ["実現時期そのものの予測は対象外"],
            "derived_from_seed_ids": ["RQ-SEED-001"],
        },
        "actor_id": "HUMAN-RESUME",
    }


def _conversation_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "documents", "proposals", "confirmation_requests", "materializations",
                "run_correlations", "state_delta_proposals",
            )
        }
    finally:
        connection.close()


def _adopt(facade, proposed, *, disposition="approve_exact"):
    candidate_id = proposed["data"]["state_delta_proposal_id"]
    apply = facade.submit_action({
        "action_type": "state.apply_candidate",
        "payload": {"state_delta_proposal_id": candidate_id},
        "actor_id": "HUMAN-RESUME",
    })
    confirmation_id = apply["confirmation_request"]["confirmation_request_id"]
    decision = facade.submit_confirmation({
        "confirmation_request_id": confirmation_id,
        "actor_id": "HUMAN-RESUME",
    })["decision_request"]
    resolved = facade.resolve_human_decision({
        "request_id": decision["request_id"],
        "request_digest": decision["request_digest"],
        "disposition": disposition,
        "actor_id": "HUMAN-RESUME",
    })
    return candidate_id, confirmation_id, decision, resolved


class ProductionResearchResumeContextTests(unittest.TestCase):
    def test_fresh_workspace_is_read_only_and_cli_works_without_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = _init_workspace(root)
            internal = workspace / ".research-loom"
            attention_path = internal / "attention.sqlite3"
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                before_status = facade.status()
                before_counts = _conversation_counts(internal / "conversation.db")
                result = facade.resume_context()
                after_status = facade.status()
                after_counts = _conversation_counts(internal / "conversation.db")

            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["project"]["project_id"], "PRJ-1")
            self.assertTrue(result["project"]["title"])
            self.assertTrue(result["research_questions"]["seeds"])
            self.assertEqual(result["research_questions"]["authoritative"], [])
            self.assertEqual(result["research_questions"]["candidates"], [])
            self.assertTrue(result["research_attention"]["baseline"])
            self.assertEqual(result["research_attention"]["effective"], result["research_attention"]["baseline"])
            self.assertIsNone(result["research_attention"]["active_map"])
            self.assertEqual(result["research_attention"]["stored_maps"], [])
            self.assertEqual(result["workflow"]["pending_confirmations"], [])
            self.assertEqual(result["workflow"]["pending_human_decisions"], [])
            self.assertEqual(result["workflow"]["pending_runs"], [])
            self.assertEqual(result["workflow"]["recent_runs"], [])
            self.assertEqual(before_status["snapshot"], after_status["snapshot"])
            self.assertEqual(before_counts, after_counts)
            self.assertFalse(attention_path.exists())

            completed = subprocess.run(
                [sys.executable, str(ROOT / "research-loom"), "resume", "--workspace", str(workspace), "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "OK")
            self.assertFalse(attention_path.exists())

    def test_probe_regression_duplicate_candidates_and_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                first = facade.submit_action(_rq_input())
                second = facade.submit_action(_rq_input())
                attention = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{
                        "statement": "横断的な責任分界を調査時に保持する。",
                        "related_question_seed_ids": ["RQ-SEED-001"],
                    }]},
                })["data"]["attention_map"]
                result = facade.resume_context()
                bounded = facade.resume_context(limits={
                    "research_question_candidates": 1,
                    "attention_maps": 1,
                })

            self.assertEqual(result["research_state"]["snapshot"]["revision"], 0)
            self.assertEqual(result["research_questions"]["authoritative"], [])
            candidates = result["research_questions"]["candidates"]
            self.assertEqual(len(candidates), 2)
            self.assertEqual(
                {item["state_delta_proposal_id"] for item in candidates},
                {first["data"]["state_delta_proposal_id"], second["data"]["state_delta_proposal_id"]},
            )
            self.assertTrue(all(item["bound_to_current_snapshot"] for item in candidates))
            self.assertTrue(all(not item["authoritative_same_id"] for item in candidates))
            self.assertIsNone(result["research_attention"]["active_map"])
            self.assertEqual([item["map_id"] for item in result["research_attention"]["stored_maps"]], [attention["map_id"]])
            self.assertEqual(result["research_attention"]["effective"], result["research_attention"]["baseline"])
            self.assertEqual(len(bounded["research_questions"]["candidates"]), 1)
            self.assertTrue(bounded["truncated"]["research_question_candidates"])

    def test_confirmation_human_decision_and_terminal_history_are_correlated(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_rq_input())
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": candidate_id},
                    "actor_id": "HUMAN-RESUME",
                })
                confirmation_id = apply["confirmation_request"]["confirmation_request_id"]
                pending = facade.resume_context()["research_questions"]["candidates"][0]
                self.assertEqual(pending["pending_confirmation_request_ids"], [confirmation_id])

                decision = facade.submit_confirmation({
                    "confirmation_request_id": confirmation_id,
                    "actor_id": "HUMAN-RESUME",
                })["decision_request"]
                waiting = facade.resume_context()
                candidate = waiting["research_questions"]["candidates"][0]
                self.assertEqual(candidate["pending_confirmation_request_ids"], [])
                self.assertEqual(candidate["human_decision_requests"][0]["status"], "PENDING")
                self.assertEqual(waiting["workflow"]["pending_human_decisions"][0]["request_id"], decision["request_id"])

                declined = facade.resolve_human_decision({
                    "request_id": decision["request_id"],
                    "request_digest": decision["request_digest"],
                    "disposition": "decline",
                    "actor_id": "HUMAN-RESUME",
                })
                self.assertEqual(declined["status"], "DECLINED")
                terminal = facade.resume_context()
                self.assertEqual(terminal["workflow"]["pending_human_decisions"], [])
                self.assertEqual(terminal["research_questions"]["candidates"][0]["human_decision_requests"][0]["status"], "DECLINED")
                self.assertEqual(terminal["research_questions"]["authoritative"], [])

                approved_proposal = facade.submit_action(_rq_input("AI委任条件をどの軸で評価するか"))
                approved_id, _, _, approved = _adopt(facade, approved_proposal)
                self.assertEqual(approved["status"], "RESOLVED")
                adopted = facade.resume_context()
                authoritative_ids = {item["id"] for item in adopted["research_questions"]["authoritative"]}
                candidate = next(item for item in adopted["research_questions"]["candidates"] if item["state_delta_proposal_id"] == approved_id)
                self.assertIn(candidate["question"]["id"], authoritative_ids)
                self.assertTrue(candidate["authoritative_same_id"])
                self.assertFalse(candidate["bound_to_current_snapshot"])

                revision_proposal = facade.submit_action(_rq_input("委任評価をどの範囲で限定するか"))
                _, _, revision_request, revision = _adopt(facade, revision_proposal, disposition="request_revision")
                self.assertEqual(revision["status"], "REVISION_REQUESTED")
                history = facade.resume_context()["research_questions"]["candidates"]
                revised = next(item for item in history if item["question"]["text"] == "委任評価をどの範囲で限定するか")
                self.assertEqual(revised["human_decision_requests"][0]["request_id"], revision_request["request_id"])
                self.assertEqual(revised["human_decision_requests"][0]["status"], "REVISION_REQUESTED")

    def test_attention_activation_history_and_recent_runs_are_factual_only(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                adopted = facade.submit_action(_rq_input())
                _, _, _, resolved = _adopt(facade, adopted)
                self.assertEqual(resolved["status"], "RESOLVED")
                rq_id = adopted["data"]["research_question_candidate"]["id"]

                map_a = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Map A guidance.", "related_question_ids": [rq_id]}]},
                })["data"]["attention_map"]
                pending_a = facade.submit_action({
                    "action_type": "research_attention.activate_candidate",
                    "payload": {"attention_map_id": map_a["map_id"]},
                    "actor_id": "HUMAN-RESUME",
                })
                facade.submit_confirmation({
                    "confirmation_request_id": pending_a["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RESUME",
                })
                map_b = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Map B guidance."}]},
                })["data"]["attention_map"]
                pending_b = facade.submit_action({
                    "action_type": "research_attention.activate_candidate",
                    "payload": {"attention_map_id": map_b["map_id"]},
                    "actor_id": "HUMAN-RESUME",
                })
                facade.submit_confirmation({
                    "confirmation_request_id": pending_b["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RESUME",
                })
                map_c = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Never activated guidance."}]},
                })["data"]["attention_map"]

                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": rq_id, "purpose": "resume run visibility"},
                    "actor_id": "HUMAN-RESUME",
                })
                run_id = prepared["run_id"]
                before_abort = facade.resume_context()
                self.assertEqual(before_abort["workflow"]["pending_runs"][0]["run_id"], run_id)
                abort = facade.submit_action({
                    "action_type": "run.abort",
                    "payload": {"run_id": run_id, "reason": "test terminal projection"},
                    "actor_id": "HUMAN-RESUME",
                })
                facade.submit_confirmation({
                    "confirmation_request_id": abort["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RESUME",
                })
                result = facade.resume_context()

            self.assertEqual(result["research_attention"]["active_map"]["map_id"], map_b["map_id"])
            maps = {item["map_id"]: item for item in result["research_attention"]["stored_maps"]}
            self.assertTrue(maps[map_b["map_id"]]["activation"]["is_active"])
            self.assertTrue(maps[map_a["map_id"]]["activation"]["activation_ids"])
            self.assertFalse(maps[map_a["map_id"]]["activation"]["is_active"])
            self.assertEqual(maps[map_c["map_id"]]["activation"]["activation_ids"], [])
            self.assertEqual(result["workflow"]["pending_runs"], [])
            recent = result["workflow"]["recent_runs"][0]
            self.assertEqual((recent["run_id"], recent["status"]), (run_id, "ABORTED"))
            for forbidden in ("research_completed", "finding_adopted", "evidence_verified", "stage", "next_step", "recommended_action"):
                self.assertNotIn(forbidden, recent)
                self.assertNotIn(forbidden, result)

    def test_malformed_candidate_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                facade.submit_action(_rq_input())
                facade._application.conversation_store._db.execute(
                    "UPDATE state_delta_proposals SET payload_json='not-json'"
                )
                with self.assertRaises(ConversationRuntimeError) as error:
                    facade.resume_context()
                self.assertEqual(error.exception.code, "RESUME-CANDIDATE-001")


if __name__ == "__main__":
    unittest.main()
