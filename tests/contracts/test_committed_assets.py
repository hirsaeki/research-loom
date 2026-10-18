"""Committed binaries and large files stay deliberate and verified (#503).

A tracked file over ``MAX_FILE_BYTES`` must be listed in ``ALLOWED_LARGE`` with
the reason it lives in the repository. Git LFS is not used: an offline checkout
or wheelhouse must not depend on an LFS server. See CONTRIBUTING.md.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MAX_FILE_BYTES = 256 * 1024
ALLOWED_LARGE = {
    # Record: the only copy of the #465/#467 v5 detached inputs, pinned by run-manifest.json.
    "docs/acceptance/writer-reader-quality/detached-inputs.zip": "acceptance record",
    # Generated: resolver output consumed by init; scripts/regenerate_project_eps.py --check.
    "projects/misco-ai-2026/effective-profile-set.json": "generated, verified byte-exact",
}
ACCEPTANCE = ROOT / "docs/acceptance/writer-reader-quality"
ARCHIVE = ACCEPTANCE / "detached-inputs.zip"
RUN_MANIFEST = ACCEPTANCE / "run-manifest.json"
# Directories that are never tracked; used only when git is unavailable.
UNTRACKED_DIRS = {".git", ".venv", ".mypy_cache", ".ruff_cache", "__pycache__", "dist"}


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_file() and not UNTRACKED_DIRS.intersection(path.relative_to(ROOT).parts)
        ]
    return [name for name in out.decode("utf-8").split("\0") if name]


def oversized(files: list[str], allowed: dict[str, str]) -> list[str]:
    return [
        name
        for name in files
        if name not in allowed
        and (ROOT / name).is_file()
        and (ROOT / name).stat().st_size > MAX_FILE_BYTES
    ]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CommittedAssetTests(unittest.TestCase):
    def test_large_files_are_explicitly_allowed(self):
        self.assertEqual(
            [],
            oversized(tracked_files(), ALLOWED_LARGE),
            f"keep files under {MAX_FILE_BYTES} bytes or add them to ALLOWED_LARGE with a reason",
        )

    def test_allowed_large_entries_are_still_needed(self):
        for name in ALLOWED_LARGE:
            with self.subTest(path=name):
                path = ROOT / name
                self.assertTrue(path.is_file(), "remove the stale ALLOWED_LARGE entry")
                self.assertGreater(path.stat().st_size, MAX_FILE_BYTES, "no longer large")

    def test_guard_flags_an_unlisted_large_file(self):
        name = "docs/acceptance/writer-reader-quality/detached-inputs.zip"
        self.assertEqual([name], oversized([name], {}))

    def test_detached_inputs_archive_matches_the_run_manifest(self):
        manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
        record = manifest["detached_inputs_archive"]
        self.assertEqual(ARCHIVE.relative_to(ROOT).as_posix(), record["path"])
        self.assertEqual(record["sha256"], _sha256(ARCHIVE.read_bytes()))

    def test_detached_inputs_archive_holds_only_the_public_inputs(self):
        manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
        with zipfile.ZipFile(ARCHIVE) as archive:
            names = archive.namelist()
            for name in names:
                with self.subTest(entry=name):
                    parts = PurePosixPath(name).parts
                    self.assertEqual("inputs", parts[0])
                    self.assertNotIn("..", parts)
                    self.assertFalse(name.startswith("/"))
            for case in manifest["cases"]:
                writer_input = case["writer_input"]
                relative = writer_input["path"].replace("\\", "/").split("/inputs/", 1)[1]
                with self.subTest(case=relative):
                    data = archive.read("inputs/" + relative)
                    self.assertEqual(writer_input["file_sha256"], _sha256(data))


if __name__ == "__main__":
    unittest.main()
