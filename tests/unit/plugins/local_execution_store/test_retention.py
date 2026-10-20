"""Characterization tests for ``plugins/local_execution_store/retention.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They pin the current behaviour of the managed capture-pair path: locator
parsing for large originals, controlled file intake, staging, installation,
pair preflight guards, and streaming integrity verification.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core.execution import RunStatus
from plugins.local_execution_store.retention import LocalExecutionStore
from plugins.local_execution_store.store_model import (
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
)
from tests.runtime.test_local_execution_store import trace_run

ORIGINAL_ROLE = "desktop_research.original_capture"
TEXT_ROLE = "desktop_research.text_rendition"


def sha(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


class RetentionStoreCase(unittest.TestCase):
    max_artifact_bytes = 8

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.store = LocalExecutionStore(
            self.root / "store",
            config=LocalExecutionStoreConfig(
                max_artifact_bytes=self.max_artifact_bytes,
                max_run_output_bytes=64,
            ),
            allowed_import_roots=(self.intake,),
        )
        self.addCleanup(self.store.close)

    def write_intake(self, name: str, content: bytes) -> Path:
        path = self.intake / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def staging_entries(self) -> list[str]:
        return sorted(item.name for item in self.store.staging_root.iterdir())


class LocatorPathTests(RetentionStoreCase):
    def test_large_original_locator_maps_into_large_original_root(self) -> None:
        digest_hex = "ab" + "0" * 62
        path = self.store._locator_path(
            f"external-original://sha256/{digest_hex}", f"sha256:{digest_hex}"
        )
        self.assertEqual(
            path,
            self.store.root / "large-originals" / "sha256" / "ab" / digest_hex,
        )

    def test_large_original_locator_rejects_bad_digest_shapes(self) -> None:
        good = "a" * 64
        cases = (
            ("a" * 63, "sha256:" + "a" * 63),
            ("A" * 64, "sha256:" + "A" * 64),
            (good, "sha256:" + "b" * 64),
        )
        for digest_hex, expected in cases:
            with self.subTest(digest_hex=digest_hex, expected=expected):
                with self.assertRaisesRegex(
                    LocalExecutionStoreIntegrityError,
                    "large original storage locator disagrees with metadata",
                ):
                    self.store._locator_path(f"external-original://sha256/{digest_hex}", expected)

    def test_other_locators_are_delegated_to_the_base_store(self) -> None:
        digest_hex = "c" * 64
        self.assertEqual(
            self.store._locator_path(f"artifact://sha256/{digest_hex}", f"sha256:{digest_hex}"),
            self.store.blob_root / "cc" / digest_hex,
        )
        with self.assertRaisesRegex(
            LocalExecutionStoreIntegrityError, "unsupported or non-local storage locator"
        ):
            self.store._locator_path("https://example.test/x", "sha256:" + "c" * 64)


class ControlledFileFdTests(RetentionStoreCase):
    def open(self, path, *, max_bytes: int = 1024):
        with self.store._controlled_file_fd(path, max_bytes=max_bytes) as (fd, size):
            return os.read(fd, 1024), size

    def test_regular_file_inside_root_is_opened(self) -> None:
        path = self.write_intake("nested/source.html", b"hello")
        self.assertEqual(self.open(path), (b"hello", 5))

    def test_file_at_exact_size_limit_is_accepted(self) -> None:
        path = self.write_intake("limit.bin", b"12345")
        self.assertEqual(self.open(path, max_bytes=5), (b"12345", 5))

    def test_negative_max_bytes_is_rejected(self) -> None:
        path = self.write_intake("a.txt", b"a")
        with self.assertRaisesRegex(ValueError, "max_bytes must be non-negative"):
            self.open(path, max_bytes=-1)

    def test_intake_is_disabled_without_allowed_roots(self) -> None:
        path = self.write_intake("a.txt", b"a")
        self.store._allowed_import_roots = ()
        with self.assertRaisesRegex(PermissionError, "file import is disabled"):
            self.open(path)

    def test_parent_traversal_is_rejected(self) -> None:
        self.write_intake("a.txt", b"a")
        with self.assertRaisesRegex(PermissionError, "path traversal is not allowed"):
            self.open(self.intake / "sub" / ".." / "a.txt")

    def test_file_outside_roots_is_rejected(self) -> None:
        path = self.outside / "x.txt"
        path.write_bytes(b"x")
        with self.assertRaisesRegex(PermissionError, "outside configured artifact/resource"):
            self.open(path)

    def test_symlinked_parent_is_anchored_to_its_real_location(self) -> None:
        self.write_intake("real/data.txt", b"data")
        alias = self.outside / "alias"
        alias.symlink_to(self.intake / "real", target_is_directory=True)
        self.assertEqual(self.open(alias / "data.txt"), (b"data", 4))

    def test_symlink_component_inside_root_is_rejected(self) -> None:
        target = self.write_intake("target.txt", b"t")
        (self.intake / "link.txt").symlink_to(target)
        with self.assertRaisesRegex(PermissionError, "symlink/reparse-point intake is forbidden"):
            self.open(self.intake / "link.txt")

    def test_directory_is_not_a_regular_file(self) -> None:
        (self.intake / "folder").mkdir()
        with self.assertRaisesRegex(PermissionError, "only regular files may be imported"):
            self.open(self.intake / "folder")

    def test_import_root_itself_is_not_a_regular_file(self) -> None:
        with self.assertRaisesRegex(PermissionError, "only regular files may be imported"):
            self.open(self.intake)

    def test_oversized_file_is_rejected(self) -> None:
        path = self.write_intake("big.bin", b"123456")
        with self.assertRaisesRegex(
            LocalExecutionStoreError, "file exceeds configured intake size limit"
        ):
            self.open(path, max_bytes=5)

    def test_symlink_swapped_in_after_component_check_is_reported_as_forbidden(self) -> None:
        target = self.write_intake("target.txt", b"t")
        (self.intake / "late-link.txt").symlink_to(target)
        with patch.object(LocalExecutionStore, "_reject_reparse_components"):
            with self.assertRaises(PermissionError):
                self.open(self.intake / "late-link.txt")

    def test_missing_file_propagates_os_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.open(self.intake / "missing.txt")


class ControlledFileFdFallbackTests(RetentionStoreCase):
    """Path used when dir_fd-relative opening is unavailable."""

    def open(self, path, *, max_bytes: int = 1024):
        with patch.object(os, "supports_dir_fd", set()):
            with self.store._controlled_file_fd(path, max_bytes=max_bytes) as (fd, size):
                return os.read(fd, 1024), size

    def test_regular_file_is_opened(self) -> None:
        path = self.write_intake("source.txt", b"fallback")
        self.assertEqual(self.open(path), (b"fallback", 8))

    def test_directory_is_rejected_before_open(self) -> None:
        (self.intake / "folder").mkdir()
        with self.assertRaisesRegex(PermissionError, "only regular files may be imported"):
            self.open(self.intake / "folder")

    def test_oversized_file_is_rejected(self) -> None:
        path = self.write_intake("big.bin", b"123456")
        with self.assertRaisesRegex(
            LocalExecutionStoreError, "file exceeds configured intake size limit"
        ):
            self.open(path, max_bytes=5)

    def test_identity_change_between_checks_is_rejected(self) -> None:
        path = self.write_intake("swap.txt", b"one")
        other = self.write_intake("other.txt", b"two")
        real_lstat = Path.lstat
        calls = {"count": 0}

        def lstat(self_path: Path):
            if self_path == path:
                calls["count"] += 1
                if calls["count"] >= 3:
                    return real_lstat(other)
            return real_lstat(self_path)

        with patch.object(Path, "lstat", lstat):
            with self.assertRaisesRegex(PermissionError, "file changed during controlled intake"):
                self.open(path)


class StageAndInstallTests(RetentionStoreCase):
    def test_stage_streams_file_into_staging_with_digest(self) -> None:
        path = self.write_intake("source.bin", b"payload")
        staged, digest, size = self.store._stage_controlled_original(path, max_bytes=100)
        self.assertEqual(staged.parent, self.store.staging_root)
        self.assertTrue(staged.name.startswith("large-original-"))
        self.assertEqual(staged.read_bytes(), b"payload")
        self.assertEqual((digest, size), (sha(b"payload"), 7))

    def test_stage_failure_removes_temporary_file(self) -> None:
        path = self.write_intake("source.bin", b"payload")
        with self.assertRaises(LocalExecutionStoreError):
            self.store._stage_controlled_original(path, max_bytes=3)
        self.assertEqual(self.staging_entries(), [])

    def fake_fd(self, declared_size: int):
        @contextmanager
        def controlled(source_path, *, max_bytes):
            fd = os.open(source_path, os.O_RDONLY)
            try:
                yield fd, declared_size
            finally:
                os.close(fd)

        return controlled

    def test_stage_rejects_growth_beyond_limit_while_reading(self) -> None:
        path = self.write_intake("source.bin", b"0123456789")
        with patch.object(self.store, "_controlled_file_fd", self.fake_fd(4)):
            with self.assertRaisesRegex(
                LocalExecutionStoreError,
                "file exceeded configured intake size limit while reading",
            ):
                self.store._stage_controlled_original(path, max_bytes=4)
        self.assertEqual(self.staging_entries(), [])

    def test_stage_rejects_size_drift_from_declared_size(self) -> None:
        path = self.write_intake("source.bin", b"0123")
        with patch.object(self.store, "_controlled_file_fd", self.fake_fd(9)):
            with self.assertRaisesRegex(PermissionError, "file changed during controlled intake"):
                self.store._stage_controlled_original(path, max_bytes=100)
        self.assertEqual(self.staging_entries(), [])

    def test_verify_blob_streaming(self) -> None:
        blob = self.root / "blob"
        blob.write_bytes(b"abc")
        LocalExecutionStore._verify_blob_streaming(blob, sha(b"abc"), 3)
        for digest, size in ((sha(b"abd"), 3), (sha(b"abc"), 4)):
            with self.subTest(digest=digest, size=size):
                with self.assertRaisesRegex(
                    LocalExecutionStoreIntegrityError,
                    "content-addressed blob failed digest/size verification",
                ):
                    LocalExecutionStore._verify_blob_streaming(blob, digest, size)

    def staged(self, content: bytes) -> Path:
        path = self.store.staging_root / f"staged-{hashlib.sha256(content).hexdigest()[:8]}"
        path.write_bytes(content)
        return path

    def test_install_small_original_into_blob_root(self) -> None:
        content = b"small"
        digest_hex = hashlib.sha256(content).hexdigest()
        locator, target, created = self.store._install_staged_original(
            self.staged(content), digest=sha(content), size=len(content), large=False
        )
        self.assertEqual(locator, f"artifact://sha256/{digest_hex}")
        self.assertEqual(target, self.store.blob_root / digest_hex[:2] / digest_hex)
        self.assertTrue(created)
        self.assertEqual(target.read_bytes(), content)

        again = self.store._install_staged_original(
            self.staged(content), digest=sha(content), size=len(content), large=False
        )
        self.assertEqual(again, (locator, target, False))

    def test_install_large_original_into_large_original_root(self) -> None:
        content = b"large original bytes"
        digest_hex = hashlib.sha256(content).hexdigest()
        locator, target, created = self.store._install_staged_original(
            self.staged(content), digest=sha(content), size=len(content), large=True
        )
        self.assertEqual(locator, f"external-original://sha256/{digest_hex}")
        self.assertEqual(
            target,
            self.store.root / "large-originals" / "sha256" / digest_hex[:2] / digest_hex,
        )
        self.assertTrue(created)

    def test_install_verifies_corrupt_existing_target(self) -> None:
        content = b"small"
        digest_hex = hashlib.sha256(content).hexdigest()
        target = self.store.blob_root / digest_hex[:2] / digest_hex
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"other")
        with self.assertRaises(LocalExecutionStoreIntegrityError):
            self.store._install_staged_original(
                self.staged(content), digest=sha(content), size=len(content), large=False
            )

    def test_install_link_race_verifies_winner(self) -> None:
        content = b"race"
        digest_hex = hashlib.sha256(content).hexdigest()
        target = self.store.blob_root / digest_hex[:2] / digest_hex
        real_link = os.link

        def racing_link(source, destination):
            real_link(source, destination)
            raise FileExistsError(destination)

        with patch("plugins.local_execution_store.retention.os.link", racing_link):
            result = self.store._install_staged_original(
                self.staged(content), digest=sha(content), size=len(content), large=False
            )
        self.assertEqual(result, (f"artifact://sha256/{digest_hex}", target, False))


class CapturePairCase(RetentionStoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.run = trace_run("RUN-CAP")
        self.store.create_run(self.run)

    def put(self, original: bytes = b"<html>", text: bytes = b"text", **overrides):
        source = self.write_intake("capture/original.html", original)
        arguments = {
            "original_path": source,
            "original_media_type": "text/html",
            "original_artifact_id": "ART-ORIG",
            "original_provenance": {"capture_id": "CAP-1"},
            "text_content": text,
            "text_artifact_id": "ART-TEXT",
            "text_provenance": {"capture_id": "CAP-1"},
            "max_original_bytes": 1024,
            "role_byte_limits": {ORIGINAL_ROLE: 1024, TEXT_ROLE: 1024},
            "role_count_limits": {ORIGINAL_ROLE: 4, TEXT_ROLE: 4},
            "expected_status": RunStatus.PREPARED,
        }
        arguments.update(overrides)
        run = arguments.pop("run", self.run)
        return self.store.put_desktop_research_capture_files(run, **arguments)

    def assert_no_artifacts(self) -> None:
        self.assertEqual(tuple(self.store.artifacts_for(self.run.run_id)), ())
        self.assertEqual(self.staging_entries(), [])


class CapturePairTests(CapturePairCase):
    def test_small_pair_is_stored_as_generic_artifacts(self) -> None:
        original, text = self.put(
            expected_original_digest=sha(b"<html>"),
            expected_original_size=6,
            expected_text_digest=sha(b"text"),
            expected_text_size=4,
        )
        self.assertEqual(
            (original.artifact_id, original.role, original.media_type, original.size),
            ("ART-ORIG", ORIGINAL_ROLE, "text/html", 6),
        )
        self.assertEqual(original.digest, sha(b"<html>"))
        self.assertTrue(original.storage_locator.startswith("artifact://sha256/"))
        self.assertEqual(
            (text.artifact_id, text.role, text.media_type, text.size),
            ("ART-TEXT", TEXT_ROLE, "text/plain", 4),
        )
        self.assertEqual(original.provenance["parent_artifact_refs"], [])
        self.assertEqual(text.provenance["parent_artifact_refs"], ["ART-ORIG"])
        for item in (original, text):
            self.assertEqual(item.provenance["capture_id"], "CAP-1")
            self.assertEqual(item.provenance["source_run_id"], "RUN-CAP")
            self.assertEqual(item.provenance["execution_mode"], "virtual")
            self.assertEqual(item.provenance["stored_by"], "plugins.local_execution_store")
            self.assertIn("stored_at", item.provenance)
            self.store.verify_artifact_integrity(item.artifact_id)
        self.assertEqual(
            sorted(item.artifact_id for item in self.store.artifacts_for("RUN-CAP")),
            ["ART-ORIG", "ART-TEXT"],
        )
        self.assertEqual(self.staging_entries(), [])

    def test_large_original_uses_external_original_storage(self) -> None:
        big = b"x" * (self.max_artifact_bytes + 1)
        original, text = self.put(original=big)
        digest_hex = hashlib.sha256(big).hexdigest()
        self.assertEqual(original.storage_locator, f"external-original://sha256/{digest_hex}")
        self.assertTrue(
            (self.store.root / "large-originals" / "sha256" / digest_hex[:2] / digest_hex).is_file()
        )
        self.store.verify_artifact_integrity(original.artifact_id)
        self.store.verify_artifact_integrity(text.artifact_id)

    def test_large_original_is_excluded_from_generic_run_output_bound(self) -> None:
        big = b"x" * 100
        self.store.config = replace(self.store.config, max_run_output_bytes=10)
        original, _ = self.put(original=big)
        self.assertTrue(original.storage_locator.startswith("external-original://"))

    def test_small_original_counts_toward_generic_run_output_bound(self) -> None:
        self.store.config = replace(self.store.config, max_run_output_bytes=9)
        with self.assertRaisesRegex(
            LocalExecutionStoreError, "Run output exceeds configured max_run_output_bytes"
        ):
            self.put(original=b"123456", text=b"1234")
        self.assert_no_artifacts()

    def test_text_rendition_guards(self) -> None:
        cases = (
            ({"text_content": "text"}, TypeError, "text rendition content must be bytes"),
            (
                {"text_content": b"x" * (self.max_artifact_bytes + 1)},
                LocalExecutionStoreError,
                "text rendition exceeds configured max_artifact_bytes",
            ),
            (
                {"text_content": b"\xff\xfe"},
                LocalExecutionStoreError,
                "text rendition must be valid UTF-8",
            ),
            (
                {"expected_text_digest": sha(b"other")},
                LocalExecutionStoreIntegrityError,
                "text rendition does not match verified source digest",
            ),
            (
                {"expected_text_size": 99},
                LocalExecutionStoreIntegrityError,
                "text rendition does not match verified source size",
            ),
        )
        for overrides, error, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(error, message):
                    self.put(**overrides)
                self.assert_no_artifacts()

    def test_text_rendition_at_artifact_limit_is_accepted(self) -> None:
        _, text = self.put(text=b"x" * self.max_artifact_bytes)
        self.assertEqual(text.size, self.max_artifact_bytes)

    def test_expected_original_digest_and_size_mismatch(self) -> None:
        cases = (
            (
                {"expected_original_digest": sha(b"other")},
                "original capture does not match verified source digest",
            ),
            (
                {"expected_original_size": 1},
                "original capture does not match verified source size",
            ),
        )
        for overrides, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(LocalExecutionStoreIntegrityError, message):
                    self.put(**overrides)
                self.assert_no_artifacts()

    def test_run_binding_guards(self) -> None:
        cases = (
            (
                {"run": trace_run("RUN-MISSING")},
                LocalExecutionStoreError,
                "artifact Run must already exist in the execution trace",
            ),
            (
                {"run": replace(self.run, capability_id="other.capability")},
                LocalExecutionStoreIntegrityError,
                "artifact Run binding does not match persisted Run",
            ),
            (
                {"run": replace(self.run, execution_mode="real")},
                LocalExecutionStoreIntegrityError,
                "artifact Run binding does not match persisted Run",
            ),
            (
                {"expected_status": RunStatus.RUNNING},
                LocalExecutionStoreError,
                "artifact Run must remain RUNNING",
            ),
        )
        for overrides, error, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(error, message):
                    self.put(**overrides)
                self.assert_no_artifacts()

    def test_role_count_limits(self) -> None:
        for role in (ORIGINAL_ROLE, TEXT_ROLE):
            with self.subTest(role=role):
                limits = {ORIGINAL_ROLE: 4, TEXT_ROLE: 4, role: 0}
                with self.assertRaisesRegex(
                    LocalExecutionStoreError, f"artifact role count limit exceeded: {role}"
                ):
                    self.put(role_count_limits=limits)
                self.assert_no_artifacts()

    def test_role_count_limit_counts_existing_artifacts(self) -> None:
        limits = {ORIGINAL_ROLE: 1, TEXT_ROLE: 1}
        self.put(role_count_limits=limits)
        with self.assertRaisesRegex(
            LocalExecutionStoreError, f"artifact role count limit exceeded: {ORIGINAL_ROLE}"
        ):
            self.put(
                text=b"second",
                original_artifact_id="ART-ORIG-2",
                text_artifact_id="ART-TEXT-2",
                role_count_limits=limits,
            )

    def test_role_byte_limits(self) -> None:
        cases = (
            ({ORIGINAL_ROLE: 5, TEXT_ROLE: 1024}, ORIGINAL_ROLE),
            ({ORIGINAL_ROLE: 1024, TEXT_ROLE: 3}, TEXT_ROLE),
        )
        for limits, role in cases:
            with self.subTest(role=role):
                with self.assertRaisesRegex(
                    LocalExecutionStoreError, f"artifact role byte limit exceeded: {role}"
                ):
                    self.put(role_byte_limits=limits)
                self.assert_no_artifacts()

    def test_role_byte_limits_are_inclusive(self) -> None:
        original, text = self.put(role_byte_limits={ORIGINAL_ROLE: 6, TEXT_ROLE: 4})
        self.assertEqual((original.size, text.size), (6, 4))

    def test_artifact_identity_collision_is_rejected(self) -> None:
        self.put()
        with self.assertRaisesRegex(ValueError, "immutable artifact identity collision"):
            self.put(text=b"other", original_artifact_id="ART-NEW")
        self.assertEqual(len(tuple(self.store.artifacts_for("RUN-CAP"))), 2)

    def test_registration_failure_removes_newly_created_blobs(self) -> None:
        big = b"y" * (self.max_artifact_bytes + 3)
        with patch.object(
            LocalExecutionStore,
            "_register_output_artifact_in_transaction",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                self.put(original=big, text=b"fresh")
        self.assert_no_artifacts()
        digest_hex = hashlib.sha256(big).hexdigest()
        self.assertFalse(
            (self.store.root / "large-originals" / "sha256" / digest_hex[:2] / digest_hex).exists()
        )
        self.assertFalse(self.store._blob_target_for(b"fresh").exists())

    def test_capture_run_reservation_creates_per_run_lock_file(self) -> None:
        with self.store._large_capture_run_reservation("RUN-CAP"):
            pass
        lock_name = hashlib.sha256(b"RUN-CAP").hexdigest() + ".lock"
        self.assertTrue((self.store.root / "large-original-locks" / lock_name).is_file())


class VerifyArtifactIntegrityTests(CapturePairCase):
    def test_unknown_artifact_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.store.verify_artifact_integrity("ART-UNKNOWN")

    def test_tampered_large_original_fails_verification(self) -> None:
        big = b"z" * (self.max_artifact_bytes + 5)
        original, _ = self.put(original=big)
        digest_hex = hashlib.sha256(big).hexdigest()
        path = self.store.root / "large-originals" / "sha256" / digest_hex[:2] / digest_hex
        os.chmod(path, 0o600)
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(
            LocalExecutionStoreIntegrityError,
            "content-addressed blob failed digest/size verification",
        ):
            self.store.verify_artifact_integrity(original.artifact_id)


if __name__ == "__main__":
    unittest.main()
