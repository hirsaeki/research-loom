from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.conversation.validation import WorkConversationValidator
from plugins.local_conversation_store.resume import (
    research_question_review_candidates_for_project,
)
from plugins.local_decision_store.resume import decision_requests_for_project


_REVIEW_PRODUCER = "research_question.review@0.1.0"
_REVIEW_OPERATIONS = {"REFINE", "SPLIT", "MERGE", "CLOSE"}
_DEFAULT_CANDIDATE_LIMIT = 100
_DEFAULT_CONFIRMATION_LIMIT = 100
_DEFAULT_DECISION_LIMIT = 100
_VALIDATOR = WorkConversationValidator()


def _limit(limits: Mapping[str, int] | None, key: str, default: int) -> int:
    if limits is None or key not in limits:
        return default
    # Base resume has already validated the public limit values before this
    # extension is called. Keep a defensive positive check here for direct use.
    value = int(limits[key])
    if value <= 0:
        raise ValueError(f"resume context limit must be positive: {key}")
    return value


def _validated_action_proposal(store, proposal_id: str, *, project_id: str) -> Mapping[str, Any]:
    proposal = store.load_proposal(proposal_id)
    if proposal is None:
        raise ConversationRuntimeError(
            "RESUME-BINDING-001", f"bound Action Proposal does not resolve: {proposal_id}"
        )
    _VALIDATOR.validate(proposal)
    if str(proposal.get("project_id")) != project_id:
        raise ConversationRuntimeError(
            "RESUME-BINDING-001", "bound Action Proposal belongs to a different project"
        )
    return proposal


def _question_projection(question: Mapping[str, Any]) -> dict[str, Any]:
    question_id = question.get("id")
    text = question.get("text")
    revision = question.get("revision")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Research Question id is missing or malformed"
        )
    if not isinstance(text, str) or not text.strip():
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Research Question text is missing or malformed"
        )
    if type(revision) is not int or revision < 0:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Research Question revision is missing or malformed"
        )
    result = {
        "id": question_id,
        "revision": revision,
        "text": text,
        "acceptance_criteria": deepcopy(list(question.get("acceptance_criteria", ()))),
        "scope_limits": deepcopy(list(question.get("scope_limits", ()))),
    }
    for key in (
        "parent_question_id",
        "rationale",
        "adoption_state",
        "decision_ids",
        "question_lineage_id",
        "derived_from_question_revisions",
        "question_delta",
        "review_inputs",
        "downstream_review_required_refs",
    ):
        if key in question:
            result[key] = deepcopy(question[key])
    return result


def _review_questions(candidate: Mapping[str, Any]) -> tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("producer") != _REVIEW_PRODUCER:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate provenance is malformed"
        )
    operation = provenance.get("question_delta")
    if operation not in _REVIEW_OPERATIONS:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate has an invalid material Question Delta"
        )
    sources = provenance.get("source_question_revisions")
    if not isinstance(sources, list) or not sources:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate source revision binding is malformed"
        )
    source_ids: list[str] = []
    source_revision_by_id: dict[str, int] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001", "Question Review candidate source revision binding is malformed"
            )
        source_id = source.get("id")
        revision = source.get("revision")
        if (
            not isinstance(source_id, str)
            or not source_id
            or type(revision) is not int
            or revision < 0
            or source_id in source_revision_by_id
        ):
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001", "Question Review candidate source revision binding is malformed"
            )
        source_ids.append(source_id)
        source_revision_by_id[source_id] = revision
    if (operation == "MERGE" and len(source_ids) < 2) or (
        operation != "MERGE" and len(source_ids) != 1
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate source revision cardinality is invalid"
        )

    actions = candidate.get("proposed_actions")
    affected = candidate.get("affected_refs")
    if not isinstance(actions, list) or not isinstance(affected, list):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate structure is malformed"
        )
    revised: list[Mapping[str, Any]] = []
    created: list[Mapping[str, Any]] = []
    ordered: list[Mapping[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping) or action.get("kind") not in {
            "REVISE_OBJECT", "CREATE_OBJECT"
        }:
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001",
                "Question Review candidate may contain only Research Question REVISE_OBJECT/CREATE_OBJECT actions",
            )
        payload = action.get("payload")
        obj = payload.get("object") if isinstance(payload, Mapping) else None
        if not isinstance(obj, Mapping) or obj.get("kind") != "research_question":
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001", "Question Review candidate contains a non-Research-Question action"
            )
        ordered.append(obj)
        (revised if action.get("kind") == "REVISE_OBJECT" else created).append(obj)

    valid_shape = (
        (operation in {"REFINE", "CLOSE"} and len(revised) == 1 and not created)
        or (operation == "SPLIT" and len(revised) == 1 and len(created) >= 2)
        or (operation == "MERGE" and len(revised) >= 2 and len(created) == 1)
    )
    if not valid_shape or [str(item.get("id") or "") for item in revised] != source_ids:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate action composition does not match its Question Delta"
        )
    for item in revised:
        source_id = str(item.get("id") or "")
        if type(item.get("revision")) is not int or item["revision"] != source_revision_by_id[source_id] + 1:
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001", "Question Review candidate revised Research Question revision is invalid"
            )
    if any(type(item.get("revision")) is not int or item["revision"] != 0 for item in created):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate created Research Question must start at revision 0"
        )
    question_ids = [str(item.get("id") or "") for item in ordered]
    affected_ids = [
        str(ref.get("id") or "")
        for ref in affected
        if isinstance(ref, Mapping) and ref.get("kind") == "research_question"
    ]
    if (
        any(not question_id for question_id in question_ids)
        or len(question_ids) != len(set(question_ids))
        or len(affected) != len(question_ids)
        or affected_ids != question_ids
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Question Review candidate affected_refs do not bind its Research Questions"
        )
    return tuple(ordered), provenance


def _confirmation_ids_by_candidate(application, project_id: str, *, limit: int) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for request in application.conversation_store.list_pending_confirmation_requests(
        project_id, limit=limit
    ):
        if not isinstance(request, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "pending Confirmation projection is malformed"
            )
        _VALIDATOR.validate(request)
        binding = request.get("proposal_binding")
        if not isinstance(binding, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "Confirmation proposal binding is malformed"
            )
        proposal = _validated_action_proposal(
            application.conversation_store,
            str(binding.get("proposal_id") or ""),
            project_id=project_id,
        )
        if proposal.get("proposal_digest") != binding.get("proposal_digest"):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "Confirmation Action Proposal digest binding is invalid"
            )
        action = proposal.get("action")
        payload = action.get("payload") if isinstance(action, Mapping) else None
        if (
            isinstance(action, Mapping)
            and action.get("action_type") == "state.apply_candidate"
            and isinstance(payload, Mapping)
            and isinstance(payload.get("state_delta_proposal_id"), str)
        ):
            result.setdefault(str(payload["state_delta_proposal_id"]), []).append(
                str(request["confirmation_request_id"])
            )
    return result


def append_question_review_candidates(
    result: dict[str, Any],
    *,
    application,
    project_id: str,
    state,
    limits: Mapping[str, int] | None,
) -> None:
    candidate_limit = _limit(limits, "research_question_candidates", _DEFAULT_CANDIDATE_LIMIT)
    confirmation_limit = _limit(limits, "pending_confirmations", _DEFAULT_CONFIRMATION_LIMIT)
    decision_limit = _limit(limits, "human_decision_requests", _DEFAULT_DECISION_LIMIT)
    probe = research_question_review_candidates_for_project(
        application.conversation_store,
        project_id,
        limit=candidate_limit + 1,
    )
    review_truncated = len(probe) > candidate_limit
    confirmations = _confirmation_ids_by_candidate(
        application, project_id, limit=confirmation_limit
    )
    decision_probe = decision_requests_for_project(
        application.decision_store,
        project_id,
        limit=decision_limit,
    )
    decisions_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for request in decision_probe:
        source = request.get("source_state_delta_proposal")
        if not isinstance(source, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "Human Decision Request source candidate binding is malformed"
            )
        candidate_id = str(source.get("proposal_id") or "")
        decisions_by_candidate.setdefault(candidate_id, []).append({
            "request_id": str(request["request_id"]),
            "source_candidate_id": candidate_id,
            "status": str(request.get("operational_status", request.get("status", ""))),
        })

    authoritative_ids = {
        str(item.get("id"))
        for item in state.effective_objects()
        if item.get("kind") == "research_question" and item.get("id")
    }
    rows: list[dict[str, Any]] = []
    for candidate in probe[:candidate_limit]:
        questions, provenance = _review_questions(candidate)
        source_binding = provenance.get("source_action_proposal")
        if not isinstance(source_binding, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "Question Review source Action Proposal binding is malformed"
            )
        source_proposal = _validated_action_proposal(
            application.conversation_store,
            str(source_binding.get("proposal_id") or ""),
            project_id=project_id,
        )
        if (
            source_proposal.get("proposal_digest") != source_binding.get("proposal_digest")
            or source_proposal.get("action", {}).get("action_type") != "research_question.review"
        ):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "Question Review source Action Proposal binding is invalid"
            )
        candidate_id = str(candidate["proposal_id"])
        snapshot_ref = str(candidate["current_snapshot_ref"])
        snapshot_digest = str(candidate["current_snapshot_digest"])
        projected = [_question_projection(question) for question in questions]
        rows.append({
            "state_delta_proposal_id": candidate_id,
            "proposal_digest": str(candidate["proposal_digest"]),
            "bound_snapshot": {
                "snapshot_id": snapshot_ref,
                "content_digest": snapshot_digest,
            },
            "bound_to_current_snapshot": (
                snapshot_ref == str(state.current_snapshot["id"])
                and snapshot_digest == str(state.current_snapshot["content_digest"])
            ),
            "source_action_proposal": {
                "proposal_id": str(source_proposal["proposal_id"]),
                "created_at": str(source_proposal["created_at"]),
            },
            "pending_confirmation_request_ids": sorted(confirmations.get(candidate_id, ())),
            "human_decision_requests": deepcopy(decisions_by_candidate.get(candidate_id, ())),
            "question_delta": str(provenance["question_delta"]),
            "source_question_revisions": deepcopy(provenance["source_question_revisions"]),
            "questions": projected,
            "authoritative_same_ids": [
                question["id"] for question in projected if question["id"] in authoritative_ids
            ],
        })

    questions_section = result.get("research_questions")
    if not isinstance(questions_section, dict):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Research Question resume projection is malformed"
        )
    existing = questions_section.get("candidates")
    if not isinstance(existing, list):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "Research Question candidate projection is malformed"
        )
    combined = [*existing, *rows]
    combined.sort(
        key=lambda row: str(row.get("source_action_proposal", {}).get("created_at", "")),
        reverse=True,
    )
    questions_section["candidates"] = combined[:candidate_limit]
    truncated = result.get("truncated")
    if isinstance(truncated, dict):
        truncated["research_question_candidates"] = bool(
            truncated.get("research_question_candidates")
            or review_truncated
            or len(combined) > candidate_limit
        )
