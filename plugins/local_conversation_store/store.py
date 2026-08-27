from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping


class LocalConversationStore:
    """Separate durable operational store for PR10 conversation documents.

    Canonical documents are immutable. Mutable rows are operational indexes only;
    this database never writes authoritative Research State. Confirmation consume
    uses BEGIN IMMEDIATE so restart and multi-process races preserve single-use.
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
            CREATE TABLE IF NOT EXISTS documents(
              message_type TEXT NOT NULL,
              document_id TEXT NOT NULL,
              digest TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY(message_type, document_id)
            );
            CREATE TABLE IF NOT EXISTS proposals(
              proposal_id TEXT PRIMARY KEY,
              conversation_id TEXT NOT NULL,
              commitment_mode TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS confirmation_requests(
              request_id TEXT PRIMARY KEY,
              request_digest TEXT NOT NULL,
              proposal_id TEXT NOT NULL,
              conversation_id TEXT NOT NULL,
              project_id TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              confirmation_receipt_id TEXT,
              FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
            );
            CREATE INDEX IF NOT EXISTS confirmation_requests_project_pending
              ON confirmation_requests(project_id, status, request_id);
            CREATE TABLE IF NOT EXISTS materializations(
              proposal_id TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_correlations(
              run_id TEXT PRIMARY KEY,
              proposal_id TEXT NOT NULL,
              input_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state_delta_proposals(
              proposal_id TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _identity(document: Mapping[str, Any]) -> tuple[str, str, str]:
        kind = str(document["message_type"])
        ids = {
            "conversation_input": "input_id",
            "action_proposal": "proposal_id",
            "confirmation_request": "confirmation_request_id",
            "confirmation_receipt": "confirmation_receipt_id",
            "action_receipt": "action_receipt_id",
            "candidate_presentation": "presentation_id",
        }
        digests = {
            "conversation_input": "input_digest",
            "action_proposal": "proposal_digest",
            "confirmation_request": "request_digest",
            "confirmation_receipt": "receipt_digest",
            "action_receipt": "receipt_digest",
            "candidate_presentation": "presentation_digest",
        }
        return kind, str(document[ids[kind]]), str(document[digests[kind]])

    def _store_document(self, document: Mapping[str, Any]) -> None:
        kind, document_id, digest = self._identity(document)
        payload = self._json(document)
        prior = self._db.execute(
            "SELECT digest,payload_json FROM documents WHERE message_type=? AND document_id=?",
            (kind, document_id),
        ).fetchone()
        if prior is not None:
            if str(prior["digest"]) == digest and str(prior["payload_json"]) == payload:
                return
            raise ValueError(f"immutable conversation document collision: {kind}/{document_id}")
        self._db.execute(
            "INSERT INTO documents(message_type,document_id,digest,payload_json) VALUES(?,?,?,?)",
            (kind, document_id, digest, payload),
        )

    def _load_document(self, kind: str, document_id: str):
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json FROM documents WHERE message_type=? AND document_id=?",
                (kind, document_id),
            ).fetchone()
        return json.loads(str(row["payload_json"])) if row else None

    def store_input(self, document):
        with self._lock:
            self._store_document(document)

    def store_proposal(self, document):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._store_document(document)
                self._db.execute(
                    "INSERT INTO proposals(proposal_id,conversation_id,commitment_mode,status) "
                    "VALUES(?,?,?,'pending') ON CONFLICT(proposal_id) DO NOTHING",
                    (document["proposal_id"], document["conversation_id"], document["commitment_mode"]),
                )
                row = self._db.execute(
                    "SELECT conversation_id,commitment_mode FROM proposals WHERE proposal_id=?",
                    (document["proposal_id"],),
                ).fetchone()
                if row is None or (
                    str(row["conversation_id"]) != str(document["conversation_id"])
                    or str(row["commitment_mode"]) != str(document["commitment_mode"])
                ):
                    raise ValueError("immutable proposal index collision")
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def load_proposal(self, proposal_id):
        return self._load_document("action_proposal", proposal_id)

    def store_confirmation_request(self, document):
        project_id = str(document.get("project_id") or "")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._store_document(document)
                self._db.execute(
                    "INSERT INTO confirmation_requests(request_id,request_digest,proposal_id,conversation_id,project_id,status) "
                    "VALUES(?,?,?,?,?,'pending') ON CONFLICT(request_id) DO NOTHING",
                    (
                        document["confirmation_request_id"],
                        document["request_digest"],
                        document["proposal_binding"]["proposal_id"],
                        document["conversation_id"],
                        project_id,
                    ),
                )
                row = self._db.execute(
                    "SELECT request_digest,proposal_id,conversation_id,project_id FROM confirmation_requests WHERE request_id=?",
                    (document["confirmation_request_id"],),
                ).fetchone()
                if row is None or (
                    str(row["request_digest"]) != str(document["request_digest"])
                    or str(row["proposal_id"]) != str(document["proposal_binding"]["proposal_id"])
                    or str(row["conversation_id"]) != str(document["conversation_id"])
                    or str(row["project_id"]) != project_id
                ):
                    raise ValueError("immutable confirmation request index collision")
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def load_confirmation_request(self, request_id):
        return self._load_document("confirmation_request", request_id)

    def consume_confirmation_request(self, request_id, request_digest, receipt):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT request_digest,status FROM confirmation_requests WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None or str(row["request_digest"]) != str(request_digest) or str(row["status"]) != "pending":
                    self._db.execute("ROLLBACK")
                    return False
                self._store_document(receipt)
                changed = self._db.execute(
                    "UPDATE confirmation_requests SET status='consumed',confirmation_receipt_id=? "
                    "WHERE request_id=? AND request_digest=? AND status='pending'",
                    (receipt["confirmation_receipt_id"], request_id, request_digest),
                ).rowcount
                if changed != 1:
                    self._db.execute("ROLLBACK")
                    return False
                self._db.execute(
                    "UPDATE proposals SET status='confirmed' WHERE proposal_id=(SELECT proposal_id FROM confirmation_requests WHERE request_id=?)",
                    (request_id,),
                )
                self._db.execute("COMMIT")
                return True
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def cancel_pending(self, target_type, target_id):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if target_type == "proposal":
                    row = self._db.execute(
                        "SELECT commitment_mode,status FROM proposals WHERE proposal_id=?", (target_id,)
                    ).fetchone()
                    if row is None or row["commitment_mode"] != "proposal_only" or row["status"] != "pending":
                        self._db.execute("ROLLBACK")
                        return False
                    changed = self._db.execute(
                        "UPDATE proposals SET status='cancelled' WHERE proposal_id=? AND status='pending'", (target_id,)
                    ).rowcount
                elif target_type == "confirmation_request":
                    row = self._db.execute(
                        "SELECT status,proposal_id FROM confirmation_requests WHERE request_id=?", (target_id,)
                    ).fetchone()
                    if row is None or row["status"] != "pending":
                        self._db.execute("ROLLBACK")
                        return False
                    changed = self._db.execute(
                        "UPDATE confirmation_requests SET status='cancelled' WHERE request_id=? AND status='pending'", (target_id,)
                    ).rowcount
                    if changed:
                        self._db.execute(
                            "UPDATE proposals SET status='cancelled' WHERE proposal_id=? AND status='pending'", (row["proposal_id"],)
                        )
                else:
                    self._db.execute("ROLLBACK")
                    return False
                self._db.execute("COMMIT")
                return changed == 1
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def store_action_receipt(self, document):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._store_document(document)
                self._db.execute(
                    "UPDATE proposals SET status=? WHERE proposal_id=?",
                    ("completed" if document["status"] in {"succeeded", "rejected", "failed"} else "cancelled",
                     document["proposal_binding"]["proposal_id"]),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def store_candidate_presentation(self, document):
        with self._lock:
            self._store_document(document)

    def store_materialization(self, proposal_id, payload):
        serialized = self._json(payload)
        with self._lock:
            prior = self._db.execute(
                "SELECT payload_json FROM materializations WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if prior is not None:
                if str(prior["payload_json"]) != serialized:
                    raise ValueError("immutable capability materialization collision")
                return
            self._db.execute(
                "INSERT INTO materializations(proposal_id,payload_json) VALUES(?,?)", (proposal_id, serialized)
            )

    def load_materialization(self, proposal_id):
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json FROM materializations WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        return json.loads(str(row["payload_json"])) if row else None

    def store_run_correlation(self, run_id, proposal_id, input_id):
        with self._lock:
            self._db.execute(
                "INSERT INTO run_correlations(run_id,proposal_id,input_id) VALUES(?,?,?)", (run_id, proposal_id, input_id)
            )

    def load_run_correlation(self, run_id):
        with self._lock:
            row = self._db.execute(
                "SELECT run_id,proposal_id,input_id FROM run_correlations WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def store_state_delta_proposal(self, proposal_id, payload):
        serialized = self._json(payload)
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json FROM state_delta_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is not None:
                if str(row["payload_json"]) != serialized:
                    raise ValueError("immutable StateDeltaProposal identity collision")
                return
            self._db.execute(
                "INSERT INTO state_delta_proposals(proposal_id,payload_json) VALUES(?,?)", (proposal_id, serialized)
            )

    def load_state_delta_proposal(self, proposal_id):
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json FROM state_delta_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        return json.loads(str(row["payload_json"])) if row else None

    def list_pending(self, conversation_id):
        result = []
        with self._lock:
            proposal_ids = [str(row["proposal_id"]) for row in self._db.execute(
                "SELECT proposal_id FROM proposals WHERE conversation_id=? AND status='pending' ORDER BY proposal_id", (conversation_id,)
            ).fetchall()]
            request_ids = [str(row["request_id"]) for row in self._db.execute(
                "SELECT request_id FROM confirmation_requests WHERE conversation_id=? AND status='pending' ORDER BY request_id", (conversation_id,)
            ).fetchall()]
        result.extend(doc for doc in (self.load_proposal(item) for item in proposal_ids) if doc is not None)
        result.extend(doc for doc in (self.load_confirmation_request(item) for item in request_ids) if doc is not None)
        return tuple(result)

    def list_pending_confirmation_requests(
        self,
        project_id: str,
        *,
        limit: int,
    ):
        """Return a bounded project-scoped set of pending Confirmation Requests."""
        if limit <= 0:
            raise ValueError("pending Confirmation query limit must be positive")
        with self._lock:
            rows = self._db.execute(
                "SELECT d.payload_json FROM confirmation_requests c "
                "JOIN documents d ON d.message_type='confirmation_request' AND d.document_id=c.request_id "
                "WHERE c.project_id=? AND c.status='pending' ORDER BY c.request_id LIMIT ?",
                (str(project_id), int(limit)),
            ).fetchall()
        return tuple(json.loads(str(row["payload_json"])) for row in rows)

    def close(self):
        with self._lock:
            self._db.close()
