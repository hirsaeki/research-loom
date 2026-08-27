from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .transition_models import (
    LineageView,
    ReductionResult,
    StateTransitionRequest,
    StateView,
    TransitionAction,
    TransitionKind,
    canonical_digest,
    stable_sorted_objects,
    with_content_digest,
)
from .validation import resolving_decision_refs


class ReductionError(RuntimeError):
    """The pure reducer could not construct a canonical next state."""


def reduce_state(current_state: StateView, request: StateTransitionRequest) -> ReductionResult:
    """Pure deterministic Research State reduction.

    RECORD_DECISION may accompany one special lineage action so the Decision and
    the action it authorizes remain in the same atomic CommitBundle. No other
    action mixing is permitted for lineage-plan or active-lineage-switch actions.
    """

    decision_actions = tuple(
        action for action in request.actions if action.kind == TransitionKind.RECORD_DECISION
    )
    semantic_actions = tuple(
        action for action in request.actions if action.kind != TransitionKind.RECORD_DECISION
    )
    lineage_actions = tuple(
        action for action in semantic_actions if action.kind == TransitionKind.APPLY_LINEAGE_PLAN
    )
    switch_actions = tuple(
        action for action in semantic_actions if action.kind == TransitionKind.SWITCH_ACTIVE_LINEAGE
    )
    if len(lineage_actions) > 1:
        raise ReductionError("one atomic transition may apply at most one lineage plan")
    if lineage_actions:
        if len(semantic_actions) != 1:
            raise ReductionError("APPLY_LINEAGE_PLAN may only be mixed with RECORD_DECISION actions")
        base = _reduce_lineage_plan(current_state, request, lineage_actions[0])
        decisions = _validated_decision_objects(current_state, decision_actions)
        return replace(
            base,
            object_revisions=stable_sorted_objects((*base.object_revisions, *decisions)),
            decision_records=stable_sorted_objects(decisions),
            applied_actions=tuple(action.kind.value for action in request.actions),
        )
    if switch_actions:
        if len(switch_actions) > 1 or len(semantic_actions) != 1:
            raise ReductionError("SWITCH_ACTIVE_LINEAGE may only be mixed with RECORD_DECISION actions")
        target = str(switch_actions[0].payload.get("target_lineage_ref", ""))
        if not target:
            raise ReductionError("active lineage switch requires target_lineage_ref")
        decisions = _validated_decision_objects(current_state, decision_actions)
        return ReductionResult(
            object_revisions=stable_sorted_objects(decisions),
            decision_records=stable_sorted_objects(decisions),
            new_snapshot=None,
            lineage_updates=(),
            new_lineages=(),
            active_lineage_update=target,
            adoption_refs=(),
            used_decision_refs=resolving_decision_refs(current_state, request),
            audit_events=(_audit_event(current_state, request),),
            applied_actions=tuple(action.kind.value for action in request.actions),
        )

    effective = _effective_members(current_state)
    new_revisions: list[Mapping[str, Any]] = []
    decisions: list[Mapping[str, Any]] = []
    adoption_refs: list[str] = []
    state_changed = False

    for action in request.actions:
        if action.kind == TransitionKind.RECORD_RUN_RESULT_ADOPTION:
            refs = action.payload.get("adoption_refs", ())
            if isinstance(refs, str) or not isinstance(refs, (list, tuple)) or not refs:
                raise ReductionError("RECORD_RUN_RESULT_ADOPTION requires non-empty adoption_refs")
            adoption_refs.extend(str(ref) for ref in refs)
            state_changed = True
            continue

        obj = action.object_payload()
        if obj is None:
            raise ReductionError(f"{action.kind.value} requires a complete object payload")
        obj = dict(obj)
        _validate_action_object_semantics(action, obj)
        prior = current_state.latest_object(str(obj.get("kind", "")), str(obj.get("id", "")))
        _validate_revision_semantics(action, obj, prior)

        if action.kind == TransitionKind.RECORD_DECISION:
            decisions.append(obj)
        new_revisions.append(obj)
        effective[(str(obj["kind"]), str(obj["id"]))] = obj
        state_changed = True

    used_decisions = resolving_decision_refs(current_state, request)
    audit = _audit_event(current_state, request)

    if not state_changed:
        raise ReductionError("transition does not produce an authoritative state delta")

    snapshot = _build_snapshot(
        current_state=current_state,
        request=request,
        members=effective,
        prior_snapshot_id=str(current_state.current_snapshot["id"]),
        mode=current_state.current_snapshot_ref.mode,
    )
    line = current_state.lineage(request.lineage_ref)
    if line is None:
        raise ReductionError(f"lineage {request.lineage_ref!r} does not resolve")
    updated_line = replace(
        line,
        head_snapshot_ref=str(snapshot["id"]),
        head_snapshot_digest=str(snapshot["content_digest"]),
        head_snapshot_revision=int(snapshot["revision"]),
    )

    return ReductionResult(
        object_revisions=stable_sorted_objects(new_revisions),
        decision_records=stable_sorted_objects(decisions),
        new_snapshot=snapshot,
        lineage_updates=(updated_line,),
        new_lineages=(),
        active_lineage_update=None,
        adoption_refs=tuple(dict.fromkeys(adoption_refs)),
        used_decision_refs=used_decisions,
        audit_events=(audit,),
        applied_actions=tuple(action.kind.value for action in request.actions),
    )


def _validated_decision_objects(
    current_state: StateView,
    actions: tuple[TransitionAction, ...],
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        obj = action.object_payload()
        if obj is None:
            raise ReductionError("RECORD_DECISION requires a complete object payload")
        obj = dict(obj)
        _validate_action_object_semantics(action, obj)
        prior = current_state.latest_object(str(obj.get("kind", "")), str(obj.get("id", "")))
        _validate_revision_semantics(action, obj, prior)
        decision_id = str(obj.get("id", ""))
        if decision_id in seen:
            raise ReductionError("duplicate RECORD_DECISION identity in one transition")
        seen.add(decision_id)
        result.append(obj)
    return tuple(result)


def _reduce_lineage_plan(
    current_state: StateView,
    request: StateTransitionRequest,
    action: TransitionAction,
) -> ReductionResult:
    payload = action.payload
    target_lineage_id = str(payload.get("target_lineage_id", ""))
    if not target_lineage_id:
        raise ReductionError("lineage plan requires target_lineage_id")
    lineage_kind = str(payload.get("lineage_kind", ""))
    if not lineage_kind:
        raise ReductionError("lineage plan requires lineage_kind")

    by_ref: dict[tuple[str, str], Mapping[str, Any]] = {}
    for treatment in payload.get("treatments", ()):
        if not isinstance(treatment, Mapping):
            raise ReductionError("lineage treatment must be an object")
        key = (str(treatment.get("object_kind", "")), str(treatment.get("source_ref", "")))
        if not all(key):
            raise ReductionError("lineage treatment requires object_kind and source_ref")
        if key in by_ref:
            raise ReductionError(f"duplicate lineage treatment for {key[0]}:{key[1]}")
        by_ref[key] = treatment

    child_members: dict[tuple[str, str], Mapping[str, Any]] = {}
    new_revisions: list[Mapping[str, Any]] = []
    baseline_keys: set[tuple[str, str]] = set()
    for member in current_state.snapshot_members():
        key = (str(member["kind"]), str(member["id"]))
        baseline_keys.add(key)
        treatment = by_ref.get(key)
        if treatment is None:
            raise ReductionError(f"missing explicit lineage treatment for {key[0]}:{key[1]}")
        treatment_kind = str(treatment.get("treatment", ""))
        source = current_state.exact_object(key[0], key[1], int(member["revision"]))
        if source is None:
            raise ReductionError(f"baseline object revision does not resolve for {key[0]}:{key[1]}")
        if treatment_kind == "PRESERVE":
            child_members[key] = source
        elif treatment_kind == "INVALIDATE":
            continue
        elif treatment_kind == "RECONFIRM":
            derived = treatment.get("derived_object")
            if not isinstance(derived, Mapping):
                raise ReductionError(f"RECONFIRM requires derived_object for {key[0]}:{key[1]}")
            derived = dict(derived)
            if derived.get("kind") != key[0]:
                raise ReductionError("reconfirmed object kind must match its source treatment")
            derived_id = str(derived.get("id", ""))
            declared_derived_ref = str(treatment.get("derived_ref", ""))
            if not derived_id:
                raise ReductionError("reconfirmed object must carry an id")
            if derived_id != key[1] and declared_derived_ref != derived_id:
                raise ReductionError(
                    "reconfirmed object identity change requires derived_ref matching derived_object id"
                )
            if declared_derived_ref and declared_derived_ref != derived_id:
                raise ReductionError("lineage treatment derived_ref must match derived_object id")
            if int(derived.get("revision", -1)) < 0:
                raise ReductionError("reconfirmed object must carry a non-negative revision")
            existing = current_state.latest_object(str(derived.get("kind", "")), derived_id)
            if existing is not None and int(derived["revision"]) != int(existing["revision"]) + 1:
                raise ReductionError("reconfirmed existing object requires the next monotonic revision")
            if existing is None and int(derived["revision"]) != 0:
                raise ReductionError("new reconfirmed object identity starts at revision 0")
            child_members[(str(derived["kind"]), derived_id)] = derived
            new_revisions.append(derived)
        else:
            raise ReductionError(f"unsupported lineage treatment {treatment_kind!r}")

    extras = set(by_ref) - baseline_keys
    if extras:
        formatted = ", ".join(f"{kind}:{object_id}" for kind, object_id in sorted(extras))
        raise ReductionError(f"lineage plan treats objects outside the pinned baseline: {formatted}")

    execution_mode = str(payload.get("execution_mode", current_state.current_snapshot_ref.mode))
    snapshot = _build_snapshot(
        current_state=current_state,
        request=request,
        members=child_members,
        prior_snapshot_id=str(current_state.current_snapshot["id"]),
        mode=execution_mode,
    )
    parent = current_state.lineage(request.lineage_ref)
    if parent is None:
        raise ReductionError(f"parent lineage {request.lineage_ref!r} does not resolve")
    child = LineageView(
        lineage_id=target_lineage_id,
        lineage_kind=lineage_kind,
        head_snapshot_ref=str(snapshot["id"]),
        head_snapshot_digest=str(snapshot["content_digest"]),
        head_snapshot_revision=int(snapshot["revision"]),
        execution_mode=execution_mode,
        status="active",
        parent_lineage_ref=parent.lineage_id,
        baseline_snapshot_ref=str(current_state.current_snapshot["id"]),
        project_config_ref=request.project_config_ref,
        project_config_digest=request.project_config_digest,
        effective_profile_set_ref=request.effective_profile_set_ref,
        effective_profile_set_digest=request.effective_profile_set_digest,
    )
    audit = _audit_event(current_state, request)
    return ReductionResult(
        object_revisions=stable_sorted_objects(new_revisions),
        decision_records=(),
        new_snapshot=snapshot,
        lineage_updates=(),
        new_lineages=(child,),
        active_lineage_update=None,
        adoption_refs=tuple(
            ref
            for ref in (
                str(payload.get("replay_plan_ref", "")),
                *tuple(str(item) for item in payload.get("replay_plan_refs", ()) if item),
            )
            if ref
        ),
        used_decision_refs=resolving_decision_refs(current_state, request),
        audit_events=(audit,),
        applied_actions=(action.kind.value,),
    )


def _validate_action_object_semantics(action: TransitionAction, obj: Mapping[str, Any]) -> None:
    if action.kind == TransitionKind.ADOPT_OBJECT and obj.get("adoption_state") != "approved":
        raise ReductionError("ADOPT_OBJECT requires adoption_state=approved")
    if action.kind == TransitionKind.REJECT_OBJECT and obj.get("adoption_state") != "rejected":
        raise ReductionError("REJECT_OBJECT requires adoption_state=rejected")
    if action.kind == TransitionKind.VERIFY_EVIDENCE and obj.get("verification_status") != "verified":
        raise ReductionError("VERIFY_EVIDENCE requires verification_status=verified")
    if action.kind == TransitionKind.RECLASSIFY_EVIDENCE and obj.get("kind") != "evidence":
        raise ReductionError("RECLASSIFY_EVIDENCE requires an Evidence revision")
    if action.kind == TransitionKind.RECORD_DECISION and obj.get("kind") != "decision":
        raise ReductionError("RECORD_DECISION requires a Core Decision object")
    if action.kind == TransitionKind.REGISTER_WRITING_FEEDBACK_ACTION and obj.get("kind") != "next_action":
        raise ReductionError("Writing Feedback may only register a NextAction candidate")


def _validate_revision_semantics(
    action: TransitionAction,
    obj: Mapping[str, Any],
    prior: Mapping[str, Any] | None,
) -> None:
    revision = int(obj.get("revision", -1))
    if action.kind in {TransitionKind.CREATE_OBJECT, TransitionKind.RECORD_DECISION}:
        if prior is not None:
            raise ReductionError(f"{action.kind.value} cannot reuse existing identity {obj.get('kind')}:{obj.get('id')}")
        if revision != 0:
            raise ReductionError("new Core object identity starts at revision 0")
        return
    if action.kind == TransitionKind.REGISTER_WRITING_FEEDBACK_ACTION and prior is None:
        if revision != 0:
            raise ReductionError("new Writing Feedback NextAction identity starts at revision 0")
        return
    if prior is None:
        raise ReductionError(f"{action.kind.value} requires an existing object identity")
    expected = int(prior.get("revision", -1)) + 1
    if revision != expected:
        raise ReductionError(f"object revision must advance monotonically to {expected}")


def _effective_members(current_state: StateView) -> dict[tuple[str, str], Mapping[str, Any]]:
    members: dict[tuple[str, str], Mapping[str, Any]] = {}
    for obj in current_state.effective_objects():
        members[(str(obj["kind"]), str(obj["id"]))] = obj
    return members


def _build_snapshot(
    *,
    current_state: StateView,
    request: StateTransitionRequest,
    members: Mapping[tuple[str, str], Mapping[str, Any]],
    prior_snapshot_id: str,
    mode: str,
) -> Mapping[str, Any]:
    member_rows = [
        {"kind": kind, "id": object_id, "revision": int(obj["revision"]), "digest": canonical_digest(obj)}
        for (kind, object_id), obj in sorted(members.items())
    ]
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "id": request.new_snapshot_id,
        "kind": "snapshot",
        "revision": 0,
        "project_id": request.project_ref,
        "snapshot_type": "research",
        "created_at": request.submitted_at,
        "mode": mode,
        "prior_snapshot_id": prior_snapshot_id,
        "members": member_rows,
    }
    return with_content_digest(payload)


def _audit_event(current_state: StateView, request: StateTransitionRequest) -> Mapping[str, Any]:
    subjects: list[Mapping[str, str]] = []
    for action in request.actions:
        target = action.target_ref()
        if target is not None:
            subjects.append({"kind": target.kind, "id": target.id})
        elif action.kind == TransitionKind.APPLY_LINEAGE_PLAN:
            subjects.append({
                "kind": "research_lineage",
                "id": str(action.payload.get("target_lineage_id", request.lineage_ref)),
            })
        elif action.kind == TransitionKind.SWITCH_ACTIVE_LINEAGE:
            subjects.append({
                "kind": "research_lineage",
                "id": str(action.payload.get("target_lineage_ref", request.lineage_ref)),
            })
        else:
            subjects.append({"kind": "research_transition", "id": request.transition_id})
    actor_type = "human" if request.actor.actor_type == "human" else "system"
    return {
        "schema_version": "0.1.0",
        "id": request.audit_event_id,
        "kind": "audit_event",
        "revision": 0,
        "project_id": request.project_ref,
        "occurred_at": request.submitted_at,
        "actor_type": actor_type,
        "actor_id": request.actor.actor_id,
        "action": "+".join(action.kind.value for action in request.actions),
        "subjects": _dedupe_subjects(subjects),
        "payload_digest": request.request_digest,
    }


def _dedupe_subjects(subjects: list[Mapping[str, str]]) -> list[Mapping[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[Mapping[str, str]] = []
    for subject in subjects:
        key = (subject["kind"], subject["id"])
        if key in seen:
            continue
        seen.add(key)
        result.append(subject)
    return result
