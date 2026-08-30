from __future__ import annotations

import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
POSIX_LAUNCHER = ROOT / "research-loom"
WINDOWS_LAUNCHER = ROOT / "research-loom.cmd"


class RepositoryLauncherContractTests(unittest.TestCase):
    def test_posix_launcher_owns_frozen_uv_execution(self):
        lines = POSIX_LAUNCHER.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "#!/usr/bin/env -S uv run --frozen python")
        self.assertNotIn("# /// script", POSIX_LAUNCHER.read_text(encoding="utf-8"))
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
