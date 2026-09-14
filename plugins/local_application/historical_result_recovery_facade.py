from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.runtime import canonical_digest
from core.runtime.ports import StaleHeadError
from plugins.desktop_research import DesktopResearchNormalizer
from plugins.desktop_research.attempts import reconstruct_attempts
from plugins.local_conversation_store import persist_state_delta_proposal_idempotently
from plugins.local_execution_store import canonical_handoff_for, result_extensions_for_run
from plugins.sqlite_state_store.exhibit_guard import guard_research_state_head

from . import finding_recovery_facade as _recovery_base
from . import historical_finding_recovery_facade as _base
from .facade import _jsonable
from .finding_recovery_lineage import RecoveryFailure


_REMATERIALIZATION_VERSION = "historical-desktop-result-rematerialization@0.1.0"


def _recovery_proposal_id(run_id: str, source_digest: str) -> str:
    token = hashlib.sha256(
        f"{_REMATERIALIZATION_VERSION}:{run_id}:{source_digest}".encode("utf-8")
    ).hexdigest()[:24]
    return f"SDP-HGR-{token}"


def _current_context(application, project_id: str) -> dict[str, str]:
    lineage_ref, snapshot_id, snapshot_digest = _base._current_binding(
        application, project_id
    )
    return {
        "project_ref": project_id,
        "lineage_ref": lineage_ref,
        "current_snapshot_ref": snapshot_id,
        "current_snapshot_digest": snapshot_digest,
    }


def _canonical_result(application, project_id: str, run_id: str):
    run = _base._eligible_completed_desktop_run(application, project_id, run_id)
    context = _current_context(application, project_id)
    _base._require_requested_current(
        run,
        project_id=project_id,
        lineage_ref=context["lineage_ref"],
        snapshot_id=context["current_snapshot_ref"],
        snapshot_digest=context["current_snapshot_digest"],
    )
    try:
        handoff = canonical_handoff_for(application.execution_store, str(run.handoff_ref))
        extensions = result_extensions_for_run(application.execution_store, run_id, limit=3)
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-RESULT-001",
            "canonical historical Desktop Research result could not be read",
            stage="canonical_result",
            failure_class="canonical_result_unreadable",
        ) from exc
    if handoff is None or len(extensions) != 1:
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-RESULT-001",
            "canonical historical Desktop Research result is incomplete or ambiguous",
            stage="canonical_result",
            failure_class="canonical_result_incomplete",
        )
    extension = deepcopy(dict(extensions[0]))
    try:
        for detail in extension.get("source_capture_details", ()):
            for key in ("original_capture", "text_rendition"):
                application.execution_store.load_artifact_verified_once(
                    str(detail[key]["content_reference"])
                )
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-MATERIAL-001",
            "required historical captured material cannot be verified through the public material boundary",
            stage="material_verification",
            failure_class="material_recovery_required",
        ) from exc

    normalizer = DesktopResearchNormalizer(
        application.execution_store,
        application.context_extension_store,
        application.execution_store,
        application.operational_store,
    )
    issues = normalizer.validate_extension(handoff, extension, context)
    if issues:
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-RESULT-001",
            "canonical historical Desktop Research result failed current normalization verification: "
            + "; ".join(issues[:5]),
            stage="canonical_result",
            failure_class="canonical_result_incomplete",
        )
    try:
        proposal = _jsonable(normalizer.normalize(handoff, extension, context))
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-RESULT-001",
            "canonical historical Desktop Research result could not be normalized",
            stage="canonical_result",
            failure_class="canonical_result_incomplete",
        ) from exc
    if not any(
        action.get("payload", {}).get("object", {}).get("kind") == "finding"
        for action in proposal.get("proposed_actions", ())
    ):
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-RESULT-001",
            "canonical result has no closed Finding candidate",
            stage="canonical_result",
            failure_class="canonical_result_incomplete",
        )
    return run, handoff, extension, proposal, context


def _replay_eligible(application, run_id: str) -> bool:
    try:
        attempts = reconstruct_attempts(application.operational_store, run_id)
        if not any(item.get("completed_at") is None for item in attempts.values()):
            return False
        correlation = application.conversation_store.load_run_correlation(run_id)
        if correlation is None:
            return False
        proposal = application.conversation_store.load_proposal(
            str(correlation["proposal_id"])
        )
    except Exception:
        return False
    return (
        isinstance(proposal, Mapping)
        and proposal.get("action", {}).get("action_type") == "desktop_research.investigate"
    )


def _classification(application, project_id: str, run_id: str) -> Mapping[str, Any]:
    try:
        requested = _base._eligible_completed_desktop_run(application, project_id, run_id)
        lineage_ref, snapshot_id, snapshot_digest = _base._current_binding(
            application, project_id
        )
        _base._require_requested_current(
            requested,
            project_id=project_id,
            lineage_ref=lineage_ref,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
        )
    except RecoveryFailure as exc:
        return _failure_classification(run_id, "not_recoverable", exc)

    try:
        requested, producer, historical, relation = _base._resolve_candidate(
            application, project_id, run_id
        )
        return {
            "recovery_class": "proposal_rematerializable",
            "route": "persisted_candidate_recovery",
            "requested_run_id": requested.run_id,
            "producer_run_id": producer.run_id,
            "producer_relation": relation,
            "historical_proposal_id": historical["proposal_id"],
            "historical_proposal_digest": historical["proposal_digest"],
            "research_state_mutation_performed": False,
        }
    except RecoveryFailure as exc:
        if exc.failure_class not in {
            "producer_candidate_not_found",
            "candidate_shape_not_recoverable",
            "multiple_producer_candidates",
        }:
            return _failure_classification(run_id, "not_recoverable", exc)

    try:
        run, handoff, extension, proposal, _context = _canonical_result(
            application, project_id, run_id
        )
        return {
            "recovery_class": "proposal_rematerializable",
            "route": "canonical_result_rematerialization",
            "requested_run_id": run.run_id,
            "source_handoff_id": handoff["handoff_id"],
            "source_handoff_digest": handoff["handoff_digest"],
            "source_extension_digest": extension["extension_digest"],
            "normalized_proposal_digest": proposal["proposal_digest"],
            "research_state_mutation_performed": False,
        }
    except RecoveryFailure as exc:
        if exc.failure_class == "material_recovery_required":
            return _failure_classification(run_id, "material_recovery_required", exc)
        if _replay_eligible(application, run_id):
            return {
                "recovery_class": "replay_required",
                "stage": "retrieval_completion",
                "failure_class": "unresolved_retrieval_work",
                "requested_run_id": run_id,
                "message": "canonical result is incomplete and bounded completed-Run replay is required",
                "research_state_mutation_performed": False,
            }
        return _failure_classification(run_id, "not_recoverable", exc)


def _failure_classification(
    run_id: str, recovery_class: str, exc: RecoveryFailure
) -> Mapping[str, Any]:
    return {
        "recovery_class": recovery_class,
        "stage": exc.stage,
        "failure_class": exc.failure_class,
        "code": exc.code,
        "message": exc.message,
        "requested_run_id": run_id,
        "research_state_mutation_performed": False,
    }


def _rematerialize(application, project_id: str, run_id: str) -> Mapping[str, Any]:
    run, handoff, extension, normalized, context = _canonical_result(
        application, project_id, run_id
    )
    recovered = deepcopy(normalized)
    normalized_digest = str(recovered["proposal_digest"])
    recovered["proposal_id"] = _recovery_proposal_id(run_id, normalized_digest)
    provenance = deepcopy(dict(recovered["provenance"]))
    provenance["historical_recovery"] = {
        "contract": _REMATERIALIZATION_VERSION,
        "classification": "historical_canonical_result_rematerialization",
        "source_run_id": run.run_id,
        "source_handoff_id": handoff["handoff_id"],
        "source_handoff_digest": handoff["handoff_digest"],
        "source_extension_digest": extension["extension_digest"],
        "verified_invocation_digest": run.invocation_digest,
        "verified_context_pack_digest": run.context_pack_digest,
        "verified_descriptor_digest": run.descriptor_digest,
    }
    recovered["provenance"] = provenance
    recovered.pop("proposal_digest", None)
    recovered["proposal_digest"] = canonical_digest(recovered)
    try:
        with guard_research_state_head(
            application.state_repository,
            project_id,
            lineage_ref=context["lineage_ref"],
            snapshot_ref=context["current_snapshot_ref"],
            snapshot_digest=context["current_snapshot_digest"],
        ):
            reused = persist_state_delta_proposal_idempotently(
                application.conversation_store, recovered["proposal_id"], recovered
            )
    except StaleHeadError as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-STALE-001",
            "Research State changed before recovery candidate persistence",
            stage="state_binding",
            failure_class="state_binding_mismatch",
        ) from exc
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-HISTORICAL-RECOVERY-INTEGRITY-001",
            "recovery candidate could not be persisted immutably",
            stage="candidate_persistence",
            failure_class="recovery_candidate_integrity",
        ) from exc
    return {
        "status": "RECOVERED",
        "recovery_class": "proposal_rematerializable",
        "route": "canonical_result_rematerialization",
        "project_id": project_id,
        "run_id": run_id,
        "state_delta_proposal_id": recovered["proposal_id"],
        "state_delta_proposal_digest": recovered["proposal_digest"],
        "source_handoff_id": handoff["handoff_id"],
        "source_handoff_digest": handoff["handoff_digest"],
        "source_extension_digest": extension["extension_digest"],
        "lineage_ref": context["lineage_ref"],
        "snapshot_id": context["current_snapshot_ref"],
        "snapshot_digest": context["current_snapshot_digest"],
        "idempotent_reuse": reused,
        "research_state_mutation_performed": False,
    }


def _recover(application, project_id: str, run_id: str) -> Mapping[str, Any]:
    classification = _classification(application, project_id, run_id)
    route = classification.get("route")
    if route == "canonical_result_rematerialization":
        return _rematerialize(application, project_id, run_id)
    if route == "persisted_candidate_recovery":
        return _base._recover(application, project_id, run_id)
    raise RecoveryFailure(
        str(classification.get("code") or "APPLICATION-HISTORICAL-RECOVERY-001"),
        str(classification.get("message") or "historical Desktop Research result is not recoverable"),
        stage=str(classification.get("stage") or "recovery_classification"),
        failure_class=str(
            classification.get("failure_class") or classification.get("recovery_class")
        ),
    )


class HistoricalResultRecoveryHandler:
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
    """#148 canonical-result rematerialization over #142/#147 recovery."""

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        result = deepcopy(dict(super().show_run(run_id)))
        diagnosis = result.get("finding_recovery")
        if not isinstance(diagnosis, Mapping):
            return result
        enriched = dict(diagnosis)
        classification = _classification(self._application, self._project_id, run_id)
        enriched["recovery_class"] = classification["recovery_class"]
        if "route" in classification:
            enriched["recovery_route"] = classification["route"]
        for key in (
            "source_handoff_id",
            "source_handoff_digest",
            "source_extension_digest",
            "normalized_proposal_digest",
        ):
            if key in classification:
                enriched[key] = classification[key]
        if classification["recovery_class"] != "proposal_rematerializable":
            enriched["recovery_stage"] = classification.get("stage")
            enriched["recovery_failure_class"] = classification.get("failure_class")
            enriched["recovery_code"] = classification.get("code")
            enriched["recovery_message"] = classification.get("message")
        result["finding_recovery"] = enriched
        return result

    def recover_legacy_desktop_research_finding_candidate(
        self, run_id: str
    ) -> Mapping[str, Any]:
        return _recover(self._application, self._project_id, run_id)

    def _ensure_finding_recovery_action(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _recovery_base._ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
            definition = existing.get(_recovery_base._ACTION_TYPE)
            if definition is None:
                action_registry.register(
                    ActionDefinition(
                        _recovery_base._ACTION_TYPE,
                        _recovery_base._PAYLOAD_CONTRACT,
                        "read_only",
                        "harness_service",
                        False,
                        human_decision_required=False,
                        service_id=_recovery_base._ACTION_TYPE,
                        payload_validator=_recovery_base._recovery_payload,
                    )
                )
            elif (
                definition.payload_contract != _recovery_base._PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _recovery_base._ACTION_TYPE
            ):
                raise RuntimeError(
                    "desktop_research.finding.recover action registration conflict"
                )
            try:
                service_registry.resolve(_recovery_base._ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _recovery_base._ACTION_TYPE,
                    HistoricalResultRecoveryHandler(
                        self._application, self._project_id
                    ),
                )
