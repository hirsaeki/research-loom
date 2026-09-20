from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import rfc8785

from plugins.local_application import LocalWorkspace
from plugins.local_project_input_store import LocalProjectInputStore

ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"

def _configuration_digest(config: dict) -> str:
    value = deepcopy(config); value.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()

def _write_inputs(root: Path) -> tuple[Path, Path]:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = _configuration_digest(config)
    config_path = root / "input-project-config.json"
    profile_path = root / "input-effective-profile-set.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    profile_path.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return config_path, profile_path

class ParentDurableStoreAcceptanceTests(unittest.TestCase):
    def test_parent_tree_move_and_initialized_child_missing_ablation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config, profile = _write_inputs(root); workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config, profile)
            state = opened.application.state_repository.load_state_view(
                opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id)
            )
            before = (state.current_snapshot["id"], state.current_snapshot["content_digest"])
            store = LocalProjectInputStore(workspace); store.close(); opened.close()
            parent = workspace / ".research-loom"
            self.assertFalse((workspace / "project-config.json").exists())
            self.assertFalse((workspace / "effective-profile-set.json").exists())
            self.assertTrue((parent / "project-config.json").is_file())
            self.assertTrue((parent / "effective-profile-set.json").is_file())
            binding = json.loads((parent / "workspace-binding.json").read_text(encoding="utf-8"))
            self.assertEqual(binding["durable_children"]["project_inputs"]["locator"], ".research-loom/project-inputs")
            self.assertNotIn("research_exhibits", binding["durable_children"])
            self.assertEqual(LocalWorkspace.doctor(workspace)["status"], "OK")
            moved = root / "moved-workspace"; moved.mkdir(); shutil.copytree(parent, moved / ".research-loom")
            with LocalWorkspace.open(moved) as reopened:
                state = reopened.application.state_repository.load_state_view(
                    reopened.project_id, reopened.application.state_repository.load_active_lineage_ref(reopened.project_id)
                )
                self.assertEqual((state.current_snapshot["id"], state.current_snapshot["content_digest"]), before)
            self.assertEqual(LocalWorkspace.doctor(moved)["status"], "OK")
            child = moved / ".research-loom" / "project-inputs"; removed = moved / "project-inputs.removed"; child.rename(removed)
            degraded = LocalWorkspace.doctor(moved)
            self.assertEqual(degraded["status"], "DEGRADED")
            self.assertEqual(degraded["issues"][0]["code"], "WORKSPACE-OPTIONAL-CHILD-MISSING-001")
            removed.rename(child)
            self.assertEqual(LocalWorkspace.doctor(moved)["status"], "OK")

    def test_never_initialized_optional_child_is_not_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config, profile = _write_inputs(root); workspace = root / "workspace"
            opened = LocalWorkspace.init(workspace, config, profile); opened.close()
            binding = json.loads((workspace / ".research-loom" / "workspace-binding.json").read_text(encoding="utf-8"))
            self.assertNotIn("research_exhibits", binding["durable_children"])
            self.assertFalse((workspace / ".research-loom" / "research-exhibits.sqlite3").exists())
            self.assertEqual(LocalWorkspace.doctor(workspace)["status"], "OK")

if __name__ == "__main__":
    unittest.main()
