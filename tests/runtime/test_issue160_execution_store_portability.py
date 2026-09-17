from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from core.execution import CapabilityRunRecord, RunLifecycleEvent, RunStatus
from plugins.local_execution_store import (
    LocalExecutionStore,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
    external_capture_artifact_metadata_for_project,
    open_read_only_execution_store,
)


_ORIGINAL = "desktop_research.original_capture"
_RENDITION = "desktop_research.text_rendition"


def _run() -> CapabilityRunRecord:
    return CapabilityRunRecord(
        "RUN-PORTABLE",
        "INV-PORTABLE",
        "sha256:" + "1" * 64,
        "desktop-research",
        "0.1.0",
        "sha256:" + "2" * 64,
        "plugin.desktop-research.external",
        "0.1.0",
        "investigate",
        "real",
        "CTX-PORTABLE",
        "sha256:" + "3" * 64,
        "PRJ-1",
        "LIN-1",
        "SNP-1",
        "sha256:" + "4" * 64,
        1,
        None,
        RunStatus.PREPARED,
        "2026-09-18T00:00:00Z",
        None,
        None,
        None,
        None,
        None,
        {"trace_id": "TRACE-PORTABLE"},
    )


class PortableExecutionMaterialStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "workspace-a" / ".research-loom" / "execution"
        self.store = LocalExecutionStore(self.source)
        run = _run()
        self.store.create_run(run)
        self.store.append_run_event(
            RunLifecycleEvent(
                run.run_id,
                1,
                None,
                RunStatus.PREPARED,
                run.prepared_at,
                "prepared",
            )
        )
        provenance = {
            "capture_id": "CAP-PORTABLE",
            "acquisition_locator": "https://example.test/source",
            "original_intake_path": r"C:\old-workspace\intake\source.html",
        }
        self.original = self.store.put_bytes(
            run,
            role=_ORIGINAL,
            media_type="text/html",
            content=b"<html>portable source</html>",
            artifact_id="ART-PORTABLE-ORIGINAL",
            provenance=provenance,
        )
        self.rendition = self.store.put_bytes(
            run,
            role=_RENDITION,
            media_type="text/plain",
            content=b"portable source\n",
            artifact_id="ART-PORTABLE-TEXT",
            provenance=provenance,
            parent_artifact_refs=(self.original.artifact_id,),
        )
        self.store.close()
        self.store = None

    def tearDown(self) -> None:
        if self.store is not None:
            self.store.close()
        self.tempdir.cleanup()

    def _copy_without_staging(self, target: Path) -> None:
        shutil.copytree(
            self.source,
            target,
            ignore=shutil.ignore_patterns("staging"),
        )

    def test_whole_child_move_reopens_read_only_and_resolves_verified_material(
        self,
    ):
        moved = self.root / "different-host-path" / "execution-material"
        self._copy_without_staging(moved)

        with open_read_only_execution_store(moved) as reopened:
            self.assertFalse((moved / "staging").exists())
            self.assertEqual(reopened.load_run("RUN-PORTABLE"), _run())
            payload = reopened.load_artifact_verified_once(self.original.artifact_id)
            self.assertEqual(payload.content, b"<html>portable source</html>")
            artifacts, cursor = external_capture_artifact_metadata_for_project(
                reopened,
                "PRJ-1",
                limit=10,
            )
            self.assertIsNone(cursor)
            by_id = {item.artifact_id: item for item in artifacts}
            self.assertEqual(
                set(by_id),
                {self.original.artifact_id, self.rendition.artifact_id},
            )
            self.assertEqual(
                by_id[self.original.artifact_id].storage_locator,
                self.original.storage_locator,
            )
            self.assertEqual(
                by_id[self.original.artifact_id].provenance["original_intake_path"],
                r"C:\old-workspace\intake\source.html",
            )
            before = sorted(
                path.relative_to(moved)
                for path in moved.rglob("*")
                if path.is_file()
            )
            with self.assertRaises(LocalExecutionStoreError):
                reopened.put_bytes(
                    _run(),
                    role="should-not-write",
                    media_type="text/plain",
                    content=b"blocked",
                )
            after = sorted(
                path.relative_to(moved)
                for path in moved.rglob("*")
                if path.is_file()
            )
            self.assertEqual(before, after)

    def test_db_only_copy_is_degraded_but_complete_restore_verifies(self):
        db_only = self.root / "db-only"
        db_only.mkdir()
        shutil.copy2(self.source / "execution.db", db_only / "execution.db")
        with open_read_only_execution_store(db_only) as incomplete:
            diagnosis = incomplete.diagnose_artifact_content(
                self.original.artifact_id
            )
            self.assertEqual(diagnosis["status"], "content_missing")
            with self.assertRaises(FileNotFoundError):
                incomplete.load_artifact_verified_once(self.original.artifact_id)

        restored = self.root / "restored" / "execution"
        self._copy_without_staging(restored)
        with open_read_only_execution_store(restored) as complete:
            diagnosis = complete.diagnose_artifact_content(
                self.original.artifact_id
            )
            self.assertEqual(diagnosis["status"], "verified")
            self.assertEqual(
                complete.load_artifact_verified_once(self.original.artifact_id).digest,
                self.original.digest,
            )

    def test_corrupt_backing_content_is_reported_and_rejected(self):
        corrupt = self.root / "corrupt" / "execution"
        self._copy_without_staging(corrupt)
        digest_hex = self.original.digest.removeprefix("sha256:")
        blob = corrupt / "blobs" / "sha256" / digest_hex[:2] / digest_hex
        blob.write_bytes(b"corrupt")

        with open_read_only_execution_store(corrupt) as reopened:
            diagnosis = reopened.diagnose_artifact_content(
                self.original.artifact_id
            )
            self.assertIn(
                diagnosis["status"],
                {"digest_mismatch", "size_mismatch", "digest_and_size_mismatch"},
            )
            with self.assertRaises(LocalExecutionStoreIntegrityError):
                reopened.load_artifact_verified_once(self.original.artifact_id)

    def test_quiesced_backup_restores_after_working_copy_is_removed(self):
        backup = self.root / "backup" / "execution"
        self._copy_without_staging(backup)
        shutil.rmtree(self.source)
        restored = self.root / "workspace-a" / ".research-loom" / "execution"
        shutil.copytree(backup, restored)

        with open_read_only_execution_store(restored) as reopened:
            self.assertEqual(
                reopened.load_artifact_verified_once(self.rendition.artifact_id).content,
                b"portable source\n",
            )
            expected = "sha256:" + hashlib.sha256(b"portable source\n").hexdigest()
            self.assertEqual(self.rendition.digest, expected)


if __name__ == "__main__":
    unittest.main()
