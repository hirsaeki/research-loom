from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application.facade import LocalApplicationError
from plugins.local_application import material_content_facade as material_content
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.workspace import LocalWorkspace
from tests.runtime.test_external_material_inventory import _capture, _create_running, _write_inputs


class Issue91ReviewFixTests(unittest.TestCase):
    def _fixture(self, root: Path):
        config, profiles = _write_inputs(root)
        opened = LocalWorkspace.init(root / "workspace", config, profiles)
        run = _create_running(
            opened.application.execution_store,
            opened.project_id,
            "RUN-ISSUE91-REVIEW",
            "2026-09-06T00:00:00Z",
        )
        _capture(
            opened.application.execution_store,
            run,
            "CAP-ISSUE91-REVIEW",
            b"review original bytes",
            "https://example.test/issue91-review",
            acquired_at="2026-09-06T00:00:20Z",
        )
        facade = LocalApplicationFacade(opened.application, opened.project_id)
        return opened, facade, run

    def test_original_parent_provenance_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            opened, facade, run = self._fixture(Path(temp))
            try:
                store = opened.application.execution_store
                original = next(
                    item
                    for item in store.artifacts_for(run.run_id)
                    if item.role.endswith("original_capture")
                )
                provenance = dict(original.provenance)
                provenance["parent_artifact_refs"] = ["ART-forged-parent"]
                with store._lock:
                    store._connection.execute(
                        "UPDATE execution_artifacts SET provenance_json=? WHERE artifact_id=?",
                        (json.dumps(provenance), original.artifact_id),
                    )
                    store._connection.commit()
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.show_external_material(run.run_id, "CAP-ISSUE91-REVIEW")
                self.assertEqual(caught.exception.code, "APPLICATION-MATERIAL-INTEGRITY-001")
            finally:
                opened.close()

    def test_bounded_show_uses_stream_verified_prefix_not_full_artifact_load(self):
        with tempfile.TemporaryDirectory() as temp:
            opened, facade, run = self._fixture(Path(temp))
            try:
                store = opened.application.execution_store
                with patch.object(
                    store,
                    "load_artifact",
                    side_effect=AssertionError("bounded show must not full-load rendition"),
                ):
                    shown = facade.show_external_material(
                        run.run_id,
                        "CAP-ISSUE91-REVIEW",
                        max_text_bytes=4,
                    )
                self.assertTrue(shown["text_rendition_view"]["truncated"])
                self.assertLessEqual(shown["text_rendition_view"]["displayed_bytes"], 4)
                self.assertGreater(shown["text_rendition_view"]["total_bytes"], 4)
            finally:
                opened.close()



    def test_windows_open_osfhandle_failure_closes_full_width_handle_and_preserves_error(self):
        import ctypes
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock

        native_handle = 0x1234567887654321
        create_file = Mock(return_value=native_handle)
        close_handle = Mock(return_value=False)
        set_disposition = Mock(return_value=True)
        kernel32 = SimpleNamespace(
            CreateFileW=create_file,
            CloseHandle=close_handle,
            SetFileInformationByHandle=set_disposition,
        )
        open_error = RuntimeError("open_osfhandle failed")
        fake_msvcrt = SimpleNamespace(open_osfhandle=Mock(side_effect=open_error))

        with (
            patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
            patch.object(ctypes, "WinDLL", return_value=kernel32, create=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "open_osfhandle failed"):
                material_content._windows_open_export_handle(Path("C:/issue91/export.bin"))

        set_disposition.assert_called_once()
        self.assertEqual(set_disposition.call_args.args[0], native_handle)
        close_handle.assert_called_once_with(native_handle)
        self.assertEqual(close_handle.argtypes, [ctypes.wintypes.HANDLE])
        self.assertIs(close_handle.restype, ctypes.wintypes.BOOL)

    def test_windows_final_path_failure_keeps_created_handle_delete_pending(self):
        root = Path("C:/issue91")
        target = material_content._ExportTarget(
            path=root / "export.bin",
            parent=root,
            parent_dev=1,
            parent_ino=2,
            managed_root=root / ".research-loom",
        )
        with (
            patch.object(material_content.os, "name", "nt"),
            patch.object(
                material_content,
                "_windows_open_export_handle",
                return_value=101,
            ) as open_export,
            patch.object(
                material_content.os,
                "open",
                side_effect=AssertionError("Windows export must use CreateFileW helper"),
            ),
            patch.object(material_content.os, "close") as close_fd,
            patch.object(
                material_content,
                "_windows_set_delete_disposition",
            ) as disposition,
            patch.object(material_content.Path, "unlink") as path_unlink,
            patch.object(
                material_content,
                "_windows_final_path",
                side_effect=OSError("final path unavailable"),
            ),
        ):
            with self.assertRaises(OSError):
                material_content._write_exclusive_bytes(target, b"payload")

        open_export.assert_called_once_with(target.path)
        disposition.assert_not_called()
        close_fd.assert_called_once_with(101)
        path_unlink.assert_not_called()


    def test_windows_post_validation_failure_never_path_unlinks_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "export.bin"
            stat_result = root.stat()
            target = material_content._ExportTarget(
                path=output,
                parent=root,
                parent_dev=stat_result.st_dev,
                parent_ino=stat_result.st_ino,
                managed_root=root / ".research-loom",
            )

            def close_and_replace(fd):
                output.write_bytes(b"other-process")

            with (
                patch.object(material_content.os, "name", "nt"),
                patch.object(
                    material_content,
                    "_windows_open_export_handle",
                    return_value=202,
                ),
                patch.object(
                    material_content,
                    "_windows_final_path",
                    return_value=output,
                ),
                patch.object(
                    material_content,
                    "_is_within",
                    return_value=True,
                ),
                patch.object(material_content.os, "close", side_effect=close_and_replace),
                patch.object(material_content.Path, "unlink") as path_unlink,
            ):
                with self.assertRaises(LocalApplicationError):
                    material_content._write_exclusive_bytes(target, b"payload")

            self.assertEqual(output.read_bytes(), b"other-process")
            path_unlink.assert_not_called()

    def test_export_writes_the_same_bytes_that_were_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            opened, facade, run = self._fixture(root)
            try:
                store = opened.application.execution_store
                original = next(
                    item
                    for item in store.artifacts_for(run.run_id)
                    if item.role.endswith("original_capture")
                )
                blob = store._locator_path(original.storage_locator, original.digest)
                verified_bytes = blob.read_bytes()
                original_guard = store._verify_blob_path

                def mutate_after_verification(
                    path: Path,
                    expected_digest: str,
                    expected_size: int,
                    *,
                    content: bytes | None = None,
                ) -> None:
                    original_guard(
                        path,
                        expected_digest,
                        expected_size,
                        content=content,
                    )
                    blob.write_bytes(bytes([verified_bytes[0] ^ 1]) + verified_bytes[1:])

                output = root / "export.bin"
                with patch.object(
                    store,
                    "_verify_blob_path",
                    side_effect=mutate_after_verification,
                ):
                    facade.export_external_material(
                        run.run_id,
                        "CAP-ISSUE91-REVIEW",
                        kind="original",
                        output_file=output,
                    )
                self.assertEqual(output.read_bytes(), verified_bytes)
                self.assertNotEqual(blob.read_bytes(), verified_bytes)
            finally:
                opened.close()


if __name__ == "__main__":
    unittest.main()
