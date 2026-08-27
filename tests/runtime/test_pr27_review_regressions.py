from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

import plugins.local_application.facade as facade_module
import plugins.local_application.workspace as workspace_module
from plugins.local_application import LocalApplicationFacade, LocalResearchApplication, LocalWorkspace
from plugins.local_conversation_store import LocalConversationStore
from runtime_fixtures import project, rq, seed_state


ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG = ROOT / "projects/fixtures/valid/generic-project-config.json"
EFFECTIVE_PROFILES = ROOT / "profiles/fixtures/valid/effective-profile-set.json"
CLI = ROOT / "plugins/local_application/cli.py"
FACADE = ROOT / "plugins/local_application/facade.py"


class NullResolver:
    def resolve(self, *_args, **_kwargs):
        return None


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


def bootstrap_config(path: Path) -> Path:
    config = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    payload = deepcopy(config)
    payload.pop("configuration_digest", None)
    config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class PR27ReviewRegressionTests(unittest.TestCase):
    def test_failed_init_cleans_only_paths_created_by_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = bootstrap_config(root / "project.json")

            for preexisting in (False, True):
                workspace = root / ("existing-empty" if preexisting else "new-workspace")
                if preexisting:
                    workspace.mkdir()

                with patch.object(
                    workspace_module,
                    "LocalResearchApplication",
                    side_effect=RuntimeError("synthetic initialization failure"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "synthetic initialization failure"):
                        LocalWorkspace.init(workspace, config, EFFECTIVE_PROFILES)

                if preexisting:
                    self.assertTrue(workspace.is_dir())
                    self.assertEqual(list(workspace.iterdir()), [])
                else:
                    self.assertFalse(workspace.exists())

    def test_partial_project_config_write_cannot_strand_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = bootstrap_config(root / "project.json")
            workspace = root / "workspace"

            def partial_copy(path, _value):
                path.write_text("{", encoding="utf-8")
                raise OSError("synthetic partial copy failure")

            with patch.object(workspace_module, "_copy_json", side_effect=partial_copy):
                with self.assertRaisesRegex(OSError, "synthetic partial copy failure"):
                    LocalWorkspace.init(workspace, config, EFFECTIVE_PROFILES)

            self.assertFalse(workspace.exists())

    def test_doctor_converts_direct_sqlite_error_to_structured_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = bootstrap_config(root / "project.json")
            workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config, EFFECTIVE_PROFILES)
            opened.close()

            real_connect = sqlite3.connect
            calls = 0

            def flaky_connect(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise sqlite3.OperationalError("synthetic locked database")
                return real_connect(*args, **kwargs)

            with patch.object(workspace_module.sqlite3, "connect", side_effect=flaky_connect):
                result = LocalWorkspace.doctor(workspace)

            self.assertEqual(result["status"], "ERROR")
            self.assertEqual(result["issues"][0]["code"], "WORKSPACE-STATE-DB-001")
            self.assertIn("unreadable or incompatible", result["issues"][0]["message"])

    def test_cli_routes_workspace_lifecycle_through_facade(self):
        source = CLI.read_text(encoding="utf-8")
        self.assertNotIn("LocalWorkspace.", source)
        self.assertIn("LocalApplicationFacade.initialize_workspace", source)
        self.assertIn("LocalApplicationFacade.doctor_workspace", source)

    def test_facade_uses_public_coordinator_and_store_queries(self):
        source = FACADE.read_text(encoding="utf-8")
        for private_call in (
            "coordinator._actions",
            "coordinator._validator",
            "coordinator._store",
            "coordinator._state",
            "coordinator._build_proposal",
            "coordinator._build_confirmation_request",
            "coordinator._execute",
            "conversation_store._db",
            "conversation_store._lock",
            "execution_store._connection",
            "execution_store._lock",
        ):
            self.assertNotIn(private_call, source)
        self.assertIn("coordinator.process_action_draft", source)
        self.assertIn("coordinator.action_definitions", source)
        self.assertIn("list_pending_confirmation_requests", source)
        self.assertIn("pending_runs_for_project", source)

    def test_pending_confirmation_query_is_project_scoped_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LocalConversationStore(Path(temp) / "conversation.db")
            try:
                for index, project_id in enumerate(("PRJ-A", "PRJ-B", "PRJ-A")):
                    proposal_id = f"PROP-{index}"
                    conversation_id = f"CONV-{index}"
                    store.store_proposal({
                        "message_type": "action_proposal",
                        "proposal_id": proposal_id,
                        "proposal_digest": f"sha256:{index:064x}",
                        "conversation_id": conversation_id,
                        "commitment_mode": "commit_requested",
                    })
                    store.store_confirmation_request({
                        "message_type": "confirmation_request",
                        "confirmation_request_id": f"CONF-{index}",
                        "request_digest": f"sha256:{index + 10:064x}",
                        "proposal_binding": {"proposal_id": proposal_id},
                        "conversation_id": conversation_id,
                        "project_id": project_id,
                    })

                result = store.list_pending_confirmation_requests("PRJ-A", limit=1)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["project_id"], "PRJ-A")
            finally:
                store.close()

    def test_status_is_bounded_and_reports_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            app = LocalResearchApplication(
                temp,
                resolver=NullResolver(),
                effective_profile_set_provider=profile_provider,
                seed_state=seed_state(
                    objects=[project(), rq(state="approved")],
                    snapshot_id="SNP-STATUS-0",
                ),
            )
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                for index in range(3):
                    pending = facade.submit_action({
                        "action_type": "state.apply_candidate",
                        "payload": {"state_delta_proposal_id": f"MISSING-{index}"},
                    })
                    self.assertEqual(pending["status"], "CONFIRMATION_REQUIRED")
                    prepared = facade.submit_action({
                        "action_type": "desktop_research.investigate",
                        "payload": {
                            "question_id": "RQ-1",
                            "purpose": f"bounded status fixture {index}",
                        },
                    })
                    self.assertEqual(prepared["status"], "CAPABILITY_EXECUTION_PREPARED")

                with patch.object(facade_module, "_STATUS_ITEM_LIMIT", 2):
                    status = facade.status()

                self.assertEqual(len(status["pending_confirmations"]), 2)
                self.assertEqual(len(status["pending_runs"]), 2)
                self.assertTrue(status["truncated"]["pending_confirmations"])
                self.assertTrue(status["truncated"]["pending_runs"])
                self.assertTrue(all(run["status"] == "RUNNING" for run in status["pending_runs"]))
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
