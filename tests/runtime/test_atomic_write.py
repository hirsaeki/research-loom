"""Behavior of the shared atomic-write helpers (plugins/_infra/atomic_write.py, #488)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins._infra.atomic_write import (
    durable_staged_file,
    publish_staged,
    replace_text,
    write_durable,
)

CI_WINDOWS = True  # hard-link publication and replace semantics differ on NTFS


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_replace_text_replaces_and_leaves_no_temporary(self):
        path = self.root / "a.json"
        path.write_text("old", encoding="utf-8")
        replace_text(path, "new\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["a.json"])

    def test_replace_text_removes_temporary_on_failure(self):
        path = self.root / "a.json"
        path.write_text("old", encoding="utf-8")
        with patch("plugins._infra.atomic_write.os.replace", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                replace_text(path, "new")
        self.assertEqual(path.read_text(encoding="utf-8"), "old")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["a.json"])

    def test_durable_staged_file_holds_bytes_and_is_removed(self):
        with durable_staged_file(self.root, b"payload", prefix=".x-", suffix=".tmp") as staged:
            self.assertEqual(staged.parent, self.root)
            self.assertTrue(staged.name.startswith(".x-") and staged.name.endswith(".tmp"))
            self.assertEqual(staged.read_bytes(), b"payload")
        self.assertFalse(staged.exists())

    def test_durable_staged_file_is_removed_when_body_raises(self):
        with self.assertRaises(RuntimeError):
            with durable_staged_file(self.root, b"payload", prefix=".x-") as staged:
                raise RuntimeError("boom")
        self.assertFalse(staged.exists())

    def test_publish_without_replace_never_clobbers(self):
        target = self.root / "t"
        self.assertTrue(write_durable(target, b"first", prefix=".s-", replace=False))
        self.assertFalse(write_durable(target, b"second", prefix=".s-", replace=False))
        self.assertEqual(target.read_bytes(), b"first")
        self.assertEqual(os.listdir(self.root), ["t"])

    def test_publish_with_replace_overwrites(self):
        target = self.root / "t"
        target.write_bytes(b"first")
        self.assertTrue(write_durable(target, b"second", prefix=".s-", replace=True))
        self.assertEqual(target.read_bytes(), b"second")
        self.assertEqual(os.listdir(self.root), ["t"])

    def test_publish_staged_across_directories(self):
        staging, blobs = self.root / "staging", self.root / "blobs"
        staging.mkdir()
        blobs.mkdir()
        with durable_staged_file(staging, b"blob", prefix="blob-") as staged:
            self.assertTrue(publish_staged(staged, blobs / "b", replace=False))
        self.assertEqual((blobs / "b").read_bytes(), b"blob")
        self.assertEqual(os.listdir(staging), [])


if __name__ == "__main__":
    unittest.main()
