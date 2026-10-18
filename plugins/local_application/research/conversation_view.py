from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .conversation_view_summaries import (
    _candidate_from_detail,
    _copy_list,
    _copy_optional,
    action_receipt_summary,
    candidate_relation,
    candidate_summary,
    confirmation_request_summary,
    decision_with_operational_summary,
    project_issue,
    project_issues,
    run_summary,
    semantic_object,
)


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
            value
            for item in confirmations
            if (value := confirmation_request_summary(item)) is not None
        ]
    decisions = detail.get("pending_human_decisions")
    if isinstance(decisions, list):
        result["pending_human_decisions"] = [
            value
            for item in decisions
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
        "pending_confirmation_request_ids": _copy_list(
            row.get("pending_confirmation_request_ids", [])
        ),
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
        "statement",
        "rationale",
        "disposition",
        "disposition_reason",
        "related_question_seed_ids",
        "source_reference_ids",
        "projection_hints",
    ):
        _copy_optional(item, key, result)
    return result


def project_resume(detail: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": str(detail.get("status") or ""),
        "project": deepcopy(detail.get("project"))
        if isinstance(detail.get("project"), Mapping)
        else {},
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
            "snapshot_revision": snapshot.get("revision")
            if isinstance(snapshot, Mapping)
            else None,
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
            "issues": project_issues(attention.get("issues", []))
            if isinstance(attention.get("issues"), (list, tuple))
            else [],
            "baseline": [
                _attention_item(item)
                for item in (attention.get("baseline") or [])
                if isinstance(item, Mapping)
            ],
            "effective": [
                _attention_item(item)
                for item in (attention.get("effective") or [])
                if isinstance(item, Mapping)
            ],
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
                value
                for item in (workflow.get("pending_confirmations") or [])
                if (value := confirmation_request_summary(item)) is not None
            ],
            "pending_human_decisions": [
                value
                for item in (workflow.get("pending_human_decisions") or [])
                if (value := decision_with_operational_summary(item)) is not None
            ],
            "pending_runs": [
                run_summary(item)
                for item in (workflow.get("pending_runs") or [])
                if isinstance(item, Mapping)
            ],
            "recent_runs": [
                run_summary(item)
                for item in (workflow.get("recent_runs") or [])
                if isinstance(item, Mapping)
            ],
        }
    if isinstance(detail.get("truncated"), Mapping):
        result["truncated"] = deepcopy(dict(detail["truncated"]))
    saved = detail.get("saved_synthesis_candidates")
    if isinstance(saved, Mapping):
        result["saved_synthesis_candidates"] = project_synthesis_list(
            {
                "status": detail.get("status", "OK"),
                "project_id": detail.get("project", {}).get("project_id")
                if isinstance(detail.get("project"), Mapping)
                else "",
                "items": saved.get("items", []),
                "truncated": saved.get("truncated", False),
                "next_cursor": saved.get("next_cursor"),
                "issues": saved.get("issues", []),
            }
        )
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
        "issues": project_issues(detail.get("issues", []))
        if isinstance(detail.get("issues"), (list, tuple))
        else [],
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
        "observations",
        "evidence_candidates",
        "candidate_findings",
        "counterevidence",
        "conflicts",
        "unknowns",
        "evidence_gaps",
        "candidate_next_actions",
        "candidate_next_methods",
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
            for item in captures
            if isinstance(item, Mapping)
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
        result["normalized_candidate_available"] = isinstance(
            execution.get("state_delta_proposal"), Mapping
        )
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
            for key in (
                "coverage_assessment",
                "evidence_gap_assessments",
                "null_results",
                "search_trace",
            ):
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
            for item in lifecycle
            if isinstance(item, Mapping)
        ]
    diagnostics = detail.get("diagnostics")
    if isinstance(diagnostics, list):
        result["diagnostics"] = [
            project_issue(item) for item in diagnostics if isinstance(item, Mapping)
        ]
    artifacts = detail.get("artifacts")
    if isinstance(artifacts, list):
        result["artifacts"] = [
            {
                key: deepcopy(item.get(key))
                for key in ("artifact_id", "role", "media_type", "byte_length")
                if key in item
            }
            for item in artifacts
            if isinstance(item, Mapping)
        ]
    desktop = detail.get("desktop_research")
    if isinstance(desktop, Mapping):
        result["desktop_research"] = {
            "retrieval_attempt_summary": deepcopy(desktop.get("retrieval_attempt_summary")),
            "retrieval_attempts": [
                {
                    key: deepcopy(item.get(key))
                    for key in (
                        "attempt_id",
                        "strategy",
                        "outcome",
                        "target_locator",
                        "failure_or_blocking_reason",
                        "resulting_capture_id",
                    )
                    if key in item
                }
                for item in (desktop.get("retrieval_attempts") or [])
                if isinstance(item, Mapping)
            ],
            "operational_terminations": [
                project_issue(item)
                for item in (desktop.get("operational_terminations") or [])
                if isinstance(item, Mapping)
            ],
        }
    known = {
        "status",
        "project_id",
        "run",
        "lifecycle",
        "diagnostics",
        "artifacts",
        "truncated",
        "desktop_research",
    }
    extension_keys = [key for key in detail if key not in known]
    for key in extension_keys:
        value = detail[key]
        if key in {
            "finding_recovery",
            "historical_finding_recovery",
            "historical_result_recovery",
            "material_reacquisition",
            "new_material_continuation",
        } and isinstance(value, Mapping):
            result[key] = {
                field: deepcopy(value.get(field))
                for field in (
                    "status",
                    "stage",
                    "failure_class",
                    "code",
                    "message",
                    "source_run_id",
                    "recovery_run_id",
                    "continuation_run_id",
                    "reacquisition_run_id",
                    "eligible",
                )
                if field in value
            }
        else:
            result.setdefault("interpretation", {"status": "UNSUPPORTED_EXTENSIONS", "keys": []})[
                "keys"
            ].append(key)
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
                for key in (
                    "attempt_id",
                    "strategy",
                    "coverage_dimension_ids",
                    "query_or_target",
                    "target_locator",
                )
                if key in item
            }
            for item in (detail.get("carried_unresolved_attempts") or [])
            if isinstance(item, Mapping)
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
            if isinstance(execution, Mapping) and isinstance(
                execution.get("result_reference"), str
            ):
                refs["result_reference"] = execution["result_reference"]
        confirmation = detail.get("confirmation_request")
        if isinstance(confirmation, Mapping) and isinstance(
            confirmation.get("confirmation_request_id"), str
        ):
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
