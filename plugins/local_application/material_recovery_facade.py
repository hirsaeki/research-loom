from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from plugins.local_execution_store import (
    LocalExecutionStoreIntegrityError,
    result_extensions_for_run,
)

from .external_desktop_facade import _ORIGINAL_ROLE, _TEXT_ROLE
from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture


def _canonical_artifact_binding_for_capture(
    store, run_id: str, capture_id: str, kind: str
):
    extensions = result_extensions_for_run(store, run_id, limit=3)
    if len(extensions) != 1 or not isinstance(extensions[0], Mapping):
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research result extension is incomplete or ambiguous"
        )
    details = extensions[0].get("source_capture_details")
    if not isinstance(details, list):
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research source capture details are unavailable"
        )
    matches = [
        detail
        for detail in details
        if isinstance(detail, Mapping) and detail.get("capture_id") == capture_id
    ]
    if len(matches) != 1:
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research capture binding is missing or ambiguous"
        )
    detail = matches[0]
    key = "original_capture" if kind == "original" else "text_rendition"
    binding = detail.get(key)
    if not isinstance(binding, Mapping):
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research artifact binding is invalid"
        )
    artifact_id = binding.get("content_reference")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research artifact binding is invalid"
        )
    artifacts = [
        artifact
        for artifact in store.artifacts_for(run_id)
        if artifact.artifact_id == artifact_id
    ]
    if len(artifacts) != 1:
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research artifact metadata is missing or ambiguous"
        )
    artifact = artifacts[0]
    expected_role = _ORIGINAL_ROLE if kind == "original" else _TEXT_ROLE
    if (
        artifact.run_id != run_id
        or artifact.role != expected_role
        or artifact.provenance.get("capture_id") != capture_id
        or binding.get("content_digest") != artifact.digest
        or binding.get("byte_length") != artifact.size
    ):
        raise LocalExecutionStoreIntegrityError(
            "canonical Desktop Research artifact binding disagrees with persisted metadata"
        )
    return artifact


class HistoricalMaterialRecoveryService:
    """Diagnose and restore exact missing bytes without rewriting historical metadata."""

    def __init__(self, store, project_id: str, workspace_root: Path | None):
        self._store = store
        self._project_id = project_id
        self._workspace_root = workspace_root

    def diagnose(self, run_id: str, capture_id: str) -> Mapping[str, Any]:
        if not isinstance(run_id, str) or not run_id or not isinstance(capture_id, str) or not capture_id:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INPUT-001",
                "external material diagnosis requires non-empty run_id and capture_id",
            )
        try:
            run, original, rendition, capture = _artifact_pair_for_capture(
                self._store, self._project_id, run_id, capture_id
            )
            original_diag = self._store.diagnose_artifact_content(original.artifact_id)
            rendition_diag = self._store.diagnose_artifact_content(rendition.artifact_id)
        except LocalApplicationError:
            raise
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INTEGRITY-001",
                "persisted external material binding could not be diagnosed",
            ) from exc
        return {
            "status": "OK",
            "project_id": self._project_id,
            "run": {
                "run_id": run.run_id,
                "status": run.status.value,
                "snapshot_id": run.snapshot_ref,
                "snapshot_digest": run.snapshot_digest,
            },
            "capture": capture,
            "artifact_verification": {
                "original": original_diag,
                "rendition": rendition_diag,
            },
            "recovery_required": any(
                item.get("status") != "verified"
                for item in (original_diag, rendition_diag)
            ),
        }

    def recover(
        self,
        run_id: str,
        capture_id: str,
        *,
        kind: str,
        source_file: str | Path,
    ) -> Mapping[str, Any]:
        if kind not in {"original", "rendition"}:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INPUT-001",
                "external material recovery kind must be original or rendition",
            )
        if self._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-RECOVERY-001",
                "external material recovery requires a workspace-bound facade",
            )
        raw = Path(source_file)
        source_path = raw if raw.is_absolute() else self._workspace_root / raw
        try:
            run, _original, _rendition, _capture = _artifact_pair_for_capture(
                self._store, self._project_id, run_id, capture_id
            )
            artifact = _canonical_artifact_binding_for_capture(
                self._store, run_id, capture_id, kind
            )
            before = self._store.diagnose_artifact_content(artifact.artifact_id)
            if before.get("status") not in {"verified", "content_missing"}:
                raise LocalExecutionStoreIntegrityError(
                    "only missing persisted artifact bytes are eligible for same-bytes recovery"
                )
            result = self._store.restore_missing_artifact_from_file(
                artifact.artifact_id, source_path
            )
            if result.get("status") == "RESTORED":
                self._store.store_diagnostic(
                    run_id,
                    "historical_material_recovery",
                    {
                        "contract": "historical-material-same-bytes-recovery@0.1.0",
                        "capture_id": capture_id,
                        "artifact_kind": kind,
                        "artifact_id": artifact.artifact_id,
                        "recovery_method": "operator_file_same_bytes",
                        "recovered_at": datetime.now(timezone.utc).isoformat(),
                        "verified_digest": artifact.digest,
                        "verified_size": artifact.size,
                    },
                )
        except LocalApplicationError:
            raise
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-RECOVERY-001",
                "historical external material could not be restored from identical bytes",
            ) from exc
        return {
            "status": result["status"],
            "project_id": self._project_id,
            "run_id": run.run_id,
            "capture_id": capture_id,
            "kind": kind,
            "artifact_id": artifact.artifact_id,
            "digest": artifact.digest,
            "byte_length": artifact.size,
            "verification_status": "verified",
            "historical_metadata_rewritten": False,
            "research_state_mutation_performed": False,
        }
