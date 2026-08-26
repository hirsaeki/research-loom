from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping
import uuid

import rfc8785

from core.execution.operational_trace import OperationalTraceEvent
from core.execution.ports import ExecutionTraceStore


class LocalOperationalTraceStore:
    """Production append-only Run-bound operational provenance store."""

    def __init__(
        self,
        execution_root: str | Path,
        run_store: ExecutionTraceStore,
    ) -> None:
        root = Path(execution_root)
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "operational-trace.sqlite3"
        self._run_store = run_store
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(self.database), isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_events(
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK(sequence > 0),
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, sequence)
            )
            """
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def append(
        self,
        run_id: str,
        event_type: str,
        occurred_at: str,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
    ) -> OperationalTraceEvent:
        if self._run_store.load_run(run_id) is None:
            raise ValueError(f"operational trace requires an existing Run: {run_id}")
        raw = rfc8785.dumps(dict(payload))
        payload_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        payload_json = raw.decode("utf-8")
        eid = event_id or f"OTE-{uuid.uuid4().hex}"
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._connection.execute(
                    "SELECT * FROM operational_events WHERE event_id=?",
                    (eid,),
                ).fetchone()
                if prior is not None:
                    if (
                        str(prior["run_id"]) != str(run_id)
                        or str(prior["event_type"]) != str(event_type)
                        or str(prior["occurred_at"]) != str(occurred_at)
                        or str(prior["payload_sha256"]) != payload_digest
                        or str(prior["payload_json"]) != payload_json
                    ):
                        raise ValueError("immutable operational event identity collision")
                    self._connection.execute("COMMIT")
                    return self._decode(prior)
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS n FROM operational_events WHERE run_id=?",
                    (str(run_id),),
                ).fetchone()
                sequence = int(row["n"]) + 1
                self._connection.execute(
                    """
                    INSERT INTO operational_events(
                        run_id, sequence, event_id, event_type, occurred_at,
                        payload_sha256, payload_json
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        str(run_id), sequence, eid, str(event_type), str(occurred_at),
                        payload_digest, payload_json,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return OperationalTraceEvent(
            str(run_id), sequence, eid, str(event_type), str(occurred_at),
            json.loads(payload_json),
        )

    def events_for(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> tuple[OperationalTraceEvent, ...]:
        sql = "SELECT * FROM operational_events WHERE run_id=?"
        args: list[Any] = [str(run_id)]
        if event_type is not None:
            sql += " AND event_type=?"
            args.append(str(event_type))
        sql += " ORDER BY sequence"
        with self._lock:
            rows = self._connection.execute(sql, tuple(args)).fetchall()
        return tuple(self._decode(row) for row in rows)

    @staticmethod
    def _decode(row: sqlite3.Row) -> OperationalTraceEvent:
        payload_json = str(row["payload_json"])
        payload = json.loads(payload_json)
        raw = rfc8785.dumps(payload)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if digest != str(row["payload_sha256"]) or raw.decode("utf-8") != payload_json:
            raise ValueError("persisted operational trace payload is corrupt")
        return OperationalTraceEvent(
            str(row["run_id"]),
            int(row["sequence"]),
            str(row["event_id"]),
            str(row["event_type"]),
            str(row["occurred_at"]),
            payload,
        )
