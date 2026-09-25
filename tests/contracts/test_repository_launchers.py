from __future__ import annotations

import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
POSIX_LAUNCHER = ROOT / "research-loom"
WINDOWS_LAUNCHER = ROOT / "research-loom.cmd"
ROOT_GITIGNORE = ROOT / ".gitignore"


class RepositoryLauncherContractTests(unittest.TestCase):
    def test_posix_launcher_uses_presynced_project_environment(self):
        text = POSIX_LAUNCHER.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertEqual(lines[1], "'''exec' \"$(dirname \"$0\")/.venv/bin/python\" \"$0\" \"$@\"")
        self.assertEqual(lines[2], "' '''")
        self.assertNotIn("/usr/bin/env -S", text)
        self.assertNotIn("# /// script", text)
        self.assertNotIn("uv run", text)
        self.assertNotIn("uv sync", text)
        compile(text, str(POSIX_LAUNCHER), "exec")
        if os.name != "nt":
            self.assertTrue(os.access(POSIX_LAUNCHER, os.X_OK))

    def test_windows_launcher_uses_presynced_project_environment_and_preserves_exit_code(self):
        text = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('set "_research_loom_python=%~dp0.venv\\Scripts\\python.exe"', text)
        self.assertIn('if not exist "%_research_loom_python%" (', text)
        self.assertIn('"%_research_loom_python%" "%~dp0research-loom" %*', text)
        self.assertIn('set "_research_loom_exit=%ERRORLEVEL%"', text)
        self.assertIn("endlocal & exit /b %_research_loom_exit%", text)
        self.assertIn("uv sync --frozen", text)
        self.assertNotIn("uv run", text)
        self.assertNotIn("python3", text)
        self.assertNotIn("py ", text)

    def test_root_gitignore_excludes_runtime_environment_and_python_bytecode(self):
        ignored = set(ROOT_GITIGNORE.read_text(encoding="utf-8").splitlines())
        self.assertIn(".venv/", ignored)
        self.assertIn("__pycache__/", ignored)
        self.assertIn("*.py[cod]", ignored)


if __name__ == "__main__":
    unittest.main()
