from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

from core.conversation import ConversationRuntimeError
from core.decision import make_response
from core.runtime import canonical_digest
from plugins.local_application import (
    LocalApplicationError,
    LocalApplicationFacade,
    LocalResearchApplication,
    LocalWorkspace,
    LocalWorkspaceError,
)
from plugins.local_application.cli import main as cli_main
from runtime_fixtures import project, rq, seed_state


ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


class NullResolver:
    def resolve(self, *_args, **_kwargs):
        return None


def _configuration_digest(config: dict) -> str:
    value = deepcopy(config)
    value.pop("configuration_digest", None)
    import hashlib
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def bootstrap_config() -> dict:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = _configuration_digest(config)
    return config


def profile_set() -> dict:
    return json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))


def write_inputs(root: Path, *, config=None, profiles=None) -> tuple[Path, Path]:
    config_path = root / "input-project-config.json"
    profile_path = root / "input-effective-profile-set.json"
    config_path.write_text(json.dumps(config or bootstrap_config()), encoding="utf-8")
    profile_path.write_text(json.dumps(profiles or profile_set()), encoding="utf-8")
    return config_path, profile_path


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
        "profile_pins": [{
            "profile_id": "fixture.research",
            "profile_type": "research",
            "profile_version": "1.0.0",
            "manifest_sha256": "1" * 64,
        }],
        "content_digest": expected_digest,
    }


def state_delta(state, proposal_id: str, action: dict, *, rationale="fixture") -> dict:
    candidate = {
        "proposal_id": proposal_id,
        "project_ref": state.project_ref,
        "lineage_ref": state.lineage_ref,
        "source_refs": ["TEST-SETUP"],
        "proposed_actions": [action],
        "affected_refs": [],
        "rationale": rationale,
        "required_human_decision_kinds": [],
        "current_snapshot_ref": state.current_snapshot["id"],
        "current_snapshot_digest": state.current_snapshot["content_digest"],
        "provenance": {"limitations": ["test setup"]},
        "candidate_only": True,
    }
    candidate["proposal_digest"] = canonical_digest(candidate)
    return candidate


def run_cli(argv, stdin_text=""):
    stream = io.StringIO()
    with patch("sys.stdin", io.StringIO(stdin_text)), redirect_stdout(stream):
        code = cli_main(argv)
    raw = stream.getvalue()
    return code, raw, json.loads(raw)


class LocalWorkspaceBootstrapTests(unittest.TestCase):
    def test_bootstrap_reopen_and_non_promotions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config_path, profile_path)
            try:
                project_id = opened.project_id
                lineage = opened.application.state_repository.load_active_lineage_ref(project_id)
                state = opened.application.state_repository.load_state_view(project_id, lineage)
                first_head = (
                    state.active_lineage_ref,
                    state.current_snapshot["id"],
                    state.current_snapshot["content_digest"],
                )
                kinds = [item["kind"] for item in state.effective_objects()]
                self.assertEqual(kinds, ["project"])
                self.assertEqual(state.project_ref, bootstrap_config()["project"]["project_id"])
                self.assertTrue(state.project_config["research_questions"]["seeds"])
                self.assertNotIn("research_question", kinds)
                self.assertNotIn("source", kinds)
                self.assertNotIn("evidence", kinds)
                self.assertNotIn("finding", kinds)
                binding = opened.binding
                self.assertNotIn("objects", binding)
                self.assertNotIn("members", binding)
                self.assertNotIn("decisions", binding)
            finally:
                opened.close()

            reopened = LocalWorkspace.open(workspace)
            try:
                state = reopened.application.state_repository.load_state_view(
                    reopened.project_id,
                    reopened.application.state_repository.load_active_lineage_ref(reopened.project_id),
                )
                self.assertEqual(
                    first_head,
                    (state.active_lineage_ref, state.current_snapshot["id"], state.current_snapshot["content_digest"]),
                )
            finally:
                reopened.close()

    def test_init_refuses_existing_and_unrelated_or_partial_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config_path, profile_path)
            opened.close()
            with self.assertRaises(LocalWorkspaceError) as initialized:
                LocalWorkspace.init(workspace, config_path, profile_path)
            self.assertEqual(initialized.exception.code, "WORKSPACE-INIT-EXISTS-001")

            unrelated = root / "unrelated"
            unrelated.mkdir()
            (unrelated / "keep.txt").write_text("do not delete", encoding="utf-8")
            with self.assertRaises(LocalWorkspaceError):
                LocalWorkspace.init(unrelated, config_path, profile_path)
            self.assertEqual((unrelated / "keep.txt").read_text(), "do not delete")

            partial = root / "partial"
            (partial / ".research-loom").mkdir(parents=True)
            (partial / ".research-loom/.initializing").write_text("initializing\n")
            with self.assertRaises(LocalWorkspaceError) as incomplete:
                LocalWorkspace.open(partial)
            self.assertEqual(incomplete.exception.code, "WORKSPACE-PARTIAL-001")

    def test_binding_and_pin_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            for case in ("project_id", "config", "profiles", "db_pin", "malformed"):
                workspace = root / case
                opened = LocalWorkspace.init(workspace, config_path, profile_path)
                opened.close()
                binding_path = workspace / ".research-loom/workspace-binding.json"
                if case == "project_id":
                    binding = json.loads(binding_path.read_text())
                    binding["project_id"] = "PRJ-OTHER"
                    binding_path.write_text(json.dumps(binding))
                elif case == "config":
                    config = json.loads((workspace / "project-config.json").read_text())
                    config["project"]["title"] += " tampered"
                    (workspace / "project-config.json").write_text(json.dumps(config))
                elif case == "profiles":
                    profiles = json.loads((workspace / "effective-profile-set.json").read_text())
                    profiles["core_contracts"]["research_contract"] = "0.1.1"
                    (workspace / "effective-profile-set.json").write_text(json.dumps(profiles))
                elif case == "db_pin":
                    db = sqlite3.connect(workspace / ".research-loom/research-state.sqlite3")
                    try:
                        db.execute("UPDATE project_state SET effective_profile_set_digest=?", ("sha256:" + "0" * 64,))
                        db.commit()
                    finally:
                        db.close()
                else:
                    binding_path.write_text("{bad-json", encoding="utf-8")
                with self.assertRaises(LocalWorkspaceError, msg=case):
                    LocalWorkspace.open(workspace)

    def test_existing_rq_reference_requires_explicit_authoritative_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
            config_path, profile_path = write_inputs(root, config=config)
            with self.assertRaises(LocalWorkspaceError) as raised:
                LocalWorkspace.init(root / "workspace", config_path, profile_path)
            self.assertEqual(raised.exception.code, "WORKSPACE-BOOTSTRAP-RQ-001")

    def test_doctor_is_read_only_and_reports_expected_stores(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config_path, profile_path)
            opened.close()
            binding_mtime = (workspace / ".research-loom/workspace-binding.json").stat().st_mtime_ns
            result = LocalWorkspace.doctor(workspace)
            self.assertEqual(result["status"], "OK")
            self.assertEqual(binding_mtime, (workspace / ".research-loom/workspace-binding.json").stat().st_mtime_ns)
            checks = {item["check"] for item in result["checks"]}
            self.assertTrue({"research_state", "conversation_store", "decision_store", "execution_store"} <= checks)


class LocalApplicationFacadeTests(unittest.TestCase):
    def make_app(self, root: str):
        seed = seed_state(objects=[project(), rq(state="approved")], snapshot_id="SNP-FACADE-0")
        return LocalResearchApplication(
            root,
            resolver=NullResolver(),
            effective_profile_set_provider=profile_provider,
            seed_state=seed,
        )

    def test_typed_status_and_action_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                actions = facade.list_actions()["actions"]
                discovered = {item["action_type"]: item for item in actions}
                self.assertIn("research.status", discovered)
                self.assertEqual(discovered["research.status"]["route_category"], "harness_service")
                self.assertNotIn("service_id", discovered["research.status"])
                result = facade.submit_action({"action_type": "research.status", "payload": {}})
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["data"]["state"]["active_lineage_ref"], "LIN-1")
                self.assertFalse(result["action_receipt"]["research_state_mutation_performed"])
            finally:
                app.close()

    def test_desktop_action_uses_existing_external_execution_path(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                result = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": "RQ-1", "purpose": "Investigate current evidence."},
                })
                self.assertEqual(result["status"], "CAPABILITY_EXECUTION_PREPARED")
                run = app.execution_store.load_run(result["run_id"])
                self.assertEqual(run.capability_id, "desktop-research")
                self.assertEqual(run.status.value, "PREPARED")
            finally:
                app.close()

    def test_typed_ingress_rejects_unknown_payload_and_authority_override(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                with self.assertRaises(ConversationRuntimeError):
                    facade.submit_action({"action_type": "unknown.action", "payload": {}})
                with self.assertRaises(LocalApplicationError) as payload_error:
                    facade.submit_action({"action_type": "research.status", "payload": {"not_allowed": True}})
                self.assertEqual(payload_error.exception.code, "APPLICATION-PAYLOAD-001")
                with self.assertRaises(LocalApplicationError) as route:
                    facade.submit_action({"action_type": "research.status", "payload": {}, "route": "override"})
                self.assertEqual(route.exception.code, "APPLICATION-INGRESS-001")
                for forbidden in ("decision_reference_ids", "state_transition_request"):
                    with self.assertRaises(LocalApplicationError) as authority:
                        facade.submit_action({
                            "action_type": "research.status",
                            "payload": {forbidden: ["DEC-X"] if forbidden.endswith("ids") else {}},
                        })
                    self.assertEqual(authority.exception.code, "APPLICATION-AUTHORITY-001")
            finally:
                app.close()

    def test_confirmation_and_dynamic_human_decision_are_not_bypassed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                state = app.state_repository.load_state_view("PRJ-1", "LIN-1")
                prior = state.latest_object("research_question", "RQ-1")
                revised = deepcopy(dict(prior))
                revised["revision"] = int(prior["revision"]) + 1
                revised["text"] = "Materially revised question?"
                candidate = state_delta(state, "SDP-FACADE", {
                    "kind": "REVISE_OBJECT",
                    "payload": {"object": revised},
                    "decision_refs": [],
                    "source_refs": ["TEST-SETUP"],
                })
                app.conversation_store.store_state_delta_proposal(candidate["proposal_id"], candidate)
                facade = LocalApplicationFacade(app, "PRJ-1")
                action = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": "SDP-FACADE"},
                    "actor_id": "HUMAN-1",
                })
                self.assertEqual(action["status"], "CONFIRMATION_REQUIRED")
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": action["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-1",
                })
                self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
                self.assertTrue(facade.status()["pending_human_decisions"])
            finally:
                app.close()


class JsonCliTests(unittest.TestCase):
    def test_init_status_actions_and_typed_stdin_are_json_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            workspace = root / "workspace"
            code, raw, init = run_cli([
                "init", "--workspace", str(workspace), "--project-config", str(config_path),
                "--effective-profile-set", str(profile_path), "--json",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(raw), init)
            self.assertEqual(init["status"], "INITIALIZED")

            for command in ("status", "actions", "doctor"):
                code, raw, value = run_cli([command, "--workspace", str(workspace), "--json"])
                self.assertEqual(code, 0, (command, value))
                self.assertEqual(json.loads(raw), value)

            code, raw, action = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({"action_type": "research.status", "payload": {}}),
            )
            self.assertEqual(code, 0)
            self.assertEqual(action["status"], "SUCCEEDED")
            self.assertEqual(json.loads(raw), action)

    def test_workflow_pending_is_exit_zero_and_malformed_input_is_nonzero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            workspace = root / "workspace"
            run_cli([
                "init", "--workspace", str(workspace), "--project-config", str(config_path),
                "--effective-profile-set", str(profile_path), "--json",
            ])
            code, _raw, pending = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": "MISSING-CANDIDATE"},
                }),
            )
            self.assertEqual(code, 0)
            self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")

            code, raw, error = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                "not-json",
            )
            self.assertNotEqual(code, 0)
            self.assertEqual(json.loads(raw), error)
            self.assertEqual(error["status"], "ERROR")
            self.assertEqual(error["issues"][0]["code"], "CLI-INPUT-001")

    def test_cli_confirmation_and_human_decision_resolution_use_existing_services(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_inputs(root)
            workspace = root / "workspace"
            run_cli([
                "init", "--workspace", str(workspace), "--project-config", str(config_path),
                "--effective-profile-set", str(profile_path), "--json",
            ])

            opened = LocalWorkspace.open(workspace)
            try:
                state = opened.application.state_repository.load_state_view(
                    opened.project_id,
                    opened.application.state_repository.load_active_lineage_ref(opened.project_id),
                )
                candidate_rq = {
                    "schema_version": "0.1.0", "id": "RQ-CLI", "kind": "research_question",
                    "revision": 0, "project_id": opened.project_id, "text": "CLI RQ?",
                    "adoption_state": "candidate",
                }
                create = state_delta(state, "SDP-CLI-CREATE", {
                    "kind": "CREATE_OBJECT", "payload": {"object": candidate_rq},
                    "decision_refs": [], "source_refs": ["TEST-SETUP"],
                })
                opened.application.conversation_store.store_state_delta_proposal(create["proposal_id"], create)
            finally:
                opened.close()

            code, _raw, pending = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": "SDP-CLI-CREATE"},
                    "actor_id": "HUMAN-CLI",
                }),
            )
            self.assertEqual((code, pending["status"]), (0, "CONFIRMATION_REQUIRED"))
            code, _raw, committed = run_cli(
                ["confirmation", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-CLI",
                }),
            )
            self.assertEqual(code, 0)
            self.assertEqual(committed["status"], "SUCCEEDED")

            opened = LocalWorkspace.open(workspace)
            try:
                state = opened.application.state_repository.load_state_view(
                    opened.project_id,
                    opened.application.state_repository.load_active_lineage_ref(opened.project_id),
                )
                prior = state.latest_object("research_question", "RQ-CLI")
                approved = deepcopy(dict(prior))
                approved["revision"] = 1
                approved["adoption_state"] = "approved"
                adopt = state_delta(state, "SDP-CLI-ADOPT", {
                    "kind": "ADOPT_OBJECT", "payload": {"object": approved},
                    "decision_refs": [], "source_refs": ["TEST-SETUP"],
                })
                opened.application.conversation_store.store_state_delta_proposal(adopt["proposal_id"], adopt)
            finally:
                opened.close()

            _code, _raw, pending = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": "SDP-CLI-ADOPT"},
                    "actor_id": "HUMAN-CLI",
                }),
            )
            _code, _raw, decision = run_cli(
                ["confirmation", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-CLI",
                }),
            )
            self.assertEqual(decision["status"], "HUMAN_DECISION_REQUIRED")

            code, _raw, status = run_cli(["status", "--workspace", str(workspace), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(len(status["pending_human_decisions"]), 1)
            request = decision["decision_request"]
            response = make_response(
                request=request,
                disposition="approve_exact",
                actor_id="HUMAN-CLI",
                responded_at=request["issued_at"],
            )
            code, _raw, resolved = run_cli(
                ["decision", "resolve", "--workspace", str(workspace), "--json", "-"],
                json.dumps(response),
            )
            self.assertEqual(code, 0)
            self.assertEqual(resolved["status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
