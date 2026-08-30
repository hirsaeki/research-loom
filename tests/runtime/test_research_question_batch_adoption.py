from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import rfc8785

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade


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


def _question(text: str, **updates) -> dict:
    value = {
        "text": text,
        "rationale": f"{text} の採択理由。",
        "acceptance_criteria": [f"{text} に回答できる"],
        "scope_limits": ["実現時期そのものの断定は対象外"],
        "derived_from_seed_ids": ["RQ-SEED-001"],
    }
    value.update(updates)
    return value


def _batch_input(*questions: dict) -> dict:
    return {
        "action_type": "research_question.propose_many",
        "payload": {"questions": list(questions)},
        "actor_id": "HUMAN-BATCH",
    }


def _five_questions() -> tuple[dict, ...]:
    return tuple(_question(text) for text in ("Main RQ", "G1", "G2", "M1", "M2"))


def _state_delta(state, proposal_id: str, action: dict) -> dict:
    value = {
        "proposal_id": proposal_id,
        "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref,
        "source_refs": [],
        "proposed_actions": [action],
        "affected_refs": [],
        "rationale": "test head advance",
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {"producer": "test-setup"},
        "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


def _state_delta_count(workspace: Path) -> int:
    connection = sqlite3.connect(workspace / ".research-loom" / "conversation.db")
    try:
        return int(connection.execute("SELECT COUNT(*) FROM state_delta_proposals").fetchone()[0])
    finally:
        connection.close()


def _apply_to_decision(facade, candidate_id: str):
    apply = facade.submit_action({
        "action_type": "state.apply_candidate",
        "payload": {"state_delta_proposal_id": candidate_id},
        "actor_id": "HUMAN-BATCH",
    })
    confirmation_id = apply["confirmation_request"]["confirmation_request_id"]
    confirmed = facade.submit_confirmation({
        "confirmation_request_id": confirmation_id,
        "actor_id": "HUMAN-BATCH",
    })
    return apply, confirmed


def _resolve(facade, request: dict, disposition: str):
    return facade.resolve_human_decision({
        "request_id": request["request_id"],
        "request_digest": request["request_digest"],
        "disposition": disposition,
        "actor_id": "HUMAN-BATCH",
    })


class ResearchQuestionBatchProposalTests(unittest.TestCase):
    def test_registry_proposal_is_one_snapshot_bound_candidate_with_five_rqs(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                definition = {
                    item["action_type"]: item for item in facade.list_actions()["actions"]
                }["research_question.propose_many"]
                self.assertEqual(definition["effect"], "read_only")
                self.assertFalse(definition["confirmation_required"])
                self.assertEqual(definition["route_category"], "harness_service")

                before = facade.status()["snapshot"]
                result = facade.submit_action(_batch_input(*_five_questions()))
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertFalse(result["action_receipt"]["research_state_mutation_performed"])
                self.assertEqual(facade.status()["snapshot"], before)

                questions = result["data"]["research_questions"]
                self.assertEqual([item["text"] for item in questions], ["Main RQ", "G1", "G2", "M1", "M2"])
                ids = [item["id"] for item in questions]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(all(item.startswith("RQ-") for item in ids))

                proposal = result["data"]["state_delta_proposal"]
                self.assertEqual(len(proposal["proposed_actions"]), 5)
                self.assertEqual(
                    [action["payload"]["object"]["id"] for action in proposal["proposed_actions"]],
                    ids,
                )
                self.assertTrue(all(
                    action["kind"] == "CREATE_OBJECT" for action in proposal["proposed_actions"]
                ))
                self.assertEqual([ref["id"] for ref in proposal["affected_refs"]], ids)
                self.assertEqual(proposal["current_snapshot_ref"], before["snapshot_id"])
                self.assertEqual(proposal["current_snapshot_digest"], before["content_digest"])
                basis = deepcopy(proposal)
                supplied_digest = basis.pop("proposal_digest")
                self.assertEqual(canonical_digest(basis), supplied_digest)
                self.assertEqual(
                    [item["research_question_id"] for item in proposal["provenance"]["research_question_seed_bindings"]],
                    ids,
                )

                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                self.assertFalse(any(
                    item["kind"] == "research_question" for item in state.effective_objects()
                ))

    def test_invalid_or_caller_owned_member_rejects_without_partial_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                before_snapshot = facade.status()["snapshot"]
                before_count = _state_delta_count(workspace)
                invalid = list(_five_questions())
                invalid[2] = _question("G2", acceptance_criteria="not-a-list")
                with self.assertRaises(LocalApplicationError):
                    facade.submit_action(_batch_input(*invalid))
                self.assertEqual(_state_delta_count(workspace), before_count)
                self.assertEqual(facade.status()["snapshot"], before_snapshot)

                for forbidden, value in (
                    ("id", "RQ-CALLER"),
                    ("adoption_state", "approved"),
                    ("revision", 0),
                    ("snapshot_binding", {}),
                ):
                    questions = list(_five_questions())
                    questions[1] = _question("G1", **{forbidden: value})
                    with self.subTest(forbidden=forbidden), self.assertRaises(LocalApplicationError):
                        facade.submit_action(_batch_input(*questions))
                    self.assertEqual(_state_delta_count(workspace), before_count)

                with self.assertRaises(LocalApplicationError):
                    facade.submit_action(_batch_input(_question("only one")))

    def test_parent_must_exist_before_batch_and_batch_local_parent_is_not_invented(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                parent = facade.submit_action({
                    "action_type": "research_question.propose",
                    "payload": _question("Existing parent"),
                    "actor_id": "HUMAN-BATCH",
                })
                parent_id = parent["data"]["research_question_candidate"]["id"]
                _, confirmed = _apply_to_decision(
                    facade, parent["data"]["state_delta_proposal_id"]
                )
                resolved = _resolve(facade, confirmed["decision_request"], "approve_exact")
                self.assertEqual(resolved["status"], "RESOLVED")

                accepted = facade.submit_action(_batch_input(
                    _question("Child A", parent_question_id=parent_id),
                    _question("Child B"),
                ))
                self.assertEqual(accepted["status"], "SUCCEEDED")
                self.assertEqual(
                    accepted["data"]["research_questions"][0]["parent_question_id"], parent_id
                )

                before_count = _state_delta_count(workspace)
                unknown = facade.submit_action(_batch_input(
                    _question("Unknown parent child", parent_question_id="RQ-NOT-CURRENT"),
                    _question("Other"),
                ))
                self.assertEqual(unknown["status"], "FAILED")
                self.assertEqual(_state_delta_count(workspace), before_count)

                batch_local = facade.submit_action(_batch_input(
                    _question("Would-be parent"),
                    _question("Would-be child", parent_question_id="questions[0]"),
                ))
                self.assertEqual(batch_local["status"], "FAILED")
                self.assertEqual(_state_delta_count(workspace), before_count)


class ResearchQuestionBatchAdoptionTests(unittest.TestCase):
    def test_probe_regression_one_confirmation_one_decision_one_atomic_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                before = facade.status()["snapshot"]
                proposed = facade.submit_action(_batch_input(*_five_questions()))
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                generated = proposed["data"]["research_questions"]
                generated_ids = [item["id"] for item in generated]

                apply, confirmed = _apply_to_decision(facade, candidate_id)
                self.assertEqual(apply["status"], "CONFIRMATION_REQUIRED")
                self.assertIn("confirmation_request", apply)
                request = confirmed["decision_request"]
                self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
                self.assertEqual(len(request["decision_units"]), 5)
                self.assertEqual(
                    [unit["subject"]["id"] for unit in request["decision_units"]], generated_ids
                )
                self.assertEqual(
                    {unit["required_decision_kind"] for unit in request["decision_units"]},
                    {"research_adoption"},
                )
                self.assertEqual(
                    {unit["required_choice"] for unit in request["decision_units"]}, {"approve"}
                )

                resolved = _resolve(facade, request, "approve_exact")
                self.assertEqual(resolved["status"], "RESOLVED")
                self.assertIsNotNone(resolved["commit_receipt"])
                after = facade.status()["snapshot"]
                self.assertNotEqual(after["snapshot_id"], before["snapshot_id"])

                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                self.assertIsNotNone(state.latest_object("snapshot", before["snapshot_id"]))
                authoritative = [
                    item for item in state.effective_objects()
                    if item.get("kind") == "research_question"
                    and item.get("id") in generated_ids
                ]
                self.assertEqual({item["id"] for item in authoritative}, set(generated_ids))
                self.assertEqual(len(state.decisions), 1)
                decision_id = state.decisions[0]["id"]
                self.assertTrue(all(item["decision_ids"] == [decision_id] for item in authoritative))
                self.assertEqual(
                    {item["id"]: item["text"] for item in authoritative},
                    {item["id"]: item["text"] for item in generated},
                )

                resumed = facade.resume_context()
                row = next(
                    item for item in resumed["research_questions"]["candidates"]
                    if item["state_delta_proposal_id"] == candidate_id
                )
                self.assertEqual(row["batch_size"], 5)
                self.assertEqual([item["id"] for item in row["questions"]], generated_ids)
                self.assertNotIn("question", row)
                self.assertFalse(row["bound_to_current_snapshot"])
                self.assertEqual(row["authoritative_same_ids"], generated_ids)

    def test_decline_and_revision_leave_batch_and_authoritative_state_unchanged(self):
        for disposition, expected in (
            ("decline", "DECLINED"),
            ("request_revision", "REVISION_REQUESTED"),
        ):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as temp:
                workspace = _init_workspace(Path(temp))
                with LocalApplicationFacade.open_workspace(workspace) as facade:
                    before = facade.status()["snapshot"]
                    proposed = facade.submit_action(_batch_input(*_five_questions()))
                    candidate_id = proposed["data"]["state_delta_proposal_id"]
                    stored_before = facade._application.conversation_store.load_state_delta_proposal(
                        candidate_id
                    )
                    _, confirmed = _apply_to_decision(facade, candidate_id)
                    resolved = _resolve(facade, confirmed["decision_request"], disposition)
                    self.assertEqual(resolved["status"], expected)
                    self.assertEqual(facade.status()["snapshot"], before)
                    self.assertEqual(
                        facade._application.conversation_store.load_state_delta_proposal(candidate_id),
                        stored_before,
                    )
                    state = facade._application.state_repository.load_state_view(
                        facade.project_id,
                        facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                    )
                    self.assertFalse(any(
                        item["kind"] == "research_question" for item in state.effective_objects()
                    ))

    def test_stale_batch_fails_closed_without_rebase_or_partial_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_batch_input(*_five_questions()))
                candidate_id = proposed["data"]["state_delta_proposal_id"]
                generated_ids = [item["id"] for item in proposed["data"]["research_questions"]]
                stored_before = facade._application.conversation_store.load_state_delta_proposal(
                    candidate_id
                )

                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                source = {
                    "schema_version": "0.1.0",
                    "id": "SRC-BATCH-HEAD-ADVANCE",
                    "kind": "source",
                    "revision": 0,
                    "project_id": facade.project_id,
                    "source_type": "report",
                    "canonical_locator": "fixture://batch-head-advance",
                }
                head_advance = _state_delta(state, "SDP-BATCH-HEAD-ADVANCE", {
                    "kind": "CREATE_OBJECT",
                    "payload": {"object": source},
                    "decision_refs": [],
                    "source_refs": [],
                })
                facade._application.conversation_store.store_state_delta_proposal(
                    head_advance["proposal_id"], head_advance
                )
                advance_apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": head_advance["proposal_id"]},
                    "actor_id": "HUMAN-BATCH",
                })
                advanced = facade.submit_confirmation({
                    "confirmation_request_id": advance_apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-BATCH",
                })
                self.assertEqual(advanced["status"], "SUCCEEDED")

                resumed = facade.resume_context()
                row = next(
                    item for item in resumed["research_questions"]["candidates"]
                    if item["state_delta_proposal_id"] == candidate_id
                )
                self.assertEqual(row["batch_size"], 5)
                self.assertFalse(row["bound_to_current_snapshot"])
                self.assertEqual([item["id"] for item in row["questions"]], generated_ids)

                apply, confirmed = _apply_to_decision(facade, candidate_id)
                self.assertEqual(apply["status"], "CONFIRMATION_REQUIRED")
                self.assertEqual(confirmed["status"], "FAILED")
                self.assertEqual(
                    facade._application.conversation_store.load_state_delta_proposal(candidate_id),
                    stored_before,
                )
                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                authoritative_ids = {
                    item["id"] for item in state.effective_objects()
                    if item.get("kind") == "research_question"
                }
                self.assertTrue(set(generated_ids).isdisjoint(authoritative_ids))

    def test_resume_keeps_single_candidate_shape_and_batch_is_one_row(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                single = facade.submit_action({
                    "action_type": "research_question.propose",
                    "payload": _question("Single RQ"),
                    "actor_id": "HUMAN-BATCH",
                })
                batch = facade.submit_action(_batch_input(
                    _question("Batch A"), _question("Batch B")
                ))
                resumed = facade.resume_context()

                rows = resumed["research_questions"]["candidates"]
                single_row = next(
                    item for item in rows
                    if item["state_delta_proposal_id"] == single["data"]["state_delta_proposal_id"]
                )
                batch_rows = [
                    item for item in rows
                    if item["state_delta_proposal_id"] == batch["data"]["state_delta_proposal_id"]
                ]
                self.assertIn("question", single_row)
                self.assertNotIn("questions", single_row)
                self.assertEqual(len(batch_rows), 1)
                self.assertEqual(batch_rows[0]["batch_size"], 2)
                self.assertEqual(
                    [item["text"] for item in batch_rows[0]["questions"]], ["Batch A", "Batch B"]
                )
                self.assertTrue(batch_rows[0]["bound_to_current_snapshot"])


if __name__ == "__main__":
    unittest.main()
