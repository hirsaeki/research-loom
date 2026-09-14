from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError, WorkConversationValidator
from plugins.local_conversation_store import find_state_delta_proposals_by_provenance_run_id
from plugins.local_execution_store import child_runs_for_parent

from .facade import LocalApplicationError


_CONVERSATION_VALIDATOR = WorkConversationValidator()


class RecoveryFailure(LocalApplicationError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        failure_class: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message)
        self.stage = stage
        self.failure_class = failure_class
        self.details = dict(details or {})


def proposal_matches(store, run_id: str) -> tuple[Mapping[str, object], ...]:
    try:
        return find_state_delta_proposals_by_provenance_run_id(store, run_id, limit=3)
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "persisted Run-derived candidate is unreadable",
            stage="producer_candidate_lookup",
            failure_class="candidate_integrity_failure",
        ) from exc


def _validate_replay_relation(application, parent, producer) -> None:
    """Validate one explicit persisted direct replay relation; never infer it."""
    if (
        producer.parent_run_id != parent.run_id
        or producer.attempt != parent.attempt + 1
        or producer.project_ref != parent.project_ref
        or producer.lineage_ref != parent.lineage_ref
        or producer.snapshot_ref != parent.snapshot_ref
        or producer.snapshot_digest != parent.snapshot_digest
        or producer.capability_id != parent.capability_id
        or producer.capability_version != parent.capability_version
        or producer.function_id != parent.function_id
        or producer.execution_mode != parent.execution_mode
    ):
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted replay child binding does not match the requested historical Run",
            stage="producer_lineage",
            failure_class="run_handoff_provenance_mismatch",
        )
    try:
        invocation = application.execution_store.load_invocation(producer.invocation_id)
        parent_correlation = application.conversation_store.load_run_correlation(parent.run_id)
        child_correlation = application.conversation_store.load_run_correlation(producer.run_id)
        parent_proposal = (
            application.conversation_store.load_proposal(str(parent_correlation["proposal_id"]))
            if parent_correlation is not None
            else None
        )
        child_proposal = (
            application.conversation_store.load_proposal(str(child_correlation["proposal_id"]))
            if child_correlation is not None
            else None
        )
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted replay relation could not be verified",
            stage="producer_lineage",
            failure_class="legacy_replay_lineage_unresolved",
        ) from exc
    try:
        if isinstance(parent_proposal, Mapping):
            _CONVERSATION_VALIDATOR.validate(parent_proposal)
        if isinstance(child_proposal, Mapping):
            _CONVERSATION_VALIDATOR.validate(child_proposal)
    except ConversationRuntimeError as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted replay Action Proposal failed integrity verification",
            stage="producer_lineage",
            failure_class="legacy_replay_lineage_unresolved",
        ) from exc
    trace = invocation.get("trace") if isinstance(invocation, Mapping) else None
    parent_action = (
        parent_proposal.get("action") if isinstance(parent_proposal, Mapping) else None
    )
    child_action = (
        child_proposal.get("action") if isinstance(child_proposal, Mapping) else None
    )
    parent_payload = (
        parent_action.get("payload") if isinstance(parent_action, Mapping) else None
    )
    child_payload = (
        child_action.get("payload") if isinstance(child_action, Mapping) else None
    )
    expected_child_payload = (
        {**deepcopy(dict(parent_payload)), "parent_run_id": parent.run_id}
        if isinstance(parent_payload, Mapping)
        else None
    )
    if (
        not isinstance(trace, Mapping)
        or trace.get("parent_run_id") != parent.run_id
        or parent_correlation is None
        or child_correlation is None
        or not isinstance(parent_action, Mapping)
        or not isinstance(child_action, Mapping)
        or parent_action.get("action_type") != "desktop_research.investigate"
        or child_action.get("action_type") != "desktop_research.investigate"
        or not isinstance(child_payload, Mapping)
        or child_payload != expected_child_payload
    ):
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted replay relation is incomplete or inconsistent",
            stage="producer_lineage",
            failure_class="legacy_replay_lineage_unresolved",
        )


def resolve_replay_child(application, requested_run):
    """Resolve one direct replay producer using only persisted structural bindings."""
    try:
        children = child_runs_for_parent(
            application.execution_store,
            requested_run.run_id,
            limit=4,
        )
    except Exception as exc:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-PROVENANCE-001",
            "persisted replay lineage could not be read",
            stage="producer_lineage",
            failure_class="legacy_replay_lineage_unresolved",
        ) from exc
    if len(children) > 3:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "historical Run has too many replay children for bounded recovery",
            stage="producer_candidate_lookup",
            failure_class="multiple_producer_candidates",
        )

    candidates: list[tuple[Any, Mapping[str, Any]]] = []
    for child in children:
        child_matches = proposal_matches(application.conversation_store, child.run_id)
        if len(child_matches) > 1:
            raise RecoveryFailure(
                "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
                "replay child resolves to multiple persisted candidates",
                stage="producer_candidate_lookup",
                failure_class="multiple_producer_candidates",
            )
        if len(child_matches) == 1:
            candidates.append((child, deepcopy(dict(child_matches[0]))))
    if not candidates:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "completed Run has no persisted producer candidate",
            stage="producer_candidate_lookup",
            failure_class="producer_candidate_not_found",
        )
    if len(candidates) != 1:
        raise RecoveryFailure(
            "APPLICATION-FINDING-RECOVERY-CANDIDATE-001",
            "historical Run has multiple plausible replay-child producer candidates",
            stage="producer_candidate_lookup",
            failure_class="multiple_producer_candidates",
        )

    producer, historical = candidates[0]
    _validate_replay_relation(application, requested_run, producer)
    return producer, historical
