from __future__ import annotations

import json
from typing import Mapping


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
    marker = f'"run_id":"{run_id}"'
    with store._lock:
        rows = store._db.execute(
            "SELECT payload_json FROM state_delta_proposals "
            "WHERE instr(payload_json, ?) > 0 ORDER BY proposal_id LIMIT ?",
            (marker, int(limit)),
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
