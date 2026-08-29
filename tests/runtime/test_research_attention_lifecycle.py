from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationFacade, LocalResearchApplication
from plugins.local_attention_store import attention_map_digest, validate_attention_store_schema
from runtime_fixtures import project, rq, seed_state


class NullResolver:
    def resolve(self, *_args, **_kwargs):
        return None


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
        "profile_pins": [],
        "content_digest": expected_digest,
    }


def project_config():
    return {
        "research_questions": {
            "references": [],
            "seeds": [{"seed_id": "RQ-SEED-1", "text": "Synthetic seed?"}],
        },
        "research_attention": [
            {
                "attention_id": "ATT-BASE-1",
                "statement": "Keep the baseline synthetic issue visible.",
                "source_reference_ids": ["REF-1"],
                "related_question_ids": ["RQ-1"],
                "related_question_seed_ids": ["RQ-SEED-1"],
                "disposition": "active",
            },
            {
                "attention_id": "ATT-BASE-2",
                "statement": "Preserve an explicitly out-of-scope synthetic issue.",
                "disposition": "out_of_scope",
                "disposition_reason": "Outside the synthetic scope.",
            },
        ],
        "resource_references": [{
            "reference_id": "REF-1",
            "reference_type": "input",
            "locator": "inputs/fixture.md",
        }],
    }


def make_seed():
    return seed_state(
        objects=[project(), rq(state="approved")],
        snapshot_id="SNP-ATT-0",
        project_config=project_config(),
    )


def open_app(root: Path, *, seed=True):
    return LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=make_seed() if seed else None,
    )


def state_pin(app):
    state = app.state_repository.load_state_view("PRJ-1", "LIN-1")
    return (
        state.current_snapshot["id"],
        state.current_snapshot["content_digest"],
        state.current_snapshot.get("revision", 0),
    )


def confirm(facade, pending, actor_id="HUMAN-ATT"):
    return facade.submit_confirmation({
        "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
        "actor_id": actor_id,
    })


class ResearchAttentionLifecycleTests(unittest.TestCase):
    def test_baseline_status_is_read_only_and_does_not_create_optional_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = open_app(root)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                before = state_pin(app)
                actions = {item["action_type"]: item for item in facade.list_actions()["actions"]}
                self.assertIn("research_attention.status", actions)
                self.assertIn("research_attention.propose", actions)
                self.assertIn("research_attention.activate_candidate", actions)
                self.assertEqual(actions["research_attention.status"]["effect"], "read_only")
                self.assertEqual(actions["research_attention.propose"]["effect"], "read_only")
                self.assertEqual(actions["research_attention.activate_candidate"]["effect"], "state_changing")
                self.assertTrue(actions["research_attention.activate_candidate"]["confirmation_required"])

                result = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertIsNone(result["data"]["active_map"])
                self.assertEqual(result["data"]["effective_attention"], project_config()["research_attention"])
                self.assertEqual(result["data"]["baseline"]["items"], project_config()["research_attention"])
                self.assertEqual(before, state_pin(app))
                self.assertFalse((root / "attention.sqlite3").exists())
            finally:
                app.close()

    def test_proposal_is_complete_persistent_and_does_not_move_research_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = open_app(root)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                before = state_pin(app)
                result = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {
                        "additions": [{
                            "statement": "Track a new synthetic cross-cutting implication.",
                            "rationale": "Keep it as guidance rather than an RQ.",
                            "source_reference_ids": ["REF-1"],
                            "related_question_ids": ["RQ-1"],
                        }],
                        "dispositions": [{
                            "attention_id": "ATT-BASE-1",
                            "disposition": "dropped",
                            "disposition_reason": "Superseded by the more precise synthetic item.",
                        }],
                        "links": [{
                            "attention_id": "ATT-BASE-2",
                            "related_question_seed_ids": ["RQ-SEED-1"],
                        }],
                    },
                })
                candidate = result["data"]["attention_map"]
                self.assertEqual(candidate["map_digest"], attention_map_digest(candidate))
                self.assertEqual(candidate["base"], {"source": "project_config_baseline"})
                self.assertEqual(len(candidate["items"]), 3)
                by_id = {item["attention_id"]: item for item in candidate["items"]}
                generated = [item for key, item in by_id.items() if key not in {"ATT-BASE-1", "ATT-BASE-2"}]
                self.assertEqual(len(generated), 1)
                self.assertTrue(generated[0]["attention_id"].startswith("ATT-"))
                self.assertEqual(generated[0]["disposition"], "active")
                self.assertEqual(by_id["ATT-BASE-1"]["disposition"], "dropped")
                self.assertIn("ATT-BASE-2", by_id)
                self.assertEqual(before, state_pin(app))
                status = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
                self.assertIsNone(status["data"]["active_map"])
                self.assertEqual(status["data"]["effective_attention"], project_config()["research_attention"])
                validate_attention_store_schema(root / "attention.sqlite3")
                map_id = candidate["map_id"]
            finally:
                app.close()

            reopened = open_app(root, seed=False)
            try:
                self.assertEqual(reopened.attention_store.load_map(map_id), candidate)
                self.assertEqual(before, state_pin(reopened))
            finally:
                reopened.close()

    def test_bounded_ingress_and_reference_validation_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = open_app(Path(temp))
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                invalid_payloads = [
                    {"additions": [{"attention_id": "CALLER-ID", "statement": "x"}]},
                    {"additions": [{"statement": "x", "disposition": "active"}]},
                    {"dispositions": [{"attention_id": "ATT-BASE-1", "disposition": "dropped"}]},
                    {"dispositions": [{"attention_id": "ATT-BASE-1", "disposition": "invalid"}]},
                    {"links": [{"attention_id": "ATT-BASE-1", "statement": "rewrite forbidden"}]},
                ]
                for payload in invalid_payloads:
                    with self.assertRaises(ValueError):
                        facade.submit_action({"action_type": "research_attention.propose", "payload": payload})

                for addition in (
                    {"statement": "bad source", "source_reference_ids": ["REF-UNKNOWN"]},
                    {"statement": "bad seed", "related_question_seed_ids": ["RQ-SEED-X"]},
                    {"statement": "bad RQ", "related_question_ids": ["RQ-X"]},
                ):
                    with self.assertRaises(ConversationRuntimeError) as invalid_ref:
                        facade.submit_action({
                            "action_type": "research_attention.propose",
                            "payload": {"additions": [addition]},
                        })
                    self.assertEqual(invalid_ref.exception.code, "ATTENTION-REF-001")
            finally:
                app.close()

    def test_exact_confirmation_activates_without_core_decision_or_snapshot_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = open_app(root)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                before = state_pin(app)
                decisions_before = tuple(app.state_repository.load_state_view("PRJ-1", "LIN-1").decisions)
                candidate = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Active synthetic guidance."}]},
                })["data"]["attention_map"]
                pending = facade.submit_action({
                    "action_type": "research_attention.activate_candidate",
                    "payload": {"attention_map_id": candidate["map_id"]},
                    "actor_id": "HUMAN-ATT",
                })
                self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")
                self.assertIsNone(facade.submit_action({"action_type": "research_attention.status", "payload": {}})["data"]["active_map"])
                self.assertEqual(before, state_pin(app))
                request_id = pending["confirmation_request"]["confirmation_request_id"]
            finally:
                app.close()

            reopened = open_app(root, seed=False)
            try:
                facade = LocalApplicationFacade(reopened, "PRJ-1")
                committed = facade.submit_confirmation({
                    "confirmation_request_id": request_id,
                    "actor_id": "HUMAN-ATT",
                })
                self.assertEqual(committed["status"], "SUCCEEDED")
                self.assertFalse(committed["action_receipt"]["research_state_mutation_performed"])
                status = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
                self.assertEqual(status["data"]["active_map"]["map_id"], candidate["map_id"])
                self.assertEqual(status["data"]["effective_attention"], candidate["items"])
                self.assertEqual(before, state_pin(reopened))
                state = reopened.state_repository.load_state_view("PRJ-1", "LIN-1")
                self.assertEqual(tuple(state.decisions), decisions_before)
                self.assertFalse(any(item.get("kind") in {"attention", "attention_map"} for item in state.effective_objects()))
                self.assertEqual(len(reopened.attention_store.activation_events("PRJ-1")), 1)
            finally:
                reopened.close()

    def test_same_base_candidates_stale_fail_without_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            app = open_app(Path(temp))
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                candidate_a = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Candidate A."}]},
                })["data"]["attention_map"]
                candidate_b = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Candidate B."}]},
                })["data"]["attention_map"]
                pending_a = facade.submit_action({
                    "action_type": "research_attention.activate_candidate",
                    "payload": {"attention_map_id": candidate_a["map_id"]},
                    "actor_id": "HUMAN-ATT",
                })
                pending_b = facade.submit_action({
                    "action_type": "research_attention.activate_candidate",
                    "payload": {"attention_map_id": candidate_b["map_id"]},
                    "actor_id": "HUMAN-ATT",
                })
                self.assertEqual(confirm(facade, pending_a)["status"], "SUCCEEDED")
                with self.assertRaises(ConversationRuntimeError) as stale:
                    confirm(facade, pending_b)
                self.assertEqual(stale.exception.code, "ATTENTION-STALE-001")
                active = facade.submit_action({"action_type": "research_attention.status", "payload": {}})["data"]["active_map"]
                self.assertEqual(active["map_id"], candidate_a["map_id"])
                self.assertEqual(len(app.attention_store.activation_events("PRJ-1")), 1)
                self.assertIsNotNone(app.attention_store.load_map(candidate_b["map_id"]))
            finally:
                app.close()

    def test_desktop_context_uses_effective_attention_and_old_materialization_stays_frozen(self):
        with tempfile.TemporaryDirectory() as temp:
            app = open_app(Path(temp))
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                first = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": "RQ-1"},
                })
                first_proposal_id = first["proposal"]["proposal_id"]
                first_materialization = deepcopy(app.conversation_store.load_materialization(first_proposal_id))
                self.assertEqual(first_materialization["context_pack"]["research_attention"], project_config()["research_attention"])
                first_digest = first_materialization["context_pack"]["context_pack_digest"]

                candidate = facade.submit_action({
                    "action_type": "research_attention.propose",
                    "payload": {"additions": [{"statement": "Projected active guidance."}]},
                })["data"]["attention_map"]
                pending = facade.submit_action({
                    "action_type": "research_attention.activate_candidate",
                    "payload": {"attention_map_id": candidate["map_id"]},
                    "actor_id": "HUMAN-ATT",
                })
                self.assertEqual(confirm(facade, pending)["status"], "SUCCEEDED")

                second = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": "RQ-1"},
                })
                second_materialization = app.conversation_store.load_materialization(second["proposal"]["proposal_id"])
                self.assertEqual(second_materialization["context_pack"]["research_attention"], candidate["items"])
                self.assertNotEqual(second_materialization["context_pack"]["context_pack_digest"], first_digest)
                self.assertEqual(app.conversation_store.load_materialization(first_proposal_id), first_materialization)
                self.assertEqual(first_materialization["context_pack"]["schema_version"], "0.1.0")
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
