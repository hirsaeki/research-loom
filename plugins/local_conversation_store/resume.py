from __future__ import annotations

from copy import deepcopy
import json
import sqlite3

from core.conversation import ConversationRuntimeError, canonical_digest


_RQ_PRODUCERS = (
    "research_question.propose@0.1.0",
    "research_question.propose_many@0.1.0",
)
_RQ_REVIEW_PRODUCER = "research_question.review@0.1.0"


def _validated_state_delta(row, *, project_ref: str):
    try:
        value = json.loads(str(row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal must be an object"
        )
    if str(value.get("proposal_id") or "") != str(row["proposal_id"]):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal identity does not match its row"
        )
    if str(value.get("project_ref") or "") != str(project_ref):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal project binding is invalid"
        )
    basis = deepcopy(value)
    supplied = str(basis.pop("proposal_digest", ""))
    if not supplied or canonical_digest(basis) != supplied:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal digest is invalid"
        )
    return value


def research_question_candidates_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
):
    """Return bounded production RQ candidate StateDeltaProposals for one project."""
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
                  AND json_extract(payload_json, '$.provenance.producer') IN (?, ?)
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (str(project_ref), *_RQ_PRODUCERS, int(limit)),
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


def research_question_review_candidates_for_project(
    store,
    project_ref: str,
    *,
    limit: int,
):
    """Return bounded material Question Review candidates for one project."""
    if limit <= 0:
        raise ValueError("Research Question review candidate query limit must be positive")
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
                (str(project_ref), _RQ_REVIEW_PRODUCER, int(limit)),
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
