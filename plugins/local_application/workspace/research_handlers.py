"""Research status, question, abort and state delta handlers (#494)."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.conversation import HarnessServiceResult
from core.runtime import (
    ObjectRef,
    StateDeltaProposal,
    TransitionAction,
    TransitionKind,
)


class ResearchStatusHandler:
    def __init__(self, human_decisions) -> None:
        self._human_decisions = human_decisions

    def execute(self, payload, *, state, actor, proposal):
        objects = [deepcopy(dict(item)) for item in state.effective_objects()]
        if payload.get("kinds"):
            allowed = {str(item) for item in payload["kinds"]}
            objects = [item for item in objects if str(item.get("kind")) in allowed]
        pending = []
        for request in self._human_decisions.pending(state.project_ref):
            pending.append(
                {
                    "request_id": request["request_id"],
                    "source_candidate": deepcopy(request["source_state_delta_proposal"]),
                    "subjects": [deepcopy(unit["subject"]) for unit in request["decision_units"]],
                    "decision_kinds": list(
                        dict.fromkeys(
                            str(unit["required_decision_kind"])
                            for unit in request["decision_units"]
                        )
                    ),
                    "snapshot_binding": deepcopy(request["snapshot_binding"]),
                    "status": request.get("operational_status", "PENDING"),
                }
            )
        return HarnessServiceResult(
            result_reference=str(state.current_snapshot["id"]),
            data={
                "state": {
                    "snapshot_id": state.current_snapshot["id"],
                    "revision": state.current_snapshot.get("revision", 0),
                    "content_digest": state.current_snapshot["content_digest"],
                    "active_lineage_ref": state.active_lineage_ref,
                },
                "objects": objects,
                "pending_human_decisions": pending,
            },
        )


class ResearchQuestionProposeHandler:
    """Materialize an untrusted typed RQ candidate without mutating Research State."""

    def __init__(self, store, id_provider) -> None:
        self._store = store
        self._ids = id_provider

    def execute(self, payload, *, state, actor, proposal):
        derived_seed_ids = tuple(str(item) for item in payload.get("derived_from_seed_ids", ()))
        configured_seeds = {
            str(item["seed_id"])
            for item in state.project_config.get("research_questions", {}).get("seeds", ())
            if isinstance(item, Mapping) and item.get("seed_id")
        }
        unknown_seeds = sorted(set(derived_seed_ids) - configured_seeds)
        if unknown_seeds:
            raise ValueError(
                "derived_from_seed_ids do not resolve in current Project Config: "
                + ", ".join(unknown_seeds)
            )

        parent_question_id = payload.get("parent_question_id")
        if parent_question_id is not None:
            parent = next(
                (
                    item
                    for item in state.effective_objects()
                    if item.get("kind") == "research_question"
                    and item.get("id") == parent_question_id
                    and item.get("project_id") == state.project_ref
                    and item.get("adoption_state") == "approved"
                ),
                None,
            )
            if parent is None:
                raise ValueError(
                    "parent_question_id must resolve to a current authoritative approved Research Question"
                )

        rq_id = self._ids.new("RQ-")
        rq_candidate: dict[str, Any] = {
            "schema_version": "0.1.0",
            "id": rq_id,
            "kind": "research_question",
            "revision": 0,
            "project_id": state.project_ref,
            "text": str(payload["text"]),
            "acceptance_criteria": list(payload.get("acceptance_criteria", ())),
            "scope_limits": list(payload.get("scope_limits", ())),
            "adoption_state": "approved",
        }
        if "rationale" in payload:
            rq_candidate["rationale"] = str(payload["rationale"])
        if parent_question_id is not None:
            rq_candidate["parent_question_id"] = str(parent_question_id)

        transition_action = TransitionAction(
            TransitionKind.CREATE_OBJECT,
            {"object": rq_candidate},
            decision_refs=(),
            source_refs=(),
        )
        provenance: dict[str, Any] = {
            "producer": "research_question.propose@0.1.0",
            "source_action_proposal": {
                "proposal_id": str(proposal["proposal_id"]),
                "proposal_digest": str(proposal["proposal_digest"]),
            },
            "source_input_id": str(proposal["source"]["input_id"]),
            "project_config": {
                "ref": state.project_config_ref,
                "digest": state.project_config_digest,
            },
        }
        if derived_seed_ids:
            provenance["project_config_seed_ids"] = list(derived_seed_ids)

        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            source_refs=(),
            proposed_actions=(transition_action,),
            affected_refs=(ObjectRef("research_question", rq_id),),
            rationale=str(
                payload.get("rationale")
                or "Research Question candidate proposed through bounded semantic ingress."
            ),
            required_human_decision_kinds=(),
            current_snapshot_ref=str(state.current_snapshot["id"]),
            current_snapshot_digest=str(state.current_snapshot["content_digest"]),
            provenance=provenance,
            candidate_only=True,
        ).with_calculated_digest()
        candidate_wire = {
            "proposal_id": candidate.proposal_id,
            "project_ref": candidate.project_ref,
            "lineage_ref": candidate.lineage_ref,
            "source_refs": list(candidate.source_refs),
            "proposed_actions": [
                {
                    "kind": transition_action.kind.value,
                    "payload": deepcopy(dict(transition_action.payload)),
                    "decision_refs": list(transition_action.decision_refs),
                    "source_refs": list(transition_action.source_refs),
                }
            ],
            "affected_refs": [{"kind": "research_question", "id": rq_id}],
            "rationale": candidate.rationale,
            "required_human_decision_kinds": list(candidate.required_human_decision_kinds),
            "current_snapshot_ref": candidate.current_snapshot_ref,
            "current_snapshot_digest": candidate.current_snapshot_digest,
            "provenance": deepcopy(dict(candidate.provenance)),
            "candidate_only": True,
            "proposal_digest": candidate.proposal_digest,
        }
        self._store.store_state_delta_proposal(candidate.proposal_id, candidate_wire)
        return HarnessServiceResult(
            result_reference=candidate.proposal_id,
            data={
                "state_delta_proposal_id": candidate.proposal_id,
                "research_question_candidate": deepcopy(rq_candidate),
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )


class RunAbortHandler:
    def __init__(self, execution_service) -> None:
        self._execution = execution_service

    def execute(self, payload, *, state, actor, proposal):
        run = self._execution.abort(
            str(payload["run_id"]),
            reason=str(payload.get("reason") or "explicit conversational run.abort"),
        )
        return HarnessServiceResult(
            result_reference=run.run_id,
            data={"run_id": run.run_id, "run_status": run.status.value},
            research_state_mutation_performed=False,
        )


class StateDeltaApplyHandler:
    """Gate an exact PR20 candidate through dynamic PR20 DecisionRequirements."""

    def __init__(self, store, human_decisions) -> None:
        self._store = store
        self._human_decisions = human_decisions

    def execute(self, payload, *, state, actor, proposal):
        candidate_id = str(payload["state_delta_proposal_id"])
        candidate = self._store.load_state_delta_proposal(candidate_id)
        if candidate is None:
            raise KeyError(f"unknown StateDeltaProposal: {candidate_id}")
        gate = self._human_decisions.gate_candidate(
            candidate,
            state=state,
            actor=actor,
            source_action_proposal=proposal,
        )
        if gate.status == "READY_TO_COMMIT":
            return HarnessServiceResult(
                result_reference=candidate_id,
                data={"candidate_proposal_id": candidate_id, "decision_required": False},
                state_transition_request=gate.transition_request,
            )
        request = gate.decision_request
        return HarnessServiceResult(
            result_reference=str(request["request_id"]),
            data={
                "candidate_proposal_id": candidate_id,
                "decision_required": True,
                "decision_request": deepcopy(dict(request)),
            },
            research_state_mutation_performed=False,
        )


def _status_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) - {"kinds"} or ("kinds" in payload and not isinstance(payload["kinds"], list)):
        raise ValueError("research.status payload is invalid")


def _rq_proposal_payload(payload: Mapping[str, Any]) -> None:
    allowed = {
        "text",
        "rationale",
        "acceptance_criteria",
        "scope_limits",
        "parent_question_id",
        "derived_from_seed_ids",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "research_question.propose payload contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("research_question.propose requires non-empty text")
    if "rationale" in payload and (
        not isinstance(payload["rationale"], str) or not payload["rationale"].strip()
    ):
        raise ValueError("rationale must be a non-empty string")
    if (
        "parent_question_id" in payload
        and payload["parent_question_id"] is not None
        and (
            not isinstance(payload["parent_question_id"], str)
            or not payload["parent_question_id"].strip()
        )
    ):
        raise ValueError("parent_question_id must be null or a non-empty string")
    for field in ("acceptance_criteria", "scope_limits", "derived_from_seed_ids"):
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(f"{field} must be an array of non-empty strings")
    seed_ids = payload.get("derived_from_seed_ids", ())
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("derived_from_seed_ids must not contain duplicates")


def _desktop_payload(payload: Mapping[str, Any]) -> None:
    allowed = {
        "question_id",
        "purpose",
        "resource_reference_ids",
        "coverage_dimensions",
        "desktop_policy",
        "parent_run_id",
    }
    if (
        set(payload) - allowed
        or not isinstance(payload.get("question_id"), str)
        or not payload["question_id"]
    ):
        raise ValueError("desktop_research.investigate payload is invalid")
    if "resource_reference_ids" in payload and not isinstance(
        payload["resource_reference_ids"], list
    ):
        raise ValueError("resource_reference_ids must be pre-registered IDs")
    if "parent_run_id" in payload and (
        not isinstance(payload["parent_run_id"], str) or not payload["parent_run_id"].strip()
    ):
        raise ValueError("parent_run_id must be a non-empty Run ID")


def _abort_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) - {"run_id", "reason"} or not isinstance(payload.get("run_id"), str):
        raise ValueError("run.abort requires run_id and optional reason")


def _apply_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != {"state_delta_proposal_id"} or not isinstance(
        payload.get("state_delta_proposal_id"), str
    ):
        raise ValueError(
            "state.apply_candidate accepts only state_delta_proposal_id; "
            "Decision refs are derived by the Human Decision Gate"
        )
