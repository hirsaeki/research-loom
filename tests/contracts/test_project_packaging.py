"""The root project is an editable package with a research-loom console script (#496)."""

from __future__ import annotations

import importlib
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict:
    return tomllib.loads((ROOT / name).read_text(encoding="utf-8"))


class ProjectPackagingTests(unittest.TestCase):
    def setUp(self):
        self.pyproject = _load("pyproject.toml")

    def test_build_backend_is_uv_build_so_sync_needs_no_network(self):
        build = self.pyproject["build-system"]
        self.assertEqual("uv_build", build["build-backend"])
        self.assertEqual(1, len(build["requires"]))
        self.assertTrue(build["requires"][0].startswith("uv_build"))

    def test_modules_are_the_repository_code_trees(self):
        backend = self.pyproject["tool"]["uv"]["build-backend"]
        self.assertEqual("", backend["module-root"])
        self.assertEqual(["core", "plugins"], backend["module-name"])
        self.assertTrue(backend["namespace"])
        self.assertNotIn("package", self.pyproject["tool"]["uv"])

    def test_console_script_targets_the_launcher_entry_point(self):
        target = self.pyproject["project"]["scripts"]["research-loom"]
        module, _, attr = target.partition(":")
        launcher = (ROOT / "research-loom").read_text(encoding="utf-8")
        self.assertIn(f"from {module} import {attr}", launcher)
        self.assertTrue(callable(getattr(importlib.import_module(module), attr)))

    def test_lock_installs_the_project_in_editable_mode(self):
        lock = _load("uv.lock")
        project = [p for p in lock["package"] if p["name"] == self.pyproject["project"]["name"]]
        self.assertEqual([{"editable": "."}], [p["source"] for p in project])


if __name__ == "__main__":
    unittest.main()
