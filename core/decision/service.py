from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from typing import Any, Mapping, Sequence

from core.runtime import (
    Actor,
    CommitReceipt,
    StateTransitionRejected,
    StateTransitionRequest,
    TransitionAction,
    TransitionKind,
    canonical_digest,
)
from core.runtime.authority_validation import DecisionRequirement, required_decisions_for_action

from .models import (
    DecisionGateResult,
    DecisionResolutionResult,
    HumanDecisionError,
    request_digest,
    response_digest,
    with_request_digest,
    with_response_digest,
)


_TERMINAL = {"RESOLVED", "DECLINED", "REVISION_REQUESTED", "STALE", "CANCELLED"}
_STALE_TRANSITION_CODES = {"RT-HEAD-001", "RT-HEAD-002", "RT-PIN-002", "RT-PIN-003", "RT-PIN-004"}


def _stable_id(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def _action_wire(action: TransitionAction) -> dict[str, Any]:
    return {
        "kind": action.kind.value,
        "payload": deepcopy(dict(action.payload)),
        "decision_refs": list(action.decision_refs),
        "source_refs": list(action.source_refs),
    }


def _action_digest(action: TransitionAction) -> str:
    return canonical_digest(_action_wire(action))


def _requirement_key(requirement: DecisionRequirement) -> tuple[str, str, str, str]:
    return (
        requirement.decision_kind,
        requirement.choice,
        requirement.subject_kind,
        requirement.subject_id,
    )


def _receipt_from_wire(value: Mapping[str, Any] | None) -> CommitReceipt | None:
    if value is None:
        return None
    actor = value.get("actor", {})
    return CommitReceipt(
        transition_id=str(value["transition_id"]),
        commit_id=str(value["commit_id"]),
        prior_snapshot_ref=str(value["prior_snapshot_ref"]),
        prior_snapshot_digest=str(value["prior_snapshot_digest"]),
        new_snapshot_ref=value.get("new_snapshot_ref"),
        new_snapshot_digest=value.get("new_snapshot_digest"),
        lineage_ref=str(value["lineage_ref"]),
        applied_typed_actions=tuple(value.get("applied_typed_actions", ())),
        resolving_decision_refs=tuple(value.get("resolving_decision_refs", ())),
        bundle_digest=str(value["bundle_digest"]),
        timestamp=str(value["timestamp"]),
        actor=Actor(str(actor["actor_id"]), str(actor["actor_type"])),
        idempotency_key=str(value["idempotency_key"]),
    )


class HumanDecisionService:
    """Production Human Decision Gate driven only by PR20 DecisionRequirements.

    The service does not parse natural language, does not infer a Decision from a
    Conversation Confirmation, and never persists a Core Decision separately from
    the target transition it resolves.
    """

    def __init__(
        self,
        *,
        store,
        state_provider,
        state_transition_service,
        clock,
        source_binding_provider=None,
    ) -> None:
        self._store = store
        self._states = state_provider
        self._transitions = state_transition_service
        self._clock = clock
        self._sources = source_binding_provider

    def gate_candidate(
        self,
        candidate: Mapping[str, Any],
        *,
        state,
        actor: Mapping[str, Any],
        source_action_proposal: Mapping[str, Any] | None = None,
        authorization_evidence: Sequence[str] = (),
    ) -> DecisionGateResult:
        self._validate_candidate(candidate, state)
        actions = self._candidate_actions(candidate, state)
        requirements = tuple(
            (index, requirement)
            for index, action in enumerate(actions)
            for requirement in required_decisions_for_action(state, action)
        )
        if not requirements:
            return DecisionGateResult(
                "READY_TO_COMMIT",
                transition_request=self._transition_from_state(
                    state=state,
                    actor=actor,
                    target_actions=actions,
                    source_refs=tuple(str(item) for item in candidate.get("source_refs", ())),
                    authorization_evidence=tuple(str(item) for item in authorization_evidence),
                    basis_id=str(candidate["proposal_id"]),
                    submitted_at=self._clock.now(),
                    decision_actions=(),
                ),
            )
        request = self._build_request(
            candidate,
            state=state,
            actor=actor,
            actions=actions,
            requirements=requirements,
            source_action_proposal=source_action_proposal,
        )
        return DecisionGateResult("DECISION_REQUIRED", decision_request=self._store.put_request(request))

    def resolve(self, response: Mapping[str, Any]) -> DecisionResolutionResult:
        response = deepcopy(dict(response))
        self._validate_response_envelope(response)
        request_id = str(response["request_id"])
        request = self._store.get_request(request_id)
        if request is None:
            raise HumanDecisionError("DECISION-REQUEST-UNKNOWN", "Human Decision Request does not resolve")
        if request.get("request_digest") != response.get("request_digest"):
            self._store.record_rejected_response(request_id, response, "request digest mismatch")
            raise HumanDecisionError("DECISION-BINDING-001", "Human response request digest mismatch")
        if request_digest(request) != request.get("request_digest"):
            raise HumanDecisionError("DECISION-BINDING-001", "stored Human Decision Request digest is invalid")

        resolution = self._resolution(request_id)
        status = str(resolution["status"]) if resolution is not None else str(self._store.get_status(request_id))
        if status in _TERMINAL:
            if resolution is None or resolution.get("response_digest") != response.get("response_digest"):
                raise HumanDecisionError(
                    "DECISION-TERMINAL-001",
                    f"Human Decision Request is already {status} with another response",
                )
            return DecisionResolutionResult(
                status,
                request,
                response,
                commit_receipt=_receipt_from_wire(resolution.get("commit_receipt")),
            )

        actor = response["actor"]
        if actor.get("actor_type") != "human" or actor.get("actor_id") != request.get("human_actor_id"):
            self._store.record_rejected_response(request_id, response, "human actor mismatch")
            raise HumanDecisionError("DECISION-ACTOR-001", "only the bound human actor may resolve this request")

        if status == "RESOLVING":
            if resolution is None or resolution.get("response_digest") != response.get("response_digest"):
                raise HumanDecisionError("DECISION-RACE-001", "another response already owns this request")
            return self._resolve_claimed(request, response)
        if status != "PENDING":
            raise HumanDecisionError("DECISION-STATE-001", f"Human Decision Request is not pending: {status}")

        current_state = self._load_bound_state(request)
        stale_reason = self._stale_reason(request, current_state)
        if stale_reason is not None:
            self._claim_or_raise(request, response)
            self._store.finalize(
                request_id,
                str(response["response_digest"]),
                "STALE",
                detail=stale_reason,
            )
            return DecisionResolutionResult("STALE", request, response)

        self._claim_or_raise(request, response)
        return self._resolve_claimed(request, response)

    def pending(self, project_ref: str) -> tuple[Mapping[str, Any], ...]:
        return self._store.list_pending(project_ref)

    def _resolution(self, request_id: str) -> Mapping[str, Any] | None:
        resolver = getattr(self._store, "resolution", None)
        return resolver(request_id) if resolver is not None else None

    def _resolve_claimed(self, request, response) -> DecisionResolutionResult:
        request_id = str(request["request_id"])
        disposition = str(response["disposition"])
        if disposition == "decline":
            self._store.finalize(request_id, str(response["response_digest"]), "DECLINED")
            return DecisionResolutionResult("DECLINED", request, response)
        if disposition == "request_revision":
            self._store.finalize(request_id, str(response["response_digest"]), "REVISION_REQUESTED")
            return DecisionResolutionResult("REVISION_REQUESTED", request, response)
        if disposition != "approve_exact":
            raise HumanDecisionError("DECISION-DISPOSITION-001", "unsupported Human Decision disposition")

        target_actions = self._request_actions(request)
        decision_actions, bound_actions = self._materialize_decisions_and_bind(
            request,
            target_actions,
            actor_id=str(response["actor"]["actor_id"]),
            decided_at=str(response["responded_at"]),
        )
        transition = self._transition_from_request(
            request,
            actor=response["actor"],
            target_actions=bound_actions,
            decision_actions=decision_actions,
            submitted_at=str(response["responded_at"]),
        )
        result = self._transitions.apply(transition)
        if isinstance(result, CommitReceipt):
            # The Research State transaction is authoritative and may already have
            # succeeded on a prior attempt. Finalization is recoverable because the
            # same structured response reconstructs the same PR20 request digest.
            self._store.finalize(
                request_id,
                str(response["response_digest"]),
                "RESOLVED",
                commit_receipt=asdict(result),
            )
            return DecisionResolutionResult("RESOLVED", request, response, commit_receipt=result)
        if not isinstance(result, StateTransitionRejected):
            raise HumanDecisionError("DECISION-COMMIT-001", "unexpected StateTransitionService result")
        if any(issue.error_code in _STALE_TRANSITION_CODES for issue in result.issues):
            self._store.finalize(
                request_id,
                str(response["response_digest"]),
                "STALE",
                detail="StateTransitionService rejected stale request binding",
            )
            return DecisionResolutionResult("STALE", request, response, transition_rejection=result)
        # Keep RESOLVING for an identical retry. A deterministic failure remains
        # auditable and a transient persistence failure can be retried without a
        # second Decision identity or Snapshot.
        return DecisionResolutionResult("COMMIT_REJECTED", request, response, transition_rejection=result)

    def _claim_or_raise(self, request, response) -> None:
        claimed = self._store.claim_response(
            str(request["request_id"]),
            str(request["request_digest"]),
            response,
        )
        if claimed not in {"claimed", "retry"}:
            raise HumanDecisionError("DECISION-RACE-001", "a different response already owns this request")

    def _validate_candidate(self, candidate, state) -> None:
        required = (
            "proposal_id",
            "proposal_digest",
            "project_ref",
            "lineage_ref",
            "current_snapshot_ref",
            "current_snapshot_digest",
        )
        missing = [key for key in required if not candidate.get(key)]
        if missing:
            raise HumanDecisionError(
                "DECISION-CANDIDATE-001",
                f"candidate missing binding fields: {', '.join(missing)}",
            )
        basis = deepcopy(dict(candidate))
        supplied = str(basis.pop("proposal_digest", ""))
        if canonical_digest(basis) != supplied:
            raise HumanDecisionError("DECISION-CANDIDATE-001", "StateDeltaProposal digest is invalid")
        if candidate.get("candidate_only") is not True:
            raise HumanDecisionError("DECISION-CANDIDATE-001", "only candidate-only StateDeltaProposal is accepted")
        if (
            candidate.get("project_ref") != state.project_ref
            or candidate.get("lineage_ref") != state.lineage_ref
            or candidate.get("current_snapshot_ref") != state.current_snapshot["id"]
            or candidate.get("current_snapshot_digest") != state.current_snapshot["content_digest"]
        ):
            raise HumanDecisionError("DECISION-STALE-001", "StateDeltaProposal is stale or bound to another state")

    def _candidate_actions(self, candidate, state) -> tuple[TransitionAction, ...]:
        actions: list[TransitionAction] = []
        for raw in candidate.get("proposed_actions", ()):
            if raw.get("decision_refs"):
                raise HumanDecisionError(
                    "DECISION-FORGED-REF-001",
                    "candidate actions may not smuggle Human Decision refs",
                )
            action = TransitionAction(
                kind=TransitionKind(str(raw["kind"])),
                payload=deepcopy(dict(raw.get("payload", {}))),
                decision_refs=(),
                source_refs=tuple(str(item) for item in raw.get("source_refs", ())),
            )
            obj = action.object_payload()
            if obj is not None and obj.get("decision_ids"):
                prior = state.latest_object(str(obj.get("kind", "")), str(obj.get("id", "")))
                prior_ids = set(prior.get("decision_ids", ()) or ()) if prior is not None else set()
                proposed_ids = set(str(item) for item in obj.get("decision_ids", ()) or ())
                if not proposed_ids.issubset(prior_ids):
                    raise HumanDecisionError(
                        "DECISION-FORGED-REF-001",
                        "candidate object contains Decision provenance not inherited from current state",
                    )
            if action.kind == TransitionKind.APPLY_LINEAGE_PLAN:
                for treatment in action.payload.get("treatments", ()):
                    if not isinstance(treatment, Mapping):
                        continue
                    derived = treatment.get("derived_object")
                    if not isinstance(derived, Mapping) or not derived.get("decision_ids"):
                        continue
                    source_kind = str(treatment.get("object_kind", ""))
                    source_id = str(treatment.get("source_ref", ""))
                    inherited = state.latest_object(source_kind, source_id)
                    inherited_ids = (
                        set(str(item) for item in inherited.get("decision_ids", ()) or ())
                        if inherited is not None
                        else set()
                    )
                    proposed_ids = set(str(item) for item in derived.get("decision_ids", ()) or ())
                    if not proposed_ids.issubset(inherited_ids):
                        raise HumanDecisionError(
                            "DECISION-FORGED-REF-001",
                            "candidate lineage-derived object contains Decision provenance not inherited from current state",
                        )
            actions.append(action)
        if not actions:
            raise HumanDecisionError("DECISION-CANDIDATE-001", "StateDeltaProposal has no proposed actions")
        return tuple(actions)

    def _build_request(
        self,
        candidate,
        *,
        state,
        actor,
        actions,
        requirements,
        source_action_proposal,
    ):
        requirement_basis = [
            {
                "action_index": index,
                "action_digest": _action_digest(actions[index]),
                "decision_kind": requirement.decision_kind,
                "choice": requirement.choice,
                "subject_kind": requirement.subject_kind,
                "subject_id": requirement.subject_id,
            }
            for index, requirement in requirements
        ]
        requirement_set_digest = canonical_digest(requirement_basis)
        source_action_binding = None
        if source_action_proposal is not None:
            source_action_binding = {
                "proposal_id": str(source_action_proposal["proposal_id"]),
                "proposal_digest": str(source_action_proposal["proposal_digest"]),
            }
        action_token = source_action_binding["proposal_digest"] if source_action_binding else "no-action-proposal"
        request_id = _stable_id(
            "HDREQ-",
            str(candidate["proposal_id"]),
            str(candidate["proposal_digest"]),
            str(state.current_snapshot["content_digest"]),
            requirement_set_digest,
            str(actor["actor_id"]),
            action_token,
        )
        context_keys = (
            "evidence_refs",
            "counterevidence_refs",
            "conflict_refs",
            "unknown_refs",
            "evidence_gap_refs",
            "limitations",
            "handoff_ref",
            "run_ref",
        )
        provenance = deepcopy(dict(candidate.get("provenance", {})))
        context = {key: deepcopy(provenance[key]) for key in context_keys if key in provenance}
        units = []
        for ordinal, (index, requirement) in enumerate(requirements):
            action = actions[index]
            obj = action.object_payload()
            prior = state.latest_object(requirement.subject_kind, requirement.subject_id)
            units.append({
                "unit_id": _stable_id("HDU-", request_id, str(ordinal), *_requirement_key(requirement)),
                "transition_action_index": index,
                "transition_action_digest": _action_digest(action),
                "required_decision_kind": requirement.decision_kind,
                "required_choice": requirement.choice,
                "subject": {"kind": requirement.subject_kind, "id": requirement.subject_id},
                "proposed_semantic_effect": action.kind.value,
                "current_value": deepcopy(prior) if prior is not None else None,
                "candidate_value": deepcopy(dict(obj)) if obj is not None else deepcopy(dict(action.payload)),
                "relevant_source_refs": list(dict.fromkeys((*candidate.get("source_refs", ()), *action.source_refs))),
                "research_context": deepcopy(context),
            })
        return with_request_digest({
            "schema_version": "0.1.0",
            "request_id": request_id,
            "project_ref": state.project_ref,
            "lineage_ref": state.lineage_ref,
            "human_actor_id": str(actor["actor_id"]),
            "source_state_delta_proposal": {
                "proposal_id": str(candidate["proposal_id"]),
                "proposal_digest": str(candidate["proposal_digest"]),
            },
            "source_action_proposal": source_action_binding,
            "snapshot_binding": {
                "snapshot_ref": str(state.current_snapshot["id"]),
                "snapshot_digest": str(state.current_snapshot["content_digest"]),
            },
            "project_config": {"ref": state.project_config_ref, "digest": state.project_config_digest},
            "effective_profile_set": {
                "ref": state.effective_profile_set_ref,
                "digest": state.effective_profile_set_digest,
            },
            "decision_units": units,
            "requirement_set_digest": requirement_set_digest,
            "target_actions": [_action_wire(action) for action in actions],
            "source_refs": list(candidate.get("source_refs", ())),
            "provenance": provenance,
            "issued_at": self._clock.now(),
            "status": "PENDING",
        })

    def _validate_response_envelope(self, response) -> None:
        required = {
            "request_id",
            "request_digest",
            "disposition",
            "actor",
            "responded_at",
            "response_digest",
        }
        if not required.issubset(response):
            raise HumanDecisionError("DECISION-RESPONSE-001", "structured Human Decision response is incomplete")
        if response.get("disposition") not in {"approve_exact", "decline", "request_revision"}:
            raise HumanDecisionError("DECISION-DISPOSITION-001", "unsupported Human Decision disposition")
        actor = response.get("actor")
        if not isinstance(actor, Mapping) or not actor.get("actor_id") or not actor.get("actor_type"):
            raise HumanDecisionError("DECISION-RESPONSE-001", "Human Decision response actor is invalid")
        if response_digest(response) != response.get("response_digest"):
            raise HumanDecisionError("DECISION-RESPONSE-001", "Human Decision response digest is invalid")

    def _load_bound_state(self, request):
        try:
            return self._states.load_state_view(str(request["project_ref"]), str(request["lineage_ref"]))
        except Exception as exc:
            raise HumanDecisionError("DECISION-BINDING-001", "bound Research State no longer resolves") from exc

    def _stale_reason(self, request, state) -> str | None:
        if (
            request["snapshot_binding"]["snapshot_ref"] != state.current_snapshot["id"]
            or request["snapshot_binding"]["snapshot_digest"] != state.current_snapshot["content_digest"]
        ):
            return "Research Lineage HEAD advanced after Decision Request issuance"
        if (
            request["project_config"]["ref"] != state.project_config_ref
            or request["project_config"]["digest"] != state.project_config_digest
        ):
            return "Project Config binding changed after Decision Request issuance"
        if (
            request["effective_profile_set"]["ref"] != state.effective_profile_set_ref
            or request["effective_profile_set"]["digest"] != state.effective_profile_set_digest
        ):
            return "Effective Profile Set binding changed after Decision Request issuance"
        source_reason = self._source_binding_reason(request)
        if source_reason is not None:
            return source_reason
        rebuilt = []
        for index, action in enumerate(self._request_actions(request)):
            for requirement in required_decisions_for_action(state, action):
                rebuilt.append({
                    "action_index": index,
                    "action_digest": _action_digest(action),
                    "decision_kind": requirement.decision_kind,
                    "choice": requirement.choice,
                    "subject_kind": requirement.subject_kind,
                    "subject_id": requirement.subject_id,
                })
        if canonical_digest(rebuilt) != request["requirement_set_digest"]:
            return "DecisionRequirement set changed after Decision Request issuance"
        return None

    def _source_binding_reason(self, request) -> str | None:
        if self._sources is None:
            return None
        candidate_binding = request["source_state_delta_proposal"]
        candidate = self._sources.load_state_delta_proposal(str(candidate_binding["proposal_id"]))
        if candidate is None or candidate.get("proposal_digest") != candidate_binding["proposal_digest"]:
            return "source StateDeltaProposal binding changed or disappeared"
        basis = deepcopy(dict(candidate))
        supplied = str(basis.pop("proposal_digest", ""))
        if canonical_digest(basis) != supplied:
            return "source StateDeltaProposal content digest is invalid"
        action_binding = request.get("source_action_proposal")
        if action_binding is not None:
            proposal = self._sources.load_proposal(str(action_binding["proposal_id"]))
            if proposal is None or proposal.get("proposal_digest") != action_binding["proposal_digest"]:
                return "source Action Proposal binding changed or disappeared"
        return None

    def _request_actions(self, request) -> tuple[TransitionAction, ...]:
        actions = tuple(
            TransitionAction(
                kind=TransitionKind(str(raw["kind"])),
                payload=deepcopy(dict(raw.get("payload", {}))),
                decision_refs=tuple(str(item) for item in raw.get("decision_refs", ())),
                source_refs=tuple(str(item) for item in raw.get("source_refs", ())),
            )
            for raw in request["target_actions"]
        )
        for unit in request["decision_units"]:
            index = int(unit["transition_action_index"])
            if index < 0 or index >= len(actions) or _action_digest(actions[index]) != unit["transition_action_digest"]:
                raise HumanDecisionError("DECISION-BINDING-001", "target action digest does not match Decision Request")
        return actions

    def _materialize_decisions_and_bind(self, request, target_actions, *, actor_id, decided_at):
        grouped: dict[tuple[str, str], list[Mapping[str, str]]] = {}
        action_groups: dict[int, list[tuple[str, str]]] = {}
        for unit in request["decision_units"]:
            key = (str(unit["required_decision_kind"]), str(unit["required_choice"]))
            subject = {"kind": str(unit["subject"]["kind"]), "id": str(unit["subject"]["id"])}
            if subject not in grouped.setdefault(key, []):
                grouped[key].append(subject)
            action_groups.setdefault(int(unit["transition_action_index"]), []).append(key)

        decision_ids: dict[tuple[str, str], str] = {}
        decision_actions = []
        for key in sorted(grouped):
            decision_id = _stable_id("DEC-", str(request["request_id"]), key[0], key[1])
            decision_ids[key] = decision_id
            decision = {
                "schema_version": "0.1.0",
                "id": decision_id,
                "kind": "decision",
                "revision": 0,
                "project_id": str(request["project_ref"]),
                "decision_kind": key[0],
                "subjects": sorted(grouped[key], key=lambda item: (item["kind"], item["id"])),
                "choice": key[1],
                "actor_type": "human",
                "decided_by": actor_id,
                "decided_at": decided_at,
            }
            decision_actions.append(TransitionAction(TransitionKind.RECORD_DECISION, {"object": decision}))

        bound_actions = []
        for index, action in enumerate(target_actions):
            refs = tuple(dict.fromkeys(decision_ids[key] for key in action_groups.get(index, ())))
            payload = deepcopy(dict(action.payload))
            obj = action.object_payload()
            if obj is not None and refs:
                bound_obj = deepcopy(dict(obj))
                existing = tuple(str(item) for item in bound_obj.get("decision_ids", ()) or ())
                bound_obj["decision_ids"] = list(dict.fromkeys((*existing, *refs)))
                payload["object"] = bound_obj
            if action.kind == TransitionKind.APPLY_LINEAGE_PLAN:
                treatments = []
                for treatment in payload.get("treatments", ()):
                    item = deepcopy(dict(treatment))
                    if item.get("treatment") == "RECONFIRM":
                        derived = item.get("derived_object")
                        if isinstance(derived, Mapping):
                            subject = (str(derived.get("kind", "")), str(derived.get("id", "")))
                            matching = [
                                decision_ids[(str(unit["required_decision_kind"]), str(unit["required_choice"]))]
                                for unit in request["decision_units"]
                                if int(unit["transition_action_index"]) == index
                                and unit["required_decision_kind"] == "lineage_reconfirmation"
                                and (str(unit["subject"]["kind"]), str(unit["subject"]["id"])) == subject
                            ]
                            if len(matching) != 1:
                                raise HumanDecisionError(
                                    "DECISION-BINDING-001",
                                    "RECONFIRM requires one exact lineage_reconfirmation Decision",
                                )
                            item["human_decision_ref"] = matching[0]
                            derived_copy = deepcopy(dict(derived))
                            existing = tuple(str(value) for value in derived_copy.get("decision_ids", ()) or ())
                            derived_copy["decision_ids"] = list(dict.fromkeys((*existing, matching[0])))
                            item["derived_object"] = derived_copy
                    treatments.append(item)
                payload["treatments"] = treatments
            bound_actions.append(replace(action, payload=payload, decision_refs=refs))
        return tuple(decision_actions), tuple(bound_actions)

    def _transition_from_state(
        self,
        *,
        state,
        actor,
        target_actions,
        source_refs,
        authorization_evidence,
        basis_id,
        submitted_at,
        decision_actions,
    ) -> StateTransitionRequest:
        return self._make_transition(
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            snapshot_ref=str(state.current_snapshot["id"]),
            snapshot_digest=str(state.current_snapshot["content_digest"]),
            project_config_ref=state.project_config_ref,
            project_config_digest=state.project_config_digest,
            profile_ref=state.effective_profile_set_ref,
            profile_digest=state.effective_profile_set_digest,
            actor=actor,
            target_actions=target_actions,
            source_refs=source_refs,
            authorization_evidence=authorization_evidence,
            basis_id=basis_id,
            submitted_at=submitted_at,
            decision_actions=decision_actions,
        )

    def _transition_from_request(
        self,
        request,
        *,
        actor,
        target_actions,
        decision_actions,
        submitted_at,
    ) -> StateTransitionRequest:
        return self._make_transition(
            project_ref=str(request["project_ref"]),
            lineage_ref=str(request["lineage_ref"]),
            snapshot_ref=str(request["snapshot_binding"]["snapshot_ref"]),
            snapshot_digest=str(request["snapshot_binding"]["snapshot_digest"]),
            project_config_ref=str(request["project_config"]["ref"]),
            project_config_digest=str(request["project_config"]["digest"]),
            profile_ref=str(request["effective_profile_set"]["ref"]),
            profile_digest=str(request["effective_profile_set"]["digest"]),
            actor=actor,
            target_actions=target_actions,
            source_refs=tuple(str(item) for item in request.get("source_refs", ())),
            authorization_evidence=(),
            basis_id=str(request["request_id"]),
            submitted_at=submitted_at,
            decision_actions=decision_actions,
        )

    def _make_transition(
        self,
        *,
        project_ref,
        lineage_ref,
        snapshot_ref,
        snapshot_digest,
        project_config_ref,
        project_config_digest,
        profile_ref,
        profile_digest,
        actor,
        target_actions,
        source_refs,
        authorization_evidence,
        basis_id,
        submitted_at,
        decision_actions,
    ) -> StateTransitionRequest:
        request = StateTransitionRequest(
            transition_id=_stable_id("TR-", basis_id),
            project_ref=project_ref,
            lineage_ref=lineage_ref,
            expected_head_snapshot_ref=snapshot_ref,
            expected_head_snapshot_digest=snapshot_digest,
            actor=Actor(str(actor["actor_id"]), str(actor["actor_type"])),
            actions=tuple((*decision_actions, *target_actions)),
            project_config_ref=project_config_ref,
            project_config_digest=project_config_digest,
            effective_profile_set_ref=profile_ref,
            effective_profile_set_digest=profile_digest,
            authorization_evidence=tuple(str(item) for item in authorization_evidence),
            idempotency_key=_stable_id("IDEMP-HD-", basis_id),
            submitted_at=submitted_at,
            new_snapshot_id=_stable_id("SNP-HD-", basis_id),
            commit_id=_stable_id("COM-HD-", basis_id),
            audit_event_id=_stable_id("AUD-HD-", basis_id),
            source_refs=tuple(source_refs),
        )
        return request.with_calculated_digest()


def make_response(
    *,
    request: Mapping[str, Any],
    disposition: str,
    actor_id: str,
    responded_at: str,
) -> Mapping[str, Any]:
    """Build an explicit structured Human response; never parse prose."""
    return with_response_digest({
        "schema_version": "0.1.0",
        "response_id": _stable_id("HDRESP-", str(request["request_id"]), disposition, actor_id),
        "request_id": str(request["request_id"]),
        "request_digest": str(request["request_digest"]),
        "disposition": disposition,
        "actor": {"actor_id": actor_id, "actor_type": "human"},
        "responded_at": responded_at,
    })
