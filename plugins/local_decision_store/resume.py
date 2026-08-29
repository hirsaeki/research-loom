from __future__ import annotations

from copy import deepcopy
import json
import sqlite3

from core.conversation import ConversationRuntimeError
from core.decision import request_digest


_KNOWN_STATUSES = {
    "PENDING",
    "RESOLVING",
    "RESOLVED",
    "DECLINED",
    "REVISION_REQUESTED",
    "STALE",
    "CANCELLED",
}


def decision_requests_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
    statuses: tuple[str, ...] | None = None,
):
    """Return bounded, digest-validated Human Decision Requests for one project."""
    if limit <= 0:
        raise ValueError("Human Decision query limit must be positive")
    if statuses is not None:
        if not statuses or any(str(item) not in _KNOWN_STATUSES for item in statuses):
            raise ValueError("Human Decision query statuses are invalid")
        placeholders = ",".join("?" for _ in statuses)
        status_clause = f" AND status IN ({placeholders})"
        status_args = tuple(str(item) for item in statuses)
    else:
        status_clause = ""
        status_args = ()
    try:
        with store._lock:
            rows = store._db.execute(
                "SELECT request_id,request_digest,project_ref,source_candidate_id,"
                "source_candidate_digest,payload_json,status,commit_id,detail "
                "FROM decision_requests WHERE project_ref=?"
                + status_clause
                + " ORDER BY rowid DESC LIMIT ?",
                (str(project_ref), *status_args, int(limit)),
            ).fetchall()
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(
            "RESUME-DECISION-001", "Human Decision Request listing is unreadable"
        ) from exc

    result = []
    for row in rows:
        try:
            request = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConversationRuntimeError(
                "RESUME-DECISION-001", "stored Human Decision Request is not valid JSON"
            ) from exc
        if not isinstance(request, dict):
            raise ConversationRuntimeError(
                "RESUME-DECISION-001", "stored Human Decision Request must be an object"
            )
        source = request.get("source_state_delta_proposal")
        if not isinstance(source, dict):
            raise ConversationRuntimeError(
                "RESUME-DECISION-001", "stored Human Decision source candidate binding is malformed"
            )
        if (
            str(request.get("request_id") or "") != str(row["request_id"])
            or str(request.get("request_digest") or "") != str(row["request_digest"])
            or str(request.get("project_ref") or "") != str(project_ref)
            or str(source.get("proposal_id") or "") != str(row["source_candidate_id"])
            or str(source.get("proposal_digest") or "") != str(row["source_candidate_digest"])
        ):
            raise ConversationRuntimeError(
                "RESUME-DECISION-001", "stored Human Decision Request identity or binding is invalid"
            )
        if request_digest(request) != str(row["request_digest"]):
            raise ConversationRuntimeError(
                "RESUME-DECISION-001", "stored Human Decision Request digest is invalid"
            )
        status = str(row["status"])
        if status not in _KNOWN_STATUSES:
            raise ConversationRuntimeError(
                "RESUME-DECISION-001", "stored Human Decision operational status is invalid"
            )
        projected = deepcopy(request)
        projected["operational_status"] = status
        if row["commit_id"] is not None:
            projected["commit_id"] = str(row["commit_id"])
        if row["detail"] is not None:
            projected["status_detail"] = str(row["detail"])
        result.append(projected)
    return tuple(result)