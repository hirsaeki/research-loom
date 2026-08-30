from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.conversation.validation import WorkConversationValidator
from plugins.local_attention_resume import attention_maps_for_project, validate_active_attention_binding
from plugins.local_conversation_store.resume import research_question_candidates_for_project
from plugins.local_decision_store.resume import decision_requests_for_project
from plugins.local_execution_store.status import pending_runs_for_project, recent_runs_for_project


DEFAULT_RESUME_LIMITS = {
    "authoritative_research_questions": 100,
    "research_question_candidates": 100,
    "attention_maps": 50,
    "human_decision_requests": 100,
    "pending_confirmations": 100,
    "pending_human_decisions": 100,
    "pending_runs": 100,
    "recent_runs": 20,
}
_CONVERSATION_VALIDATOR = WorkConversationValidator()
_STATUS_ITEM_LIMIT = 100
_ATTENTION_ACTIVATION_ITEM_LIMIT = 100


def _status_projection(
    application,
    project_id: str,
    *,
    pending_confirmation_limit: int = _STATUS_ITEM_LIMIT,
    pending_run_limit: int = _STATUS_ITEM_LIMIT,
) -> Mapping[str, Any]:
    repo = application.state_repository
    lineage_id = repo.load_active_lineage_ref(project_id)
    state = repo.load_state_view(project_id, lineage_id)
    confirmations = application.conversation_store.list_pending_confirmation_requests(
        project_id, limit=pending_confirmation_limit + 1
    )
    decisions = decision_requests_for_project(
        application.decision_store,
        project_id,
        limit=_STATUS_ITEM_LIMIT + 1,
        statuses=("PENDING", "RESOLVING"),
    )
    runs = pending_runs_for_project(
        application.execution_store,
        project_id,
        limit=pending_run_limit + 1,
    )
    snapshot = state.current_snapshot
    return {
        "status": "OK",
        "project_id": project_id,
        "active_lineage": state.active_lineage_ref,
        "snapshot": {
            "snapshot_id": str(snapshot["id"]),
            "revision": int(snapshot.get("revision", 0)),
            "content_digest": str(snapshot["content_digest"]),
        },
        "bindings": {
            "project_config": {"ref": state.project_config_ref, "digest": state.project_config_digest},
            "effective_profile_set": {
                "ref": state.effective_profile_set_ref,
                "digest": state.effective_profile_set_digest,
            },
        },
        "pending_confirmations": deepcopy(list(confirmations[:pending_confirmation_limit])),
        "pending_human_decisions": deepcopy(list(decisions[:_STATUS_ITEM_LIMIT])),
        "pending_runs": [
            {
                "run_id": run.run_id,
                "capability_id": run.capability_id,
                "function_id": run.function_id,
                "execution_mode": run.execution_mode,
                "status": run.status.value,
                "lineage_ref": run.lineage_ref,
                "snapshot_ref": run.snapshot_ref,
                "snapshot_digest": run.snapshot_digest,
            }
            for run in runs[:pending_run_limit]
        ],
        "truncated": {
            "pending_confirmations": len(confirmations) > pending_confirmation_limit,
            "pending_human_decisions": len(decisions) > _STATUS_ITEM_LIMIT,
            "pending_runs": len(runs) > pending_run_limit,
        },
    }


def _validated_limits(limits: Mapping[str, int] | None) -> dict[str, int]:
    effective = dict(DEFAULT_RESUME_LIMITS)
    if limits is None:
        return effective
    unknown = set(limits) - set(effective)
    if unknown:
        raise ValueError("unknown resume context limits: " + ", ".join(sorted(unknown)))
    for key, raw_value in limits.items():
        value = int(raw_value)
        maximum = DEFAULT_RESUME_LIMITS[str(key)]
        if value <= 0 or value > maximum:
            raise ValueError(
                f"resume context limit must be between 1 and {maximum}: {key}"
            )
        effective[str(key)] = value
    return effective


def _limit(limits: Mapping[str, int], key: str) -> int:
    value = int(limits[key])
    maximum = DEFAULT_RESUME_LIMITS[key]
    if value <= 0 or value > maximum:
        raise ValueError(f"resume context limit must be between 1 and {maximum}: {key}")
    return value


def _validated_action_proposal(store, proposal_id: str, *, project_id: str) -> Mapping[str, Any]:
    proposal = store.load_proposal(proposal_id)
    if proposal is None:
        raise ConversationRuntimeError(
            "RESUME-BINDING-001", f"bound Action Proposal does not resolve: {proposal_id}"
        )
    _CONVERSATION_VALIDATOR.validate(proposal)
    if str(proposal.get("project_id")) != project_id:
        raise ConversationRuntimeError(
            "RESUME-BINDING-001", "bound Action Proposal belongs to a different project"
        )
    return proposal


def _validated_confirmation_request(document: Mapping[str, Any], *, project_id: str) -> Mapping[str, Any]:
    _CONVERSATION_VALIDATOR.validate(document)
    if str(document.get("project_id")) != project_id:
        raise ConversationRuntimeError(
            "RESUME-BINDING-001", "Confirmation Request belongs to a different project"
        )
    return document


def _rq_candidate(candidate: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    if candidate.get("candidate_only") is not True:
        return None
    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("producer") != "research_question.propose@0.1.0":
        return None
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
    matches: list[Mapping[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping) or action.get("kind") != "CREATE_OBJECT":
            continue
        payload = action.get("payload")
        obj = payload.get("object") if isinstance(payload, Mapping) else None
        if isinstance(obj, Mapping) and obj.get("kind") == "research_question":
            matches.append(obj)
    if len(matches) != 1:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "research_question.propose candidate must contain one Research Question CREATE_OBJECT"
        )
    question = matches[0]
    question_id = str(question.get("id") or "")
    if not question_id or not any(
        isinstance(ref, Mapping)
        and ref.get("kind") == "research_question"
        and str(ref.get("id") or "") == question_id
        for ref in affected
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "RQ candidate affected_refs do not bind the proposed Research Question"
        )
    return question, provenance


def _question_revision(question: Mapping[str, Any], *, error_code: str) -> int:
    if "revision" not in question:
        raise ConversationRuntimeError(
            error_code, "Research Question revision is missing or malformed"
        )
    revision = question["revision"]
    if type(revision) is not int or revision < 0:
        raise ConversationRuntimeError(
            error_code, "Research Question revision is missing or malformed"
        )
    return revision


def _question_projection(
    question: Mapping[str, Any],
    *,
    error_code: str,
) -> dict[str, Any]:
    question_id = question.get("id")
    text = question.get("text")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ConversationRuntimeError(error_code, "Research Question id is missing or malformed")
    if not isinstance(text, str) or not text.strip():
        raise ConversationRuntimeError(error_code, "Research Question text is missing or malformed")
    revision = _question_revision(question, error_code=error_code)
    result = {
        "id": question_id,
        "revision": revision,
        "text": text,
        "acceptance_criteria": deepcopy(list(question.get("acceptance_criteria", ()))),
        "scope_limits": deepcopy(list(question.get("scope_limits", ()))),
    }
    for key in ("parent_question_id", "rationale", "adoption_state", "decision_ids"):
        if key in question:
            result[key] = deepcopy(question[key])
    return result


def _project_projection(project_config: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    project = project_config.get("project")
    if not isinstance(project, Mapping):
        raise ConversationRuntimeError("RESUME-PROJECT-001", "Project Config project section is malformed")
    scope = project_config.get("scope", {})
    if not isinstance(scope, Mapping):
        raise ConversationRuntimeError("RESUME-PROJECT-001", "Project Config scope section is malformed")
    in_scope = scope.get("in_scope")
    out_of_scope = scope.get("out_of_scope")
    if not isinstance(in_scope, list) or not isinstance(out_of_scope, list):
        raise ConversationRuntimeError(
            "RESUME-PROJECT-001", "Project Config scope lists are missing or malformed"
        )
    configured_project_id = project.get("project_id")
    title = project.get("title")
    if (
        not isinstance(configured_project_id, str)
        or not configured_project_id.strip()
        or configured_project_id != project_id
    ):
        raise ConversationRuntimeError(
            "RESUME-PROJECT-001", "Project Config project identity does not bind the requested project"
        )
    if not isinstance(title, str) or not title.strip():
        raise ConversationRuntimeError("RESUME-PROJECT-001", "Project Config project title is missing")
    return {
        "project_id": configured_project_id,
        "title": title,
        "objective": deepcopy(project.get("objective")),
        "scope": {
            "in_scope": deepcopy(in_scope),
            "out_of_scope": deepcopy(out_of_scope),
        },
    }


def _run_projection(run) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "capability_id": run.capability_id,
        "function_id": run.function_id,
        "execution_mode": run.execution_mode,
        "status": run.status.value,
        "prepared_at": run.prepared_at,
        "completed_at": run.completed_at,
        "handoff_ref": run.handoff_ref,
        "snapshot_binding": {
            "lineage_ref": run.lineage_ref,
            "snapshot_ref": run.snapshot_ref,
            "snapshot_digest": run.snapshot_digest,
        },
    }


def build_resume_context(
    application,
    project_id: str,
    *,
    limits: Mapping[str, int] | None = None,
) -> Mapping[str, Any]:
    """Build one bounded read-only projection over existing production stores."""
    effective_limits = _validated_limits(limits)
    pending_confirmation_limit = _limit(effective_limits, "pending_confirmations")
    pending_run_limit = _limit(effective_limits, "pending_runs")
    status_projection = _status_projection(
        application,
        project_id,
        pending_confirmation_limit=pending_confirmation_limit,
        pending_run_limit=pending_run_limit,
    )

    repo = application.state_repository
    lineage_id = repo.load_active_lineage_ref(project_id)
    state = repo.load_state_view(project_id, lineage_id)
    if (
        str(status_projection.get("project_id")) != project_id
        or str(status_projection.get("active_lineage")) != state.active_lineage_ref
        or status_projection.get("snapshot", {}).get("snapshot_id") != str(state.current_snapshot["id"])
        or status_projection.get("snapshot", {}).get("content_digest") != str(state.current_snapshot["content_digest"])
    ):
        raise ConversationRuntimeError(
            "RESUME-STATE-001", "status projection does not bind the current authoritative Research State"
        )

    project_config = state.project_config
    project_projection = _project_projection(project_config, project_id)

    authoritative_all = [
        item
        for item in state.effective_objects()
        if item.get("kind") == "research_question" and item.get("project_id") == project_id
    ]
    authoritative_all.sort(
        key=lambda item: (
            str(item.get("id", "")),
            _question_revision(item, error_code="RESUME-STATE-001"),
        )
    )
    authoritative_limit = _limit(effective_limits, "authoritative_research_questions")
    authoritative = [
        _question_projection(item, error_code="RESUME-STATE-001")
        for item in authoritative_all[:authoritative_limit]
    ]
    authoritative_ids = {str(item["id"]) for item in authoritative_all}

    candidate_limit = _limit(effective_limits, "research_question_candidates")
    candidate_probe = research_question_candidates_for_project(
        application.conversation_store,
        project_id,
        limit=candidate_limit + 1,
    )
    rq_candidates: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    for candidate in candidate_probe:
        parsed = _rq_candidate(candidate)
        if parsed is not None:
            question, provenance = parsed
            rq_candidates.append((candidate, question, provenance))
    candidates_truncated = len(rq_candidates) > candidate_limit
    rq_candidates = rq_candidates[:candidate_limit]

    decision_limit = _limit(effective_limits, "human_decision_requests")
    decision_probe = decision_requests_for_project(
        application.decision_store,
        project_id,
        limit=decision_limit + 1,
    )
    decisions_truncated = len(decision_probe) > decision_limit
    decision_requests = decision_probe[:decision_limit]

    pending_decision_limit = _limit(effective_limits, "pending_human_decisions")
    pending_decision_probe = decision_requests_for_project(
        application.decision_store,
        project_id,
        limit=pending_decision_limit + 1,
        statuses=("PENDING", "RESOLVING"),
    )
    pending_decisions_truncated = len(pending_decision_probe) > pending_decision_limit
    pending_decisions = pending_decision_probe[:pending_decision_limit]
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
    for raw_request in status_projection.get("pending_confirmations", ()):
        if not isinstance(raw_request, Mapping):
            raise ConversationRuntimeError("RESUME-BINDING-001", "pending Confirmation projection is malformed")
        request = _validated_confirmation_request(raw_request, project_id=project_id)
        binding = request.get("proposal_binding")
        if not isinstance(binding, Mapping):
            raise ConversationRuntimeError("RESUME-BINDING-001", "Confirmation proposal binding is malformed")
        proposal = _validated_action_proposal(
            application.conversation_store,
            str(binding.get("proposal_id") or ""),
            project_id=project_id,
        )
        if proposal.get("proposal_digest") != binding.get("proposal_digest"):
            raise ConversationRuntimeError("RESUME-BINDING-001", "Confirmation Action Proposal digest binding is invalid")
        action = proposal.get("action")
        payload = action.get("payload") if isinstance(action, Mapping) else None
        if (
            isinstance(action, Mapping)
            and action.get("action_type") == "state.apply_candidate"
            and isinstance(payload, Mapping)
            and isinstance(payload.get("state_delta_proposal_id"), str)
        ):
            confirmations_by_candidate.setdefault(str(payload["state_delta_proposal_id"]), []).append(
                str(request["confirmation_request_id"])
            )

    candidate_output = []
    for candidate, question, provenance in rq_candidates:
        candidate_id = str(candidate["proposal_id"])
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
            raise ConversationRuntimeError("RESUME-BINDING-001", "RQ candidate source Action Proposal digest mismatch")
        if source_proposal.get("action", {}).get("action_type") != "research_question.propose":
            raise ConversationRuntimeError("RESUME-BINDING-001", "RQ candidate source action is not research_question.propose")
        for request in decision_requests:
            source_candidate = request.get("source_state_delta_proposal", {})
            if str(source_candidate.get("proposal_id") or "") == candidate_id:
                if str(source_candidate.get("proposal_digest") or "") != str(candidate["proposal_digest"]):
                    raise ConversationRuntimeError(
                        "RESUME-BINDING-001", "Human Decision Request candidate digest binding is invalid"
                    )
        snapshot_ref = str(candidate["current_snapshot_ref"])
        snapshot_digest = str(candidate["current_snapshot_digest"])
        candidate_output.append({
            "state_delta_proposal_id": candidate_id,
            "proposal_digest": str(candidate["proposal_digest"]),
            "question": _question_projection(question, error_code="RESUME-CANDIDATE-001"),
            "bound_snapshot": {
                "snapshot_id": snapshot_ref,
                "content_digest": snapshot_digest,
            },
            "bound_to_current_snapshot": (
                snapshot_ref == str(state.current_snapshot["id"])
                and snapshot_digest == str(state.current_snapshot["content_digest"])
            ),
            "authoritative_same_id": str(question["id"]) in authoritative_ids,
            "source_action_proposal": {
                "proposal_id": str(source_proposal["proposal_id"]),
                "created_at": str(source_proposal["created_at"]),
            },
            "pending_confirmation_request_ids": sorted(confirmations_by_candidate.get(candidate_id, ())),
            "human_decision_requests": deepcopy(decisions_by_candidate.get(candidate_id, ())),
        })

    attention_limit = _limit(effective_limits, "attention_maps")
    active_activation_id = None
    try:
        active, effective_attention = application.effective_attention.resolve(state)
        map_probe = attention_maps_for_project(
            application.attention_store,
            project_id,
            limit=attention_limit + 1,
            activation_limit=_ATTENTION_ACTIVATION_ITEM_LIMIT,
        )
        if active is not None:
            active_activation_id = validate_active_attention_binding(
                application.attention_store,
                project_id,
                active,
            )
    except Exception as exc:
        if isinstance(exc, ConversationRuntimeError):
            raise
        code = getattr(exc, "code", "RESUME-ATTENTION-001")
        message = getattr(exc, "message", str(exc))
        raise ConversationRuntimeError(str(code), str(message)) from exc
    maps_truncated = len(map_probe) > attention_limit
    stored_maps = []
    active_map_id = str(active["map_id"]) if active is not None else None
    activation_events_truncated = False
    for stored in map_probe[:attention_limit]:
        document = stored["map"]
        stored_activation_truncated = bool(stored.get("activation_ids_truncated", False))
        activation_events_truncated = activation_events_truncated or stored_activation_truncated
        stored_maps.append({
            "map_id": str(document["map_id"]),
            "map_digest": str(document["map_digest"]),
            "created_at": str(document["created_at"]),
            "activation": {
                "is_active": str(document["map_id"]) == active_map_id,
                "activation_ids": deepcopy(list(stored["activation_ids"])),
                "activation_ids_truncated": stored_activation_truncated,
            },
            "base": deepcopy(document["base"]),
            "items": deepcopy(list(document["items"])),
        })

    active_projection = None
    if active is not None:
        active_document = active["map"]
        active_projection = {
            "map_id": str(active["map_id"]),
            "map_digest": str(active["map_digest"]),
            "activation_id": str(active_activation_id),
            "created_at": str(active_document["created_at"]),
            "base": deepcopy(active_document["base"]),
            "items": deepcopy(list(active_document["items"])),
        }

    recent_limit = _limit(effective_limits, "recent_runs")
    recent_probe = recent_runs_for_project(
        application.execution_store,
        project_id,
        limit=recent_limit + 1,
    )
    recent_truncated = len(recent_probe) > recent_limit

    truncated = deepcopy(dict(status_projection.get("truncated", {})))
    truncated.update({
        "authoritative_research_questions": len(authoritative_all) > authoritative_limit,
        "research_question_candidates": candidates_truncated,
        "attention_maps": maps_truncated,
        "attention_activation_events": activation_events_truncated,
        "human_decision_requests": decisions_truncated,
        "pending_human_decisions": pending_decisions_truncated,
        "recent_runs": recent_truncated,
    })

    return {
        "status": "OK",
        "project": project_projection,
        "research_state": {
            "active_lineage": str(status_projection["active_lineage"]),
            "snapshot": deepcopy(status_projection["snapshot"]),
            "bindings": deepcopy(status_projection["bindings"]),
        },
        "research_questions": {
            "seeds": deepcopy(list(project_config.get("research_questions", {}).get("seeds", ()))),
            "authoritative": authoritative,
            "candidates": candidate_output,
        },
        "research_attention": {
            "baseline": deepcopy(list(project_config.get("research_attention", ()))),
            "active_map": active_projection,
            "effective": deepcopy(list(effective_attention)),
            "stored_maps": stored_maps,
        },
        "workflow": {
            "pending_confirmations": deepcopy(list(status_projection.get("pending_confirmations", ()))),
            "pending_human_decisions": deepcopy(list(pending_decisions)),
            "pending_runs": deepcopy(list(status_projection.get("pending_runs", ()))),
            "recent_runs": [_run_projection(run) for run in recent_probe[:recent_limit]],
        },
        "truncated": truncated,
    }
