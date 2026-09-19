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

    def get_claimed_response(self, request_id: str):
        """Read the exact response selected by the request's atomic claim.

        A missing payload remains visible; never substitute another (possibly
        rejected) response for this request or regenerate its original facts.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT q.status,q.claimed_response_digest,r.payload_json "
                "FROM decision_requests q LEFT JOIN decision_responses r "
                "ON r.response_digest=q.claimed_response_digest AND r.request_id=q.request_id "
                "WHERE q.request_id=?", (request_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "status": str(row["status"]),
            "response_digest": row["claimed_response_digest"],
            "response": json.loads(row["payload_json"]) if row["payload_json"] is not None else None,
        }
