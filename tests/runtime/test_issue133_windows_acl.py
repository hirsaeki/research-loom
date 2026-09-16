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
    def _acl_access(path: Path) -> list[dict[str, object]]:
        script = (
            "$ErrorActionPreference='Stop'; "
            "$acl=Get-Acl -LiteralPath $args[0]; "
            "@($acl.Access | ForEach-Object { [pscustomobject]@{"
            "identity=$_.IdentityReference.Value; "
            "rights=[int64]$_.FileSystemRights; "
            "access_type=$_.AccessControlType.ToString(); "
            "inheritance_flags=$_.InheritanceFlags.ToString(); "
            "propagation_flags=$_.PropagationFlags.ToString(); "
            "is_inherited=[bool]$_.IsInherited"
            "} }) | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = completed.stdout.strip()
        if not payload:
            return []
        decoded = json.loads(payload)
        return [decoded] if isinstance(decoded, dict) else decoded

    @staticmethod
    def _acl_signature(entry: dict[str, object]) -> tuple[object, ...]:
        return (
            entry["identity"],
            entry["rights"],
            entry["access_type"],
            entry["inheritance_flags"],
            entry["propagation_flags"],
        )

    def _expected_child_acl_signatures(self) -> list[tuple[object, ...]]:
        return sorted(
            self._acl_signature(entry)
            for entry in self._acl_access(self.root)
            if entry["inheritance_flags"] != "None"
        )

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
        parent_acl = self._icacls(self.root).stdout
        expected_signatures = self._expected_child_acl_signatures()
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
        final_access = self._acl_access(output)
        self.assertTrue(final_access)
        self.assertTrue(all(entry["is_inherited"] for entry in final_access))
        self.assertEqual(
            sorted(self._acl_signature(entry) for entry in final_access),
            expected_signatures,
        )
        self._assert_fresh_process_reads_package(output)
        verified = verify_export_root(output)
        self.assertEqual(verified["status"], "VERIFIED")
        self.assertEqual(verified["package_digest"], exported["package_digest"])
        print(json.dumps({
            "ISSUE133_ACL1_ACL2": {
                "parent_acl": parent_acl,
                "final_acl": final_acl,
                "final_access": final_access,
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

    def test_acl3_replace_race_does_not_delete_competing_output(self):
        facade, case = self._build()
        output = self.root / "issue133-replace-race"
        marker = output / "foreign.txt"

        def competing_replace(_src, dst):
            Path(dst).mkdir()
            marker.write_text("foreign-output", encoding="utf-8")
            raise OSError("fixture replace collision")

        try:
            with patch(
                "plugins.local_application.research_package_service.os.replace",
                side_effect=competing_replace,
            ):
                with self.assertRaises(LocalApplicationError) as error:
                    facade.export_research_package(case["package_id"], output)
            self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-WRITE-001")
            self.assertEqual(marker.read_text(encoding="utf-8"), "foreign-output")
        finally:
            facade.close()

    def test_ablation_old_rename_behavior_retains_restrictive_staging_acl(self):
        facade, case = self._build()
        output = self.root / "issue133-ablation"
        parent_acl = self._icacls(self.root).stdout
        expected_signatures = self._expected_child_acl_signatures()
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
        ablated_access = self._acl_access(output)
        self.assertNotEqual(
            sorted(self._acl_signature(entry) for entry in ablated_access),
            expected_signatures,
        )
        self.assertEqual(verify_export_root(output)["status"], "VERIFIED")
        print(json.dumps({
            "ISSUE133_ABLATION": {
                "parent_acl": parent_acl,
                "final_acl": ablated_acl,
                "final_access": ablated_access,
            }
        }, sort_keys=True))


if __name__ == "__main__":
    import unittest
    unittest.main()
