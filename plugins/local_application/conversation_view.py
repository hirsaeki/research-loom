from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.runtime import canonical_digest

from .candidate_projection import build_candidate_projection


class ConversationViewError(ValueError):
    pass


_VIEWS = {None, "detail", "conversation"}
_OPERATIONAL_REQUEST_FIELDS = {"operational_status", "commit_id", "status_detail"}


def normalize_view(view: str | None) -> str:
    if view not in _VIEWS:
        raise ConversationViewError("view must be 'conversation' or 'detail'")
    return "detail" if view is None else view


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConversationViewError(f"{field} is malformed")
    return value


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConversationViewError(f"{field} is malformed")
    return value


def _copy_list(value: Any) -> list[Any]:
    return deepcopy(list(value)) if isinstance(value, (list, tuple)) else []


def _copy_optional(value: Mapping[str, Any], key: str, target: dict[str, Any]) -> None:
    if key in value:
        target[key] = deepcopy(value[key])


def semantic_object(value: Mapping[str, Any], *, authoritative: bool = False) -> dict[str, Any]:
    kind = value.get("kind")
    object_id = value.get("id")
    if not isinstance(kind, str) or not isinstance(object_id, str) or not object_id:
        raise ConversationViewError("candidate object identity is malformed")
    base: dict[str, Any] = {"kind": kind, "id": object_id}
    if type(value.get("revision")) is int:
        base["revision"] = int(value["revision"])

    if kind == "research_question":
        if not isinstance(value.get("text"), str):
            raise ConversationViewError("Research Question text is malformed")
        base.update({
            "text": value["text"],
            "acceptance_criteria": _copy_list(value.get("acceptance_criteria", [])),
            "scope_limits": _copy_list(value.get("scope_limits", [])),
        })
        for key in (
            "rationale",
            "parent_question_id",
            "question_lineage_id",
            "derived_from_question_revisions",
            "question_delta",
            "review_inputs",
            "downstream_review_required_refs",
        ):
            _copy_optional(value, key, base)
        if authoritative and isinstance(value.get("adoption_state"), str):
            base["current_status"] = value["adoption_state"]
        return base

    if kind == "recommendation":
        if not isinstance(value.get("statement"), str):
            raise ConversationViewError("Recommendation statement is malformed")
        base.update({
            "statement": value["statement"],
            "finding_ids": _copy_list(value.get("finding_ids", [])),
            "conditions": _copy_list(value.get("conditions", [])),
            "scope": _copy_list(value.get("scope", [])),
        })
        _copy_optional(value, "rationale", base)
        return base

    if kind == "argument":
        if not isinstance(value.get("conclusion"), str) or not isinstance(value.get("warrant"), str):
            raise ConversationViewError("Argument content is malformed")
        base.update({
            "conclusion": value["conclusion"],
            "warrant": value["warrant"],
            "question_ids": _copy_list(value.get("question_ids", [])),
            "conclusion_claim_id": deepcopy(value.get("conclusion_claim_id")),
            "premise_claim_ids": _copy_list(value.get("premise_claim_ids", [])),
            "finding_ids": _copy_list(value.get("finding_ids", [])),
            "evidence_ids": _copy_list(value.get("evidence_ids", [])),
            "qualifier": deepcopy(value.get("qualifier")),
            "counter_review_ids": _copy_list(value.get("counter_review_ids", [])),
            "implications": _copy_list(value.get("implications", [])),
        })
        _copy_optional(value, "rationale", base)
        return base

    # Known Desktop Research candidates can be represented by their semantic payload
    # without serializing the canonical object envelope.
    if kind in {"research_input", "source", "evidence", "finding", "next_action", "method"}:
        for key in (
            "title", "statement", "description", "result_summary", "normalized_statement",
            "locator", "source_id", "source_ids", "question_ids", "finding_ids", "evidence_ids",
            "counter_evidence_ids", "boundary_conditions", "limitations", "confidence", "rationale",
            "action_type", "instruction", "reason", "priority", "blocked_by", "source_type",
            "canonical_locator", "content_digest", "media_type", "byte_length", "origin_type",
        ):
            _copy_optional(value, key, base)
        return base

    return {
        "kind": kind,
        "id": object_id,
        **({"revision": int(value["revision"])} if type(value.get("revision")) is int else {}),
        "interpretation": "UNSUPPORTED_OBJECT_KIND",
    }


def candidate_relation(projection: Mapping[str, Any]) -> dict[str, Any]:
    subjects = _list(projection.get("subjects"), field="candidate_projection.subjects")
    output: list[dict[str, Any]] = []
    for item in subjects:
        row = _mapping(item, field="candidate_projection.subject")
        subject = _mapping(row.get("subject"), field="candidate_projection.subject.ref")
        current = row.get("current_value")
        candidate = row.get("candidate_value")
        if not isinstance(candidate, Mapping):
            raise ConversationViewError("candidate_projection candidate value is malformed")
        current_present = isinstance(current, Mapping)
        output.append({
            "subject": {
                "kind": str(subject.get("kind") or ""),
                "id": str(subject.get("id") or ""),
            },
            "current_value_present": current_present,
            "candidate_value_matches_current": (
                canonical_digest(current) == canonical_digest(candidate)
                if current_present else None
            ),
        })
    return {
        "bound_to_current_lineage": bool(projection.get("bound_to_current_lineage")),
        "bound_to_current_snapshot": bool(projection.get("bound_to_current_snapshot")),
        "subjects": output,
    }


def candidate_summary(candidate: Mapping[str, Any], state: Any) -> dict[str, Any]:
    projection = build_candidate_projection(candidate, state)
    actions = _list(candidate.get("proposed_actions"), field="candidate.proposed_actions")
    content: list[dict[str, Any]] = []
    for action in actions:
        action_map = _mapping(action, field="candidate.proposed_action")
        payload = _mapping(action_map.get("payload"), field="candidate.action.payload")
        obj = _mapping(payload.get("object"), field="candidate.action.object")
        content.append({
            "change": str(action_map.get("kind") or ""),
            "content": semantic_object(obj),
        })
    provenance = candidate.get("provenance")
    summary: dict[str, Any] = {
        "candidate_id": str(candidate.get("proposal_id") or ""),
        "saved": True,
        "content": content,
        "current_relation": candidate_relation(projection),
    }
    if isinstance(provenance, Mapping) and isinstance(provenance.get("question_delta"), str):
        summary["question_review_operation"] = provenance["question_delta"]
    if isinstance(candidate.get("rationale"), str):
        summary["rationale"] = candidate["rationale"]
    return summary


def _candidate_from_detail(detail: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = detail.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("state_delta_proposal"), Mapping):
        return data["state_delta_proposal"]
    execution = detail.get("execution_result")
    if isinstance(execution, Mapping) and isinstance(execution.get("state_delta_proposal"), Mapping):
        return execution["state_delta_proposal"]
    return None


def action_receipt_summary(receipt: Any) -> dict[str, Any] | None:
    if not isinstance(receipt, Mapping):
        return None
    binding = receipt.get("action_binding")
    execution = receipt.get("execution")
    result: dict[str, Any] = {
        "status": str(receipt.get("status") or ""),
        "research_state_mutation_performed": bool(receipt.get("research_state_mutation_performed")),
    }
    if isinstance(binding, Mapping) and isinstance(binding.get("action_type"), str):
        result["action_type"] = binding["action_type"]
    if isinstance(execution, Mapping):
        if isinstance(execution.get("execution_type"), str):
            result["execution_type"] = execution["execution_type"]
        if isinstance(execution.get("result_reference"), str):
            result["result_reference"] = execution["result_reference"]
    if isinstance(receipt.get("completed_at"), str):
        result["completed_at"] = receipt["completed_at"]
    return result


def confirmation_request_summary(request: Any) -> dict[str, Any] | None:
    if not isinstance(request, Mapping):
        return None
    result: dict[str, Any] = {
        "confirmation_request_id": str(request.get("confirmation_request_id") or ""),
    }
    for key in ("action_type", "expires_at"):
        if isinstance(request.get(key), str):
            result[key] = request[key]
    binding = request.get("proposal_binding")
    if isinstance(binding, Mapping) and isinstance(binding.get("proposal_id"), str):
        result["action_proposal_id"] = binding["proposal_id"]
    return result


def confirmation_receipt_summary(receipt: Any) -> dict[str, Any] | None:
    if not isinstance(receipt, Mapping):
        return None
    result: dict[str, Any] = {}
    for source, target in (
        ("confirmation_receipt_id", "confirmation_receipt_id"),
        ("confirmation_request_id", "confirmation_request_id"),
        ("status", "status"),
        ("confirmed_at", "confirmed_at"),
    ):
        if isinstance(receipt.get(source), str):
            result[target] = receipt[source]
    return result


def decision_request_summary(request: Any) -> dict[str, Any] | None:
    if not isinstance(request, Mapping):
        return None
    if any(key in request for key in _OPERATIONAL_REQUEST_FIELDS):
        raise ConversationViewError("immutable Decision Request contains operational projection fields")
    result: dict[str, Any] = {
        "request_id": str(request.get("request_id") or ""),
        "request_digest": str(request.get("request_digest") or ""),
        "issued_status": str(request.get("status") or ""),
    }
    if isinstance(request.get("human_actor_id"), str):
        result["human_actor_id"] = request["human_actor_id"]
    source = request.get("source_state_delta_proposal")
    if isinstance(source, Mapping):
        result["source_candidate"] = {
            "candidate_id": str(source.get("proposal_id") or ""),
            "candidate_digest": str(source.get("proposal_digest") or ""),
        }
    units = request.get("decision_units")
    if isinstance(units, list):
        projected_units = []
        for unit in units:
            if not isinstance(unit, Mapping):
                raise ConversationViewError("Decision unit is malformed")
            item: dict[str, Any] = {}
            subject = unit.get("subject")
            if isinstance(subject, Mapping):
                item["subject"] = {
                    "kind": str(subject.get("kind") or ""),
                    "id": str(subject.get("id") or ""),
                }
            for key in ("required_decision_kind", "required_choice", "proposed_semantic_effect"):
                if key in unit:
                    item[key] = deepcopy(unit[key])
            item["current_value_present"] = isinstance(unit.get("current_value"), Mapping)
            candidate = unit.get("candidate_value")
            if isinstance(candidate, Mapping):
                item["candidate_content"] = semantic_object(candidate)
            projected_units.append(item)
        result["decision_units"] = projected_units
    return result


def decision_with_operational_summary(request: Any) -> dict[str, Any] | None:
    if not isinstance(request, Mapping):
        return None
    canonical = deepcopy(dict(request))
    operational_status = canonical.pop("operational_status", None)
    commit_id = canonical.pop("commit_id", None)
    status_detail = canonical.pop("status_detail", None)
    result = decision_request_summary(canonical)
    if result is None:
        return None
    if operational_status is not None:
        result["operational_status"] = str(operational_status)
    if commit_id is not None:
        result["commit_id"] = str(commit_id)
    if status_detail is not None:
        result["status_detail"] = str(status_detail)
    return result


def project_action_result(detail: Mapping[str, Any], *, action_type: str, state: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(detail.get("status") or ""),
        "operation": {"action_type": action_type},
    }
    receipt = action_receipt_summary(detail.get("action_receipt"))
    if receipt is not None:
        result["operation"]["receipt"] = receipt
    confirmation = confirmation_request_summary(detail.get("confirmation_request"))
    if confirmation is not None:
        result["confirmation_required"] = confirmation
    decision = decision_with_operational_summary(detail.get("decision_request"))
    if decision is not None:
        result["human_decision_required"] = decision
    candidate = _candidate_from_detail(detail)
    if candidate is not None:
        result["candidate"] = candidate_summary(candidate, state)
    elif action_type == "research_question.review":
        data = detail.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("question_review"), Mapping):
            review = data["question_review"]
            result["question_review"] = {
                "operation": deepcopy(review.get("operation")),
                "material_change": bool(review.get("material_change")),
                "rationale": deepcopy(review.get("rationale")),
                "question_ids": _copy_list(review.get("question_ids", [])),
            }
    if action_type not in {
        "research_question.propose",
        "research_question.propose_many",
        "research_question.review",
        "research.argument.propose",
        "research.recommendation.propose",
        "state.apply_candidate",
        "desktop_research.investigate",
    } and candidate is None and confirmation is None and decision is None:
        result["interpretation"] = {
            "status": "UNSUPPORTED",
            "message": "The operation result is recorded, but conversation interpretation is not implemented for this action type.",
        }
    issues = detail.get("issues")
    if isinstance(issues, list) and issues:
        result["issues"] = project_issues(issues)
    run_id = detail.get("run_id")
    if isinstance(run_id, str):
        result["run_id"] = run_id
    prepared = detail.get("prepared_execution")
    if isinstance(prepared, Mapping):
        run = prepared.get("run")
        if isinstance(run, Mapping):
            result["run"] = run_summary(run)
    return result


def project_confirmation_result(detail: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": str(detail.get("status") or "")}
    receipt = confirmation_receipt_summary(detail.get("confirmation_receipt"))
    if receipt is not None:
        result["confirmation"] = receipt
    action = action_receipt_summary(detail.get("action_receipt"))
    if action is not None:
        result["operation"] = action
    decision = decision_with_operational_summary(detail.get("decision_request"))
    if decision is not None:
        result["human_decision_required"] = decision
    issues = detail.get("issues")
    if isinstance(issues, list) and issues:
        result["issues"] = project_issues(issues)
    return result


def project_decision_result(detail: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": str(detail.get("status") or "")}
    request = decision_with_operational_summary(detail.get("request"))
    if request is not None:
        result["request"] = request
    response = detail.get("response")
    if isinstance(response, Mapping):
        result["response"] = {
            "request_id": str(response.get("request_id") or ""),
            "disposition": deepcopy(response.get("disposition")),
            "responded_at": deepcopy(response.get("responded_at")),
        }
    receipt = detail.get("commit_receipt")
    if isinstance(receipt, Mapping):
        result["commit"] = {
            "commit_id": str(receipt.get("commit_id") or ""),
            "status": deepcopy(receipt.get("status")),
        }
        for key in ("new_snapshot_id", "committed_at"):
            if key in receipt:
                result["commit"][key] = deepcopy(receipt[key])
    rejection = detail.get("transition_rejection")
    if isinstance(rejection, Mapping):
        result["transition_rejection"] = project_issue(rejection)
    return result


def project_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("code", "message", "severity", "kind", "status", "failure_class"):
        if key in issue:
            result[key] = deepcopy(issue[key])
    if not result:
        result["message"] = "An issue was recorded; exact diagnostics are available in detail view."
    return result


def project_issues(issues: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    return [project_issue(item) for item in issues if isinstance(item, Mapping)]


def run_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "run_id", "capability_id", "function_id", "execution_mode", "attempt", "parent_run_id",
        "status", "prepared_at", "started_at", "completed_at",
    ):
        if key in run:
            result[key] = deepcopy(run[key])
    failure = run.get("failure")
    if isinstance(failure, Mapping):
        result["failure"] = project_issue(failure)
        if "retryable" in failure:
            result["failure"]["retryable"] = bool(failure["retryable"])
    elif failure is not None:
        result["failure"] = {"message": str(failure)}
    else:
        result["failure"] = None
    return result


def project_status(detail: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(detail.get("status") or ""),
        "project_id": str(detail.get("project_id") or ""),
    }
    optional = detail.get("optional_children")
    if isinstance(optional, list):
        result["optional_components"] = [
            {
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
                "payload_integrity": str(item.get("payload_integrity") or ""),
            }
            for item in optional
            if isinstance(item, Mapping) and item.get("status") not in {"OK", "UNINITIALIZED"}
        ]
    confirmations = detail.get("pending_confirmations")
    if isinstance(confirmations, list):
        result["pending_confirmations"] = [
            value for item in confirmations
            if (value := confirmation_request_summary(item)) is not None
        ]
    decisions = detail.get("pending_human_decisions")
    if isinstance(decisions, list):
        result["pending_human_decisions"] = [
            value for item in decisions
            if (value := decision_with_operational_summary(item)) is not None
        ]
    runs = detail.get("pending_runs")
    if isinstance(runs, list):
        result["pending_runs"] = [run_summary(item) for item in runs if isinstance(item, Mapping)]
    if isinstance(detail.get("truncated"), Mapping):
        result["truncated"] = deepcopy(dict(detail["truncated"]))
    return result


def _research_question_resume_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = str(row.get("state_delta_proposal_id") or "")
    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "source_action_proposal": deepcopy(row.get("source_action_proposal")),
        "pending_confirmation_request_ids": _copy_list(row.get("pending_confirmation_request_ids", [])),
        "human_decision_requests": [
            {
                key: deepcopy(item.get(key))
                for key in ("request_id", "source_candidate_id", "status")
                if key in item
            }
            for item in row.get("human_decision_requests", [])
            if isinstance(item, Mapping)
        ],
    }
    if isinstance(row.get("question"), Mapping):
        question = deepcopy(dict(row["question"]))
        question.setdefault("kind", "research_question")
        result["content"] = [semantic_object(question)]
    elif isinstance(row.get("questions"), list):
        content = []
        for item in row["questions"]:
            if not isinstance(item, Mapping):
                continue
            question = deepcopy(dict(item))
            question.setdefault("kind", "research_question")
            content.append(semantic_object(question))
        result["content"] = content
    if isinstance(row.get("question_delta"), str):
        result["question_review_operation"] = row["question_delta"]
    if isinstance(row.get("source_question_revisions"), list):
        result["source_question_revisions"] = deepcopy(row["source_question_revisions"])
    projection = row.get("candidate_projection")
    if isinstance(projection, Mapping):
        result["current_relation"] = candidate_relation(projection)
    else:
        result["current_relation"] = {
            "bound_to_current_snapshot": bool(row.get("bound_to_current_snapshot")),
            "subjects": [],
            "relation_detail": "UNAVAILABLE",
        }
    return result


def _attention_item(item: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for key in (
        "statement", "rationale", "disposition", "disposition_reason",
        "related_question_seed_ids", "source_reference_ids", "projection_hints",
    ):
        _copy_optional(item, key, result)
    return result


def project_resume(detail: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(detail.get("status") or ""),
        "project": deepcopy(detail.get("project")) if isinstance(detail.get("project"), Mapping) else {},
    }
    optional = detail.get("optional_children")
    if isinstance(optional, list):
        result["optional_components"] = [
            {
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
                "payload_integrity": str(item.get("payload_integrity") or ""),
            }
            for item in optional
            if isinstance(item, Mapping) and item.get("status") not in {"OK", "UNINITIALIZED"}
        ]
    state = detail.get("research_state")
    if isinstance(state, Mapping):
        snapshot = state.get("snapshot")
        result["research_state"] = {
            "snapshot_revision": snapshot.get("revision") if isinstance(snapshot, Mapping) else None,
        }
    rq = detail.get("research_questions")
    if isinstance(rq, Mapping):
        result["research_questions"] = {
            "seeds": deepcopy(rq.get("seeds", [])) if isinstance(rq.get("seeds"), list) else [],
            "authoritative": [
                semantic_object({"kind": "research_question", **dict(item)}, authoritative=True)
                for item in (rq.get("authoritative") or [])
                if isinstance(item, Mapping)
            ],
            "candidates": [
                _research_question_resume_candidate(item)
                for item in (rq.get("candidates") or [])
                if isinstance(item, Mapping)
            ],
        }
    attention = detail.get("research_attention")
    if isinstance(attention, Mapping):
        result["research_attention"] = {
            "status": deepcopy(attention.get("status")),
            "issues": project_issues(attention.get("issues", [])) if isinstance(attention.get("issues"), (list, tuple)) else [],
            "baseline": [_attention_item(item) for item in (attention.get("baseline") or []) if isinstance(item, Mapping)],
            "effective": [_attention_item(item) for item in (attention.get("effective") or []) if isinstance(item, Mapping)],
        }
        if isinstance(attention.get("active_map"), Mapping):
            result["research_attention"]["active_map"] = {
                key: deepcopy(attention["active_map"].get(key))
                for key in ("label", "rationale", "status")
                if key in attention["active_map"]
            }
    workflow = detail.get("workflow")
    if isinstance(workflow, Mapping):
        result["workflow"] = {
            "pending_confirmations": [
                value for item in (workflow.get("pending_confirmations") or [])
                if (value := confirmation_request_summary(item)) is not None
            ],
            "pending_human_decisions": [
                value for item in (workflow.get("pending_human_decisions") or [])
                if (value := decision_with_operational_summary(item)) is not None
            ],
            "pending_runs": [run_summary(item) for item in (workflow.get("pending_runs") or []) if isinstance(item, Mapping)],
            "recent_runs": [run_summary(item) for item in (workflow.get("recent_runs") or []) if isinstance(item, Mapping)],
        }
    if isinstance(detail.get("truncated"), Mapping):
        result["truncated"] = deepcopy(dict(detail["truncated"]))
    saved = detail.get("saved_synthesis_candidates")
    if isinstance(saved, Mapping):
        result["saved_synthesis_candidates"] = project_synthesis_list({
            "status": detail.get("status", "OK"),
            "project_id": detail.get("project", {}).get("project_id") if isinstance(detail.get("project"), Mapping) else "",
            "items": saved.get("items", []),
            "truncated": saved.get("truncated", False),
            "next_cursor": saved.get("next_cursor"),
            "issues": saved.get("issues", []),
        })
    return result


def project_synthesis_list(detail: Mapping[str, Any]) -> dict[str, Any]:
    items = []
    for row in detail.get("items", []) if isinstance(detail.get("items"), list) else []:
        if not isinstance(row, Mapping):
            continue
        item: dict[str, Any] = {
            "candidate_id": str(row.get("candidate_id") or ""),
            "kind": deepcopy(row.get("kind")),
            "availability": deepcopy(row.get("availability")),
            "label": deepcopy(row.get("label")),
            "created_at": deepcopy(row.get("created_at")),
        }
        if isinstance(row.get("candidate_projection"), Mapping):
            item["current_relation"] = candidate_relation(row["candidate_projection"])
        if isinstance(row.get("candidate_position"), Mapping):
            position = row["candidate_position"]
            item["current_relation"] = {
                "bound_to_current_lineage": bool(position.get("bound_to_current_lineage")),
                "bound_to_current_snapshot": bool(position.get("bound_to_current_snapshot")),
                "subjects": deepcopy(position.get("subjects", [])),
            }
        if isinstance(row.get("issue"), Mapping):
            item["issue"] = project_issue(row["issue"])
        if isinstance(row.get("issues"), (list, tuple)):
            item["issues"] = project_issues(row["issues"])
        items.append(item)
    return {
        "status": str(detail.get("status") or ""),
        "project_id": str(detail.get("project_id") or ""),
        "items": items,
        "truncated": bool(detail.get("truncated")),
        "next_cursor": deepcopy(detail.get("next_cursor")),
        "issues": project_issues(detail.get("issues", [])) if isinstance(detail.get("issues"), (list, tuple)) else [],
    }


def project_synthesis_show(detail: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "status": str(detail.get("status") or ""),
        "project_id": str(detail.get("project_id") or ""),
        "candidate_id": str(detail.get("candidate_id") or ""),
        "kind": deepcopy(detail.get("kind")),
        "created_at": deepcopy(detail.get("created_at")),
        "content": deepcopy(detail.get("content")),
    }
    if isinstance(detail.get("candidate_projection"), Mapping):
        result["current_relation"] = candidate_relation(detail["candidate_projection"])
    if isinstance(detail.get("source_action_proposal"), Mapping):
        result["source_action_proposal"] = {
            "proposal_id": deepcopy(detail["source_action_proposal"].get("proposal_id")),
            "created_at": deepcopy(detail["source_action_proposal"].get("created_at")),
        }
    return result


def _handoff_outputs(handoff: Mapping[str, Any]) -> dict[str, Any]:
    outputs = handoff.get("outputs")
    if not isinstance(outputs, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "observations", "evidence_candidates", "candidate_findings", "counterevidence",
        "conflicts", "unknowns", "evidence_gaps", "candidate_next_actions", "candidate_next_methods",
    ):
        if isinstance(outputs.get(key), list):
            result[key] = deepcopy(outputs[key])
    captures = outputs.get("source_captures")
    if isinstance(captures, list):
        result["source_captures"] = [
            {
                key: deepcopy(item.get(key))
                for key in ("capture_id", "locator", "origin", "content_digest")
                if key in item
            }
            for item in captures if isinstance(item, Mapping)
        ]
    return result


def project_collect(detail: Mapping[str, Any], *, state: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": str(detail.get("status") or "")}
    execution = detail.get("execution_result")
    if isinstance(execution, Mapping):
        run = execution.get("run")
        if isinstance(run, Mapping):
            result["run"] = run_summary(run)
        for key in ("handoff_status",):
            if key in execution:
                result[key] = deepcopy(execution[key])
        if isinstance(execution.get("issues"), (list, tuple)):
            result["issues"] = project_issues(execution["issues"])
        result["normalized_candidate_available"] = isinstance(execution.get("state_delta_proposal"), Mapping)
    data = detail.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("handoff"), Mapping):
        result["research_outputs"] = _handoff_outputs(data["handoff"])
    candidate = _candidate_from_detail(detail)
    if candidate is not None:
        result["candidate"] = candidate_summary(candidate, state)
        provenance = candidate.get("provenance")
        desktop = provenance.get("desktop_research") if isinstance(provenance, Mapping) else None
        if isinstance(desktop, Mapping):
            research_context = {}
            for key in ("coverage_assessment", "evidence_gap_assessments", "null_results", "search_trace"):
                if key in desktop:
                    research_context[key] = deepcopy(desktop[key])
            if research_context:
                result["research_context"] = research_context
    action = action_receipt_summary(detail.get("action_receipt"))
    if action is not None:
        result["operation"] = action
    return result


def project_run(detail: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(detail.get("status") or ""),
        "project_id": str(detail.get("project_id") or ""),
    }
    run = detail.get("run")
    if isinstance(run, Mapping):
        result["run"] = run_summary(run)
    lifecycle = detail.get("lifecycle")
    if isinstance(lifecycle, list):
        result["lifecycle"] = [
            {
                key: deepcopy(item.get(key))
                for key in ("from_status", "to_status", "occurred_at", "reason")
                if key in item
            }
            for item in lifecycle if isinstance(item, Mapping)
        ]
    diagnostics = detail.get("diagnostics")
    if isinstance(diagnostics, list):
        result["diagnostics"] = [project_issue(item) for item in diagnostics if isinstance(item, Mapping)]
    artifacts = detail.get("artifacts")
    if isinstance(artifacts, list):
        result["artifacts"] = [
            {
                key: deepcopy(item.get(key))
                for key in ("artifact_id", "role", "media_type", "byte_length")
                if key in item
            }
            for item in artifacts if isinstance(item, Mapping)
        ]
    desktop = detail.get("desktop_research")
    if isinstance(desktop, Mapping):
        result["desktop_research"] = {
            "retrieval_attempt_summary": deepcopy(desktop.get("retrieval_attempt_summary")),
            "retrieval_attempts": [
                {
                    key: deepcopy(item.get(key))
                    for key in ("attempt_id", "strategy", "outcome", "target_locator", "failure_or_blocking_reason", "resulting_capture_id")
                    if key in item
                }
                for item in (desktop.get("retrieval_attempts") or []) if isinstance(item, Mapping)
            ],
            "operational_terminations": [
                project_issue(item) for item in (desktop.get("operational_terminations") or []) if isinstance(item, Mapping)
            ],
        }
    known = {"status", "project_id", "run", "lifecycle", "diagnostics", "artifacts", "truncated", "desktop_research"}
    extension_keys = [key for key in detail if key not in known]
    for key in extension_keys:
        value = detail[key]
        if key in {
            "finding_recovery", "historical_finding_recovery", "historical_result_recovery",
            "material_reacquisition", "new_material_continuation",
        } and isinstance(value, Mapping):
            result[key] = {
                field: deepcopy(value.get(field))
                for field in (
                    "status", "stage", "failure_class", "code", "message", "source_run_id",
                    "recovery_run_id", "continuation_run_id", "reacquisition_run_id", "eligible",
                ) if field in value
            }
        else:
            result.setdefault("interpretation", {"status": "UNSUPPORTED_EXTENSIONS", "keys": []})["keys"].append(key)
    if isinstance(detail.get("truncated"), Mapping):
        result["truncated"] = deepcopy(dict(detail["truncated"]))
    return result


def project_replay(detail: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(detail.get("status") or ""),
        "parent_run_id": deepcopy(detail.get("parent_run_id")),
        "run_id": deepcopy(detail.get("run_id")),
        "attempt": deepcopy(detail.get("attempt")),
        "carried_unresolved_attempts": [
            {
                key: deepcopy(item.get(key))
                for key in ("attempt_id", "strategy", "coverage_dimension_ids", "query_or_target", "target_locator")
                if key in item
            }
            for item in (detail.get("carried_unresolved_attempts") or []) if isinstance(item, Mapping)
        ],
    }


def projection_unavailable(
    *, status: Any, operation: str, message: str, detail: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(status or "RESULT_RECORDED"),
        "operation": operation,
        "conversation_projection": {
            "status": "UNAVAILABLE",
            "code": "APPLICATION-CONVERSATION-VIEW-001",
            "message": message,
        },
    }
    if isinstance(detail, Mapping):
        refs: dict[str, Any] = {}
        if isinstance(detail.get("run_id"), str):
            refs["run_id"] = detail["run_id"]
        receipt = detail.get("action_receipt")
        if isinstance(receipt, Mapping):
            execution = receipt.get("execution")
            if isinstance(execution, Mapping) and isinstance(execution.get("result_reference"), str):
                refs["result_reference"] = execution["result_reference"]
        confirmation = detail.get("confirmation_request")
        if isinstance(confirmation, Mapping) and isinstance(confirmation.get("confirmation_request_id"), str):
            refs["confirmation_request_id"] = confirmation["confirmation_request_id"]
        decision = detail.get("decision_request")
        if isinstance(decision, Mapping):
            if isinstance(decision.get("request_id"), str):
                refs["request_id"] = decision["request_id"]
            if isinstance(decision.get("request_digest"), str):
                refs["request_digest"] = decision["request_digest"]
        commit = detail.get("commit_receipt")
        if isinstance(commit, Mapping) and isinstance(commit.get("commit_id"), str):
            refs["commit_id"] = commit["commit_id"]
        if refs:
            result["exact_references"] = refs
    return result
