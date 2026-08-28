from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"
RESEARCH_SCHEMA = json.loads((ROOT / "core/models/research-object.schema.json").read_text(encoding="utf-8"))


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


def _write_inputs(root: Path) -> tuple[Path, Path]:
    config = root / "project-config.json"
    profiles = root / "effective-profile-set.json"
    config.write_text(json.dumps(_bootstrap_config()), encoding="utf-8")
    profiles.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return config, profiles


def _run_cli(argv: list[str]) -> tuple[int, dict]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main(argv)
    return code, json.loads(stream.getvalue())


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _state_delta(state, proposal_id: str, action: dict) -> dict:
    value = {
        "proposal_id": proposal_id,
        "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref,
        "source_refs": [],
        "proposed_actions": [action],
        "affected_refs": [],
        "rationale": "test setup",
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {"producer": "test-setup"},
        "candidate_only": True,
    }
    value["proposal_digest"] = canonical_digest(value)
    return value


def _init_workspace(root: Path) -> Path:
    config, profiles = _write_inputs(root)
    workspace = root / "workspace"
    result = LocalApplicationFacade.initialize_workspace(workspace, config, profiles)
    assert result["status"] == "INITIALIZED"
    return workspace


def _proposal_input(**payload) -> dict:
    value = {
        "text": "企業はどの条件でAIへ意思決定を委ねるべきか",
        "rationale": "研究テーマを意思決定条件へ蒸溜した。",
        "acceptance_criteria": ["委任レベルを比較可能に説明できる"],
        "scope_limits": ["AGI実現時期そのものの予測は対象外"],
        "derived_from_seed_ids": ["RQ-SEED-001"],
    }
    value.update(payload)
    return {"action_type": "research_question.propose", "payload": value, "actor_id": "HUMAN-RQ"}


class ResearchQuestionProposalTests(unittest.TestCase):
    def test_registry_candidate_contract_authority_seed_and_parent_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                before = facade.status()["snapshot"]
                definitions = {item["action_type"]: item for item in facade.list_actions()["actions"]}
                definition = definitions["research_question.propose"]
                self.assertEqual(definition["effect"], "read_only")
                self.assertFalse(definition["confirmation_required"])
                self.assertEqual(definition["route_category"], "harness_service")

                result = facade.submit_action(_proposal_input())
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertFalse(result["action_receipt"]["research_state_mutation_performed"])
                self.assertEqual(before, facade.status()["snapshot"])

                candidate = result["data"]["research_question_candidate"]
                self.assertTrue(candidate["id"].startswith("RQ-"))
                self.assertEqual(candidate["revision"], 0)
                self.assertEqual(candidate["project_id"], facade.project_id)
                self.assertEqual(candidate["kind"], "research_question")
                self.assertEqual(candidate["adoption_state"], "approved")
                self.assertNotIn("decision_ids", candidate)
                validator = Draft202012Validator(RESEARCH_SCHEMA, format_checker=FormatChecker())
                self.assertEqual(list(validator.iter_errors(candidate)), [])

                state_delta = result["data"]["state_delta_proposal"]
                basis = deepcopy(state_delta)
                supplied_digest = basis.pop("proposal_digest")
                self.assertEqual(canonical_digest(basis), supplied_digest)
                self.assertTrue(state_delta["candidate_only"])
                self.assertEqual(state_delta["proposed_actions"][0]["kind"], "CREATE_OBJECT")
                self.assertEqual(state_delta["source_refs"], [])
                self.assertEqual(state_delta["proposed_actions"][0]["source_refs"], [])
                self.assertEqual(
                    state_delta["provenance"]["project_config_seed_ids"], ["RQ-SEED-001"]
                )
                stored = facade._application.conversation_store.load_state_delta_proposal(
                    state_delta["proposal_id"]
                )
                self.assertEqual(stored, state_delta)
                kinds = {item["kind"] for item in facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                ).effective_objects()}
                self.assertNotIn("research_question", kinds)
                self.assertNotIn("source", kinds)
                self.assertNotIn("evidence", kinds)

                null_parent = facade.submit_action(_proposal_input(parent_question_id=None))
                self.assertEqual(null_parent["status"], "SUCCEEDED")
                self.assertNotIn("parent_question_id", null_parent["data"]["research_question_candidate"])

                forbidden_fields = {
                    "id": "RQ-CALLER",
                    "project_id": facade.project_id,
                    "kind": "research_question",
                    "schema_version": "0.1.0",
                    "revision": 0,
                    "adoption_state": "approved",
                    "decision_ids": ["DEC-X"],
                    "transition_kind": "CREATE_OBJECT",
                    "decision_reference_ids": ["DEC-X"],
                    "snapshot_binding": {},
                }
                for field, value in forbidden_fields.items():
                    with self.subTest(field=field), self.assertRaises(LocalApplicationError):
                        facade.submit_action(_proposal_input(**{field: value}))

                invalid_payloads = [
                    {"text": ""},
                    {"acceptance_criteria": "not-a-list"},
                    {"acceptance_criteria": [""]},
                    {"scope_limits": [1]},
                    {"derived_from_seed_ids": ["RQ-SEED-001", "RQ-SEED-001"]},
                ]
                for payload in invalid_payloads:
                    with self.subTest(payload=payload), self.assertRaises(LocalApplicationError):
                        facade.submit_action(_proposal_input(**payload))

                for payload in (
                    {"derived_from_seed_ids": ["RQ-SEED-MISSING"]},
                    {"parent_question_id": "RQ-MISSING"},
                ):
                    with self.subTest(payload=payload):
                        failed = facade.submit_action(_proposal_input(**payload))
                        self.assertEqual(failed["status"], "FAILED")
                        self.assertFalse(failed["action_receipt"]["research_state_mutation_performed"])
                        self.assertEqual(before, facade.status()["snapshot"])

    def test_valid_authoritative_parent_is_accepted_after_adoption(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                parent_id = proposed["data"]["research_question_candidate"]["id"]
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-RQ",
                })
                decision = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })["decision_request"]
                resolved = facade.resolve_human_decision({
                    "request_id": decision["request_id"],
                    "request_digest": decision["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-RQ",
                })
                self.assertEqual(resolved["status"], "RESOLVED")
                child = facade.submit_action(_proposal_input(
                    text="親RQを実装条件へ分解すると何が必要か",
                    parent_question_id=parent_id,
                ))
                self.assertEqual(child["status"], "SUCCEEDED")
                self.assertEqual(
                    child["data"]["research_question_candidate"]["parent_question_id"], parent_id
                )


class ResearchQuestionAdoptionCliTests(unittest.TestCase):
    def test_process_restart_temp_file_vertical_slice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config, profiles = _write_inputs(root)
            workspace = root / "workspace"
            code, initialized = _run_cli([
                "init", "--workspace", str(workspace), "--project-config", str(config),
                "--effective-profile-set", str(profiles), "--json",
            ])
            self.assertEqual((code, initialized["status"]), (0, "INITIALIZED"))
            initial_snapshot = initialized["snapshot_id"]

            actions_file = _write_json(root / "rq-proposal.json", _proposal_input())
            code, proposed = _run_cli([
                "action", "submit", "--workspace", str(workspace), "--json", str(actions_file),
            ])
            self.assertEqual((code, proposed["status"]), (0, "SUCCEEDED"))
            rq_candidate = proposed["data"]["research_question_candidate"]
            candidate_id = proposed["data"]["state_delta_proposal_id"]
            self.assertFalse(proposed["action_receipt"]["research_state_mutation_performed"])

            status_query = _write_json(root / "research-status.json", {
                "action_type": "research.status",
                "payload": {"kinds": ["research_question"]},
            })
            code, status_before = _run_cli([
                "action", "submit", "--workspace", str(workspace), "--json", str(status_query),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(status_before["data"]["objects"], [])

            apply_file = _write_json(root / "apply.json", {
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": candidate_id},
                "actor_id": "HUMAN-RQ",
            })
            code, apply = _run_cli([
                "action", "submit", "--workspace", str(workspace), "--json", str(apply_file),
            ])
            self.assertEqual((code, apply["status"]), (0, "CONFIRMATION_REQUIRED"))
            self.assertFalse(apply["action_receipt"]["research_state_mutation_performed"] if "action_receipt" in apply else False)

            confirmation_file = _write_json(root / "confirmation.json", {
                "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-RQ",
            })
            code, confirmed = _run_cli([
                "confirmation", "submit", "--workspace", str(workspace), "--json", str(confirmation_file),
            ])
            self.assertEqual((code, confirmed["status"]), (0, "HUMAN_DECISION_REQUIRED"))
            request = confirmed["decision_request"]
            unit = request["decision_units"][0]
            self.assertEqual(unit["required_decision_kind"], "research_adoption")
            self.assertEqual(unit["required_choice"], "approve")
            self.assertEqual(unit["subject"], {"kind": "research_question", "id": rq_candidate["id"]})
            self.assertEqual(unit["candidate_value"], rq_candidate)

            decision_file = _write_json(root / "decision.json", {
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-RQ",
            })
            code, resolved = _run_cli([
                "decision", "resolve", "--workspace", str(workspace), "--json", str(decision_file),
            ])
            self.assertEqual((code, resolved["status"]), (0, "RESOLVED"))
            self.assertIsNotNone(resolved["commit_receipt"])

            code, research_status = _run_cli([
                "action", "submit", "--workspace", str(workspace), "--json", str(status_query),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(len(research_status["data"]["objects"]), 1)
            authoritative = research_status["data"]["objects"][0]
            self.assertEqual(authoritative["id"], rq_candidate["id"])
            self.assertEqual(authoritative["adoption_state"], "approved")
            self.assertEqual(len(authoritative["decision_ids"]), 1)

            code, final_status = _run_cli(["status", "--workspace", str(workspace), "--json"])
            self.assertEqual(code, 0)
            self.assertNotEqual(final_status["snapshot"]["snapshot_id"], initial_snapshot)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                self.assertIsNotNone(state.latest_object("snapshot", initial_snapshot))
                self.assertEqual(len(state.decisions), 1)
                self.assertEqual(state.decisions[0]["decision_kind"], "research_adoption")
                self.assertEqual(state.decisions[0]["choice"], "approve")

    def test_decline_revision_and_stale_leave_authoritative_state_unchanged(self):
        for disposition, expected in (
            ("decline", "DECLINED"),
            ("request_revision", "REVISION_REQUESTED"),
        ):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as temp:
                workspace = _init_workspace(Path(temp))
                with LocalApplicationFacade.open_workspace(workspace) as facade:
                    before = facade.status()["snapshot"]
                    proposed = facade.submit_action(_proposal_input())
                    apply = facade.submit_action({
                        "action_type": "state.apply_candidate",
                        "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                        "actor_id": "HUMAN-RQ",
                    })
                    request = facade.submit_confirmation({
                        "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                        "actor_id": "HUMAN-RQ",
                    })["decision_request"]
                    resolved = facade.resolve_human_decision({
                        "request_id": request["request_id"],
                        "request_digest": request["request_digest"],
                        "disposition": disposition,
                        "actor_id": "HUMAN-RQ",
                    })
                    self.assertEqual(resolved["status"], expected)
                    self.assertEqual(facade.status()["snapshot"], before)
                    state = facade._application.state_repository.load_state_view(
                        facade.project_id,
                        facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                    )
                    self.assertFalse(any(item["kind"] == "research_question" for item in state.effective_objects()))
                    if disposition == "request_revision":
                        revised = facade.submit_action(_proposal_input(text="修正版の研究問い"))
                        self.assertEqual(revised["status"], "SUCCEEDED")

        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                stale_id = proposed["data"]["state_delta_proposal_id"]
                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                source = {
                    "schema_version": "0.1.0", "id": "SRC-HEAD-ADVANCE", "kind": "source",
                    "revision": 0, "project_id": facade.project_id, "source_type": "report",
                    "canonical_locator": "fixture://head-advance",
                }
                head_advance = _state_delta(state, "SDP-HEAD-ADVANCE", {
                    "kind": "CREATE_OBJECT", "payload": {"object": source},
                    "decision_refs": [], "source_refs": [],
                })
                facade._application.conversation_store.store_state_delta_proposal(
                    head_advance["proposal_id"], head_advance
                )
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": head_advance["proposal_id"]},
                    "actor_id": "HUMAN-RQ",
                })
                advanced = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })
                self.assertEqual(advanced["status"], "SUCCEEDED")

                stale_apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": stale_id},
                    "actor_id": "HUMAN-RQ",
                })
                stale_result = facade.submit_confirmation({
                    "confirmation_request_id": stale_apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-RQ",
                })
                self.assertEqual(stale_result["status"], "FAILED")
                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                self.assertFalse(any(item["kind"] == "research_question" for item in state.effective_objects()))
                stored = facade._application.conversation_store.load_state_delta_proposal(stale_id)
                self.assertNotEqual(stored["current_snapshot_ref"], state.current_snapshot["id"])


if __name__ == "__main__":
    unittest.main()
