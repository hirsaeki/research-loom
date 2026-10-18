"""Conversation view building blocks: semantic objects, candidate, receipt, request and issue summaries (#494)."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

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
        base.update(
            {
                "text": value["text"],
                "acceptance_criteria": _copy_list(value.get("acceptance_criteria", [])),
                "scope_limits": _copy_list(value.get("scope_limits", [])),
            }
        )
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
        base.update(
            {
                "statement": value["statement"],
                "finding_ids": _copy_list(value.get("finding_ids", [])),
                "conditions": _copy_list(value.get("conditions", [])),
                "scope": _copy_list(value.get("scope", [])),
            }
        )
        _copy_optional(value, "rationale", base)
        return base

    if kind == "argument":
        if not isinstance(value.get("conclusion"), str) or not isinstance(
            value.get("warrant"), str
        ):
            raise ConversationViewError("Argument content is malformed")
        base.update(
            {
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
            }
        )
        _copy_optional(value, "rationale", base)
        return base

    # Known Desktop Research candidates can be represented by their semantic payload
    # without serializing the canonical object envelope.
    if kind in {"research_input", "source", "evidence", "finding", "next_action", "method"}:
        for key in (
            "title",
            "statement",
            "description",
            "result_summary",
            "normalized_statement",
            "locator",
            "source_id",
            "source_ids",
            "question_ids",
            "finding_ids",
            "evidence_ids",
            "counter_evidence_ids",
            "boundary_conditions",
            "limitations",
            "confidence",
            "rationale",
            "action_type",
            "instruction",
            "reason",
            "priority",
            "blocked_by",
            "source_type",
            "canonical_locator",
            "content_digest",
            "media_type",
            "byte_length",
            "origin_type",
            "verification_status",
            "excerpt",
            "capture_digest",
            "evidence_kind",
            "evidence_mode",
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
        output.append(
            {
                "subject": {
                    "kind": str(subject.get("kind") or ""),
                    "id": str(subject.get("id") or ""),
                },
                "current_value_present": current_present,
                "candidate_value_matches_current": (
                    canonical_digest(current) == canonical_digest(candidate)
                    if current_present
                    else None
                ),
            }
        )
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
        content.append(
            {
                "change": str(action_map.get("kind") or ""),
                "content": semantic_object(obj),
            }
        )
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
    if isinstance(execution, Mapping) and isinstance(
        execution.get("state_delta_proposal"), Mapping
    ):
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
        raise ConversationViewError(
            "immutable Decision Request contains operational projection fields"
        )
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


def project_action_result(
    detail: Mapping[str, Any], *, action_type: str, state: Any
) -> dict[str, Any]:
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
    if (
        action_type
        not in {
            "research_question.propose",
            "research_question.propose_many",
            "research_question.review",
            "research.argument.propose",
            "research.recommendation.propose",
            "state.apply_candidate",
            "desktop_research.investigate",
        }
        and candidate is None
        and confirmation is None
        and decision is None
    ):
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
        "run_id",
        "capability_id",
        "function_id",
        "execution_mode",
        "attempt",
        "parent_run_id",
        "status",
        "prepared_at",
        "started_at",
        "completed_at",
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
