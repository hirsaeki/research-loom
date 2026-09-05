from __future__ import annotations

import re
from typing import Mapping, Sequence

from .transition_models import CommitBundle, ReductionResult, StateTransitionRequest, StateView, TransitionKind, ValidationIssue, ValidationStage
from ._validation_common import _issue, _snapshot_digest
from .authority_validation import (
    _validate_epistemic_preconditions, _validate_human_decisions, _validate_lineage_preconditions,
    required_decisions_for_action, resolving_decision_refs,
)
from .state_validation import (
    _validate_adoption_boundaries, _validate_core_invariants, _validate_epistemic_postconditions,
    _validate_lineage_postconditions, _validate_next_state, _validate_profile_strengthening,
    _validate_project_guards, _validate_reference_integrity,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

def validate_pre_reduction(current_state: StateView, request: StateTransitionRequest) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    issues.extend(_validate_schema(request))
    issues.extend(_validate_pins(current_state, request))
    issues.extend(_validate_expected_head(current_state, request))
    issues.extend(_validate_authorization(request))
    issues.extend(_validate_human_decisions(current_state, request))
    issues.extend(_validate_lineage_preconditions(current_state, request))
    issues.extend(_validate_epistemic_preconditions(current_state, request))
    return tuple(issues)


def validate_post_reduction(
    current_state: StateView,
    request: StateTransitionRequest,
    reduction: ReductionResult,
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    issues.extend(_validate_reference_integrity(current_state, reduction))
    issues.extend(_validate_core_invariants(current_state, request, reduction))
    issues.extend(_validate_profile_strengthening(current_state, reduction))
    issues.extend(_validate_resolved_profile_constraints(current_state, reduction))
    issues.extend(_validate_project_guards(current_state, reduction))
    issues.extend(_validate_adoption_boundaries(current_state, request, reduction))
    issues.extend(_validate_lineage_postconditions(current_state, request, reduction))
    issues.extend(_validate_epistemic_postconditions(current_state, request, reduction))
    issues.extend(_validate_next_state(current_state, reduction))
    return tuple(issues)


def _validate_resolved_profile_constraints(
    current_state: StateView,
    reduction: ReductionResult,
) -> list[ValidationIssue]:
    """Execute the canonical resolved Profile constraints supported at this boundary."""
    issues: list[ValidationIssue] = []
    constraint = current_state.effective_constraints.get("evidence.capture.required_fields")
    if not isinstance(constraint, Mapping):
        return issues
    required_fields = constraint.get("value", ())
    if not isinstance(required_fields, Sequence) or isinstance(required_fields, (str, bytes)):
        return issues
    for obj in reduction.object_revisions:
        if obj.get("kind") != "evidence":
            continue
        missing = [field for field in required_fields if field not in obj]
        if missing:
            issues.append(_issue(
                "RT-PROFILE-002",
                ValidationStage.PROFILE_CONSTRAINTS,
                f"Resolved Profile strengthening requires fields: {', '.join(map(str, missing))}.",
                (str(obj.get("id", "")),),
            ))
    return issues


def validate_commit_bundle(bundle: CommitBundle) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if not bundle.bundle_digest or bundle.bundle_digest != bundle.calculated_digest():
        issues.append(_issue(
            "RT-BUNDLE-001",
            ValidationStage.COMMIT_BUNDLE,
            "Commit Bundle digest does not match its canonical payload.",
            (bundle.commit_id,),
        ))
    if bundle.receipt is None:
        issues.append(_issue(
            "RT-BUNDLE-002",
            ValidationStage.COMMIT_BUNDLE,
            "Commit Bundle must carry the receipt that will be persisted atomically with it.",
            (bundle.commit_id,),
        ))
    elif bundle.receipt.bundle_digest != bundle.bundle_digest:
        issues.append(_issue(
            "RT-BUNDLE-003",
            ValidationStage.COMMIT_BUNDLE,
            "Commit Receipt is not bound to the Commit Bundle digest.",
            (bundle.commit_id,),
        ))
    if bundle.new_snapshot is not None:
        digest = _snapshot_digest(bundle.new_snapshot)
        if bundle.new_snapshot.get("content_digest") != digest:
            issues.append(_issue(
                "RT-BUNDLE-004",
                ValidationStage.COMMIT_BUNDLE,
                "New Snapshot content digest is invalid.",
                (str(bundle.new_snapshot.get("id", "")),),
            ))
    return tuple(issues)


def _validate_schema(request: StateTransitionRequest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    identifiers = {
        "transition_id": request.transition_id,
        "project_ref": request.project_ref,
        "lineage_ref": request.lineage_ref,
        "expected_head_snapshot_ref": request.expected_head_snapshot_ref,
        "project_config_ref": request.project_config_ref,
        "effective_profile_set_ref": request.effective_profile_set_ref,
        "idempotency_key": request.idempotency_key,
        "new_snapshot_id": request.new_snapshot_id,
        "commit_id": request.commit_id,
        "audit_event_id": request.audit_event_id,
        "actor_id": request.actor.actor_id,
    }
    for label, value in identifiers.items():
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            issues.append(_issue(
                "RT-SCHEMA-001",
                ValidationStage.SCHEMA,
                f"{label} is not a valid runtime identifier.",
                (str(value),),
            ))
    for label, value in {
        "expected_head_snapshot_digest": request.expected_head_snapshot_digest,
        "project_config_digest": request.project_config_digest,
        "effective_profile_set_digest": request.effective_profile_set_digest,
        "request_digest": request.request_digest,
    }.items():
        if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
            issues.append(_issue(
                "RT-SCHEMA-002",
                ValidationStage.SCHEMA,
                f"{label} must be a canonical sha256 digest.",
                (label,),
            ))
    if not request.actions:
        issues.append(_issue("RT-SCHEMA-003", ValidationStage.SCHEMA, "A state transition requires at least one typed action."))
    if not request.submitted_at:
        issues.append(_issue("RT-SCHEMA-004", ValidationStage.SCHEMA, "submitted_at must be supplied by the caller."))
    for index, action in enumerate(request.actions):
        if not isinstance(action.kind, TransitionKind):
            issues.append(_issue(
                "RT-SCHEMA-005",
                ValidationStage.SCHEMA,
                "Public state-changing actions must use the closed TransitionKind vocabulary.",
                (f"action:{index}",),
            ))
            continue
        if action.kind in {
            TransitionKind.CREATE_OBJECT,
            TransitionKind.REVISE_OBJECT,
            TransitionKind.ADOPT_OBJECT,
            TransitionKind.REJECT_OBJECT,
            TransitionKind.VERIFY_EVIDENCE,
            TransitionKind.RECLASSIFY_EVIDENCE,
            TransitionKind.RECORD_DECISION,
            TransitionKind.REGISTER_WRITING_FEEDBACK_ACTION,
        }:
            obj = action.object_payload()
            if obj is None:
                issues.append(_issue(
                    "RT-SCHEMA-006",
                    ValidationStage.SCHEMA,
                    f"{action.kind.value} requires a complete object payload; arbitrary patches are not accepted.",
                    (f"action:{index}",),
                ))
                continue
            for required in ("schema_version", "id", "kind", "revision"):
                if required not in obj:
                    issues.append(_issue(
                        "RT-SCHEMA-007",
                        ValidationStage.SCHEMA,
                        f"Object payload is missing required field {required!r}.",
                        (f"action:{index}",),
                    ))
            if obj.get("schema_version") != "0.1.0":
                issues.append(_issue(
                    "RT-SCHEMA-008",
                    ValidationStage.SCHEMA,
                    "Runtime object payloads must use the canonical Core 0.1.0 research-object schema version.",
                    (str(obj.get("id", "")),),
                ))
            if action.kind == TransitionKind.RECORD_DECISION and obj.get("kind") != "decision":
                issues.append(_issue("RT-SCHEMA-009", ValidationStage.SCHEMA, "RECORD_DECISION only accepts Core Decision objects."))
            if action.kind == TransitionKind.REGISTER_WRITING_FEEDBACK_ACTION and obj.get("kind") != "next_action":
                issues.append(_issue(
                    "RT-SCHEMA-010",
                    ValidationStage.SCHEMA,
                    "Writing Feedback may register a candidate NextAction, but cannot mutate a Finding or other research object directly.",
                    (str(obj.get("id", "")),),
                ))
            if action.kind in {TransitionKind.VERIFY_EVIDENCE, TransitionKind.RECLASSIFY_EVIDENCE} and obj.get("kind") != "evidence":
                issues.append(_issue("RT-SCHEMA-011", ValidationStage.SCHEMA, f"{action.kind.value} only accepts Evidence revisions."))
    return issues


def _validate_pins(current_state: StateView, request: StateTransitionRequest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if request.request_digest != request.calculated_digest():
        issues.append(_issue(
            "RT-PIN-001",
            ValidationStage.PINS,
            "StateTransitionRequest digest does not match the pinned request payload.",
            (request.transition_id,),
        ))
    if request.project_config_ref != current_state.project_config_ref or request.project_config_digest != current_state.project_config_digest:
        issues.append(_issue(
            "RT-PIN-002",
            ValidationStage.PINS,
            "Project Config pin is stale or mismatched.",
            (request.project_config_ref,),
            retryable=True,
        ))
    if request.effective_profile_set_ref != current_state.effective_profile_set_ref or request.effective_profile_set_digest != current_state.effective_profile_set_digest:
        issues.append(_issue(
            "RT-PIN-003",
            ValidationStage.PINS,
            "Effective Profile Set pin is stale or mismatched.",
            (request.effective_profile_set_ref,),
            retryable=True,
        ))
    if request.project_ref != current_state.project_ref or request.lineage_ref != current_state.lineage_ref:
        issues.append(_issue(
            "RT-PIN-004",
            ValidationStage.PINS,
            "Transition project/lineage binding does not match the loaded StateView.",
            (request.project_ref, request.lineage_ref),
        ))
    return issues


def _validate_expected_head(current_state: StateView, request: StateTransitionRequest) -> list[ValidationIssue]:
    head = current_state.current_snapshot_ref
    if request.expected_head_snapshot_ref != head.snapshot_id or request.expected_head_snapshot_digest != head.content_digest:
        return [_issue(
            "RT-HEAD-001",
            ValidationStage.EXPECTED_HEAD,
            "Expected Research Snapshot head is stale; automatic rebase is forbidden.",
            (request.expected_head_snapshot_ref, head.snapshot_id),
            retryable=True,
        )]
    return []


def _validate_authorization(request: StateTransitionRequest) -> list[ValidationIssue]:
    if request.actor.actor_type not in {"human", "service", "adapter", "system"}:
        return [_issue(
            "RT-AUTH-001",
            ValidationStage.AUTHORIZATION,
            "Transition actor_type is not recognized by the runtime boundary.",
            (request.actor.actor_type,),
        )]
    if request.actor.actor_type != "human" and not request.authorization_evidence:
        return [_issue(
            "RT-AUTH-002",
            ValidationStage.AUTHORIZATION,
            "Non-human state-transition callers must supply runtime authorization evidence.",
            (request.actor.actor_id,),
        )]
    return []
