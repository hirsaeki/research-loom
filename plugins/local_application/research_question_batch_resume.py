from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from plugins.local_application.resume import (
    DEFAULT_RESUME_LIMITS,
    _question_projection,
    _validated_action_proposal,
    _validated_confirmation_request,
    build_resume_context as _build_resume_context,
)
from plugins.local_conversation_store.resume import _validated_state_delta
from plugins.local_decision_store.resume import decision_requests_for_project


_BATCH_PRODUCER = "research_question.propose_many@0.1.0"
_BATCH_ACTION = "research_question.propose_many"


def _batch_candidates_for_project(store, project_ref: str, *, limit: int):
    if limit <= 0:
        raise ValueError("Research Question candidate query limit must be positive")
    try:
        with store._lock:
            malformed = store._db.execute(
                "SELECT 1 FROM state_delta_proposals WHERE NOT json_valid(payload_json) LIMIT 1"
            ).fetchone()
            if malformed is not None:
                raise ConversationRuntimeError(
                    "RESUME-CANDIDATE-001", "stored StateDeltaProposal JSON is malformed"
                )
            rows = store._db.execute(
                """
                SELECT proposal_id, payload_json
                FROM state_delta_proposals
                WHERE json_extract(payload_json, '$.project_ref')=?
                  AND json_extract(payload_json, '$.candidate_only')=1
                  AND json_extract(payload_json, '$.provenance.producer')=?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (str(project_ref), _BATCH_PRODUCER, int(limit)),
            ).fetchall()
    except ConversationRuntimeError:
        raise
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "StateDeltaProposal listing is unreadable"
        ) from exc
    return tuple(
        _validated_state_delta(row, project_ref=str(project_ref))
        for row in rows
    )


def _batch_questions(candidate: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("producer") != _BATCH_PRODUCER:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "multi-RQ candidate producer binding is malformed"
        )
    snapshot_ref = candidate.get("current_snapshot_ref")
    snapshot_digest = candidate.get("current_snapshot_digest")
    if (
        not isinstance(snapshot_ref, str)
        or not snapshot_ref
        or not isinstance(snapshot_digest, str)
        or not snapshot_digest
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "RQ candidate snapshot binding is missing or malformed"
        )
    actions = candidate.get("proposed_actions")
    affected = candidate.get("affected_refs")
    if not isinstance(actions, list) or not isinstance(affected, list):
        raise ConversationRuntimeError("RESUME-CANDIDATE-001", "RQ candidate structure is malformed")

    questions: list[Mapping[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping) or action.get("kind") != "CREATE_OBJECT":
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001",
                "research_question.propose_many candidate may contain only Research Question CREATE_OBJECT actions",
            )
        payload = action.get("payload")
        obj = payload.get("object") if isinstance(payload, Mapping) else None
        if not isinstance(obj, Mapping) or obj.get("kind") != "research_question":
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001",
                "research_question.propose_many candidate contains a non-Research-Question action",
            )
        questions.append(obj)
    if len(questions) < 2:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001",
            "research_question.propose_many candidate must contain at least two Research Questions",
        )

    question_ids = [str(question.get("id") or "") for question in questions]
    affected_ids = [
        str(ref.get("id") or "")
        for ref in affected
        if isinstance(ref, Mapping) and ref.get("kind") == "research_question"
    ]
    if (
        any(not question_id for question_id in question_ids)
        or len(question_ids) != len(set(question_ids))
        or affected_ids != question_ids
        or len(affected) != len(question_ids)
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001",
            "multi-RQ candidate affected_refs do not exactly bind its Research Questions",
        )
    return tuple(questions)


def _batch_projection(
    application,
    project_id: str,
    *,
    candidate_limit: int,
    decision_limit: int,
    base: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    probe = _batch_candidates_for_project(
        application.conversation_store,
        project_id,
        limit=candidate_limit + 1,
    )
    truncated = len(probe) > candidate_limit
    candidates = probe[:candidate_limit]
    if not candidates:
        return [], truncated

    repo = application.state_repository
    lineage_id = repo.load_active_lineage_ref(project_id)
    state = repo.load_state_view(project_id, lineage_id)
    authoritative_ids = {
        str(item["id"])
        for item in state.effective_objects()
        if item.get("kind") == "research_question"
        and item.get("project_id") == project_id
        and item.get("id")
    }

    decision_requests = decision_requests_for_project(
        application.decision_store,
        project_id,
        limit=decision_limit + 1,
    )[:decision_limit]
    decisions_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for request in decision_requests:
        source_candidate = request.get("source_state_delta_proposal")
        if not isinstance(source_candidate, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "Human Decision Request source candidate binding is malformed"
            )
        candidate_id = str(source_candidate.get("proposal_id") or "")
        decisions_by_candidate.setdefault(candidate_id, []).append({
            "request_id": str(request["request_id"]),
            "source_candidate_id": candidate_id,
            "status": str(request.get("operational_status", request.get("status", ""))),
        })

    confirmations_by_candidate: dict[str, list[str]] = {}
    for raw_request in base.get("workflow", {}).get("pending_confirmations", ()):
        if not isinstance(raw_request, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "pending Confirmation projection is malformed"
            )
        request = _validated_confirmation_request(raw_request, project_id=project_id)
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
            confirmations_by_candidate.setdefault(
                str(payload["state_delta_proposal_id"]), []
            ).append(str(request["confirmation_request_id"]))

    output: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["proposal_id"])
        questions = _batch_questions(candidate)
        provenance = candidate["provenance"]
        source_binding = provenance.get("source_action_proposal")
        if not isinstance(source_binding, Mapping):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "RQ candidate source Action Proposal binding is malformed"
            )
        source_proposal = _validated_action_proposal(
            application.conversation_store,
            str(source_binding.get("proposal_id") or ""),
            project_id=project_id,
        )
        if source_proposal.get("proposal_digest") != source_binding.get("proposal_digest"):
            raise ConversationRuntimeError(
                "RESUME-BINDING-001", "RQ candidate source Action Proposal digest mismatch"
            )
        if source_proposal.get("action", {}).get("action_type") != _BATCH_ACTION:
            raise ConversationRuntimeError(
                "RESUME-BINDING-001",
                "multi-RQ candidate source action is not research_question.propose_many",
            )

        for request in decision_requests:
            source_candidate = request.get("source_state_delta_proposal", {})
            if str(source_candidate.get("proposal_id") or "") == candidate_id:
                if str(source_candidate.get("proposal_digest") or "") != str(candidate["proposal_digest"]):
                    raise ConversationRuntimeError(
                        "RESUME-BINDING-001",
                        "Human Decision Request candidate digest binding is invalid",
                    )

        snapshot_ref = str(candidate["current_snapshot_ref"])
        snapshot_digest = str(candidate["current_snapshot_digest"])
        question_rows = [
            _question_projection(question, error_code="RESUME-CANDIDATE-001")
            for question in questions
        ]
        output.append({
            "state_delta_proposal_id": candidate_id,
            "proposal_digest": str(candidate["proposal_digest"]),
            "batch_size": len(question_rows),
            "questions": question_rows,
            "bound_snapshot": {
                "snapshot_id": snapshot_ref,
                "content_digest": snapshot_digest,
            },
            "bound_to_current_snapshot": (
                snapshot_ref == str(state.current_snapshot["id"])
                and snapshot_digest == str(state.current_snapshot["content_digest"])
            ),
            "authoritative_same_ids": [
                question["id"] for question in question_rows if question["id"] in authoritative_ids
            ],
            "source_action_proposal": {
                "proposal_id": str(source_proposal["proposal_id"]),
                "created_at": str(source_proposal["created_at"]),
            },
            "pending_confirmation_request_ids": sorted(
                confirmations_by_candidate.get(candidate_id, ())
            ),
            "human_decision_requests": deepcopy(
                decisions_by_candidate.get(candidate_id, ())
            ),
        })
    return output, truncated


def build_resume_context(
    application,
    project_id: str,
    *,
    limits: Mapping[str, int] | None = None,
) -> Mapping[str, Any]:
    """Add PR33 batch RQ candidates to the unchanged PR31 resume projection."""
    base = deepcopy(dict(_build_resume_context(application, project_id, limits=limits)))
    candidate_limit = int(
        (limits or {}).get(
            "research_question_candidates",
            DEFAULT_RESUME_LIMITS["research_question_candidates"],
        )
    )
    decision_limit = int(
        (limits or {}).get(
            "human_decision_requests",
            DEFAULT_RESUME_LIMITS["human_decision_requests"],
        )
    )
    batches, batches_truncated = _batch_projection(
        application,
        project_id,
        candidate_limit=candidate_limit,
        decision_limit=decision_limit,
        base=base,
    )
    if not batches:
        if batches_truncated:
            base["truncated"]["research_question_candidates"] = True
        return base

    candidates = list(base["research_questions"]["candidates"])
    candidates.extend(batches)
    candidates.sort(
        key=lambda item: (
            str(item.get("source_action_proposal", {}).get("created_at", "")),
            str(item.get("state_delta_proposal_id", "")),
        ),
        reverse=True,
    )
    combined_truncated = len(candidates) > candidate_limit
    base["research_questions"]["candidates"] = candidates[:candidate_limit]
    base["truncated"]["research_question_candidates"] = bool(
        base["truncated"].get("research_question_candidates")
        or batches_truncated
        or combined_truncated
    )
    return base
