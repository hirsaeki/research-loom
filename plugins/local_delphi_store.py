from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

import rfc8785

SCHEMA_VERSION = "0.1.0"


class LocalDelphiStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_digest(value: Any, *, omit: tuple[str, ...] = ()) -> str:
    payload = deepcopy(value)
    if isinstance(payload, dict):
        for field in omit:
            payload.pop(field, None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def registry_digest(document: Mapping[str, Any]) -> str:
    return canonical_digest(dict(document), omit=("registry_digest",))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS delphi_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS delphi_documents (
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    identity TEXT NOT NULL,
    version TEXT NOT NULL,
    panel_id TEXT,
    round_sequence INTEGER,
    content_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, kind, identity, version)
);
CREATE INDEX IF NOT EXISTS idx_delphi_panel_round
ON delphi_documents(project_id, panel_id, round_sequence, kind);
"""


class LocalDelphiStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            con.executescript(_SCHEMA)
            con.execute(
                "INSERT OR IGNORE INTO delphi_store_meta(schema_version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            row = con.execute("SELECT schema_version FROM delphi_store_meta").fetchone()
            if row is None or str(row[0]) != SCHEMA_VERSION:
                raise LocalDelphiStoreError(
                    "DELPHI-STORE-SCHEMA-001", "Delphi registry schema is incompatible"
                )
            con.commit()
            return con
        except LocalDelphiStoreError:
            if "con" in locals():
                con.close()
            raise
        except sqlite3.Error as exc:
            if "con" in locals():
                con.close()
            raise LocalDelphiStoreError(
                "DELPHI-STORE-DB-001", "Delphi registry could not be initialized"
            ) from exc

    def _read(self) -> sqlite3.Connection | None:
        if not self.exists:
            return None
        try:
            con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT schema_version FROM delphi_store_meta").fetchone()
            if row is None or str(row[0]) != SCHEMA_VERSION:
                raise LocalDelphiStoreError(
                    "DELPHI-STORE-SCHEMA-001", "Delphi registry schema is incompatible"
                )
            return con
        except LocalDelphiStoreError:
            if "con" in locals():
                con.close()
            raise
        except sqlite3.Error as exc:
            if "con" in locals():
                con.close()
            raise LocalDelphiStoreError(
                "DELPHI-STORE-DB-001", "Delphi registry is unreadable"
            ) from exc

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        try:
            value = json.loads(str(row["document_json"]))
        except json.JSONDecodeError as exc:
            raise LocalDelphiStoreError(
                "DELPHI-STORE-INTEGRITY-001", "stored Delphi document is invalid JSON"
            ) from exc
        if not isinstance(value, dict) or value.get("registry_digest") != registry_digest(value):
            raise LocalDelphiStoreError(
                "DELPHI-STORE-INTEGRITY-001", "stored Delphi document digest is invalid"
            )
        if (
            str(value.get("project_id")) != str(row["project_id"])
            or str(value.get("document_kind")) != str(row["kind"])
            or str(value.get("identity")) != str(row["identity"])
            or str(value.get("version")) != str(row["version"])
            or str(value.get("content_digest")) != str(row["content_digest"])
            or str(value.get("created_at")) != str(row["created_at"])
        ):
            raise LocalDelphiStoreError(
                "DELPHI-STORE-INTEGRITY-001", "stored Delphi row metadata is inconsistent"
            )
        return value

    def capture(self, document: Mapping[str, Any]) -> bool:
        required = {
            "project_id", "document_kind", "identity", "version",
            "content_digest", "created_at", "registry_digest",
        }
        if not required <= set(document) or document["registry_digest"] != registry_digest(document):
            raise LocalDelphiStoreError(
                "DELPHI-STORE-INTEGRITY-001", "Delphi registry document is invalid"
            )
        con = self._write()
        try:
            row = con.execute(
                "SELECT * FROM delphi_documents WHERE project_id=? AND kind=? AND identity=? AND version=?",
                (
                    str(document["project_id"]), str(document["document_kind"]),
                    str(document["identity"]), str(document["version"]),
                ),
            ).fetchone()
            if row is not None:
                existing = self._decode(row)
                comparable_existing = deepcopy(existing)
                comparable_new = deepcopy(dict(document))
                for value in (comparable_existing, comparable_new):
                    value.pop("created_at", None)
                    value.pop("registry_digest", None)
                if comparable_existing != comparable_new:
                    raise LocalDelphiStoreError(
                        "DELPHI-STORE-CONFLICT-001",
                        "immutable Delphi identity already exists with different content",
                    )
                return False
            con.execute(
                "INSERT INTO delphi_documents(project_id,kind,identity,version,panel_id,round_sequence,content_digest,created_at,document_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(document["project_id"]), str(document["document_kind"]),
                    str(document["identity"]), str(document["version"]),
                    document.get("panel_id"), document.get("round_sequence"),
                    str(document["content_digest"]), str(document["created_at"]),
                    json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
            con.commit()
            return True
        except LocalDelphiStoreError:
            con.rollback()
            raise
        except sqlite3.Error as exc:
            con.rollback()
            raise LocalDelphiStoreError(
                "DELPHI-STORE-DB-001", "Delphi document could not be persisted"
            ) from exc
        finally:
            con.close()

    def load(self, project_id: str, kind: str, identity: str, version: str = "1") -> dict[str, Any] | None:
        con = self._read()
        if con is None:
            return None
        try:
            row = con.execute(
                "SELECT * FROM delphi_documents WHERE project_id=? AND kind=? AND identity=? AND version=?",
                (project_id, kind, identity, version),
            ).fetchone()
            return None if row is None else deepcopy(self._decode(row))
        finally:
            con.close()

    def panel_documents(self, project_id: str, panel_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        con = self._read()
        if con is None:
            return []
        try:
            sql = "SELECT * FROM delphi_documents WHERE project_id=? AND panel_id=?"
            params: list[Any] = [project_id, panel_id]
            if kind is not None:
                sql += " AND kind=?"
                params.append(kind)
            sql += " ORDER BY COALESCE(round_sequence,0), created_at, identity, version"
            return [deepcopy(self._decode(row)) for row in con.execute(sql, params).fetchall()]
        finally:
            con.close()
