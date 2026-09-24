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


def state_delta_proposals_by_ids_for_project(
    store,
    project_ref: str,
    proposal_ids,
):
    """Load an exact bounded set of candidate documents for one project in one query."""
    ids = tuple(str(item) for item in proposal_ids)
    if not ids:
        return {}
    if len(ids) > 100 or any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("candidate proposal ID query must contain 1-100 unique non-empty IDs")
    placeholders = ",".join("?" for _ in ids)
    try:
        with store._lock:
            rows = store._db.execute(
                f"SELECT proposal_id,payload_json FROM state_delta_proposals "
                f"WHERE proposal_id IN ({placeholders})",
                ids,
            ).fetchall()
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "StateDeltaProposal lookup is unreadable"
        ) from exc
    result = {}
    for row in rows:
        candidate = _validated_state_delta(row, project_ref=str(project_ref))
        result[str(candidate["proposal_id"])] = candidate
    return result


def state_delta_proposal_for_project(
    store,
    project_ref: str,
    proposal_id: str,
):
    """Load one exact persisted candidate without rebinding it to current state."""
    if not isinstance(proposal_id, str) or not proposal_id:
        raise ValueError("candidate proposal ID must be a non-empty string")
    try:
        with store._lock:
            row = store._db.execute(
                "SELECT proposal_id,payload_json FROM state_delta_proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "StateDeltaProposal lookup is unreadable"
        ) from exc
    if row is None:
        return None

    candidate = _validated_state_delta(row, project_ref=str(project_ref))
    if candidate.get("candidate_only") is not True:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal is not candidate-only"
        )
    if not isinstance(candidate.get("lineage_ref"), str) or not candidate["lineage_ref"]:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal lineage binding is invalid"
        )
    if not isinstance(candidate.get("source_refs"), list):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal source_refs are malformed"
        )
    if not isinstance(candidate.get("proposed_actions"), list) or not candidate["proposed_actions"]:
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal actions are malformed"
        )
    if any(
        not isinstance(action, dict)
        or not isinstance(action.get("kind"), str)
        or not isinstance(action.get("payload"), dict)
        or not isinstance(action.get("decision_refs"), list)
        or not isinstance(action.get("source_refs"), list)
        for action in candidate["proposed_actions"]
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal action structure is invalid"
        )
    affected = candidate.get("affected_refs")
    if not isinstance(affected, list) or any(
        not isinstance(ref, dict)
        or not isinstance(ref.get("kind"), str)
        or not ref["kind"]
        or not isinstance(ref.get("id"), str)
        or not ref["id"]
        for ref in affected
    ):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal affected_refs are malformed"
        )
    if not isinstance(candidate.get("rationale"), str):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal rationale is malformed"
        )
    if not isinstance(candidate.get("required_human_decision_kinds"), list):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal decision requirements are malformed"
        )
    for field in ("current_snapshot_ref", "current_snapshot_digest"):
        if not isinstance(candidate.get(field), str) or not candidate[field]:
            raise ConversationRuntimeError(
                "RESUME-CANDIDATE-001", "stored StateDeltaProposal snapshot binding is invalid"
            )
    if not isinstance(candidate.get("provenance"), dict):
        raise ConversationRuntimeError(
            "RESUME-CANDIDATE-001", "stored StateDeltaProposal provenance is malformed"
        )
    return candidate
