from __future__ import annotations

import sqlite3
from typing import Any

from core.conversation import ConversationRuntimeError

_KIND_TO_PRODUCER = {
    "recommendation": "research.recommendation.propose@0.1.0",
    "argument": "research.argument.propose@0.1.0",
}
_ERROR = "SYNTHESIS-CANDIDATE-READ-001"
_CURSOR_ERROR = "SYNTHESIS-CANDIDATE-CURSOR-001"


def _producer_filter(kind: str | None) -> tuple[str, ...]:
    if kind is None:
        return tuple(_KIND_TO_PRODUCER.values())
    producer = _KIND_TO_PRODUCER.get(str(kind))
    if producer is None:
        raise ValueError("synthesis candidate kind must be recommendation or argument")
    return (producer,)


def _cursor_rowid(store, cursor: str, *, project_ref: str, producers: tuple[str, ...]) -> int:
    row = store._db.execute(
        "SELECT rowid,proposal_id,payload_json FROM state_delta_proposals WHERE proposal_id=?",
        (str(cursor),),
    ).fetchone()
    if row is None:
        raise ConversationRuntimeError(_CURSOR_ERROR, "synthesis candidate cursor does not resolve")
    try:
        valid = int(store._db.execute(
            "SELECT json_valid(?)", (str(row["payload_json"]),)
        ).fetchone()[0])
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(_CURSOR_ERROR, "synthesis candidate cursor is unreadable") from exc
    if valid != 1:
        raise ConversationRuntimeError(_CURSOR_ERROR, "synthesis candidate cursor is unreadable")
    payload = str(row["payload_json"])
    placeholders = ",".join("?" for _ in producers)
    bound = store._db.execute(
        f"""
        SELECT 1
        WHERE json_extract(?, '$.project_ref')=?
          AND json_extract(?, '$.candidate_only')=1
          AND json_extract(?, '$.provenance.producer') IN ({placeholders})
        """,
        (payload, str(project_ref), payload, payload, *producers),
    ).fetchone()
    if bound is None:
        raise ConversationRuntimeError(_CURSOR_ERROR, "synthesis candidate cursor is outside the requested collection")
    return int(row["rowid"])


def list_synthesis_candidate_rows(
    store,
    project_ref: str,
    *,
    kind: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return a bounded newest-first page of known synthesis candidate rows."""
    if type(limit) is not int or limit <= 0 or limit > 100:
        raise ValueError("synthesis candidate list limit must be between 1 and 100")
    producers = _producer_filter(kind)
    try:
        with store._lock:
            malformed = store._db.execute(
                "SELECT 1 FROM state_delta_proposals "
                "WHERE json_valid(payload_json)=0 LIMIT 1"
            ).fetchone() is not None
            cursor_rowid = None
            if cursor is not None:
                if not isinstance(cursor, str) or not cursor:
                    raise ConversationRuntimeError(_CURSOR_ERROR, "synthesis candidate cursor is invalid")
                cursor_rowid = _cursor_rowid(
                    store, cursor, project_ref=str(project_ref), producers=producers
                )

            rows = []
            for producer in producers:
                where_cursor = "AND s.rowid < ?" if cursor_rowid is not None else ""
                params: list[Any] = [str(project_ref), producer]
                if cursor_rowid is not None:
                    params.append(cursor_rowid)
                params.append(limit + 1)
                rows.extend(store._db.execute(
                    f"""
                    SELECT s.rowid,s.proposal_id,s.payload_json,d.payload_json AS source_payload_json
                    FROM state_delta_proposals s
                    LEFT JOIN documents d
                      ON d.message_type='action_proposal'
                     AND d.document_id=json_extract(s.payload_json, '$.provenance.source_action_proposal.proposal_id')
                    WHERE json_valid(s.payload_json)=1
                      AND json_extract(s.payload_json, '$.project_ref')=?
                      AND json_extract(s.payload_json, '$.candidate_only')=1
                      AND json_extract(s.payload_json, '$.provenance.producer')=?
                      {where_cursor}
                    ORDER BY s.rowid DESC
                    LIMIT ?
                    """,
                    tuple(params),
                ).fetchall())
    except ConversationRuntimeError:
        raise
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate collection is unreadable") from exc

    rows.sort(key=lambda row: int(row["rowid"]), reverse=True)
    page_probe = rows[: limit + 1]
    page = page_probe[:limit]
    return {
        "rows": tuple(dict(row) for row in page),
        "truncated": len(page_probe) > limit,
        "next_cursor": str(page[-1]["proposal_id"]) if len(page_probe) > limit and page else None,
        "collection_incomplete": malformed,
    }


def load_synthesis_candidate_row(store, proposal_id: str) -> dict[str, Any] | None:
    """Load one candidate plus its source Action Proposal without scanning siblings."""
    if not isinstance(proposal_id, str) or not proposal_id:
        raise ValueError("synthesis candidate id must be a non-empty string")
    try:
        with store._lock:
            row = store._db.execute(
                """
                SELECT s.proposal_id,s.payload_json,d.payload_json AS source_payload_json
                FROM state_delta_proposals s
                LEFT JOIN documents d
                  ON d.message_type='action_proposal'
                 AND json_valid(s.payload_json)
                 AND d.document_id=json_extract(s.payload_json, '$.provenance.source_action_proposal.proposal_id')
                WHERE s.proposal_id=?
                """,
                (proposal_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate is unreadable") from exc
    return dict(row) if row is not None else None
