from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from core.execution.models import ResourcePayload

from .store import LocalExecutionStoreIntegrityError


class VerifiedArtifactReadMixin:
    """Single-read and bounded verified reads for persisted artifact content."""

    def _load_verified_blob(
        self,
        locator: str,
        expected_digest: str,
        expected_size: int,
    ) -> bytes:
        target = self._locator_path(locator, expected_digest)
        if not target.exists():
            raise FileNotFoundError(target)
        content = target.read_bytes()
        self._verify_blob_path(
            target,
            expected_digest,
            expected_size,
            content=content,
        )
        return content

    def _verify_blob_path(
        self,
        path: Path,
        expected_digest: str,
        expected_size: int,
        *,
        content: bytes | None = None,
    ) -> None:
        data = path.read_bytes() if content is None else content
        actual_digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual_digest != expected_digest or len(data) != expected_size:
            raise LocalExecutionStoreIntegrityError(
                "content-addressed blob failed digest/size verification"
            )

    def diagnose_artifact_content(self, artifact_id: str) -> dict[str, object]:
        """Return bounded verification state without exposing storage paths."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_id, run_id, role, media_type, size, digest, storage_locator
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            return {
                "artifact_id": artifact_id,
                "status": "metadata_missing",
                "expected_digest": None,
                "expected_size": None,
                "actual_digest": None,
                "actual_size": None,
            }

        expected_digest = str(row["digest"])
        expected_size = int(row["size"])
        base = {
            "artifact_id": str(row["artifact_id"]),
            "run_id": str(row["run_id"]),
            "role": str(row["role"]),
            "media_type": str(row["media_type"]),
            "expected_digest": expected_digest,
            "expected_size": expected_size,
            "actual_digest": None,
            "actual_size": None,
        }
        try:
            path = self._locator_path(str(row["storage_locator"]), expected_digest)
        except LocalExecutionStoreIntegrityError:
            return {**base, "status": "locator_invalid"}
        if not path.exists():
            return {**base, "status": "content_missing"}

        actual = hashlib.sha256()
        total = 0
        try:
            with path.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    actual.update(chunk)
                    total += len(chunk)
        except OSError:
            return {**base, "status": "content_unreadable"}
        actual_digest = "sha256:" + actual.hexdigest()
        status = "verified"
        if actual_digest != expected_digest and total != expected_size:
            status = "digest_and_size_mismatch"
        elif actual_digest != expected_digest:
            status = "digest_mismatch"
        elif total != expected_size:
            status = "size_mismatch"
        return {
            **base,
            "status": status,
            "actual_digest": actual_digest,
            "actual_size": total,
        }

    def restore_missing_artifact_from_file(
        self,
        artifact_id: str,
        source_path: str | Path,
    ) -> Mapping[str, Any]:
        """Restore missing content-addressed bytes when the supplied file is identical."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_id, run_id, role, media_type, size, digest, storage_locator
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)

        expected_digest = str(row["digest"])
        expected_size = int(row["size"])
        locator = str(row["storage_locator"])
        target = self._locator_path(locator, expected_digest)
        if target.exists():
            self._verify_blob_streaming(target, expected_digest, expected_size)
            return {
                "status": "ALREADY_VERIFIED",
                "artifact_id": artifact_id,
                "run_id": str(row["run_id"]),
                "role": str(row["role"]),
                "digest": expected_digest,
                "byte_length": expected_size,
                "content_created": False,
            }

        if locator.startswith("external-original://sha256/"):
            large = True
        elif locator.startswith("artifact://sha256/"):
            large = False
        else:
            raise LocalExecutionStoreIntegrityError(
                "persisted artifact storage locator is not eligible for same-bytes restoration"
            )

        temporary, actual_digest, actual_size = self._stage_controlled_original(
            source_path, max_bytes=expected_size
        )
        try:
            if actual_digest != expected_digest or actual_size != expected_size:
                raise LocalExecutionStoreIntegrityError(
                    "provided recovery bytes do not match persisted artifact digest/size"
                )
            installed_locator, installed_path, created = self._install_staged_original(
                temporary,
                digest=actual_digest,
                size=actual_size,
                large=large,
            )
            try:
                if installed_locator != locator:
                    raise LocalExecutionStoreIntegrityError(
                        "restored artifact locator would not preserve persisted binding"
                    )
                self._verify_blob_streaming(
                    installed_path, expected_digest, expected_size
                )
            except Exception:
                if created:
                    try:
                        installed_path.unlink()
                    except OSError:
                        pass
                raise
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return {
            "status": "RESTORED",
            "artifact_id": artifact_id,
            "run_id": str(row["run_id"]),
            "role": str(row["role"]),
            "digest": expected_digest,
            "byte_length": expected_size,
            "content_created": created,
        }

    def load_artifact_verified_once(self, artifact_id: str) -> ResourcePayload:
        """Return the exact bytes from the same read that passed verification."""
        return self.load_artifact(artifact_id)

    def load_artifact_verified_prefix(
        self,
        artifact_id: str,
        *,
        max_bytes: int,
    ) -> tuple[ResourcePayload, int]:
        """Stream-verify a full artifact while retaining only a bounded prefix."""
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_id, media_type, size, digest, storage_locator
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)

        expected_digest = str(row["digest"])
        expected_size = int(row["size"])
        path = self._locator_path(str(row["storage_locator"]), expected_digest)
        actual = hashlib.sha256()
        total = 0
        prefix = bytearray()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                actual.update(chunk)
                total += len(chunk)
                if len(prefix) < max_bytes:
                    prefix.extend(chunk[: max_bytes - len(prefix)])
        actual_digest = "sha256:" + actual.hexdigest()
        if actual_digest != expected_digest or total != expected_size:
            raise LocalExecutionStoreIntegrityError(
                "content-addressed blob failed digest/size verification"
            )
        return (
            ResourcePayload(
                str(row["artifact_id"]),
                bytes(prefix),
                expected_digest,
                str(row["media_type"]),
            ),
            total,
        )
