from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .transition_models import ReductionResult, StateTransitionRequest, StateView, TransitionKind, ValidationIssue, ValidationStage, canonical_digest
from ._validation_common import _issue, _dedupe_issues, _snapshot_digest
from .authority_validation import _decision_pool, _decision_refs_for_object, _decision_subject_matches

_TEXT_FIELDS = ("text", "statement", "summary", "conclusion", "warrant", "instruction", "reason", "objective")

def _validate_reference_integrity(current_state: StateView, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    effective = _effective_object_map(current_state, reduction.object_revisions)
    for obj in effective.values():
        for expected_kind, object_id in _references_from_object(obj):
            if expected_kind == "*":
                if not any(key[1] == object_id for key in effective):
                    issues.append(_issue("RT-REF-001", ValidationStage.REFERENCE_INTEGRITY, "Referenced object ID does not resolve.", (object_id,)))
            elif (expected_kind, object_id) not in effective:
                issues.append(_issue(
                    "RT-REF-001",
                    ValidationStage.REFERENCE_INTEGRITY,
                    f"Referenced {expected_kind}:{object_id} does not resolve in the proposed state.",
                    (object_id,),
                ))
    return _dedupe_issues(issues)


def _validate_core_invariants(current_state: StateView, request: StateTransitionRequest, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    effective = _effective_object_map(current_state, reduction.object_revisions)
    for obj in effective.values():
        kind = obj.get("kind")
        if kind == "evidence":
            if not obj.get("source_id") or not obj.get("locator"):
                issues.append(_issue("RT-CORE-TRACE-001", ValidationStage.CORE_INVARIANTS, "Evidence must retain Source and exact locator.", (str(obj.get("id", "")),)))
        elif kind == "finding" and not obj.get("question_ids"):
            issues.append(_issue("RT-CORE-TRACE-002", ValidationStage.CORE_INVARIANTS, "Finding must remain bound to at least one Research Question.", (str(obj.get("id", "")),)))
        elif kind == "argument" and not obj.get("finding_ids") and not obj.get("evidence_ids"):
            issues.append(_issue("RT-CORE-TRACE-003", ValidationStage.CORE_INVARIANTS, "Argument must remain supported by Finding or Evidence.", (str(obj.get("id", "")),)))
        elif kind == "recommendation" and not obj.get("finding_ids"):
            issues.append(_issue("RT-CORE-TRACE-004", ValidationStage.CORE_INVARIANTS, "Recommendation must remain downstream of at least one Finding.", (str(obj.get("id", "")),)))
        elif kind == "artifact":
            if obj.get("artifact_class") in {"generated", "published"} and not obj.get("source_snapshot_id"):
                issues.append(_issue("RT-CORE-PROV-001", ValidationStage.CORE_INVARIANTS, "Generated/published Artifact must reference an immutable Research Snapshot."))
            if obj.get("lane") == "publication" and obj.get("evidence_eligible") is not False:
                issues.append(_issue("RT-CORE-FW-001", ValidationStage.CORE_INVARIANTS, "Publication artifacts are never eligible as Research Evidence."))
    for obj in reduction.object_revisions:
        existing = current_state.exact_object(str(obj.get("kind", "")), str(obj.get("id", "")), int(obj.get("revision", -1)))
        if existing is not None and canonical_digest(existing) != canonical_digest(obj):
            issues.append(_issue(
                "RT-CORE-PROV-002",
                ValidationStage.CORE_INVARIANTS,
                "An existing immutable object revision cannot be replaced with different content.",
                (str(obj.get("id", "")),),
            ))
    return issues


def _validate_profile_strengthening(current_state: StateView, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    constraints = current_state.effective_constraints
    if constraints.get("weakens_core") or constraints.get("core_override_requests"):
        issues.append(_issue(
            "RT-PROFILE-001",
            ValidationStage.PROFILE_CONSTRAINTS,
            "Effective Profile Set attempts to weaken/override a non-overridable Core invariant.",
        ))
    required_fields = constraints.get("required_fields_by_kind", {})
    if isinstance(required_fields, Mapping):
        for obj in reduction.object_revisions:
            fields = required_fields.get(obj.get("kind"), ())
            if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
                missing = [field for field in fields if not obj.get(field)]
                if missing:
                    issues.append(_issue(
                        "RT-PROFILE-002",
                        ValidationStage.PROFILE_CONSTRAINTS,
                        f"Resolved Profile strengthening requires fields: {', '.join(map(str, missing))}.",
                        (str(obj.get("id", "")),),
                    ))
    return issues


def _validate_project_guards(current_state: StateView, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    constraints = current_state.project_config.get("project_constraints", {}) if isinstance(current_state.project_config, Mapping) else {}
    guards = constraints.get("must_not_claim", ()) if isinstance(constraints, Mapping) else ()
    forbidden: list[tuple[str, str]] = []
    if isinstance(guards, Sequence) and not isinstance(guards, (str, bytes)):
        for guard in guards:
            if isinstance(guard, Mapping) and guard.get("statement"):
                forbidden.append((str(guard.get("guard_id", "guard")), str(guard["statement"])))
    for obj in reduction.object_revisions:
        text = "\n".join(str(obj[field]) for field in _TEXT_FIELDS if obj.get(field))
        for guard_id, statement in forbidden:
            if statement and statement in text:
                issues.append(_issue(
                    "RT-PROJECT-001",
                    ValidationStage.PROJECT_GUARDS,
                    "Proposed authoritative state contains a literal Project must-not-claim guard statement.",
                    (guard_id, str(obj.get("id", ""))),
                ))
    return issues


def _validate_adoption_boundaries(current_state: StateView, request: StateTransitionRequest, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for action in request.actions:
        if action.payload.get("direct_handoff_mutation") is True:
            issues.append(_issue(
                "RT-BOUNDARY-001",
                ValidationStage.ADOPTION_BOUNDARIES,
                "Capability Handoff must be normalized to StateDeltaProposal and typed transitions before the reducer boundary.",
            ))
        if action.payload.get("direct_writer_feedback_mutation") is True:
            issues.append(_issue(
                "RT-BOUNDARY-002",
                ValidationStage.ADOPTION_BOUNDARIES,
                "Writing Feedback is proposal material and cannot directly mutate Research State.",
            ))
    return issues


def _validate_lineage_postconditions(current_state: StateView, request: StateTransitionRequest, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for action in request.actions:
        if action.kind == TransitionKind.APPLY_LINEAGE_PLAN:
            parent_before = current_state.lineage(request.lineage_ref)
            parent_after = next((item for item in reduction.lineage_updates if item.lineage_id == request.lineage_ref), parent_before)
            if parent_before is not None and parent_after is not None:
                if parent_after.head_snapshot_ref != parent_before.head_snapshot_ref or parent_after.head_snapshot_digest != parent_before.head_snapshot_digest:
                    issues.append(_issue(
                        "RT-LINEAGE-011",
                        ValidationStage.LINEAGE,
                        "Fork/Recovery creation must not move the parent lineage head.",
                        (request.lineage_ref,),
                    ))
            target = str(action.payload.get("target_lineage_id", ""))
            if not any(lineage.lineage_id == target for lineage in reduction.new_lineages):
                issues.append(_issue("RT-LINEAGE-012", ValidationStage.LINEAGE, "Lineage plan did not create its declared child lineage.", (target,)))
    return issues


def _validate_epistemic_postconditions(current_state: StateView, request: StateTransitionRequest, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for obj in reduction.object_revisions:
        if obj.get("kind") != "evidence":
            continue
        prior = current_state.latest_object("evidence", str(obj.get("id", "")))
        if prior is None:
            continue
        if prior.get("evidence_mode") == "synthetic" and obj.get("evidence_mode") != "synthetic":
            issues.append(_issue("RT-EPI-005", ValidationStage.EPISTEMIC_FIREWALL, "Synthetic Evidence mode is immutable across revisions.", (str(obj.get("id", "")),)))
        old_limitations = set(prior.get("limitations", ()) or ())
        new_limitations = set(obj.get("limitations", ()) or ())
        if old_limitations - new_limitations:
            decision_pool = _decision_pool(current_state, request)
            refs = _decision_refs_for_object(request, "evidence", str(obj.get("id", "")))
            has_revision = any(
                (decision := decision_pool.get(ref)) is not None
                and decision.get("actor_type") == "human"
                and decision.get("decision_kind") == "research_revision"
                and decision.get("choice") == "revise"
                and _decision_subject_matches(decision, "evidence", str(obj.get("id", "")))
                for ref in refs
            )
            if not has_revision:
                issues.append(_issue(
                    "RT-EPI-006",
                    ValidationStage.EPISTEMIC_FIREWALL,
                    "Recorded Evidence limitations cannot be silently erased.",
                    (str(obj.get("id", "")),),
                ))
    return issues


def _validate_next_state(current_state: StateView, reduction: ReductionResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if reduction.new_snapshot is not None:
        snapshot = reduction.new_snapshot
        if current_state.latest_object("snapshot", str(snapshot.get("id", ""))) is not None or str(snapshot.get("id", "")) == current_state.current_snapshot.get("id"):
            issues.append(_issue(
                "RT-STATE-001",
                ValidationStage.NEXT_STATE,
                "Snapshot identity may not be reused.",
                (str(snapshot.get("id", "")),),
            ))
        members = snapshot.get("members", ())
        seen: set[tuple[str, str, int]] = set()
        effective = _object_revision_map(current_state.objects, reduction.object_revisions)
        for member in members:
            key = (str(member.get("kind", "")), str(member.get("id", "")), int(member.get("revision", -1)))
            if key in seen:
                issues.append(_issue("RT-STATE-002", ValidationStage.NEXT_STATE, "Snapshot contains duplicate object revision membership.", (key[1],)))
            seen.add(key)
            obj = effective.get(key)
            if obj is None:
                issues.append(_issue("RT-STATE-003", ValidationStage.NEXT_STATE, "Snapshot member does not resolve to an exact immutable object revision.", (key[1],)))
            elif member.get("digest") != canonical_digest(obj):
                issues.append(_issue("RT-STATE-004", ValidationStage.NEXT_STATE, "Snapshot member digest does not match the exact object revision.", (key[1],)))
        if snapshot.get("content_digest") != _snapshot_digest(snapshot):
            issues.append(_issue("RT-STATE-005", ValidationStage.NEXT_STATE, "Snapshot content digest is not canonical/deterministic.", (str(snapshot.get("id", "")),)))
    return issues


def _references_from_object(obj: Mapping[str, Any]) -> Iterable[tuple[str, str]]:
    kind = obj.get("kind")
    project_id = obj.get("project_id")
    if project_id:
        yield ("project", str(project_id))
    if kind == "research_question" and obj.get("parent_question_id"):
        yield ("research_question", str(obj["parent_question_id"]))
    elif kind == "claim":
        if obj.get("question_id"):
            yield ("research_question", str(obj["question_id"]))
        yield from _ids("evidence", obj.get("supporting_evidence_ids"))
        yield from _ids("evidence", obj.get("challenging_evidence_ids"))
    elif kind == "method":
        yield from _ids("research_question", obj.get("question_ids"))
    elif kind == "evidence" and obj.get("source_id"):
        yield ("source", str(obj["source_id"]))
    elif kind == "analysis":
        yield from _ids("research_question", obj.get("question_ids"))
        if obj.get("method_id"):
            yield ("method", str(obj["method_id"]))
        yield from _ids("evidence", obj.get("evidence_ids"))
    elif kind == "finding":
        yield from _ids("research_question", obj.get("question_ids"))
        yield from _ids("evidence", obj.get("evidence_ids"))
        yield from _ids("analysis", obj.get("analysis_ids"))
        yield from _ids("evidence", obj.get("counter_evidence_ids"))
    elif kind == "counter_review":
        target = obj.get("target")
        if isinstance(target, Mapping) and target.get("kind") and target.get("id"):
            yield (str(target["kind"]), str(target["id"]))
        yield from _ids("evidence", obj.get("evidence_ids"))
    elif kind == "argument":
        yield from _ids("research_question", obj.get("question_ids"))
        if obj.get("conclusion_claim_id"):
            yield ("claim", str(obj["conclusion_claim_id"]))
        yield from _ids("claim", obj.get("premise_claim_ids"))
        yield from _ids("finding", obj.get("finding_ids"))
        yield from _ids("evidence", obj.get("evidence_ids"))
        yield from _ids("counter_review", obj.get("counter_review_ids"))
    elif kind == "contribution":
        yield from _ids("finding", obj.get("finding_ids"))
    elif kind == "recommendation":
        yield from _ids("finding", obj.get("finding_ids"))
    elif kind == "next_action":
        target = obj.get("target")
        if isinstance(target, Mapping) and target.get("kind") and target.get("id"):
            yield (str(target["kind"]), str(target["id"]))
        yield from _ids("*", obj.get("blocked_by"))
    elif kind == "decision":
        for subject in obj.get("subjects", ()) or ():
            if isinstance(subject, Mapping) and subject.get("kind") and subject.get("id"):
                if subject.get("kind") in {
                    "project", "research_question", "claim", "method", "source", "evidence", "analysis", "finding",
                    "counter_review", "argument", "contribution", "recommendation", "next_action", "artifact", "snapshot", "decision"
                }:
                    yield (str(subject["kind"]), str(subject["id"]))
    elif kind == "artifact" and obj.get("source_snapshot_id"):
        yield ("snapshot", str(obj["source_snapshot_id"]))


def _ids(kind: str, value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield (kind, str(item))


def _effective_object_map(current_state: StateView, new_revisions: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {
        (str(obj["kind"]), str(obj["id"])): obj for obj in current_state.effective_objects()
    }
    for obj in new_revisions:
        result[(str(obj.get("kind", "")), str(obj.get("id", "")))] = obj
    return result


def _object_revision_map(
    existing: Sequence[Mapping[str, Any]],
    new_revisions: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, int], Mapping[str, Any]]:
    result: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for obj in (*existing, *new_revisions):
        result[(str(obj.get("kind", "")), str(obj.get("id", "")), int(obj.get("revision", -1)))] = obj
    return result
