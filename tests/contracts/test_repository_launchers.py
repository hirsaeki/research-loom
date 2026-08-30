from __future__ import annotations

import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
POSIX_LAUNCHER = ROOT / "research-loom"
WINDOWS_LAUNCHER = ROOT / "research-loom.cmd"


class RepositoryLauncherContractTests(unittest.TestCase):
    def test_posix_launcher_owns_frozen_uv_execution(self):
        text = POSIX_LAUNCHER.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertEqual(lines[1], "'''exec' uv run --frozen python \"$0\" \"$@\"")
        self.assertEqual(lines[2], "' '''")
        self.assertNotIn("/usr/bin/env -S", text)
        self.assertNotIn("# /// script", text)
        self.assertNotIn("uv sync", text)
        compile(text, str(POSIX_LAUNCHER), "exec")
        if os.name != "nt":
            self.assertTrue(os.access(POSIX_LAUNCHER, os.X_OK))

    def test_windows_launcher_owns_frozen_uv_execution_and_preserves_exit_code(self):
        text = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn('uv run --frozen python "%~dp0research-loom" %*', text)
        self.assertIn('set "_research_loom_exit=%ERRORLEVEL%"', text)
        self.assertIn("endlocal & exit /b %_research_loom_exit%", text)
        self.assertNotIn("uv sync", text)
        self.assertNotIn("python3", text)
        self.assertNotIn("py ", text)


if __name__ == "__main__":
    unittest.main()
