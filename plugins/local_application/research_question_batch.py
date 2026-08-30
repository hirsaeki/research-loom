from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import HarnessServiceResult
from core.runtime import ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind


_RQ_INPUT_FIELDS = {
    "text",
    "rationale",
    "acceptance_criteria",
    "scope_limits",
    "parent_question_id",
    "derived_from_seed_ids",
}


def _validate_question_item(payload: Mapping[str, Any], *, index: int) -> None:
    unknown = set(payload) - _RQ_INPUT_FIELDS
    if unknown:
        raise ValueError(
            f"questions[{index}] contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"questions[{index}] requires non-empty text")
    if "rationale" in payload and (
        not isinstance(payload["rationale"], str) or not payload["rationale"].strip()
    ):
        raise ValueError(f"questions[{index}].rationale must be a non-empty string")
    if (
        "parent_question_id" in payload
        and payload["parent_question_id"] is not None
        and (
            not isinstance(payload["parent_question_id"], str)
            or not payload["parent_question_id"].strip()
        )
    ):
        raise ValueError(
            f"questions[{index}].parent_question_id must be null or a non-empty string"
        )
    for field in ("acceptance_criteria", "scope_limits", "derived_from_seed_ids"):
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(
                f"questions[{index}].{field} must be an array of non-empty strings"
            )
    seed_ids = payload.get("derived_from_seed_ids", ())
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError(
            f"questions[{index}].derived_from_seed_ids must not contain duplicates"
        )


def research_question_propose_many_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != {"questions"}:
        raise ValueError("research_question.propose_many payload accepts only questions")
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) < 2:
        raise ValueError("research_question.propose_many requires at least two questions")
    for index, item in enumerate(questions):
        if not isinstance(item, Mapping):
            raise ValueError(f"questions[{index}] must be an object")
        _validate_question_item(item, index=index)


class ResearchQuestionProposeManyHandler:
    """Materialize one exact multi-RQ candidate without mutating Research State."""

    def __init__(self, store, id_provider) -> None:
        self._store = store
        self._ids = id_provider

    def execute(self, payload, *, state, actor, proposal):
        # Keep the operation all-or-nothing: validate every member and every current-
        # state reference before allocating identities or persisting a candidate.
        research_question_propose_many_payload(payload)
        questions = tuple(payload["questions"])
        configured_seeds = {
            str(item["seed_id"])
            for item in state.project_config.get("research_questions", {}).get("seeds", ())
            if isinstance(item, Mapping) and item.get("seed_id")
        }
        authoritative_parent_ids = {
            str(item["id"])
            for item in state.effective_objects()
            if item.get("kind") == "research_question"
            and item.get("project_id") == state.project_ref
            and item.get("adoption_state") == "approved"
            and item.get("id")
        }

        for index, item in enumerate(questions):
            derived_seed_ids = tuple(
                str(seed_id) for seed_id in item.get("derived_from_seed_ids", ())
            )
            unknown_seeds = sorted(set(derived_seed_ids) - configured_seeds)
            if unknown_seeds:
                raise ValueError(
                    f"questions[{index}].derived_from_seed_ids do not resolve in current Project Config: "
                    + ", ".join(unknown_seeds)
                )
            parent_question_id = item.get("parent_question_id")
            if (
                parent_question_id is not None
                and str(parent_question_id) not in authoritative_parent_ids
            ):
                raise ValueError(
                    f"questions[{index}].parent_question_id must resolve to a current "
                    "authoritative approved Research Question"
                )

        rq_candidates: list[dict[str, Any]] = []
        transition_actions: list[TransitionAction] = []
        affected_refs: list[ObjectRef] = []
        seed_bindings: list[dict[str, Any]] = []
        all_seed_ids: list[str] = []

        for item in questions:
            rq_id = self._ids.new("RQ-")
            rq_candidate: dict[str, Any] = {
                "schema_version": "0.1.0",
                "id": rq_id,
                "kind": "research_question",
                "revision": 0,
                "project_id": state.project_ref,
                "text": str(item["text"]),
                "acceptance_criteria": list(item.get("acceptance_criteria", ())),
                "scope_limits": list(item.get("scope_limits", ())),
                "adoption_state": "approved",
            }
            if "rationale" in item:
                rq_candidate["rationale"] = str(item["rationale"])
            parent_question_id = item.get("parent_question_id")
            if parent_question_id is not None:
                rq_candidate["parent_question_id"] = str(parent_question_id)

            rq_candidates.append(rq_candidate)
            transition_actions.append(TransitionAction(
                TransitionKind.CREATE_OBJECT,
                {"object": rq_candidate},
                decision_refs=(),
                source_refs=(),
            ))
            affected_refs.append(ObjectRef("research_question", rq_id))

            derived_seed_ids = [
                str(seed_id) for seed_id in item.get("derived_from_seed_ids", ())
            ]
            if derived_seed_ids:
                seed_bindings.append({
                    "research_question_id": rq_id,
                    "project_config_seed_ids": derived_seed_ids,
                })
                for seed_id in derived_seed_ids:
                    if seed_id not in all_seed_ids:
                        all_seed_ids.append(seed_id)

        provenance: dict[str, Any] = {
            "producer": "research_question.propose_many@0.1.0",
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
        if all_seed_ids:
            provenance["project_config_seed_ids"] = all_seed_ids
            provenance["research_question_seed_bindings"] = seed_bindings

        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            source_refs=(),
            proposed_actions=tuple(transition_actions),
            affected_refs=tuple(affected_refs),
            rationale="Research Question batch candidate proposed through bounded semantic ingress.",
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
                    "kind": action.kind.value,
                    "payload": deepcopy(dict(action.payload)),
                    "decision_refs": list(action.decision_refs),
                    "source_refs": list(action.source_refs),
                }
                for action in transition_actions
            ],
            "affected_refs": [
                {"kind": "research_question", "id": question["id"]}
                for question in rq_candidates
            ],
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
                "research_questions": deepcopy(rq_candidates),
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )
