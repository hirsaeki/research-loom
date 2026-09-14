from __future__ import annotations

import json
from typing import Any, Mapping


def find_state_delta_proposals_by_provenance_run_id(
    store, run_id: str, *, limit: int = 3
) -> tuple[Mapping[str, object], ...]:
    """Return a bounded exact match set for one persisted producer Run.

    This stays inside the conversation-store plugin so the application recovery
    path does not depend on SQLite schema details or expose generic proposal
    enumeration.
    """
    if not isinstance(run_id, str) or not run_id or limit <= 0:
        raise ValueError("run_id and positive limit are required")
    with store._lock:
        store._db.execute(
            "CREATE INDEX IF NOT EXISTS state_delta_proposals_provenance_run_id "
            "ON state_delta_proposals("
            "json_extract(payload_json, '$.provenance.run_id')"
            ") WHERE json_valid(payload_json)"
        )
        rows = store._db.execute(
            "SELECT payload_json FROM state_delta_proposals "
            "WHERE json_valid(payload_json) "
            "AND json_extract(payload_json, '$.provenance.run_id')=? "
            "ORDER BY proposal_id LIMIT ?",
            (run_id, int(limit)),
        ).fetchall()
    result = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        provenance = payload.get("provenance")
        if (
            isinstance(provenance, dict)
            and provenance.get("run_id") == run_id
            and "legacy_recovery" not in provenance
        ):
            result.append(payload)
    return tuple(result)


def persist_state_delta_proposal_idempotently(
    store, proposal_id: str, payload: Mapping[str, Any]
) -> bool:
    """Persist one immutable candidate atomically and report exact reuse.

    Returns True only when the identical proposal already existed. BEGIN IMMEDIATE
    makes the read/insert decision consistent across concurrent processes sharing
    the same conversation store.
    """
    serialized = store._json(payload)
    with store._lock:
        store._db.execute("BEGIN IMMEDIATE")
        try:
            row = store._db.execute(
                "SELECT payload_json FROM state_delta_proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if row is not None:
                if str(row["payload_json"]) != serialized:
                    raise ValueError(
                        "immutable StateDeltaProposal identity collision"
                    )
                store._db.execute("COMMIT")
                return True
            store._db.execute(
                "INSERT INTO state_delta_proposals(proposal_id,payload_json) "
                "VALUES(?,?)",
                (proposal_id, serialized),
            )
            store._db.execute("COMMIT")
            return False
        except Exception:
            store._db.execute("ROLLBACK")
            raise
