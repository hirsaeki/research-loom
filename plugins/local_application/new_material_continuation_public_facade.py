from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from plugins.local_execution_store import diagnostics_for

from .facade import LocalApplicationError
from .material_reacquisition_facade import (
    _CAPABILITY_ID as _MRA_CAPABILITY_ID,
    _RESULT_DIAGNOSTIC as _MRA_RESULT_DIAGNOSTIC,
)
from .material_reacquisition_public_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from . import new_material_continuation_admission as admission
from .new_material_continuation_admission import _find_reacquisition_result
from .new_material_continuation_service import NewMaterialContinuationService

_ACTION_TYPE = "desktop_research.material.continue_new_version"
_PAYLOAD_CONTRACT = "desktop-research-new-material-continuation@0.1.0"
_ACTION_REGISTRATION_LOCK = RLock()

def _payload(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"reacquisition_run_id"}:
        raise ValueError(
            "desktop_research.material.continue_new_version requires only reacquisition_run_id"
        )
    run_id = payload.get("reacquisition_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("reacquisition_run_id must be a non-empty string")
    return {"reacquisition_run_id": run_id}

class NewMaterialContinuationHandler:
    def __init__(self, application, project_id: str, workspace_root) -> None:
        self._service = NewMaterialContinuationService(
            application, project_id, workspace_root
        )

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        state: Any,
        actor: Any,
        proposal: Mapping[str, Any],
    ):
        del state, actor, proposal
        result = self._service.continue_new_version(str(payload["reacquisition_run_id"]))
        return HarnessServiceResult(
            result_reference=str(
                result.get("new_run_id") or payload["reacquisition_run_id"]
            ),
            data=result,
            research_state_mutation_performed=False,
        )


def ensure_new_material_continuation_action(
    application, project_id: str, workspace_root
) -> None:
    coordinator = application.coordinator
    with _ACTION_REGISTRATION_LOCK:
        definitions = {item.action_type: item for item in coordinator.action_definitions()}
        definition = definitions.get(_ACTION_TYPE)
        if definition is None:
            coordinator._actions.register(
                ActionDefinition(
                    _ACTION_TYPE,
                    _PAYLOAD_CONTRACT,
                    "read_only",
                    "harness_service",
                    False,
                    human_decision_required=False,
                    service_id=_ACTION_TYPE,
                    payload_validator=_payload,
                )
            )
        elif (
            definition.payload_contract != _PAYLOAD_CONTRACT
            or definition.effect != "read_only"
            or definition.route_kind != "harness_service"
            or definition.confirmation_required
            or definition.service_id != _ACTION_TYPE
        ):
            raise RuntimeError("new material continuation action registration conflict")
        try:
            coordinator._services.resolve(_ACTION_TYPE)
        except ConversationRuntimeError as exc:
            if exc.code != "CONV-ROUTE-001":
                raise
            coordinator._services.register(
                _ACTION_TYPE,
                NewMaterialContinuationHandler(
                    application, project_id, workspace_root
                ),
            )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Continue persisted divergent material through a new normal research result."""

    def list_actions(self) -> Mapping[str, Any]:
        ensure_new_material_continuation_action(
            self._application, self._project_id, self._workspace_root
        )
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        ensure_new_material_continuation_action(
            self._application, self._project_id, self._workspace_root
        )
        return super().submit_action(draft_input)

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        result = deepcopy(dict(super().show_run(run_id)))
        try:
            run = self._application.execution_store.load_run(run_id)
        except Exception:
            return result
        if run is None:
            return result

        if run.capability_id == _MRA_CAPABILITY_ID:
            nmv_records = [
                item.get("payload")
                for item in diagnostics_for(
                    self._application.execution_store,
                    run_id,
                    kind=_MRA_RESULT_DIAGNOSTIC,
                    limit=2,
                )
                if isinstance(item.get("payload"), Mapping)
                and item["payload"].get("status") == "NEW_MATERIAL_VERSION"
            ]
            if len(nmv_records) != 1:
                return result
            try:
                _run, mra, _artifact, historical, _original, _capture = (
                    _find_reacquisition_result(
                        self._application, self._project_id, run_id
                    )
                )
            except LocalApplicationError as exc:
                result["new_material_continuation"] = {
                    "status": "blocked",
                    "reacquisition_run_id": run_id,
                    "failure_code": exc.code,
                    "historical_recovery_satisfied": False,
                }
                return result
            try:
                binding = admission._continuation_binding(
                    self._application.execution_store, run_id
                )
                if binding is None:
                    claim = admission._continuation_claim(
                        self._application.execution_store, run_id
                    )
                    if claim is None:
                        status, new_run_id = "available", None
                    else:
                        result["new_material_continuation"] = {
                            "status": "blocked",
                            "reacquisition_run_id": run_id,
                            "failure_code": "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                            "historical_recovery_satisfied": False,
                        }
                        return result
                else:
                    bound = admission._validate_continuation_binding(
                        self._application, self._project_id, binding, mra, historical
                    )
                    status, new_run_id = bound.status.value.lower(), bound.run_id
            except LocalApplicationError as exc:
                result["new_material_continuation"] = {
                    "status": "conflict",
                    "reacquisition_run_id": run_id,
                    "failure_code": exc.code,
                    "historical_recovery_satisfied": False,
                }
                return result
            result["new_material_continuation"] = {
                "status": status,
                "reacquisition_run_id": run_id,
                "historical_run_id": historical.run_id,
                "historical_capture_id": mra["historical_capture_id"],
                "new_material_artifact_id": mra["new_artifact_id"],
                "new_material_digest": mra["actual_digest"],
                "new_material_size": mra["actual_size"],
                "historical_acquired_at": mra["historical_acquired_at"],
                "reacquired_at": mra["reacquired_at"],
                "exact_locator": mra["requested_exact_locator"],
                "new_run_id": new_run_id,
                "historical_recovery_satisfied": False,
            }
        else:
            own_bindings = [
                item.get("payload")
                for item in diagnostics_for(
                    self._application.execution_store,
                    run.run_id,
                    kind=admission._CONTINUATION_BINDING_DIAGNOSTIC,
                    limit=2,
                )
            ]
            if len(own_bindings) == 1 and isinstance(own_bindings[0], Mapping):
                binding = own_bindings[0]
                reacquisition_run_id = str(binding.get("reacquisition_run_id") or "")
                try:
                    _parent, mra, artifact, historical, _original, _capture = (
                        _find_reacquisition_result(
                            self._application, self._project_id, reacquisition_run_id
                        )
                    )
                    admission._validate_continuation_binding(
                        self._application, self._project_id, binding, mra, historical
                    )
                except LocalApplicationError:
                    return result
                result["new_material_continuation"] = {
                    "status": run.status.value.lower(),
                    "reacquisition_run_id": reacquisition_run_id,
                    "historical_run_id": historical.run_id,
                    "historical_capture_id": mra["historical_capture_id"],
                    "new_material_artifact_id": artifact.reference_id,
                    "new_material_digest": mra["actual_digest"],
                    "new_material_size": mra["actual_size"],
                    "historical_acquired_at": mra["historical_acquired_at"],
                    "reacquired_at": mra["reacquired_at"],
                    "exact_locator": mra["requested_exact_locator"],
                    "new_run_id": run.run_id,
                    "new_handoff_id": run.handoff_ref,
                    "new_handoff_digest": run.handoff_digest,
                    "historical_recovery_satisfied": False,
                }
        return result
