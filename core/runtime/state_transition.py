from __future__ import annotations

from typing import Iterable

from .ports import (
    AtomicCommitError,
    IdempotencyConflictError,
    ResearchStateRepository,
    StaleHeadError,
    StatePolicyValidator,
    StateSchemaValidator,
)
from .state_reducer import ReductionError, reduce_state
from .transition_models import (
    CommitBundle,
    CommitReceipt,
    StateTransitionRejected,
    StateTransitionRequest,
    ValidationIssue,
    ValidationStage,
)
from .validation import validate_commit_bundle, validate_post_reduction, validate_pre_reduction


class StateTransitionService:
    """Only runtime write boundary for authoritative Research State.

    The service validates pinned input state, invokes the pure reducer, validates
    the proposed next state, prepares one storage-neutral CommitBundle and makes
    exactly one repository commit call. Rejections perform no repository writes.
    """

    def __init__(
        self,
        repository: ResearchStateRepository,
        *,
        schema_validator: StateSchemaValidator,
        policy_validators: Iterable[StatePolicyValidator] = (),
    ) -> None:
        self._repository = repository
        self._schema_validator = schema_validator
        self._policy_validators = tuple(policy_validators)

    def apply(self, request: StateTransitionRequest) -> CommitReceipt | StateTransitionRejected:
        # Fail closed before treating an idempotency key as a replay token. A
        # modified request may never retrieve a prior successful receipt.
        if request.request_digest != request.calculated_digest():
            return _reject(
                request,
                ValidationIssue(
                    error_code="RT-PIN-001",
                    stage=ValidationStage.PINS,
                    message="StateTransitionRequest digest does not match the pinned request payload.",
                    affected_refs=(request.transition_id,),
                ),
            )

        schema_issues = self._schema_validator.validate_request(request)
        if schema_issues:
            return StateTransitionRejected(transition_id=request.transition_id, issues=schema_issues)

        prior = self._repository.find_commit_by_idempotency_key(request.idempotency_key)
        if prior is not None:
            prior_digest, prior_receipt = prior
            if prior_digest == request.request_digest:
                return prior_receipt
            return _reject(
                request,
                ValidationIssue(
                    error_code="RT-IDEMPOTENCY-001",
                    stage=ValidationStage.PINS,
                    message="Idempotency key was already committed with a different request digest.",
                    affected_refs=(request.idempotency_key,),
                ),
            )

        current_state = self._repository.load_state_view(request.project_ref, request.lineage_ref)
        issues = list(validate_pre_reduction(current_state, request))
        if issues:
            return _rejected_with_head(request, current_state, issues)

        try:
            reduction = reduce_state(current_state, request)
        except ReductionError as exc:
            return _rejected_with_head(
                request,
                current_state,
                [ValidationIssue("RT-REDUCE-001", ValidationStage.NEXT_STATE, str(exc))],
            )

        issues = list(self._schema_validator.validate_reduction(reduction))
        issues.extend(validate_post_reduction(current_state, request, reduction))
        for validator in self._policy_validators:
            issues.extend(validator.validate(current_state, request, reduction))
        if issues:
            return _rejected_with_head(request, current_state, issues)

        bundle = CommitBundle(
            transition_id=request.transition_id,
            commit_id=request.commit_id,
            project_ref=request.project_ref,
            lineage_ref=request.lineage_ref,
            idempotency_key=request.idempotency_key,
            request_digest=request.request_digest,
            previous_snapshot_ref=str(current_state.current_snapshot["id"]),
            previous_snapshot_digest=str(current_state.current_snapshot["content_digest"]),
            object_revisions=reduction.object_revisions,
            decision_records=reduction.decision_records,
            new_snapshot=reduction.new_snapshot,
            lineage_updates=reduction.lineage_updates,
            new_lineages=reduction.new_lineages,
            active_lineage_update=reduction.active_lineage_update,
            adoption_refs=reduction.adoption_refs,
            audit_events=reduction.audit_events,
            used_decision_refs=reduction.used_decision_refs,
            applied_actions=reduction.applied_actions,
        ).with_digest_and_receipt(request)
        bundle_issues = validate_commit_bundle(bundle)
        if bundle_issues:
            return _rejected_with_head(request, current_state, bundle_issues)

        try:
            return self._repository.commit(
                bundle,
                expected_head_snapshot_digest=request.expected_head_snapshot_digest,
            )
        except StaleHeadError as exc:
            # Covers the race between StateView load and atomic commit check.
            fresh = self._repository.load_state_view(request.project_ref, request.lineage_ref)
            return _rejected_with_head(
                request,
                fresh,
                [ValidationIssue(
                    "RT-HEAD-002",
                    ValidationStage.PERSISTENCE,
                    str(exc) or "Research Lineage HEAD changed before atomic commit.",
                    retryable=True,
                )],
            )
        except IdempotencyConflictError as exc:
            return _rejected_with_head(
                request,
                current_state,
                [ValidationIssue("RT-IDEMPOTENCY-002", ValidationStage.PERSISTENCE, str(exc))],
            )
        except AtomicCommitError as exc:
            return _rejected_with_head(
                request,
                current_state,
                [ValidationIssue("RT-PERSIST-001", ValidationStage.PERSISTENCE, str(exc))],
            )


def _reject(request: StateTransitionRequest, issue: ValidationIssue) -> StateTransitionRejected:
    return StateTransitionRejected(transition_id=request.transition_id, issues=(issue,))


def _rejected_with_head(
    request: StateTransitionRequest,
    current_state,
    issues,
) -> StateTransitionRejected:
    ordered = tuple(sorted(issues, key=lambda item: (item.stage.value, item.error_code, item.message)))
    return StateTransitionRejected(
        transition_id=request.transition_id,
        issues=ordered,
        current_head_snapshot_ref=str(current_state.current_snapshot.get("id")),
        current_head_snapshot_digest=str(current_state.current_snapshot.get("content_digest")),
    )
