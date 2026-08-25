from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .transition_models import StateTransitionRequest, StateView, TransitionAction, TransitionKind, ValidationIssue, ValidationStage, canonical_digest
from ._validation_common import _issue, _dedupe_issues

_PROTECTED_RESEARCH_KINDS = {"research_question", "method", "finding", "recommendation"}
_RESEARCH_CONTENT_KINDS = {"claim", "evidence", "analysis", "finding", "argument", "contribution", "recommendation"}

@dataclass(frozen=True)
class DecisionRequirement:
    decision_kind: str
    choice: str
    subject_kind: str
    subject_id: str


def required_decisions_for_action(current_state: StateView, action: TransitionAction) -> tuple[DecisionRequirement, ...]:
    requirements: list[DecisionRequirement] = []
    obj = action.object_payload()
    if obj is not None:
        kind = str(obj.get("kind", ""))
        object_id = str(obj.get("id", ""))
        prior = current_state.latest_object(kind, object_id)
        if kind in _PROTECTED_RESEARCH_KINDS:
            old_adoption = prior.get("adoption_state") if prior else None
            new_adoption = obj.get("adoption_state")
            if new_adoption != old_adoption:
                if new_adoption == "approved":
                    requirements.append(DecisionRequirement("research_adoption", "approve", kind, object_id))
                elif new_adoption in {"rejected", "closed", "out_of_scope"}:
                    requirements.append(DecisionRequirement("research_adoption", "reject", kind, object_id))
            if prior is not None and _material_research_change(prior, obj):
                requirements.append(DecisionRequirement("research_revision", "revise", kind, object_id))
        if kind == "evidence":
            old_verification = prior.get("verification_status") if prior else None
            old_kind = prior.get("evidence_kind") if prior else None
            if obj.get("verification_status") == "verified" and old_verification != "verified":
                requirements.append(DecisionRequirement("evidence_qualification", "verify", kind, object_id))
            if prior is not None and obj.get("evidence_kind") != old_kind:
                requirements.append(DecisionRequirement("evidence_reclassification", "reclassify", kind, object_id))
    if action.kind == TransitionKind.APPLY_LINEAGE_PLAN:
        plan_ref = str(action.payload.get("plan_ref", ""))
        requirements.append(DecisionRequirement("lineage_plan", "apply", "lineage_plan", plan_ref))
        treatments = action.payload.get("treatments", ())
        if isinstance(treatments, Sequence) and not isinstance(treatments, (str, bytes)):
            for treatment in treatments:
                if not isinstance(treatment, Mapping) or treatment.get("treatment") != "RECONFIRM":
                    continue
                derived = treatment.get("derived_object")
                if isinstance(derived, Mapping):
                    requirements.append(DecisionRequirement(
                        "lineage_reconfirmation",
                        "reconfirm",
                        str(derived.get("kind", "")),
                        str(derived.get("id", "")),
                    ))
    if action.kind == TransitionKind.SWITCH_ACTIVE_LINEAGE:
        target = str(action.payload.get("target_lineage_ref", ""))
        requirements.append(DecisionRequirement("active_lineage_selection", "switch", "research_lineage", target))
    return tuple(_dedupe(requirements))


def resolving_decision_refs(current_state: StateView, request: StateTransitionRequest) -> tuple[str, ...]:
    refs: list[str] = []
    for action in request.actions:
        requirements = required_decisions_for_action(current_state, action)
        if requirements:
            refs.extend(action.decision_refs)
    return tuple(dict.fromkeys(refs))


def _validate_human_decisions(current_state: StateView, request: StateTransitionRequest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    decisions = _decision_pool(current_state, request)
    for action in request.actions:
        requirements = required_decisions_for_action(current_state, action)
        if not requirements:
            continue
        obj = action.object_payload()
        object_decision_ids = set(obj.get("decision_ids", ())) if obj is not None else set(action.decision_refs)
        for required in requirements:
            matched = False
            for decision_ref in action.decision_refs:
                decision = decisions.get(decision_ref)
                if decision is None or decision_ref in current_state.used_decision_ids:
                    continue
                if decision.get("actor_type") != "human":
                    continue
                if decision.get("project_id") != request.project_ref:
                    continue
                if decision.get("decision_kind") != required.decision_kind or decision.get("choice") != required.choice:
                    continue
                if not _decision_subject_matches(decision, required.subject_kind, required.subject_id):
                    continue
                if obj is not None and decision_ref not in object_decision_ids:
                    continue
                matched = True
                break
            if not matched:
                issues.append(_issue(
                    "RT-DECISION-001",
                    ValidationStage.HUMAN_DECISION,
                    f"Authoritative transition requires an unused human Decision bound as {required.decision_kind}/{required.choice} to {required.subject_kind}:{required.subject_id}.",
                    (required.subject_id,),
                ))
    for action in request.actions:
        target = action.target_ref()
        for decision_ref in action.decision_refs:
            decision = decisions.get(decision_ref)
            if decision is None:
                issues.append(_issue("RT-DECISION-002", ValidationStage.HUMAN_DECISION, "Referenced Decision does not resolve.", (decision_ref,)))
                continue
            if decision_ref in current_state.used_decision_ids:
                issues.append(_issue(
                    "RT-DECISION-005",
                    ValidationStage.HUMAN_DECISION,
                    "A Human Decision may not be replayed for a second authoritative transition.",
                    (decision_ref,),
                ))
            if decision.get("actor_type") != "human":
                issues.append(_issue("RT-DECISION-003", ValidationStage.HUMAN_DECISION, "Resolving authoritative Decision must be human-owned.", (decision_ref,)))
            if target is not None and not _decision_subject_matches(decision, target.kind, target.id):
                if action.kind not in {TransitionKind.APPLY_LINEAGE_PLAN, TransitionKind.SWITCH_ACTIVE_LINEAGE}:
                    issues.append(_issue("RT-DECISION-004", ValidationStage.HUMAN_DECISION, "Decision subject is not bound to the transition target.", (decision_ref, target.id)))
    return _dedupe_issues(issues)


def _validate_lineage_preconditions(current_state: StateView, request: StateTransitionRequest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if current_state.lineage(request.lineage_ref) is None:
        issues.append(_issue("RT-LINEAGE-001", ValidationStage.LINEAGE, "Source Research Lineage does not resolve.", (request.lineage_ref,)))
    for action in request.actions:
        if action.kind == TransitionKind.APPLY_LINEAGE_PLAN:
            payload = action.payload
            required = ("plan_ref", "target_lineage_id", "lineage_kind", "baseline_snapshot_ref", "baseline_snapshot_digest", "treatments")
            missing = [key for key in required if key not in payload]
            if missing:
                issues.append(_issue("RT-LINEAGE-002", ValidationStage.LINEAGE, f"Lineage plan payload is incomplete: {', '.join(missing)}."))
                continue
            if payload.get("lineage_kind") not in {"exploratory_fork", "corrective_recovery"}:
                issues.append(_issue("RT-LINEAGE-003", ValidationStage.LINEAGE, "Lineage plan kind must be exploratory_fork or corrective_recovery."))
            if payload.get("baseline_snapshot_ref") != request.expected_head_snapshot_ref or payload.get("baseline_snapshot_digest") != request.expected_head_snapshot_digest:
                issues.append(_issue("RT-LINEAGE-004", ValidationStage.LINEAGE, "Fork/Recovery baseline must be exactly pinned to the expected source head."))
            target = str(payload.get("target_lineage_id", ""))
            if current_state.lineage(target) is not None:
                issues.append(_issue("RT-LINEAGE-005", ValidationStage.LINEAGE, "Target Research Lineage ID already exists.", (target,)))
            treatments = payload.get("treatments")
            if not isinstance(treatments, Sequence) or isinstance(treatments, (str, bytes)):
                issues.append(_issue("RT-LINEAGE-006", ValidationStage.LINEAGE, "Lineage treatments must be an explicit sequence."))
            else:
                source_refs = {
                    (str(item.get("object_kind", "")), str(item.get("source_ref", "")))
                    for item in treatments
                    if isinstance(item, Mapping)
                }
                baseline_refs = {
                    (str(member.get("kind", "")), str(member.get("id", "")))
                    for member in current_state.snapshot_members()
                }
                missing_treatment = sorted(baseline_refs - source_refs)
                if missing_treatment:
                    issues.append(_issue(
                        "RT-LINEAGE-007",
                        ValidationStage.LINEAGE,
                        "Every inherited baseline member requires explicit PRESERVE/RECONFIRM/INVALIDATE treatment.",
                        tuple(f"{kind}:{object_id}" for kind, object_id in missing_treatment),
                    ))
                for item in treatments:
                    if not isinstance(item, Mapping) or item.get("treatment") not in {"PRESERVE", "RECONFIRM", "INVALIDATE"}:
                        issues.append(_issue("RT-LINEAGE-008", ValidationStage.LINEAGE, "Invalid lineage inheritance treatment."))
                        continue
                    if item.get("treatment") == "RECONFIRM":
                        derived = item.get("derived_object")
                        decision_ref = item.get("human_decision_ref")
                        if not isinstance(derived, Mapping) or not decision_ref:
                            issues.append(_issue(
                                "RT-LINEAGE-013",
                                ValidationStage.LINEAGE,
                                "RECONFIRM requires a derived Core object and explicit Human Decision binding.",
                                (str(item.get("source_ref", "")),),
                            ))
                            continue
                        derived_id = str(derived.get("id", ""))
                        source_ref = str(item.get("source_ref", ""))
                        derived_ref = str(item.get("derived_ref", ""))
                        if derived_id != source_ref and derived_ref != derived_id:
                            issues.append(_issue(
                                "RT-LINEAGE-015",
                                ValidationStage.LINEAGE,
                                "RECONFIRM identity changes require explicit derived_ref matching the derived Core object.",
                                (source_ref, derived_id),
                            ))
                        elif derived_ref and derived_ref != derived_id:
                            issues.append(_issue(
                                "RT-LINEAGE-015",
                                ValidationStage.LINEAGE,
                                "RECONFIRM derived_ref must match the derived Core object identity.",
                                (derived_ref, derived_id),
                            ))
                        if decision_ref not in set(action.decision_refs) or decision_ref not in set(derived.get("decision_ids", ()) or ()):
                            issues.append(_issue(
                                "RT-LINEAGE-014",
                                ValidationStage.LINEAGE,
                                "RECONFIRM Decision must be bound to both the lineage action and derived object provenance.",
                                (str(decision_ref), str(derived.get("id", ""))),
                            ))
            if payload.get("lineage_kind") == "corrective_recovery" and not payload.get("replay_plan_ref"):
                issues.append(_issue("RT-LINEAGE-009", ValidationStage.LINEAGE, "Corrective recovery must register its approved Replay Plan reference."))
        elif action.kind == TransitionKind.SWITCH_ACTIVE_LINEAGE:
            target = str(action.payload.get("target_lineage_ref", ""))
            if current_state.lineage(target) is None:
                issues.append(_issue("RT-LINEAGE-010", ValidationStage.LINEAGE, "Active lineage switch target does not resolve.", (target,)))
    return issues


def _validate_epistemic_preconditions(current_state: StateView, request: StateTransitionRequest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    target_lineage = current_state.lineage(request.lineage_ref)
    target_mode = target_lineage.execution_mode if target_lineage is not None else str(current_state.current_snapshot.get("mode", "real"))
    for action in request.actions:
        obj = action.object_payload()
        if obj is not None and obj.get("kind") == "evidence":
            prior = current_state.latest_object("evidence", str(obj.get("id", "")))
            if prior is not None and prior.get("evidence_mode") == "synthetic" and obj.get("evidence_mode") == "empirical":
                issues.append(_issue(
                    "RT-EPI-001",
                    ValidationStage.EPISTEMIC_FIREWALL,
                    "Synthetic Evidence can never be promoted to empirical Evidence.",
                    (str(obj.get("id", "")),),
                ))
        if target_mode == "real":
            refs = tuple(dict.fromkeys((*request.source_refs, *action.source_refs)))
            virtual_sources = [ref for ref in refs if current_state.source_modes.get(ref) in {"virtual", "synthetic_test"}]
            content_kind = str(obj.get("kind")) if obj is not None else str(action.payload.get("content_class", ""))
            if virtual_sources and content_kind in _RESEARCH_CONTENT_KINDS:
                issues.append(_issue(
                    "RT-EPI-002",
                    ValidationStage.EPISTEMIC_FIREWALL,
                    "VIRTUAL/synthetic research content may not be adopted into a REAL lineage.",
                    tuple(virtual_sources),
                ))
            if virtual_sources and action.payload.get("content_class") in {
                "response", "observation", "raw_data", "evidence", "finding", "participant_identity", "analysis"
            }:
                issues.append(_issue(
                    "RT-EPI-003",
                    ValidationStage.EPISTEMIC_FIREWALL,
                    "VIRTUAL responses/observations/raw data/identities cannot cross the REAL epistemic firewall.",
                    tuple(virtual_sources),
                ))
        for ref in (*request.source_refs, *action.source_refs):
            if ref in current_state.non_reusable_refs and action.kind == TransitionKind.RECORD_RUN_RESULT_ADOPTION:
                issues.append(_issue(
                    "RT-EPI-004",
                    ValidationStage.EPISTEMIC_FIREWALL,
                    "A Run/Handoff marked non-reusable by recovery semantics cannot be adopted again.",
                    (ref,),
                ))
    return _dedupe_issues(issues)


def _decision_pool(current_state: StateView, request: StateTransitionRequest) -> dict[str, Mapping[str, Any]]:
    pool = {str(item["id"]): item for item in current_state.decisions if item.get("id")}
    for action in request.actions:
        if action.kind == TransitionKind.RECORD_DECISION:
            obj = action.object_payload()
            if obj is not None and obj.get("id"):
                pool[str(obj["id"])] = obj
    return pool


def _decision_refs_for_object(request: StateTransitionRequest, kind: str, object_id: str) -> tuple[str, ...]:
    refs: list[str] = []
    for action in request.actions:
        target = action.target_ref()
        if target is not None and target.kind == kind and target.id == object_id:
            refs.extend(action.decision_refs)
    return tuple(dict.fromkeys(refs))


def _decision_subject_matches(decision: Mapping[str, Any], kind: str, object_id: str) -> bool:
    for subject in decision.get("subjects", ()) or ():
        if isinstance(subject, Mapping) and subject.get("kind") == kind and subject.get("id") == object_id:
            return True
    return False


def _material_research_change(prior: Mapping[str, Any], proposed: Mapping[str, Any]) -> bool:
    excluded = {"revision", "decision_ids", "adoption_state"}
    before = {key: value for key, value in prior.items() if key not in excluded}
    after = {key: value for key, value in proposed.items() if key not in excluded}
    return canonical_digest(before) != canonical_digest(after)


def _dedupe(items: Sequence[DecisionRequirement]) -> list[DecisionRequirement]:
    result: list[DecisionRequirement] = []
    seen: set[DecisionRequirement] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
