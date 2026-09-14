from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.execution import RunStatus

from . import finding_recovery_facade as _base
from .facade import LocalApplicationError
from .finding_recovery_lineage import RecoveryFailure, proposal_matches, resolve_replay_child


def _eligible_completed_desktop_run(application, project_id: str, run_id: str):
    try:
        run = application.execution_store.load_run(run_id)
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-RUN-001",
            "persisted Run could not be read",
            stage="run_eligibility",
            failure_class="run_unreadable",
        ) from exc
    if run is None:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-RUN-001",
            "unknown Run",
            stage="run_eligibility",
            failure_class="run_not_found",
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
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-RUN-001",
            "Run is not an eligible completed REAL Desktop Research investigate Run",
            stage="run_eligibility",
            failure_class="run_ineligible",
        )
    try:
        _base._validate_run_documents(application.execution_store, run)
        _base._validate_handoff(application.execution_store, run)
    except LocalApplicationError as exc:
        raise RecoveryFailure(
            exc.code,
            exc.message,
            stage="run_handoff_validation",
            failure_class="run_handoff_provenance_mismatch",
        ) from exc
    return run


def _current_binding(application, project_id: str) -> tuple[str, str, str]:
    try:
        repository = application.state_repository
        lineage_ref = repository.load_active_lineage_ref(project_id)
        state = repository.load_state_view(project_id, lineage_ref)
        snapshot = state.current_snapshot
        return lineage_ref, str(snapshot["id"]), str(snapshot["content_digest"])
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-STALE-001",
            "current Research State binding could not be verified",
            stage="state_binding",
            failure_class="state_binding_mismatch",
        ) from exc


def _require_requested_current(
    requested_run,
    *,
    project_id: str,
    lineage_ref: str,
    snapshot_id: str,
    snapshot_digest: str,
) -> None:
    if (
        requested_run.project_ref != project_id
        or requested_run.lineage_ref != lineage_ref
        or requested_run.snapshot_ref != snapshot_id
        or requested_run.snapshot_digest != snapshot_digest
    ):
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-STALE-001",
            "requested historical Run is not bound to the exact current Research Snapshot",
            stage="state_binding",
            failure_class="state_binding_mismatch",
        )


def _inspect_historical_candidate(
    application,
    project_id: str,
    requested_run,
    producer_run,
    historical: Mapping[str, Any],
) -> tuple[str, str, str]:
    lineage_ref, snapshot_id, snapshot_digest = _current_binding(application, project_id)
    _require_requested_current(
        requested_run,
        project_id=project_id,
        lineage_ref=lineage_ref,
        snapshot_id=snapshot_id,
        snapshot_digest=snapshot_digest,
    )
    declared_digest = historical.get("proposal_digest")
    if not isinstance(declared_digest, str) or declared_digest != _base._proposal_digest(historical):
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-INTEGRITY-001",
            "persisted candidate digest is invalid",
            stage="candidate_integrity",
            failure_class="candidate_integrity_failure",
        )
    provenance = historical.get("provenance")
    if not isinstance(provenance, Mapping) or (
        provenance.get("run_id") != producer_run.run_id
        or provenance.get("implementation_id") != producer_run.implementation_id
        or provenance.get("implementation_version") != producer_run.implementation_version
        or provenance.get("execution_mode") != "real"
        or not isinstance(provenance.get("desktop_research"), Mapping)
    ):
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted candidate provenance does not match the producer Run",
            stage="candidate_provenance",
            failure_class="run_handoff_provenance_mismatch",
        )
    try:
        _base._require_exact_current_snapshot(
            producer_run,
            historical,
            project_id=project_id,
            lineage_ref=lineage_ref,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
        )
    except LocalApplicationError as exc:
        raise RecoveryFailure(
            exc.code,
            exc.message,
            stage="state_binding",
            failure_class="state_binding_mismatch",
        ) from exc
    if (
        historical.get("candidate_only") is not True
        or historical.get("source_refs") != [producer_run.handoff_ref]
        or historical.get("required_human_decision_kinds") != ["research_adoption"]
    ):
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-BINDING-001",
            "persisted candidate binding is not eligible for exact recovery",
            stage="candidate_binding",
            failure_class="run_handoff_provenance_mismatch",
        )
    try:
        _base._legacy_actions(historical, str(producer_run.handoff_ref), project_id)
    except LocalApplicationError as exc:
        raise RecoveryFailure(
            exc.code,
            exc.message,
            stage="candidate_shape",
            failure_class=(
                "candidate_shape_not_recoverable"
                if exc.code == "APPLICATION-FINDING-RECOVERY-SHAPE-001"
                else "run_handoff_provenance_mismatch"
            ),
        ) from exc
    return lineage_ref, snapshot_id, snapshot_digest


def _resolve_candidate(application, project_id: str, run_id: str):
    requested_run = _eligible_completed_desktop_run(application, project_id, run_id)
    matches = proposal_matches(application.conversation_store, requested_run.run_id)
    if len(matches) > 1:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "completed Run resolves to multiple persisted candidates",
            stage="producer_candidate_lookup",
            failure_class="multiple_producer_candidates",
        )
    if len(matches) == 1:
        historical = deepcopy(dict(matches[0]))
        _inspect_historical_candidate(
            application, project_id, requested_run, requested_run, historical
        )
        return requested_run, requested_run, historical, "exact_run"

    producer_run, historical = resolve_replay_child(application, requested_run)
    producer_run = _eligible_completed_desktop_run(
        application, project_id, producer_run.run_id
    )
    _inspect_historical_candidate(
        application, project_id, requested_run, producer_run, historical
    )
    return requested_run, producer_run, historical, "replay_child"


def _diagnose(application, project_id: str, run_id: str) -> Mapping[str, Any]:
    try:
        requested_run, producer_run, historical, relation = _resolve_candidate(
            application, project_id, run_id
        )
    except RecoveryFailure as exc:
        return {
            "status": "NOT_RECOVERABLE",
            "stage": exc.stage,
            "failure_class": exc.failure_class,
            "code": exc.code,
            "message": exc.message,
            "requested_run_id": run_id,
            "producer_run_id": None,
            "producer_relation": None,
            "research_state_mutation_performed": False,
        }
    return {
        "status": "RECOVERABLE",
        "stage": "ready",
        "failure_class": None,
        "code": None,
        "message": "persisted historical candidate is eligible for #142 recovery",
        "requested_run_id": requested_run.run_id,
        "producer_run_id": producer_run.run_id,
        "producer_relation": relation,
        "historical_proposal_id": historical["proposal_id"],
        "historical_proposal_digest": historical["proposal_digest"],
        "research_state_mutation_performed": False,
    }


def _recover(application, project_id: str, run_id: str) -> Mapping[str, Any]:
    requested_run, producer_run, _historical, relation = _resolve_candidate(
        application, project_id, run_id
    )
    recovered = dict(
        _base._recover_legacy_candidate(application, project_id, producer_run.run_id)
    )
    recovered["run_id"] = requested_run.run_id
    recovered["producer_run_id"] = producer_run.run_id
    recovered["producer_relation"] = relation
    return recovered


class HistoricalFindingRecoveryHandler:
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
        result = _recover(self._application, self._project_id, str(payload["run_id"]))
        return HarnessServiceResult(
            result_reference=str(result["state_delta_proposal_id"]),
            data=result,
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(_base.LocalApplicationFacade):
    """#142 recovery plus bounded diagnosis and persisted direct-replay compatibility."""

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        result = deepcopy(dict(super().show_run(run_id)))
        run = result.get("run")
        if (
            isinstance(run, Mapping)
            and run.get("capability_id") == "desktop-research"
            and run.get("function_id") == "investigate"
            and run.get("execution_mode") == "real"
            and run.get("status") == RunStatus.COMPLETED.value
        ):
            result["finding_recovery"] = _diagnose(
                self._application, self._project_id, run_id
            )
        return result

    def recover_legacy_desktop_research_finding_candidate(
        self, run_id: str
    ) -> Mapping[str, Any]:
        return _recover(self._application, self._project_id, run_id)

    def _ensure_finding_recovery_action(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _base._ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
            definition = existing.get(_base._ACTION_TYPE)
            if definition is None:
                action_registry.register(
                    ActionDefinition(
                        _base._ACTION_TYPE,
                        _base._PAYLOAD_CONTRACT,
                        "read_only",
                        "harness_service",
                        False,
                        human_decision_required=False,
                        service_id=_base._ACTION_TYPE,
                        payload_validator=_base._recovery_payload,
                    )
                )
            elif (
                definition.payload_contract != _base._PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _base._ACTION_TYPE
            ):
                raise RuntimeError(
                    "desktop_research.finding.recover action registration conflict"
                )
            try:
                service_registry.resolve(_base._ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _base._ACTION_TYPE,
                    HistoricalFindingRecoveryHandler(
                        self._application, self._project_id
                    ),
                )
