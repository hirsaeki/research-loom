from __future__ import annotations

import hashlib
from pathlib import Path

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
