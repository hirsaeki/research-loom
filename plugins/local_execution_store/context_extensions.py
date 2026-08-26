from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping

import rfc8785


class LocalCapabilityContextExtensionStore:
    """Production local immutable store for capability Context extensions.

    This is non-authoritative execution input provenance. It deliberately lives
    beside, rather than inside, authoritative Research State persistence.
    """

    def __init__(self, execution_root: str | Path) -> None:
        root = Path(execution_root)
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "context-extensions.sqlite3"
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(self.database), isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS context_extensions(
                capability_id TEXT NOT NULL,
                capability_version TEXT NOT NULL,
                function_id TEXT NOT NULL,
                context_pack_id TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(
                    capability_id, capability_version, function_id, context_pack_id
                )
            )
            """
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _payload(extension: Mapping[str, Any]) -> tuple[str, str]:
        raw = rfc8785.dumps(dict(extension))
        return "sha256:" + hashlib.sha256(raw).hexdigest(), raw.decode("utf-8")

    def store(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
        context_pack_id: str,
        extension: Mapping[str, Any],
    ) -> str:
        digest, payload_json = self._payload(extension)
        key = (
            str(capability_id), str(capability_version), str(function_id),
            str(context_pack_id),
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._connection.execute(
                    """
                    SELECT payload_sha256, payload_json FROM context_extensions
                    WHERE capability_id=? AND capability_version=?
                      AND function_id=? AND context_pack_id=?
                    """,
                    key,
                ).fetchone()
                if prior is not None:
                    if (
                        str(prior["payload_sha256"]) != digest
                        or str(prior["payload_json"]) != payload_json
                    ):
                        raise ValueError(
                            "immutable capability Context extension identity collision"
                        )
                    self._connection.execute("COMMIT")
                    return digest
                self._connection.execute(
                    """
                    INSERT INTO context_extensions(
                        capability_id, capability_version, function_id,
                        context_pack_id, payload_sha256, payload_json
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (*key, digest, payload_json),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return digest

    def load(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
        context_pack_id: str,
    ) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_sha256, payload_json FROM context_extensions
                WHERE capability_id=? AND capability_version=?
                  AND function_id=? AND context_pack_id=?
                """,
                (
                    str(capability_id), str(capability_version), str(function_id),
                    str(context_pack_id),
                ),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        digest, canonical = self._payload(payload)
        if digest != str(row["payload_sha256"]) or canonical != str(row["payload_json"]):
            raise ValueError("persisted capability Context extension is corrupt")
        return deepcopy(payload)
