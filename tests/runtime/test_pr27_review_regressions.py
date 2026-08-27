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

import plugins.local_application.workspace as workspace_module
from plugins.local_application import LocalWorkspace


ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG = ROOT / "projects/fixtures/valid/generic-project-config.json"
EFFECTIVE_PROFILES = ROOT / "profiles/fixtures/valid/effective-profile-set.json"
CLI = ROOT / "plugins/local_application/cli.py"


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


if __name__ == "__main__":
    unittest.main()
