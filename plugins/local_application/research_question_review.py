from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import HarnessServiceResult
from core.runtime import ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind


_OPERATIONS = {"KEEP", "REFINE", "SPLIT", "MERGE", "CLOSE"}
_COMMON_FIELDS = {
    "operation", "question_ids", "rationale", "review_inputs",
    "text", "acceptance_criteria", "scope_limits", "questions",
}
_REVIEW_INPUT_FIELDS = {"uncovered_attention_ids", "evidence_gap_ids", "publication_feedback_ids", "project_input_ids"}
_QUESTION_FIELDS = {"text", "rationale", "acceptance_criteria", "scope_limits"}
_MAX_QUESTION_IDS = 16
_MAX_SPLIT_QUESTIONS = 16
_MAX_LIST_ITEMS = 64
_MAX_ID_LENGTH = 256
_MAX_TEXT_LENGTH = 8_192
_MAX_LIST_ITEM_LENGTH = 4_096


def _non_empty_string(value: Any, field: str, *, max_length: int = _MAX_TEXT_LENGTH) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{field} must contain at most {max_length} characters")


def _non_empty_strings(
    value: Any,
    field: str,
    *,
    min_items: int = 0,
    max_items: int = _MAX_LIST_ITEMS,
    max_length: int = _MAX_LIST_ITEM_LENGTH,
) -> None:
    if not isinstance(value, list) or len(value) < min_items or len(value) > max_items or any(
        not isinstance(item, str) or not item.strip() or len(item) > max_length
        for item in value
    ):
        raise ValueError(
            f"{field} must be an array of {min_items} through {max_items} non-empty strings "
            f"with at most {max_length} characters each"
        )
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must not contain duplicates")


def research_question_review_payload(payload: Mapping[str, Any]) -> None:
    unknown = set(payload) - _COMMON_FIELDS
    if unknown:
        raise ValueError(
            "research_question.review payload contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    operation = payload.get("operation")
    if operation not in _OPERATIONS:
        raise ValueError("operation must be one of KEEP, REFINE, SPLIT, MERGE, CLOSE")
    _non_empty_strings(
        payload.get("question_ids"),
        "question_ids",
        min_items=1,
        max_items=_MAX_QUESTION_IDS,
        max_length=_MAX_ID_LENGTH,
    )
    question_ids = payload["question_ids"]
    if operation == "MERGE" and len(question_ids) < 2:
        raise ValueError("MERGE requires at least two question_ids")
    if operation != "MERGE" and len(question_ids) != 1:
        raise ValueError(f"{operation} requires exactly one question_id")
    rationale = payload.get("rationale")
    _non_empty_string(rationale, "rationale")
    review_inputs = payload.get("review_inputs", {})
    if not isinstance(review_inputs, Mapping) or set(review_inputs) - _REVIEW_INPUT_FIELDS:
        raise ValueError("review_inputs contains unknown fields")
    for field, value in review_inputs.items():
        _non_empty_strings(value, f"review_inputs.{field}")

    if operation in {"REFINE", "MERGE"}:
        _non_empty_string(payload.get("text"), f"{operation}.text")
        for field in ("acceptance_criteria", "scope_limits"):
            if field in payload:
                _non_empty_strings(payload[field], field)
    elif any(field in payload for field in ("text", "acceptance_criteria", "scope_limits")):
        raise ValueError(f"{operation} does not accept text/acceptance_criteria/scope_limits")

    if operation == "SPLIT":
        questions = payload.get("questions")
        if (
            not isinstance(questions, list)
            or len(questions) < 2
            or len(questions) > _MAX_SPLIT_QUESTIONS
        ):
            raise ValueError(
                f"SPLIT requires between 2 and {_MAX_SPLIT_QUESTIONS} questions"
            )
        for index, item in enumerate(questions):
            if not isinstance(item, Mapping) or set(item) - _QUESTION_FIELDS:
                raise ValueError(f"questions[{index}] contains unknown fields")
            _non_empty_string(item.get("text"), f"questions[{index}].text")
            if "rationale" in item:
                _non_empty_string(item["rationale"], f"questions[{index}].rationale")
            for field in ("acceptance_criteria", "scope_limits"):
                if field in item:
                    _non_empty_strings(item[field], f"questions[{index}].{field}")
    elif "questions" in payload:
        raise ValueError(f"{operation} does not accept questions")


def _question_by_id(state, question_id: str) -> Mapping[str, Any]:
    question = next((
        item for item in state.effective_objects()
        if item.get("kind") == "research_question"
        and item.get("id") == question_id
        and item.get("project_id") == state.project_ref
        and item.get("adoption_state") == "approved"
    ), None)
    if question is None:
        raise ValueError(
            f"question_ids must resolve to current authoritative approved Research Questions: {question_id}"
        )
    return question


def _downstream_refs(state, question_ids: set[str]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in state.effective_objects():
        if (
            item.get("kind") == "research_question"
            and str(item.get("id", "")) in question_ids
        ):
            continue
        linked = False
        for field in ("question_id", "parent_question_id"):
            if str(item.get(field, "")) in question_ids:
                linked = True
        for field in ("question_ids", "rq_ids", "research_question_ids"):
            value = item.get(field, ())
            if isinstance(value, (list, tuple)) and question_ids.intersection(str(x) for x in value):
                linked = True
        target = item.get("target")
        if isinstance(target, Mapping) and target.get("kind") == "research_question" and str(target.get("id")) in question_ids:
            linked = True
        if linked and item.get("id"):
            refs.append({"kind": str(item.get("kind", "unknown")), "id": str(item["id"])})
    refs.sort(key=lambda item: (item["kind"], item["id"]))
    return refs


def _review_meta(operation: str, sources: list[Mapping[str, Any]], payload: Mapping[str, Any], downstream: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "question_lineage_id": str(sources[0].get("question_lineage_id") or sources[0]["id"]),
        "derived_from_question_revisions": [
            {"id": str(item["id"]), "revision": int(item["revision"])} for item in sources
        ],
        "question_delta": operation,
        "review_inputs": deepcopy(dict(payload.get("review_inputs", {}))),
        "downstream_review_required_refs": deepcopy(downstream),
    }


class ResearchQuestionReviewHandler:
    """Emit KEEP or one material, snapshot-bound Question Delta candidate."""

    def __init__(self, store, id_provider) -> None:
        self._store = store
        self._ids = id_provider

    def execute(self, payload, *, state, actor, proposal):
        research_question_review_payload(payload)
        operation = str(payload["operation"])
        sources = [_question_by_id(state, str(qid)) for qid in payload["question_ids"]]
        review_inputs = deepcopy(dict(payload.get("review_inputs", {})))
        if operation == "KEEP":
            source = sources[0]
            return HarnessServiceResult(
                result_reference=str(source["id"]),
                data={
                    "question_review": {
                        "operation": "KEEP",
                        "question_id": str(source["id"]),
                        "active_revision": int(source["revision"]),
                        "question_lineage_id": str(source.get("question_lineage_id") or source["id"]),
                        "review_inputs": review_inputs,
                        "bound_snapshot": {
                            "snapshot_id": str(state.current_snapshot["id"]),
                            "snapshot_digest": str(state.current_snapshot["content_digest"]),
                        },
                        "material_change": False,
                    }
                },
                research_state_mutation_performed=False,
            )

        source_ids = {str(item["id"]) for item in sources}
        downstream = _downstream_refs(state, source_ids)
        actions: list[TransitionAction] = []
        affected: list[ObjectRef] = []
        outputs: list[dict[str, Any]] = []

        if operation == "REFINE":
            source = sources[0]
            revised = deepcopy(dict(source))
            revised["revision"] = int(source["revision"]) + 1
            revised["text"] = str(payload["text"])
            if "acceptance_criteria" in payload:
                revised["acceptance_criteria"] = list(payload["acceptance_criteria"])
            if "scope_limits" in payload:
                revised["scope_limits"] = list(payload["scope_limits"])
            revised["rationale"] = str(payload["rationale"])
            revised.update(_review_meta(operation, sources, payload, downstream))
            actions.append(TransitionAction(TransitionKind.REVISE_OBJECT, {"object": revised}))
            affected.append(ObjectRef("research_question", str(source["id"])))
            outputs.append(revised)

        elif operation == "CLOSE":
            source = sources[0]
            revised = deepcopy(dict(source))
            revised["revision"] = int(source["revision"]) + 1
            revised["adoption_state"] = "closed"
            revised["rationale"] = str(payload["rationale"])
            revised.update(_review_meta(operation, sources, payload, downstream))
            actions.append(TransitionAction(TransitionKind.REVISE_OBJECT, {"object": revised}))
            affected.append(ObjectRef("research_question", str(source["id"])))
            outputs.append(revised)

        elif operation == "SPLIT":
            source = sources[0]
            closed = deepcopy(dict(source))
            closed["revision"] = int(source["revision"]) + 1
            closed["adoption_state"] = "closed"
            closed["rationale"] = str(payload["rationale"])
            closed.update(_review_meta(operation, sources, payload, downstream))
            actions.append(TransitionAction(TransitionKind.REVISE_OBJECT, {"object": closed}))
            affected.append(ObjectRef("research_question", str(source["id"])))
            outputs.append(closed)
            for item in payload["questions"]:
                new_id = self._ids.new("RQ-")
                created = {
                    "schema_version": "0.1.0", "id": new_id, "kind": "research_question",
                    "revision": 0, "project_id": state.project_ref, "text": str(item["text"]),
                    "acceptance_criteria": list(item.get("acceptance_criteria", ())),
                    "scope_limits": list(item.get("scope_limits", ())), "adoption_state": "approved",
                    "rationale": str(item.get("rationale") or payload["rationale"]),
                    "question_lineage_id": str(source.get("question_lineage_id") or source["id"]),
                    "derived_from_question_revisions": [{"id": str(source["id"]), "revision": int(source["revision"])}],
                    "question_delta": "SPLIT", "review_inputs": review_inputs,
                    "downstream_review_required_refs": deepcopy(downstream),
                }
                actions.append(TransitionAction(TransitionKind.CREATE_OBJECT, {"object": created}))
                affected.append(ObjectRef("research_question", new_id)); outputs.append(created)

        elif operation == "MERGE":
            for source in sources:
                closed = deepcopy(dict(source))
                closed["revision"] = int(source["revision"]) + 1
                closed["adoption_state"] = "closed"
                closed["rationale"] = str(payload["rationale"])
                closed.update(_review_meta(operation, sources, payload, downstream))
                closed["question_lineage_id"] = str(source.get("question_lineage_id") or source["id"])
                actions.append(TransitionAction(TransitionKind.REVISE_OBJECT, {"object": closed}))
                affected.append(ObjectRef("research_question", str(source["id"])))
                outputs.append(closed)
            new_id = self._ids.new("RQ-")
            created = {
                "schema_version": "0.1.0", "id": new_id, "kind": "research_question",
                "revision": 0, "project_id": state.project_ref, "text": str(payload["text"]),
                "acceptance_criteria": list(payload.get("acceptance_criteria", ())),
                "scope_limits": list(payload.get("scope_limits", ())), "adoption_state": "approved",
                "rationale": str(payload["rationale"]), "question_lineage_id": new_id,
                "derived_from_question_revisions": [
                    {"id": str(item["id"]), "revision": int(item["revision"])} for item in sources
                ],
                "question_delta": "MERGE", "review_inputs": review_inputs,
                "downstream_review_required_refs": deepcopy(downstream),
            }
            actions.append(TransitionAction(TransitionKind.CREATE_OBJECT, {"object": created}))
            affected.append(ObjectRef("research_question", new_id)); outputs.append(created)

        provenance = {
            "producer": "research_question.review@0.1.0",
            "question_delta": operation,
            "source_action_proposal": {
                "proposal_id": str(proposal["proposal_id"]),
                "proposal_digest": str(proposal["proposal_digest"]),
            },
            "source_input_id": str(proposal["source"]["input_id"]),
            "source_question_revisions": [
                {"id": str(item["id"]), "revision": int(item["revision"])} for item in sources
            ],
            "review_inputs": review_inputs,
            "project_config": {"ref": state.project_config_ref, "digest": state.project_config_digest},
        }
        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"), project_ref=state.project_ref,
            lineage_ref=state.lineage_ref, source_refs=(), proposed_actions=tuple(actions),
            affected_refs=tuple(affected), rationale=str(payload["rationale"]),
            required_human_decision_kinds=("research_revision",),
            current_snapshot_ref=str(state.current_snapshot["id"]),
            current_snapshot_digest=str(state.current_snapshot["content_digest"]),
            provenance=provenance, candidate_only=True,
        ).with_calculated_digest()
        candidate_wire = {
            "proposal_id": candidate.proposal_id, "project_ref": candidate.project_ref,
            "lineage_ref": candidate.lineage_ref, "source_refs": [],
            "proposed_actions": [{
                "kind": action.kind.value, "payload": deepcopy(dict(action.payload)),
                "decision_refs": [], "source_refs": [],
            } for action in actions],
            "affected_refs": [{"kind": ref.kind, "id": ref.id} for ref in affected],
            "rationale": candidate.rationale,
            "required_human_decision_kinds": list(candidate.required_human_decision_kinds),
            "current_snapshot_ref": candidate.current_snapshot_ref,
            "current_snapshot_digest": candidate.current_snapshot_digest,
            "provenance": deepcopy(provenance), "candidate_only": True,
            "proposal_digest": candidate.proposal_digest,
        }
        self._store.store_state_delta_proposal(candidate.proposal_id, candidate_wire)
        return HarnessServiceResult(
            result_reference=candidate.proposal_id,
            data={
                "question_delta": {"operation": operation, "questions": deepcopy(outputs), "downstream_review_required_refs": deepcopy(downstream)},
                "state_delta_proposal_id": candidate.proposal_id,
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )
