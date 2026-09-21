from __future__ import annotations

from plugins.local_durable_store import require_optional_available, register_optional_path

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
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

    @staticmethod
    def _check_schema(con: sqlite3.Connection) -> None:
        rows = con.execute("SELECT schema_version FROM delphi_store_meta").fetchall()
        required = {"project_id", "kind", "identity", "version", "panel_id",
                    "round_sequence", "content_digest", "created_at", "document_json"}
        columns = {row["name"] for row in con.execute("PRAGMA table_info(delphi_documents)")}
        if len(rows) != 1 or str(rows[0][0]) != SCHEMA_VERSION or not required <= columns:
            raise LocalDelphiStoreError("DELPHI-STORE-SCHEMA-001", "Delphi registry schema is incompatible")

    def _initialize(self) -> None:
        descriptor, name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        os.close(descriptor)
        staging = Path(name)
        try:
            con = sqlite3.connect(staging)
            try:
                con.row_factory = sqlite3.Row
                con.executescript(_SCHEMA)
                con.execute("INSERT INTO delphi_store_meta(schema_version) VALUES (?)", (SCHEMA_VERSION,))
                con.commit()
                self._check_schema(con)
            finally:
                con.close()
            try:
                os.link(staging, self.path)
            except FileExistsError:
                pass  # Never replace a concurrent initializer's complete store.
        finally:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass

    def _write(self) -> sqlite3.Connection:
        require_optional_available(self.path, LocalDelphiStoreError)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not self.exists:
                self._initialize()
            con = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=5.0)
            con.row_factory = sqlite3.Row
            self._check_schema(con)
            register_optional_path(self.path)
            return con
        except BaseException as exc:
            if "con" in locals():
                con.close()
            if isinstance(exc, (sqlite3.Error, OSError)):
                raise LocalDelphiStoreError("DELPHI-STORE-DB-001", "Delphi registry could not be opened for writing") from exc
            raise

    def _read(self) -> sqlite3.Connection | None:
        require_optional_available(self.path, LocalDelphiStoreError)
        if not self.exists:
            return None
        try:
            con = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            self._check_schema(con)
            return con
        except BaseException as exc:
            if "con" in locals():
                con.close()
            if isinstance(exc, sqlite3.Error):
                raise LocalDelphiStoreError("DELPHI-STORE-DB-001", "Delphi registry is unreadable") from exc
            raise

    @contextmanager
    def _transaction(self):
        con = self._write()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException as exc:
            con.rollback()
            if isinstance(exc, sqlite3.Error):
                raise LocalDelphiStoreError("DELPHI-STORE-DB-001", "Delphi document could not be persisted") from exc
            raise
        finally:
            con.close()

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
            or value.get("panel_id") != row["panel_id"]
            or value.get("round_sequence") != row["round_sequence"]
        ):
            raise LocalDelphiStoreError(
                "DELPHI-STORE-INTEGRITY-001", "stored Delphi row metadata is inconsistent"
            )
        return value

    @staticmethod
    def _validate(document: Mapping[str, Any]) -> None:
        required = {"project_id", "document_kind", "identity", "version",
                    "content_digest", "created_at", "registry_digest"}
        if not required <= set(document) or document["registry_digest"] != registry_digest(document):
            raise LocalDelphiStoreError("DELPHI-STORE-INTEGRITY-001", "Delphi registry document is invalid")

    @classmethod
    def _load_on(cls, con, project_id, kind, identity, version="1"):
        row = con.execute(
            "SELECT * FROM delphi_documents WHERE project_id=? AND kind=? AND identity=? AND version=?",
            (project_id, kind, identity, version),
        ).fetchone()
        return None if row is None else cls._decode(row)

    @classmethod
    def _insert_on(cls, con, document: Mapping[str, Any]) -> None:
        cls._validate(document)
        con.execute(
            "INSERT INTO delphi_documents(project_id,kind,identity,version,panel_id,round_sequence,content_digest,created_at,document_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (document["project_id"], document["document_kind"], document["identity"], document["version"],
             document.get("panel_id"), document.get("round_sequence"), document["content_digest"],
             document["created_at"], json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        )

    @classmethod
    def _capture_on(cls, con, document: Mapping[str, Any]) -> bool:
        cls._validate(document)
        existing = cls._load_on(con, document["project_id"], document["document_kind"], document["identity"], document["version"])
        if existing is not None:
            ignored = ("created_at", "registry_digest")
            if canonical_digest(existing, omit=ignored) != canonical_digest(dict(document), omit=ignored):
                raise LocalDelphiStoreError("DELPHI-STORE-CONFLICT-001", "immutable Delphi identity already exists with different content")
            return False
        cls._insert_on(con, document)
        return True

    def capture(self, document: Mapping[str, Any]) -> bool:
        self._validate(document)
        with self._transaction() as con:
            return self._capture_on(con, document)

    def capture_approval_request(self, document: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        self._validate(document)
        if document["document_kind"] != "approval_request":
            raise LocalDelphiStoreError("DELPHI-STORE-INTEGRITY-001", "expected an Instrument approval request")
        with self._transaction() as con:
            rows = con.execute(
                "SELECT * FROM delphi_documents WHERE project_id=? AND kind='approval_request' AND content_digest=? LIMIT 2",
                (document["project_id"], document["content_digest"]),
            ).fetchall()
            if rows:
                prior = self._decode(rows[0])
                if len(rows) != 1 or prior["request_basis"] != document["request_basis"]:
                    raise LocalDelphiStoreError("DELPHI-STORE-CONFLICT-001", "Instrument approval request identity is ambiguous")
                return prior, False
            self._insert_on(con, document)
            return deepcopy(dict(document)), True

    def resolve_approval(self, request: Mapping[str, Any], receipt: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        self._validate(request)
        self._validate(receipt)
        with self._transaction() as con:
            stored = self._load_on(con, request["project_id"], "approval_request", request["identity"])
            if stored != request:
                raise LocalDelphiStoreError("DELPHI-STORE-CONFLICT-001", "Instrument approval request changed or is unavailable")
            prior = self._load_on(con, receipt["project_id"], "approval_receipt", receipt["identity"])
            target = request["target_document"]
            if prior is not None:
                if canonical_digest(prior, omit=("created_at", "registry_digest")) != canonical_digest(dict(receipt), omit=("created_at", "registry_digest")):
                    raise LocalDelphiStoreError("DELPHI-STORE-CONFLICT-001", "another Human Decision already resolved this request")
                if prior["choice"] == "approve_exact":
                    instrument = self._load_on(con, target["project_id"], "instrument", target["identity"], target["version"])
                    if instrument != target:
                        raise LocalDelphiStoreError("DELPHI-STORE-INTEGRITY-001", "approved Instrument/receipt mismatch; restore an exact backup")
                return prior, False
            if receipt["choice"] == "approve_exact":
                self._capture_on(con, target)
            self._insert_on(con, receipt)
            return deepcopy(dict(receipt)), True

    def capture_round_revision(self, document: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        # One existing SQLite transaction allocates a revision and its full result.
        # No mutable head or separate response write can leave half a Round behind.
        self._validate(document)
        if document["document_kind"] != "round":
            raise LocalDelphiStoreError("DELPHI-STORE-INTEGRITY-001", "expected a Round result")
        with self._transaction() as con:
            params = (document["project_id"], document["identity"])
            exact = con.execute(
                "SELECT * FROM delphi_documents WHERE project_id=? AND kind='round' AND identity=? AND content_digest=? LIMIT 2",
                (*params, document["content_digest"]),
            ).fetchall()
            if exact:
                prior = self._decode(exact[0])
                ignored = ("created_at", "registry_digest", "version")
                if len(exact) != 1 or canonical_digest(prior, omit=ignored) != canonical_digest(dict(document), omit=ignored):
                    raise LocalDelphiStoreError("DELPHI-STORE-CONFLICT-001", "Round result digest resolves inconsistently")
                return prior, False
            source_ref = document.get("recalculated_from")
            if source_ref is not None:
                source = self._load_on(con, document["project_id"], "round", source_ref["round_result_id"], source_ref["version"])
                if (source is None or source["content_digest"] != source_ref["content_digest"]
                    or source["identity"] != document["identity"]
                    or source["instrument_ref"] != document["instrument_ref"]
                    or source["panel_id"] != document["panel_id"]
                    or source["round_sequence"] != document["round_sequence"]
                    or sorted(source["expected_participant_ids"]) != document["expected_participant_ids"]
                    or sorted(source["responses"], key=lambda row: (row["participant_id"], row["response_id"])) != document["responses"]):
                    raise LocalDelphiStoreError("DELPHI-STORE-INTEGRITY-001", "recalculation source does not bind the exact historical response set")
            previous = con.execute(
                "SELECT * FROM delphi_documents WHERE project_id=? AND kind='round' AND identity=? "
                "AND json_extract(document_json, '$.instrument_ref.content_digest')=? "
                "AND json_type(document_json, '$.recalculated_from') IS NULL "
                "ORDER BY CAST(version AS INTEGER) DESC LIMIT 1",
                (*params, document["instrument_ref"]["content_digest"]),
            ).fetchone()
            if previous is not None and source_ref is None:
                prior = self._decode(previous)
                new_responses = {entry["response_id"]: entry for entry in document["responses"]}
                if (prior["instrument_ref"] != document["instrument_ref"]
                    or not set(prior["expected_participant_ids"]) <= set(document["expected_participant_ids"])
                    or any(new_responses.get(entry["response_id"]) != entry for entry in prior["responses"])):
                    raise LocalDelphiStoreError("DELPHI-STORE-CONFLICT-001", "late-response revision must preserve earlier answers and expected participants")
            latest = con.execute(
                "SELECT version FROM delphi_documents WHERE project_id=? AND kind='round' AND identity=? "
                "ORDER BY CAST(version AS INTEGER) DESC LIMIT 1", params,
            ).fetchone()
            version = 0 if latest is None else int(latest["version"])
            if latest is not None and (version < 1 or str(version) != latest["version"]):
                raise LocalDelphiStoreError("DELPHI-STORE-INTEGRITY-001", "stored Round revision is invalid")
            result = deepcopy(dict(document))
            result["version"] = str(version + 1)
            result["registry_digest"] = registry_digest(result)
            self._insert_on(con, result)
            return result, True

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

    def panel_documents(self, project_id: str, panel_id: str, kind: str | None = None, *, limit: int = 101, offset: int = 0, round_sequence: int | None = None) -> list[dict[str, Any]]:
        con = self._read()
        if con is None:
            return []
        try:
            sql = "SELECT * FROM delphi_documents WHERE project_id=? AND panel_id=?"
            params: list[Any] = [project_id, panel_id]
            if kind is not None:
                sql += " AND kind=?"
                params.append(kind)
            if round_sequence is not None:
                sql += " AND round_sequence=?"
                params.append(round_sequence)
            sql += " ORDER BY COALESCE(round_sequence,0), created_at, identity, version LIMIT ? OFFSET ?"
            params.extend((limit, offset))
            return [deepcopy(self._decode(row)) for row in con.execute(sql, params).fetchall()]
        finally:
            con.close()
