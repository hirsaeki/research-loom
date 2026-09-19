from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from core.runtime import canonical_digest


def check_decision_state_receipts(state_path: Path, decision_path: Path, project_id: str) -> int:
    """Read-only cross-store history check; never restore or reapply an effect.

    Start the Decision read before reading State. A concurrently finalized
    Decision cannot therefore precede its already committed State transaction.
    Iterate the immutable terminal records without accumulating their payloads.
    """
    decisions = sqlite3.connect(decision_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        decisions.row_factory = sqlite3.Row
        rows = decisions.execute(
            "SELECT request_id,commit_id,commit_receipt_json FROM decision_requests "
            "WHERE project_ref=? AND status='RESOLVED' ORDER BY request_id", (project_id,),
        )
        state = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            state.row_factory = sqlite3.Row
            count = 0
            for row in rows:
                try:
                    receipt = json.loads(row["commit_receipt_json"])
                    commit = state.execute(
                        "SELECT * FROM commits WHERE commit_id=? AND project_ref=?",
                        (row["commit_id"], project_id),
                    ).fetchone()
                    if not isinstance(receipt, Mapping) or commit is None:
                        raise ValueError("canonical commit or saved receipt is missing")
                    if json.loads(commit["receipt_json"]) != receipt:
                        raise ValueError("saved receipt differs from canonical commit receipt")
                    for key in (
                        "commit_id", "transition_id", "lineage_ref", "idempotency_key",
                        "bundle_digest", "prior_snapshot_ref", "prior_snapshot_digest",
                        "new_snapshot_ref", "new_snapshot_digest",
                    ):
                        if receipt.get(key) != commit[key]:
                            raise ValueError(f"canonical commit {key} does not match receipt")
                    if (
                        receipt.get("actor") != {"actor_id": commit["actor_id"], "actor_type": commit["actor_type"]}
                        or receipt.get("timestamp") != commit["committed_at"]
                    ):
                        raise ValueError("canonical commit actor/time does not match receipt")
                    snapshot_ref = receipt.get("new_snapshot_ref")
                    if snapshot_ref is not None:
                        snapshot_row = state.execute(
                            "SELECT o.payload_json,o.payload_digest FROM snapshots s "
                            "JOIN object_revisions o ON o.kind='snapshot' AND o.object_id=s.snapshot_ref AND o.revision=s.revision "
                            "WHERE s.snapshot_ref=? AND s.project_ref=? AND s.content_digest=?",
                            (snapshot_ref, project_id, receipt["new_snapshot_digest"]),
                        ).fetchone()
                        snapshot = _verified_payload(snapshot_row)
                        basis = dict(snapshot)
                        basis.pop("content_digest", None)
                        if snapshot.get("content_digest") != receipt["new_snapshot_digest"] or canonical_digest(basis) != receipt["new_snapshot_digest"]:
                            raise ValueError("canonical Snapshot digest does not match receipt")
                    for decision_ref in receipt["resolving_decision_refs"]:
                        decision_row = state.execute(
                            "SELECT o.payload_json,o.payload_digest FROM decisions d "
                            "JOIN object_revisions o ON o.kind='decision' AND o.object_id=d.decision_ref AND o.revision=d.revision "
                            "JOIN used_decisions u ON u.decision_ref=d.decision_ref "
                            "WHERE d.decision_ref=? AND d.project_ref=? AND u.consuming_commit_id=?",
                            (decision_ref, project_id, receipt["commit_id"]),
                        ).fetchone()
                        _verified_payload(decision_row)
                    count += 1
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"resolved Human Decision {row['request_id']} does not match canonical State history: {exc}; "
                        "restore a consistent quiesced Parent backup set, not individual stores"
                    ) from exc
            return count
        finally:
            state.close()
    finally:
        decisions.close()


def _verified_payload(row) -> Mapping[str, Any]:
    if row is None:
        raise ValueError("canonical Snapshot/Decision is missing")
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, Mapping) or canonical_digest(payload) != row["payload_digest"]:
        raise ValueError("canonical Snapshot/Decision payload does not verify")
    return payload
