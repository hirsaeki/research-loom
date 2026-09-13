from __future__ import annotations

from copy import deepcopy
import hashlib
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.execution import RunStatus
from core.runtime import canonical_digest
from core.runtime.ports import StaleHeadError
from plugins.local_conversation_store import find_state_delta_proposals_by_provenance_run_id
from plugins.local_execution_store import canonical_handoff_for
from plugins.sqlite_state_store.exhibit_guard import guard_research_state_head

from .facade import LocalApplicationError
from .argument_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


_RECOVERY_VERSION = "legacy-desktop-finding-candidate-to-approved@0.1.0"
_ACTION_TYPE = "desktop_research.finding.recover"
_PAYLOAD_CONTRACT = "desktop-research-finding-recovery@0.1.0"
_ACTION_REGISTRATION_LOCK = RLock()
_ALLOWED_OBJECT_KINDS = {"artifact", "source", "evidence", "finding"}


def _proposal_digest(payload: Mapping[str, Any]) -> str:
    basis = deepcopy(dict(payload))
    basis.pop("proposal_digest", None)
    return canonical_digest(basis)


def _fresh_proposal_id(run_id: str, proposal_digest: str) -> str:
    basis = f"{_RECOVERY_VERSION}:{run_id}:{proposal_digest}"
    return "SDP-RECOVERY-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _legacy_actions(
    payload: Mapping[str, Any], handoff_ref: str, project_id: str
) -> list[dict[str, Any]]:
    actions = payload.get("proposed_actions")
    if not isinstance(actions, list) or not actions:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-SHAPE-001",
            "persisted Desktop Research candidate has an unrecognized action shape",
        )
    affected = payload.get("affected_refs")
    if not isinstance(affected, list) or len(affected) != len(actions):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-SHAPE-001",
            "legacy recovery requires one affected reference per proposed object",
        )
    findings = 0
    recovered = deepcopy(actions)
    expected_refs: list[dict[str, str]] = []
    for action in recovered:
        if not isinstance(action, dict) or action.get("kind") != "CREATE_OBJECT":
            raise LocalApplicationError(
                "APPLICATION-FINDING-RECOVERY-SHAPE-001",
                "legacy recovery accepts only Desktop Research CREATE_OBJECT actions",
            )
        source_refs = action.get("source_refs", [])
        if source_refs != [handoff_ref]:
            raise LocalApplicationError(
                "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
                "candidate action provenance does not match the completed Run Handoff",
            )
        body = action.get("payload")
        obj = body.get("object") if isinstance(body, dict) else None
        if not isinstance(obj, dict) or obj.get("kind") not in _ALLOWED_OBJECT_KINDS:
            raise LocalApplicationError(
                "APPLICATION-FINDING-RECOVERY-SHAPE-001",
                "persisted Desktop Research candidate contains an unexpected object kind",
            )
        if (
            obj.get("project_id") != project_id
            or obj.get("schema_version") != "0.1.0"
            or obj.get("revision") != 0
            or not isinstance(obj.get("id"), str)
            or not obj.get("id")
        ):
            raise LocalApplicationError(
                "APPLICATION-FINDING-RECOVERY-SHAPE-001",
                "legacy recovery object binding is not recognized",
            )
        expected_refs.append({"kind": str(obj["kind"]), "id": str(obj["id"])})
        if obj.get("kind") == "finding":
            findings += 1
            if obj.get("adoption_state") != "candidate":
                raise LocalApplicationError(
                    "APPLICATION-FINDING-RECOVERY-SHAPE-001",
                    "candidate is not the recognized pre-#139 Finding shape",
                )
            obj["adoption_state"] = "approved"
        elif "adoption_state" in obj:
            raise LocalApplicationError(
                "APPLICATION-FINDING-RECOVERY-SHAPE-001",
                "non-Finding adoption semantics are not eligible for legacy recovery",
            )
    if affected != expected_refs:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-SHAPE-001",
            "legacy recovery affected references do not match proposed objects",
        )
    if findings == 0:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-SHAPE-001",
            "candidate contains no legacy Finding target to recover",
        )
    return recovered


def _validate_run_documents(execution_store, run) -> None:
    try:
        invocation = execution_store.load_invocation(run.invocation_id)
        context = execution_store.load_context_pack(run.context_pack_id)
        descriptor = execution_store.load_descriptor(run.descriptor_digest)
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "persisted Run execution documents failed integrity verification",
        ) from exc
    if invocation is None or context is None or descriptor is None:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "persisted Run execution documents are incomplete",
        )
    capability = invocation.get("capability")
    snapshot = context.get("pins", {}).get("research_snapshot")
    if (
        invocation.get("run_id") != run.run_id
        or invocation.get("invocation_id") != run.invocation_id
        or invocation.get("invocation_digest") != run.invocation_digest
        or invocation.get("project_id") != run.project_ref
        or invocation.get("execution_mode") != run.execution_mode
        or not isinstance(capability, Mapping)
        or capability.get("capability_id") != run.capability_id
        or capability.get("capability_version") != run.capability_version
        or capability.get("function_id") != run.function_id
        or capability.get("descriptor_digest") != run.descriptor_digest
        or context.get("context_pack_id") != run.context_pack_id
        or context.get("context_pack_digest") != run.context_pack_digest
        or not isinstance(snapshot, Mapping)
        or snapshot.get("snapshot_id") != run.snapshot_ref
        or snapshot.get("content_digest") != run.snapshot_digest
    ):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted Run execution-document bindings are inconsistent",
        )


def _validate_handoff(execution_store, run) -> None:
    try:
        handoff = canonical_handoff_for(execution_store, run.handoff_ref)
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "persisted Run Handoff failed integrity verification",
        ) from exc
    capability = handoff.get("capability") if isinstance(handoff, Mapping) else None
    if (
        not isinstance(handoff, Mapping)
        or handoff.get("handoff_id") != run.handoff_ref
        or handoff.get("handoff_digest") != run.handoff_digest
        or handoff.get("run_id") != run.run_id
        or handoff.get("invocation_id") != run.invocation_id
        or handoff.get("project_id") != run.project_ref
        or handoff.get("execution_mode") != "real"
        or not isinstance(capability, Mapping)
        or capability.get("capability_id") != run.capability_id
        or capability.get("capability_version") != run.capability_version
        or capability.get("function_id") != run.function_id
        or capability.get("descriptor_digest") != run.descriptor_digest
    ):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted Run Handoff binding does not match the producer Run",
        )


def _require_exact_current_snapshot(
    run,
    historical: Mapping[str, Any],
    *,
    project_id: str,
    lineage_ref: str,
    snapshot_id: str,
    snapshot_digest: str,
) -> None:
    if (
        run.project_ref != project_id
        or run.lineage_ref != lineage_ref
        or run.snapshot_ref != snapshot_id
        or run.snapshot_digest != snapshot_digest
        or historical.get("project_ref") != project_id
        or historical.get("lineage_ref") != lineage_ref
        or historical.get("current_snapshot_ref") != snapshot_id
        or historical.get("current_snapshot_digest") != snapshot_digest
    ):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-STALE-001",
            "Run and candidate must be bound to the exact current Research Snapshot",
        )


def _recovery_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"run_id"}:
        raise ValueError("desktop_research.finding.recover requires only run_id")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    return {"run_id": run_id}


def _recover_legacy_candidate(application, project_id: str, run_id: str) -> Mapping[str, Any]:
    try:
        run = application.execution_store.load_run(run_id)
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-RUN-001",
            "persisted Run could not be read",
        ) from exc
    if run is None:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-RUN-001", "unknown Run"
        )
    if (
        run.project_ref != project_id
        or run.capability_id != "desktop-research"
        or run.function_id != "investigate"
        or run.execution_mode != "real"
        or run.status != RunStatus.COMPLETED
        or run.handoff_ref is None
        or run.handoff_digest is None
    ):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-RUN-001",
            "Run is not an eligible completed REAL Desktop Research investigate Run",
        )
    _validate_run_documents(application.execution_store, run)
    _validate_handoff(application.execution_store, run)

    repository = application.state_repository
    lineage_ref = repository.load_active_lineage_ref(project_id)
    state = repository.load_state_view(project_id, lineage_ref)
    snapshot = state.current_snapshot
    snapshot_id = str(snapshot["id"])
    snapshot_digest = str(snapshot["content_digest"])
    store = application.conversation_store
    try:
        matches = find_state_delta_proposals_by_provenance_run_id(
            store, run_id, limit=3
        )
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "persisted Run-derived candidate is unreadable",
        ) from exc
    if len(matches) != 1:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "completed Run must resolve to exactly one persisted candidate",
        )
    historical = deepcopy(dict(matches[0]))
    declared_digest = historical.get("proposal_digest")
    if not isinstance(declared_digest, str) or declared_digest != _proposal_digest(historical):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "persisted candidate digest is invalid",
        )
    provenance = historical.get("provenance")
    if not isinstance(provenance, Mapping) or (
        provenance.get("run_id") != run_id
        or provenance.get("implementation_id") != run.implementation_id
        or provenance.get("implementation_version") != run.implementation_version
        or provenance.get("execution_mode") != "real"
        or not isinstance(provenance.get("desktop_research"), Mapping)
    ):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted candidate provenance does not match the producer Run",
        )
    _require_exact_current_snapshot(
        run,
        historical,
        project_id=project_id,
        lineage_ref=lineage_ref,
        snapshot_id=snapshot_id,
        snapshot_digest=snapshot_digest,
    )
    if (
        historical.get("candidate_only") is not True
        or historical.get("source_refs") != [run.handoff_ref]
        or historical.get("required_human_decision_kinds") != ["research_adoption"]
    ):
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-BINDING-001",
            "persisted candidate binding is not eligible for exact recovery",
        )

    recovered_actions = _legacy_actions(historical, run.handoff_ref, project_id)
    recovered = deepcopy(historical)
    recovered["proposal_id"] = _fresh_proposal_id(run_id, declared_digest)
    recovered["proposed_actions"] = recovered_actions
    recovered["provenance"] = deepcopy(dict(provenance))
    recovered["provenance"]["legacy_recovery"] = {
        "contract": _RECOVERY_VERSION,
        "source_proposal_id": historical["proposal_id"],
        "source_proposal_digest": declared_digest,
    }
    recovered.pop("proposal_digest", None)
    recovered["proposal_digest"] = _proposal_digest(recovered)

    prior = store.load_state_delta_proposal(recovered["proposal_id"])
    if prior is not None and prior != recovered:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "recovery candidate identity collides with different persisted content",
        )
    try:
        with guard_research_state_head(
            repository,
            project_id,
            lineage_ref=lineage_ref,
            snapshot_ref=snapshot_id,
            snapshot_digest=snapshot_digest,
        ):
            store.store_state_delta_proposal(recovered["proposal_id"], recovered)
    except StaleHeadError as exc:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-STALE-001",
            "Research State changed before recovery candidate persistence",
        ) from exc
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "recovery candidate could not be persisted immutably",
        ) from exc

    return {
        "status": "RECOVERED",
        "project_id": project_id,
        "run_id": run_id,
        "historical_proposal_id": historical["proposal_id"],
        "historical_proposal_digest": declared_digest,
        "state_delta_proposal_id": recovered["proposal_id"],
        "state_delta_proposal_digest": recovered["proposal_digest"],
        "lineage_ref": lineage_ref,
        "snapshot_id": snapshot_id,
        "snapshot_digest": snapshot_digest,
        "idempotent_reuse": prior is not None,
        "research_state_mutation_performed": False,
    }


class LegacyFindingRecoveryHandler:
    def __init__(self, application, project_id: str) -> None:
        self._application = application
        self._project_id = project_id

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        state: Any,
        actor: Any,
        proposal: Mapping[str, Any],
    ) -> HarnessServiceResult:
        del state, actor, proposal
        result = _recover_legacy_candidate(
            self._application, self._project_id, str(payload["run_id"])
        )
        return HarnessServiceResult(
            result_reference=str(result["state_delta_proposal_id"]),
            data=result,
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public bounded recovery for immutable pre-#139 Desktop Research candidates."""

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_finding_recovery_action()
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_finding_recovery_action()
        return super().submit_action(draft_input)

    def recover_legacy_desktop_research_finding_candidate(
        self, run_id: str
    ) -> Mapping[str, Any]:
        return _recover_legacy_candidate(self._application, self._project_id, run_id)

    def _ensure_finding_recovery_action(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
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
                        payload_validator=_recovery_payload,
                    )
                )
            elif (
                definition.payload_contract != _PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _ACTION_TYPE
            ):
                raise RuntimeError(
                    "desktop_research.finding.recover action registration conflict"
                )
            try:
                service_registry.resolve(_ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _ACTION_TYPE,
                    LegacyFindingRecoveryHandler(self._application, self._project_id),
                )
