from __future__ import annotations

import hashlib
from typing import Mapping

from .store import LocalExecutionStoreIntegrityError
from .verified_artifact_read import VerifiedArtifactReadMixin


def _diagnosed_integrity_error(
    message: str,
    diagnosis: Mapping[str, object],
) -> LocalExecutionStoreIntegrityError:
    error = LocalExecutionStoreIntegrityError(message)
    error.diagnosis = dict(diagnosis)
    return error


class DiagnosedArtifactReadMixin(VerifiedArtifactReadMixin):
    """Reuse the failed verified read when public diagnosis immediately follows it."""

    def _remember_artifact_diagnosis(
        self,
        artifact_id: str,
        diagnosis: Mapping[str, object],
    ) -> None:
        with self._lock:
            cached = getattr(self, "_verified_artifact_diagnoses", None)
            if cached is None:
                cached = {}
                self._verified_artifact_diagnoses = cached
            cached[artifact_id] = dict(diagnosis)

    def _take_artifact_diagnosis(self, artifact_id: str) -> dict[str, object] | None:
        with self._lock:
            cached = getattr(self, "_verified_artifact_diagnoses", None)
            if not isinstance(cached, dict):
                return None
            diagnosis = cached.pop(artifact_id, None)
        return dict(diagnosis) if isinstance(diagnosis, Mapping) else None

    def _load_verified_blob(
        self,
        locator: str,
        expected_digest: str,
        expected_size: int,
    ) -> bytes:
        target = self._locator_path(locator, expected_digest)
        if not target.exists():
            raise FileNotFoundError(target)
        try:
            content = target.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise _diagnosed_integrity_error(
                "content-addressed blob could not be read",
                {
                    "status": "content_unreadable",
                    "expected_digest": expected_digest,
                    "expected_size": expected_size,
                    "actual_digest": None,
                    "actual_size": None,
                },
            ) from exc
        actual_digest = "sha256:" + hashlib.sha256(content).hexdigest()
        actual_size = len(content)
        if actual_digest != expected_digest or actual_size != expected_size:
            if actual_digest != expected_digest and actual_size != expected_size:
                status = "digest_and_size_mismatch"
            elif actual_digest != expected_digest:
                status = "digest_mismatch"
            else:
                status = "size_mismatch"
            raise _diagnosed_integrity_error(
                "content-addressed blob failed digest/size verification",
                {
                    "status": status,
                    "expected_digest": expected_digest,
                    "expected_size": expected_size,
                    "actual_digest": actual_digest,
                    "actual_size": actual_size,
                },
            )
        return content

    def load_artifact_verified_once(self, artifact_id: str):
        try:
            payload = super().load_artifact_verified_once(artifact_id)
        except LocalExecutionStoreIntegrityError as exc:
            diagnosis = getattr(exc, "diagnosis", None)
            if isinstance(diagnosis, Mapping):
                self._remember_artifact_diagnosis(artifact_id, diagnosis)
            raise
        self._take_artifact_diagnosis(artifact_id)
        return payload

    def diagnose_artifact_content(self, artifact_id: str) -> dict[str, object]:
        cached = self._take_artifact_diagnosis(artifact_id)
        if cached is None:
            return super().diagnose_artifact_content(artifact_id)
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_id, run_id, role, media_type, size, digest
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            return super().diagnose_artifact_content(artifact_id)
        return {
            "artifact_id": str(row["artifact_id"]),
            "run_id": str(row["run_id"]),
            "role": str(row["role"]),
            "media_type": str(row["media_type"]),
            "expected_digest": str(row["digest"]),
            "expected_size": int(row["size"]),
            **cached,
        }
