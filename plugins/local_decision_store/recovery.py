from __future__ import annotations

import json

from .store import LocalHumanDecisionStore as _BaseStore


class RecoverableLocalHumanDecisionStore(_BaseStore):
    """Adds read-only resolution recovery metadata to the base local store."""

    def resolution(self, request_id: str):
        with self._lock:
            row = self._db.execute(
                "SELECT status,claimed_response_digest,commit_receipt_json,detail "
                "FROM decision_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "status": str(row["status"]),
            "response_digest": str(row["claimed_response_digest"]) if row["claimed_response_digest"] is not None else None,
            "commit_receipt": json.loads(str(row["commit_receipt_json"])) if row["commit_receipt_json"] is not None else None,
            "detail": str(row["detail"]) if row["detail"] is not None else None,
        }
