from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from plugins.local_execution_store import artifact_metadata_for, diagnostics_for

from .facade import LocalApplicationError
from .material_reacquisition_facade import (
    _CAPABILITY_ID as _MRA_CAPABILITY_ID,
    _RESULT_DIAGNOSTIC as _MRA_RESULT_DIAGNOSTIC,
)
from .material_reacquisition_public_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from . import new_material_continuation_admission as admission
from .new_material_continuation_admission import _find_reacquisition_result
from .new_material_continuation_service import NewMaterialContinuationService
from .new_material_group_continuation_service import (
    PairedNewMaterialContinuationService,
    _GROUP_RELATION,
)

_ACTION_TYPE = "desktop_research.material.continue_new_version"
_PAYLOAD_CONTRACT = "desktop-research-new-material-continuation@0.2.0"
_ACTION_REGISTRATION_LOCK = RLock()
_GROUP_INSPECTION_ARTIFACT_LIMIT = 100

def _payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"reacquisition_run_id", "paired_reacquisition_run_ids"}
    if (
        not isinstance(payload, Mapping)
        or "reacquisition_run_id" not in payload
        or set(payload) - allowed
    ):
        raise ValueError(
            "desktop_research.material.continue_new_version requires reacquisition_run_id "
            "and optional paired_reacquisition_run_ids"
        )
    run_id = payload.get("reacquisition_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("reacquisition_run_id must be a non-empty string")
    paired = payload.get("paired_reacquisition_run_ids", [])
    if (
        not isinstance(paired, list)
        or len(paired) > 15
        or any(not isinstance(item, str) or not item for item in paired)
        or len(set(paired)) != len(paired)
        or run_id in paired
    ):
        raise ValueError(
            "paired_reacquisition_run_ids must contain up to 15 unique non-empty Run IDs "
            "different from reacquisition_run_id"
        )
    normalized: dict[str, Any] = {"reacquisition_run_id": run_id}
    if paired:
        normalized["paired_reacquisition_run_ids"] = sorted(paired)
    return normalized

class NewMaterialContinuationHandler:
    def __init__(self, application, project_id: str, workspace_root) -> None:
        self._service = NewMaterialContinuationService(
            application, project_id, workspace_root
        )
        self._paired_service = PairedNewMaterialContinuationService(
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
        primary = str(payload["reacquisition_run_id"])
        paired = tuple(str(item) for item in payload.get("paired_reacquisition_run_ids", []))
        result = (
            self._paired_service.continue_new_versions((primary, *paired))
            if paired
            else self._service.continue_new_version(primary)
        )
        return HarnessServiceResult(
            result_reference=str(result.get("new_run_id") or primary),
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
                    status, new_run_id = "available", None
                else:
                    bound = admission._validate_continuation_binding(
                        self._application,
                        self._project_id,
                        binding,
                        mra,
                        historical,
                        require_mirror=False,
                        require_completed_capture=False,
                    )
                    mirror_complete = admission._continuation_mirror_complete(
                        self._application.execution_store, binding
                    )
                    if bound.status.value == "COMPLETED" and mirror_complete:
                        status = (
                            "completed"
                            if admission._completed_continuation_is_reusable(
                                self._application,
                                self._project_id,
                                binding,
                                mra,
                                historical,
                            )
                            else "retryable"
                        )
                    elif not mirror_complete:
                        status = "interrupted"
                    else:
                        status = bound.status.value.lower()
                    new_run_id = bound.run_id
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
                "new_material_kind": mra.get("new_material_kind") or mra.get("kind"),
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
                    "new_material_kind": mra.get("new_material_kind") or mra.get("kind"),
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
            elif not own_bindings:
                artifacts = artifact_metadata_for(
                    self._application.execution_store,
                    run.run_id,
                    limit=_GROUP_INSPECTION_ARTIFACT_LIMIT,
                )
                grouped = [
                    item
                    for item in artifacts
                    if item.provenance.get("relation") == _GROUP_RELATION
                ]
                if grouped:
                    group_ids = {
                        str(item.provenance.get("continuation_group_id") or "")
                        for item in grouped
                    }
                    historical_ids = {
                        str(item.provenance.get("historical_run_id") or "")
                        for item in grouped
                    }
                    run_id_lists = {
                        tuple(item.provenance.get("reacquisition_run_ids") or ())
                        for item in grouped
                    }
                    if (
                        len(group_ids) == 1
                        and "" not in group_ids
                        and len(historical_ids) == 1
                        and "" not in historical_ids
                        and len(run_id_lists) == 1
                    ):
                        paired_ids = next(iter(run_id_lists))
                        replacements = []
                        valid = bool(paired_ids)
                        for paired_id in paired_ids:
                            try:
                                _parent, mra, _artifact, historical, _original, _capture = (
                                    _find_reacquisition_result(
                                        self._application, self._project_id, str(paired_id)
                                    )
                                )
                            except LocalApplicationError:
                                valid = False
                                break
                            kind = str(mra.get("new_material_kind") or mra.get("kind") or "")
                            role = (
                                "desktop_research.original_capture"
                                if kind == "original"
                                else "desktop_research.text_rendition"
                            )
                            matches = [
                                item
                                for item in grouped
                                if item.role == role
                                and item.provenance.get("reacquisition_run_id") == paired_id
                                and item.provenance.get("historical_capture_id")
                                == mra.get("historical_capture_id")
                                and item.provenance.get("reacquired_artifact_id")
                                == mra.get("new_artifact_id")
                                and item.digest == mra.get("actual_digest")
                                and item.size == mra.get("actual_size")
                            ]
                            if len(matches) != 1 or historical.run_id not in historical_ids:
                                valid = False
                                break
                            replacements.append(
                                {
                                    "reacquisition_run_id": str(paired_id),
                                    "historical_capture_id": mra["historical_capture_id"],
                                    "new_material_artifact_id": mra["new_artifact_id"],
                                    "new_material_kind": kind,
                                    "new_material_digest": mra["actual_digest"],
                                    "new_material_size": mra["actual_size"],
                                }
                            )
                        if valid:
                            result["new_material_continuation"] = {
                                "status": run.status.value.lower(),
                                "mode": "paired",
                                "continuation_group_id": next(iter(group_ids)),
                                "reacquisition_run_ids": list(paired_ids),
                                "historical_run_id": next(iter(historical_ids)),
                                "replacements": replacements,
                                "new_run_id": run.run_id,
                                "new_handoff_id": run.handoff_ref,
                                "new_handoff_digest": run.handoff_digest,
                                "historical_recovery_satisfied": False,
                            }
        return result
