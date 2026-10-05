from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts.runtime_wheelhouse import WheelhouseError, create_manifest, verify_bundle


class RuntimeWheelhouseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.repo = self.root / "repo"
        self.bundle = self.root / "bundle"
        (self.bundle / "wheels").mkdir(parents=True)
        self.repo.mkdir()
        (self.repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        (self.repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (self.bundle / "requirements.txt").write_text(
            "demo==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8"
        )
        (self.bundle / "wheels" / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_manifest_verifies_exact_repository_inputs_and_wheels(self) -> None:
        manifest = create_manifest(self.repo, self.bundle)
        verified = verify_bundle(self.repo, self.bundle, check_host=False)
        self.assertEqual(verified, manifest)
        self.assertEqual(verified["target"]["python"], "3.12")
        self.assertEqual(len(verified["wheels"]), 1)

    def test_tampered_wheel_fails_closed(self) -> None:
        create_manifest(self.repo, self.bundle)
        (self.bundle / "wheels" / "demo-1.0-py3-none-any.whl").write_bytes(b"changed")
        with self.assertRaisesRegex(WheelhouseError, "byte length mismatch|digest mismatch"):
            verify_bundle(self.repo, self.bundle, check_host=False)

    def test_repository_head_mismatch_fails_closed(self) -> None:
        create_manifest(self.repo, self.bundle)
        (self.repo / "new.txt").write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "new.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "next"], check=True)
        with self.assertRaisesRegex(WheelhouseError, "repository HEAD mismatch"):
            verify_bundle(self.repo, self.bundle, check_host=False)

    def test_repository_lock_tamper_fails_closed(self) -> None:
        create_manifest(self.repo, self.bundle)
        (self.repo / "uv.lock").write_text("version = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(WheelhouseError, "repository input uv.lock"):
            verify_bundle(self.repo, self.bundle, check_host=False)

    def test_unrecorded_extra_wheel_fails_closed(self) -> None:
        create_manifest(self.repo, self.bundle)
        (self.bundle / "wheels" / "extra-1.0-py3-none-any.whl").write_bytes(b"extra")
        with self.assertRaisesRegex(WheelhouseError, "does not exactly match manifest"):
            verify_bundle(self.repo, self.bundle, check_host=False)

    def test_host_target_mismatch_is_not_silently_accepted(self) -> None:
        create_manifest(self.repo, self.bundle)
        with mock.patch("scripts.runtime_wheelhouse.sys.platform", "win32"):
            with self.assertRaisesRegex(WheelhouseError, "requires Linux"):
                verify_bundle(self.repo, self.bundle, check_host=True)

    def test_manifest_schema_tamper_fails_closed(self) -> None:
        create_manifest(self.repo, self.bundle)
        path = self.bundle / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["schema_version"] = "other/v1"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(WheelhouseError, "unsupported wheelhouse schema"):
            verify_bundle(self.repo, self.bundle, check_host=False)


if __name__ == "__main__":
    unittest.main()
