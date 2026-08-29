from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from core.conversation import canonical_digest


ROOT = Path(__file__).resolve().parents[1]
ATTENTION_MAP_SCHEMA_PATH = ROOT / "projects/contracts/research-attention-map.schema.json"
ATTENTION_STORE_SCHEMA_VERSION = "0.1.0"


class LocalAttentionStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def attention_map_digest(value: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(value))
    payload.pop("map_digest", None)
    return canonical_digest(payload)


def attention_event_digest(value: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(value))
    payload.pop("event_digest", None)
    return canonical_digest(payload)


def _map_validator() -> Draft202012Validator:
    schema = json.loads(ATTENTION_MAP_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_attention_map(value: Mapping[str, Any]) -> None:
    errors = sorted(
        _map_validator().iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise LocalAttentionStoreError(
            "ATTENTION-MAP-SCHEMA-001",
            f"Attention Map schema violation at {location}: {error.message}",
        )
    if value.get("map_digest") != attention_map_digest(value):
        raise LocalAttentionStoreError(
            "ATTENTION-MAP-DIGEST-001", "Attention Map digest does not match immutable content"
        )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS attention_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS attention_maps (
    map_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    map_digest TEXT NOT NULL,
    document_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS attention_maps_digest_idx
    ON attention_maps(map_digest);
CREATE TABLE IF NOT EXISTS attention_activation_events (
    activation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    map_id TEXT NOT NULL,
    map_digest TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    event_digest TEXT NOT NULL,
    document_json TEXT NOT NULL,
    FOREIGN KEY(map_id) REFERENCES attention_maps(map_id)
);
CREATE TABLE IF NOT EXISTS active_attention_map (
    project_id TEXT PRIMARY KEY,
    map_id TEXT NOT NULL,
    map_digest TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    FOREIGN KEY(map_id) REFERENCES attention_maps(map_id),
    FOREIGN KEY(activation_id) REFERENCES attention_activation_events(activation_id)
);
"""


def _read_schema_version(connection: sqlite3.Connection) -> str:
    try:
        row = connection.execute(
            "SELECT schema_version FROM attention_store_meta"
        ).fetchone()
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-SCHEMA-001", "Attention store schema is missing or incompatible"
        ) from exc
    if row is None or str(row[0]) != ATTENTION_STORE_SCHEMA_VERSION:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-SCHEMA-001", "Attention store schema version is incompatible"
        )
    return str(row[0])


def validate_attention_store_schema(path: str | Path) -> None:
    database = Path(path)
    if not database.is_file():
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-MISSING-001", "Attention store does not exist"
        )
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
            if row is None or str(row[0]).lower() != "ok":
                raise LocalAttentionStoreError(
                    "ATTENTION-STORE-DB-001", "Attention store SQLite quick_check failed"
                )
            _read_schema_version(connection)
            required = {
                "attention_store_meta",
                "attention_maps",
                "attention_activation_events",
                "active_attention_map",
            }
            present = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not required <= present:
                raise LocalAttentionStoreError(
                    "ATTENTION-STORE-SCHEMA-001", "Attention store tables are incomplete"
                )
        finally:
            connection.close()
    except LocalAttentionStoreError:
        raise
    except sqlite3.Error as exc:
        raise LocalAttentionStoreError(
            "ATTENTION-STORE-DB-001", "Attention store is unreadable"
        ) from exc


class LocalAttentionStore:
    """Optional additive guidance store. Reads never create the SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _connect_read(self) -> sqlite3.Connection | None:
        if not self.exists:
            return None
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            _read_schema_version(connection)
            return connection
        except Exception:
            if "connection" in locals():
                connection.close()
            raise

    def _connect_write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA_SQL)
            connection.execute(
                "INSERT OR IGNORE INTO attention_store_meta(schema_version) VALUES (?)",
                (ATTENTION_STORE_SCHEMA_VERSION,),
            )
            _read_schema_version(connection)
            connection.commit()
            return connection
        except Exception:
            if "connection" in locals():
                connection.close()
            raise

    def load_map(self, map_id: str) -> Mapping[str, Any] | None:
        connection = self._connect_read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT document_json FROM attention_maps WHERE map_id=?", (str(map_id),)
            ).fetchone()
            if row is None:
                return None
            value = json.loads(str(row["document_json"]))
            validate_attention_map(value)
            return value
        finally:
            connection.close()

    def load_active(self, project_id: str) -> Mapping[str, Any] | None:
        connection = self._connect_read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                """
                SELECT p.map_id, p.map_digest, p.activation_id, m.document_json
                FROM active_attention_map p
                JOIN attention_maps m ON m.map_id=p.map_id
                WHERE p.project_id=?
                """,
                (str(project_id),),
            ).fetchone()
            if row is None:
                return None
            value = json.loads(str(row["document_json"]))
            validate_attention_map(value)
            if value["map_id"] != row["map_id"] or value["map_digest"] != row["map_digest"]:
                raise LocalAttentionStoreError(
                    "ATTENTION-STORE-INTEGRITY-001", "active Attention pointer does not match stored map"
                )
            return {
                "map_id": str(row["map_id"]),
                "map_digest": str(row["map_digest"]),
                "activation_id": str(row["activation_id"]),
                "map": value,
            }
        finally:
            connection.close()

    def store_map(self, value: Mapping[str, Any]) -> None:
        document = deepcopy(dict(value))
        validate_attention_map(document)
        serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection = self._connect_write()
        try:
            with connection:
                existing = connection.execute(
                    "SELECT map_digest, document_json FROM attention_maps WHERE map_id=?",
                    (str(document["map_id"]),),
                ).fetchone()
                if existing is not None:
                    raise LocalAttentionStoreError(
                        "ATTENTION-MAP-IMMUTABLE-001", "Attention Map ID already exists; overwrite is forbidden"
                    )
                connection.execute(
                    "INSERT INTO attention_maps(map_id, project_id, map_digest, document_json) VALUES (?,?,?,?)",
                    (
                        str(document["map_id"]),
                        str(document["project_id"]),
                        str(document["map_digest"]),
                        serialized,
                    ),
                )
        finally:
            connection.close()

    def activate(
        self,
        *,
        project_id: str,
        map_id: str,
        activation_id: str,
        actor_id: str,
        source_action_proposal: Mapping[str, Any],
        activated_at: str,
    ) -> Mapping[str, Any]:
        connection = self._connect_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT project_id, map_digest, document_json FROM attention_maps WHERE map_id=?",
                (str(map_id),),
            ).fetchone()
            if row is None:
                raise LocalAttentionStoreError(
                    "ATTENTION-MAP-UNKNOWN-001", f"unknown Attention Map: {map_id}"
                )
            document = json.loads(str(row["document_json"]))
            validate_attention_map(document)
            if str(row["project_id"]) != str(project_id) or document["project_id"] != str(project_id):
                raise LocalAttentionStoreError(
                    "ATTENTION-MAP-PROJECT-001", "Attention Map belongs to a different project"
                )

            prior = connection.execute(
                "SELECT map_id, map_digest FROM active_attention_map WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
            base = document["base"]
            if base["source"] == "project_config_baseline":
                matches = prior is None
            else:
                matches = (
                    prior is not None
                    and str(prior["map_id"]) == str(base["map_id"])
                    and str(prior["map_digest"]) == str(base["map_digest"])
                )
            if not matches:
                raise LocalAttentionStoreError(
                    "ATTENTION-STALE-001",
                    "Attention Map base no longer matches current active guidance; automatic merge/rebase is forbidden",
                )

            event: dict[str, Any] = {
                "schema_version": "0.1.0",
                "activation_id": str(activation_id),
                "project_id": str(project_id),
                "map_id": str(document["map_id"]),
                "map_digest": str(document["map_digest"]),
                "prior_map_id": str(prior["map_id"]) if prior is not None else None,
                "prior_map_digest": str(prior["map_digest"]) if prior is not None else None,
                "source_action_proposal": {
                    "proposal_id": str(source_action_proposal["proposal_id"]),
                    "proposal_digest": str(source_action_proposal["proposal_digest"]),
                },
                "actor_id": str(actor_id),
                "activated_at": str(activated_at),
            }
            event["event_digest"] = attention_event_digest(event)
            event_json = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            connection.execute(
                """
                INSERT INTO attention_activation_events(
                    activation_id, project_id, map_id, map_digest, activated_at, event_digest, document_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    str(activation_id), str(project_id), str(document["map_id"]),
                    str(document["map_digest"]), str(activated_at), str(event["event_digest"]), event_json,
                ),
            )
            connection.execute(
                """
                INSERT INTO active_attention_map(project_id, map_id, map_digest, activation_id)
                VALUES (?,?,?,?)
                ON CONFLICT(project_id) DO UPDATE SET
                    map_id=excluded.map_id,
                    map_digest=excluded.map_digest,
                    activation_id=excluded.activation_id
                """,
                (str(project_id), str(document["map_id"]), str(document["map_digest"]), str(activation_id)),
            )
            connection.commit()
            return event
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def activation_events(self, project_id: str) -> tuple[Mapping[str, Any], ...]:
        connection = self._connect_read()
        if connection is None:
            return ()
        try:
            rows = connection.execute(
                "SELECT document_json FROM attention_activation_events WHERE project_id=? ORDER BY rowid",
                (str(project_id),),
            ).fetchall()
            return tuple(json.loads(str(row["document_json"])) for row in rows)
        finally:
            connection.close()
