from __future__ import annotations

import os
from pathlib import Path
import tempfile
from threading import Barrier, Lock, Thread
import unittest
from unittest.mock import patch

from core.execution import RunLifecycleEvent, RunStatus
from plugins.local_execution_store import (
    LocalExecutionStore,
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
)
from test_local_execution_store import trace_run


class LocalExecutionStoreConcurrencySecurityTests(unittest.TestCase):
    def _seed_run(
        self,
        root: Path,
        config: LocalExecutionStoreConfig,
        run_id: str,
    ):
        store = LocalExecutionStore(root, config=config)
        run = trace_run(run_id)
        store.create_run(run)
        store.append_run_event(
            RunLifecycleEvent(
                run.run_id,
                1,
                None,
                RunStatus.PREPARED,
                "2026-08-26T00:00:00Z",
                "prepared",
            )
        )
        return store, run

    def test_run_output_quota_is_atomic_across_connections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "execution-store"
            config = LocalExecutionStoreConfig(
                max_artifact_bytes=4,
                max_run_output_bytes=6,
                max_resource_bytes=16,
            )
            seed, run = self._seed_run(root, config, "RUN-CONCURRENT")
            seed.close()
            first = LocalExecutionStore(root, config=config)
            second = LocalExecutionStore(root, config=config)
            barrier = Barrier(3)
            guard = Lock()
            outcomes: list[tuple[str, object]] = []

            def worker(store, artifact_id: str, content: bytes) -> None:
                barrier.wait()
                try:
                    value = store.put_bytes(
                        run,
                        role="log",
                        media_type="application/octet-stream",
                        content=content,
                        artifact_id=artifact_id,
                    )
                    outcome = ("ok", value)
                except Exception as exc:  # captured for exact post-join assertion
                    outcome = ("error", exc)
                with guard:
                    outcomes.append(outcome)

            threads = (
                Thread(target=worker, args=(first, "ART-C1", b"aaaa")),
                Thread(target=worker, args=(second, "ART-C2", b"bbbb")),
            )
            try:
                for thread in threads:
                    thread.start()
                barrier.wait()
                for thread in threads:
                    thread.join(timeout=10)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                successes = [value for kind, value in outcomes if kind == "ok"]
                failures = [value for kind, value in outcomes if kind == "error"]
                self.assertEqual(len(successes), 1)
                self.assertEqual(len(failures), 1)
                self.assertIsInstance(failures[0], LocalExecutionStoreError)
                self.assertEqual(
                    sum(item.size for item in first.artifacts_for(run.run_id)),
                    4,
                )
            finally:
                first.close()
                second.close()

    @unittest.skipIf(os.name == "nt", "symlink-parent regression is POSIX-specific")
    def test_file_intake_accepts_allowed_root_through_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            physical_parent = root / "physical"
            physical_parent.mkdir()
            physical_intake = physical_parent / "intake"
            physical_intake.mkdir()
            source = physical_intake / "input.bin"
            source.write_bytes(b"through-parent-link")
            linked_parent = root / "linked"
            linked_parent.symlink_to(physical_parent, target_is_directory=True)
            linked_source = linked_parent / "intake" / source.name
            store = LocalExecutionStore(
                root / "execution-store",
                allowed_import_roots=(linked_parent / "intake",),
            )
            try:
                resource = store.register_input_file("REF-LINKED-PARENT", linked_source)
                loaded = store.load(
                    {
                        "reference_id": resource.reference_id,
                        "locator": resource.storage_locator,
                        "digest": resource.digest,
                    }
                )
                self.assertEqual(loaded.content, b"through-parent-link")
            finally:
                store.close()

    @unittest.skipUnless(
        os.name != "nt"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd,
        "descriptor-anchored O_NOFOLLOW traversal is POSIX-specific",
    )
    def test_file_intake_rejects_symlink_swap_at_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = root / "intake"
            intake.mkdir()
            source = intake / "race.bin"
            source.write_bytes(b"safe")
            outside = root / "outside.bin"
            outside.write_bytes(b"outside")
            store = LocalExecutionStore(
                root / "execution-store",
                allowed_import_roots=(intake,),
            )
            real_open = os.open
            real_supports_dir_fd = set(os.supports_dir_fd)
            swapped = False

            def racing_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if (
                    path == source.name
                    and kwargs.get("dir_fd") is not None
                    and not swapped
                ):
                    swapped = True
                    source.unlink()
                    source.symlink_to(outside)
                return real_open(path, flags, *args, **kwargs)

            try:
                with patch(
                    "plugins.local_execution_store.store.os.open",
                    side_effect=racing_open,
                ) as mocked_open:
                    with patch.object(
                        os,
                        "supports_dir_fd",
                        real_supports_dir_fd | {mocked_open},
                    ):
                        with self.assertRaises(PermissionError):
                            store.register_input_file("REF-RACE", source)
                self.assertTrue(swapped)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
