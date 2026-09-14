from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult

from plugins.local_execution_store import (
    LocalExecutionStoreIntegrityError,
    bind_controlled_import_root,
    result_extensions_for_run,
)

from .external_desktop_facade import _ORIGINAL_ROLE, _TEXT_ROLE
from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture




_ACTION_TYPE = "desktop_research.material.recover"
_PAYLOAD_CONTRACT = "desktop-research-material-recovery@0.1.0"
_ACTION_REGISTRATION_LOCK = RLock()


def material_recovery_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    required = {"run_id", "capture_id", "kind", "source_file"}
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise ValueError(
            "desktop_research.material.recover requires run_id, capture_id, kind, and source_file"
        )
    run_id = payload.get("run_id")
    capture_id = payload.get("capture_id")
    kind = payload.get("kind")
    source_file = payload.get("source_file")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(capture_id, str) or not capture_id:
        raise ValueError("capture_id must be a non-empty string")
    if kind not in {"original", "rendition"}:
        raise ValueError("kind must be original or rendition")
    if not isinstance(source_file, str) or not source_file:
        raise ValueError("source_file must be a non-empty workspace-relative or workspace-contained path")
    return {
        "run_id": run_id,
        "capture_id": capture_id,
        "kind": str(kind),
        "source_file": source_file,
    }

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


class HistoricalMaterialRecoveryHandler:
    def __init__(self, application, project_id: str, workspace_root: Path | None) -> None:
        self._service = HistoricalMaterialRecoveryService(
            application.execution_store, project_id, workspace_root
        )

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        state: Any,
        actor: Any,
        proposal: Mapping[str, Any],
    ) -> HarnessServiceResult:
        del state, actor, proposal
        result = self._service.recover(
            str(payload["run_id"]),
            str(payload["capture_id"]),
            kind=str(payload["kind"]),
            source_file=str(payload["source_file"]),
        )
        return HarnessServiceResult(
            result_reference=str(result["artifact_id"]),
            data=result,
            research_state_mutation_performed=False,
        )


def ensure_material_recovery_action(application, project_id: str, workspace_root: Path | None) -> None:
    coordinator = application.coordinator
    action_registry = coordinator._actions
    service_registry = coordinator._services
    with _ACTION_REGISTRATION_LOCK:
        existing = {definition.action_type: definition for definition in coordinator.action_definitions()}
        definition = existing.get(_ACTION_TYPE)
        if definition is None:
            action_registry.register(
                ActionDefinition(
                    _ACTION_TYPE,
                    _PAYLOAD_CONTRACT,
                    "read_only",
                    "harness_service",
                    False,
                    human_decision_required=False,
                    service_id=_ACTION_TYPE,
                    payload_validator=material_recovery_payload,
                )
            )
        elif (
            definition.payload_contract != _PAYLOAD_CONTRACT
            or definition.effect != "read_only"
            or definition.route_kind != "harness_service"
            or definition.confirmation_required
            or definition.service_id != _ACTION_TYPE
        ):
            raise RuntimeError("desktop_research.material.recover action registration conflict")
        try:
            service_registry.resolve(_ACTION_TYPE)
        except ConversationRuntimeError as exc:
            if exc.code != "CONV-ROUTE-001":
                raise
            service_registry.register(
                _ACTION_TYPE,
                HistoricalMaterialRecoveryHandler(application, project_id, workspace_root),
            )


class HistoricalMaterialRecoveryService:
    """Diagnose and restore exact missing bytes without rewriting historical metadata."""

    def __init__(self, store, project_id: str, workspace_root: Path | None):
        self._store = store
        self._project_id = project_id
        self._workspace_root = workspace_root

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
        managed_root = self._workspace_root / ".research-loom"
        try:
            source_path.resolve(strict=False).relative_to(managed_root.resolve(strict=False))
        except ValueError:
            pass
        else:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-RECOVERY-001",
                "historical material recovery source must be an operator-controlled workspace file",
            )
        bind_controlled_import_root(self._store, self._workspace_root)
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
        except LocalApplicationError:
            raise
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-RECOVERY-001",
                "historical external material could not be restored from identical bytes",
            ) from exc

        diagnostic_recorded = False
        diagnostic_warning = None
        if result.get("status") == "RESTORED":
            try:
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
            except Exception:
                diagnostic_warning = {
                    "code": "APPLICATION-MATERIAL-RECOVERY-DIAGNOSTIC-001",
                    "message": "material bytes were restored and verified but the recovery diagnostic could not be persisted",
                }
            else:
                diagnostic_recorded = True

        response = {
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
            "diagnostic_recorded": diagnostic_recorded,
        }
        if diagnostic_warning is not None:
            response["diagnostic_warning"] = diagnostic_warning
        return response
