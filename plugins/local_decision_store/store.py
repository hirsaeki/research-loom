from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping


class LocalHumanDecisionStore:
    """Separate production-local operational store for Human Decision lifecycle.

    This database never writes Research State. Request/response payloads are
    immutable; mutable lifecycle rows only coordinate single-terminal resolution
    and recovery around the separate Research State transaction.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(
            str(self.path), isolation_level=None, check_same_thread=False, timeout=5.0
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS decision_requests(
              request_id TEXT PRIMARY KEY,
              request_digest TEXT NOT NULL,
              project_ref TEXT NOT NULL,
              lineage_ref TEXT NOT NULL,
              source_candidate_id TEXT NOT NULL,
              source_candidate_digest TEXT NOT NULL,
              snapshot_ref TEXT NOT NULL,
              snapshot_digest TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL,
              claimed_response_digest TEXT,
              commit_id TEXT,
              commit_receipt_json TEXT,
              detail TEXT
            );
            CREATE INDEX IF NOT EXISTS decision_requests_pending
              ON decision_requests(project_ref,status,request_id);
            CREATE TABLE IF NOT EXISTS decision_responses(
              response_digest TEXT PRIMARY KEY,
              request_id TEXT NOT NULL,
              response_id TEXT NOT NULL,
              disposition TEXT NOT NULL,
              actor_id TEXT NOT NULL,
              actor_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              outcome TEXT NOT NULL,
              detail TEXT,
              FOREIGN KEY(request_id) REFERENCES decision_requests(request_id)
            );
            """
        )

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def put_request(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = self._json(request)
        candidate = request["source_state_delta_proposal"]
        snapshot = request["snapshot_binding"]
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO decision_requests(request_id,request_digest,project_ref,lineage_ref,"
                    "source_candidate_id,source_candidate_digest,snapshot_ref,snapshot_digest,payload_json,status) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'PENDING') ON CONFLICT(request_id) DO NOTHING",
                    (
                        request["request_id"], request["request_digest"], request["project_ref"],
                        request["lineage_ref"], candidate["proposal_id"], candidate["proposal_digest"],
                        snapshot["snapshot_ref"], snapshot["snapshot_digest"], payload,
                    ),
                )
                row = self._db.execute(
                    "SELECT request_digest,payload_json FROM decision_requests WHERE request_id=?",
                    (request["request_id"],),
                ).fetchone()
                if row is None or str(row["request_digest"]) != str(request["request_digest"]) or str(row["payload_json"]) != payload:
                    raise ValueError("immutable Human Decision Request identity collision")
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return self.get_request(str(request["request_id"])) or deepcopy(dict(request))

    def get_request(self, request_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json,status,commit_id,detail FROM decision_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        payload["operational_status"] = str(row["status"])
        if row["commit_id"] is not None:
            payload["commit_id"] = str(row["commit_id"])
        if row["detail"] is not None:
            payload["status_detail"] = str(row["detail"])
        return payload

    def get_status(self, request_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT status FROM decision_requests WHERE request_id=?", (request_id,)
            ).fetchone()
        return str(row["status"]) if row else None

    def list_pending(self, project_ref: str) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            ids = [
                str(row["request_id"])
                for row in self._db.execute(
                    "SELECT request_id FROM decision_requests WHERE project_ref=? AND status IN ('PENDING','RESOLVING') ORDER BY request_id",
                    (project_ref,),
                ).fetchall()
            ]
        return tuple(item for item in (self.get_request(request_id) for request_id in ids) if item is not None)

    def record_rejected_response(self, request_id: str, response: Mapping[str, Any], reason: str) -> None:
        self._insert_response(request_id, response, outcome="REJECTED", detail=reason)

    def claim_response(self, request_id: str, request_digest: str, response: Mapping[str, Any]) -> str:
        digest = str(response["response_digest"])
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT request_digest,status,claimed_response_digest FROM decision_requests WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None or str(row["request_digest"]) != str(request_digest):
                    self._db.execute("ROLLBACK")
                    return "rejected"
                status = str(row["status"])
                claimed = str(row["claimed_response_digest"]) if row["claimed_response_digest"] is not None else None
                if status == "RESOLVING":
                    self._db.execute("ROLLBACK")
                    return "retry" if claimed == digest else "rejected"
                if status != "PENDING":
                    self._db.execute("ROLLBACK")
                    return "rejected"
                self._insert_response_locked(request_id, response, outcome="CLAIMED", detail=None)
                changed = self._db.execute(
                    "UPDATE decision_requests SET status='RESOLVING',claimed_response_digest=? "
                    "WHERE request_id=? AND request_digest=? AND status='PENDING'",
                    (digest, request_id, request_digest),
                ).rowcount
                if changed != 1:
                    self._db.execute("ROLLBACK")
                    return "rejected"
                self._db.execute("COMMIT")
                return "claimed"
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def finalize(
        self,
        request_id: str,
        response_digest: str,
        status: str,
        *,
        commit_receipt: Mapping[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        if status not in {"RESOLVED", "DECLINED", "REVISION_REQUESTED", "STALE", "CANCELLED"}:
            raise ValueError(f"invalid terminal Human Decision status: {status}")
        receipt_json = self._json(commit_receipt) if commit_receipt is not None else None
        commit_id = str(commit_receipt["commit_id"]) if commit_receipt is not None else None
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT status,claimed_response_digest,commit_id,commit_receipt_json FROM decision_requests WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("unknown Human Decision Request")
                prior_status = str(row["status"])
                claimed = str(row["claimed_response_digest"]) if row["claimed_response_digest"] is not None else None
                if prior_status == status:
                    if claimed != response_digest:
                        raise ValueError("terminal Human Decision response digest mismatch")
                    if receipt_json is not None and str(row["commit_receipt_json"]) != receipt_json:
                        raise ValueError("terminal Human Decision commit receipt mismatch")
                    self._db.execute("COMMIT")
                    return
                if prior_status != "RESOLVING" or claimed != response_digest:
                    raise ValueError("Human Decision Request is not owned by this response")
                changed = self._db.execute(
                    "UPDATE decision_requests SET status=?,commit_id=?,commit_receipt_json=?,detail=? "
                    "WHERE request_id=? AND status='RESOLVING' AND claimed_response_digest=?",
                    (status, commit_id, receipt_json, detail, request_id, response_digest),
                ).rowcount
                if changed != 1:
                    raise ValueError("Human Decision terminal update lost concurrency race")
                self._db.execute(
                    "UPDATE decision_responses SET outcome=?,detail=? WHERE request_id=? AND response_digest=?",
                    (status, detail, request_id, response_digest),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def _insert_response(self, request_id, response, *, outcome, detail):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._insert_response_locked(request_id, response, outcome=outcome, detail=detail)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def _insert_response_locked(self, request_id, response, *, outcome, detail):
        payload = self._json(response)
        digest = str(response.get("response_digest", ""))
        actor = response.get("actor", {})
        self._db.execute(
            "INSERT INTO decision_responses(response_digest,request_id,response_id,disposition,actor_id,actor_type,payload_json,outcome,detail) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(response_digest) DO NOTHING",
            (
                digest, request_id, str(response.get("response_id", "")), str(response.get("disposition", "")),
                str(actor.get("actor_id", "")), str(actor.get("actor_type", "")), payload, outcome, detail,
            ),
        )
        row = self._db.execute(
            "SELECT request_id,payload_json FROM decision_responses WHERE response_digest=?", (digest,)
        ).fetchone()
        if row is None or str(row["request_id"]) != request_id or str(row["payload_json"]) != payload:
            raise ValueError("immutable Human Decision Response digest collision")

    def close(self) -> None:
        with self._lock:
            self._db.close()
