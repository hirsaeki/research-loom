from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import skipUnless
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_service import verify_export_root
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


@skipUnless(os.name == "nt", "Windows ACL regression")
class Issue133WindowsAclTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _icacls(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["icacls", str(path), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def _restrict_export_temp(self, real_mkdtemp):
        username = os.environ["USERNAME"]

        def restricted(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            self._icacls(path, "/inheritance:r")
            self._icacls(path, "/grant:r", f"{username}:(OI)(CI)F")
            return str(path)

        return restricted

    @staticmethod
    def _acl_entries(path: Path, stdout: str) -> list[str]:
        entries: list[str] = []
        rendered_path = str(path)
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("Successfully processed"):
                continue
            if line.startswith(rendered_path):
                stripped = line[len(rendered_path):].strip()
            entries.append(stripped)
        return entries

    def _assert_fresh_process_reads_package(self, output: Path) -> None:
        script = (
            "from pathlib import Path; import sys; "
            "root=Path(sys.argv[1]); "
            "targets=[root/'research-package.json',root/'research-package.md',"
            "next((root/'attachments').rglob('*.*'))]; "
            "[p.read_bytes() for p in targets]; print('fresh-process-read-ok')"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(output)],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("fresh-process-read-ok", completed.stdout)

    def test_acl1_acl2_export_resets_staging_acl_and_is_fresh_process_readable(self):
        facade, case = self._build()
        output = self.root / "issue133-detached"
        ordinary = self.root / "ordinary-child"
        ordinary.mkdir()
        ordinary_acl = self._icacls(ordinary).stdout
        real_mkdtemp = __import__("tempfile").mkdtemp
        try:
            with patch(
                "plugins.local_application.research_package_service.tempfile.mkdtemp",
                side_effect=self._restrict_export_temp(real_mkdtemp),
            ):
                exported = facade.export_research_package(case["package_id"], output)
        finally:
            facade.close()

        final_acl = self._icacls(output).stdout
        self.assertEqual(
            self._acl_entries(output, final_acl),
            self._acl_entries(ordinary, ordinary_acl),
        )
        self._assert_fresh_process_reads_package(output)
        verified = verify_export_root(output)
        self.assertEqual(verified["status"], "VERIFIED")
        self.assertEqual(verified["package_digest"], exported["package_digest"])
        print(json.dumps({
            "ISSUE133_ACL1_ACL2": {
                "ordinary_acl": ordinary_acl,
                "final_acl": final_acl,
                "package_digest": exported["package_digest"],
            }
        }, sort_keys=True))

    def test_acl3_acl_normalization_failure_removes_committed_output(self):
        facade, case = self._build()
        output = self.root / "issue133-acl-failure"
        try:
            with patch(
                "plugins.local_application.research_package_service._normalize_windows_export_acl",
                side_effect=OSError("fixture ACL reset failure"),
            ):
                with self.assertRaises(LocalApplicationError) as error:
                    facade.export_research_package(case["package_id"], output)
            self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-WRITE-001")
            self.assertFalse(output.exists())
        finally:
            facade.close()

    def test_ablation_old_rename_behavior_retains_restrictive_staging_acl(self):
        facade, case = self._build()
        output = self.root / "issue133-ablation"
        ordinary = self.root / "ordinary-ablation-child"
        ordinary.mkdir()
        ordinary_acl = self._icacls(ordinary).stdout
        real_mkdtemp = __import__("tempfile").mkdtemp
        try:
            with patch(
                "plugins.local_application.research_package_service.tempfile.mkdtemp",
                side_effect=self._restrict_export_temp(real_mkdtemp),
            ), patch(
                "plugins.local_application.research_package_service._normalize_windows_export_acl",
                return_value=None,
            ):
                facade.export_research_package(case["package_id"], output)
        finally:
            facade.close()

        ablated_acl = self._icacls(output).stdout
        self.assertNotEqual(
            self._acl_entries(output, ablated_acl),
            self._acl_entries(ordinary, ordinary_acl),
        )
        self.assertEqual(verify_export_root(output)["status"], "VERIFIED")
        print(json.dumps({
            "ISSUE133_ABLATION": {
                "ordinary_acl": ordinary_acl,
                "final_acl": ablated_acl,
            }
        }, sort_keys=True))


if __name__ == "__main__":
    import unittest
    unittest.main()
