from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.execution import CapabilityRunRecord, RunStatus
from plugins.local_execution_store import (
    LocalExecutionStore,
    LocalExecutionStoreError,
    LocalOperationalTraceStore,
)


def running_run(run_id: str = "RUN-BATCH-CLEANUP") -> CapabilityRunRecord:
    return CapabilityRunRecord(
        run_id=run_id,
        invocation_id=f"INV-{run_id}",
        invocation_digest="sha256:" + "1" * 64,
        capability_id="desktop-research",
        capability_version="0.1.0",
        descriptor_digest="sha256:" + "2" * 64,
        implementation_id="plugin.desktop-research.external",
        implementation_version="0.1.0",
        function_id="investigate",
        execution_mode="real",
        context_pack_id=f"CTX-{run_id}",
        context_pack_digest="sha256:" + "3" * 64,
        project_ref="PRJ-BATCH-CLEANUP",
        lineage_ref="LIN-BATCH-CLEANUP",
        snapshot_ref="SNP-BATCH-CLEANUP",
        snapshot_digest="sha256:" + "4" * 64,
        attempt=1,
        parent_run_id=None,
        status=RunStatus.RUNNING,
        prepared_at="2026-08-31T00:00:00Z",
        started_at="2026-08-31T00:00:00Z",
    )


def batch(content_a: bytes, content_b: bytes):
    return (
        {
            "role": "desktop_research.original_capture",
            "media_type": "application/octet-stream",
            "content": content_a,
            "artifact_id": "ART-BATCH-A",
        },
        {
            "role": "desktop_research.text_rendition",
            "media_type": "text/plain",
            "content": content_b,
            "artifact_id": "ART-BATCH-B",
            "parent_artifact_refs": ("ART-BATCH-A",),
        },
    )


class NonAtomicRunStore:
    def load_run(self, _run_id: str):
        return running_run("RUN-NON-ATOMIC")


class LocalExecutionAtomicBatchCleanupTests(unittest.TestCase):
    def test_second_blob_failure_removes_new_unreferenced_blob(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LocalExecutionStore(Path(temp) / "execution")
            try:
                run = running_run()
                store.create_run(run)
                real_store_blob = store._store_blob
                calls = 0

                def fail_second(content: bytes, *, scheme: str):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise LocalExecutionStoreError("injected second blob failure")
                    return real_store_blob(content, scheme=scheme)

                with patch.object(store, "_store_blob", side_effect=fail_second):
                    with self.assertRaises(LocalExecutionStoreError):
                        store.put_bytes_batch(
                            run,
                            batch(b"new original bytes", b"new text bytes"),
                            expected_status=RunStatus.RUNNING,
                        )

                self.assertEqual(store.artifacts_for(run.run_id), ())
                blob_files = [path for path in store.blob_root.rglob("*") if path.is_file()]
                self.assertEqual(blob_files, [])
            finally:
                store.close()

    def test_identity_collision_is_rejected_before_creating_new_blobs(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LocalExecutionStore(Path(temp) / "execution")
            try:
                run = running_run("RUN-BATCH-COLLISION")
                store.create_run(run)
                store.put_bytes_batch(
                    run,
                    batch(b"original one", b"text one"),
                    expected_status=RunStatus.RUNNING,
                )
                before = {
                    path.relative_to(store.blob_root)
                    for path in store.blob_root.rglob("*")
                    if path.is_file()
                }

                with self.assertRaises(ValueError):
                    store.put_bytes_batch(
                        run,
                        batch(b"different original", b"different text"),
                        expected_status=RunStatus.RUNNING,
                    )

                after = {
                    path.relative_to(store.blob_root)
                    for path in store.blob_root.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)
                self.assertEqual(len(store.artifacts_for(run.run_id)), 2)
            finally:
                store.close()

    def test_conditioned_operational_append_fails_closed_without_atomic_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LocalOperationalTraceStore(
                Path(temp) / "operational",
                NonAtomicRunStore(),
            )
            try:
                with self.assertRaisesRegex(
                    TypeError,
                    "requires an atomic require_run_status guard",
                ):
                    store.append_if_run_status(
                        "RUN-NON-ATOMIC",
                        RunStatus.RUNNING,
                        "desktop_research.retrieval_attempt_started",
                        "2026-08-31T00:00:00Z",
                        {"attempt_id": "ATT-NON-ATOMIC"},
                    )
                self.assertEqual(store.events_for("RUN-NON-ATOMIC"), ())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
