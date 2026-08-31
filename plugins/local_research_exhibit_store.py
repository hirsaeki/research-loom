from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

import rfc8785


EXHIBIT_STORE_SCHEMA_VERSION = "0.1.0"
EXHIBIT_CONTENT_MAX_BYTES = 1_048_576
SUPPORTED_EXHIBIT_KINDS = frozenset({"table", "matrix", "graph", "note"})
SUPPORTED_EXHIBIT_REPRESENTATIONS = frozenset({"markdown", "json", "text"})
_MEDIA_TYPES = {
    "markdown": "text/markdown",
    "json": "application/json",
    "text": "text/plain",
}
_METADATA_FIELDS = {
    "exhibit_id",
    "project_id",
    "kind",
    "title",
    "purpose",
    "rq_ids",
    "source_run_ids",
    "source_artifact_refs",
    "source_object_ids",
    "derived_from_exhibit_ids",
    "content_representation",
    "content_digest",
    "captured_against",
    "captured_at",
    "capture_origin",
}


class LocalResearchExhibitStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_bytes(content: Mapping[str, Any]) -> bytes:
    representation = content.get("representation")
    value = content.get("value")
    if representation not in SUPPORTED_EXHIBIT_REPRESENTATIONS:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-CONTENT-001", "unsupported Research Exhibit content representation"
        )
    if representation == "json":
        if not isinstance(value, (dict, list)):
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-CONTENT-001", "JSON Research Exhibit content must be an object or array"
            )
        try:
            return rfc8785.dumps(value)
        except (TypeError, ValueError) as exc:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-CONTENT-001", "JSON Research Exhibit content is not canonicalizable"
            ) from exc
    if not isinstance(value, str):
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-CONTENT-001", "text Research Exhibit content must be a UTF-8 string"
        )
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-CONTENT-001", "Research Exhibit text content is not valid UTF-8"
        ) from exc


def content_digest(content: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(content_bytes(content)).hexdigest()


def normalized_content(content: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(content, Mapping) or set(content) != {"representation", "value"}:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-CONTENT-001",
            "content accepts only representation and value",
        )
    representation = str(content["representation"])
    normalized = {
        "representation": representation,
        "media_type": _MEDIA_TYPES.get(representation),
        "value": deepcopy(content["value"]),
    }
    encoded = content_bytes(normalized)
    if len(encoded) > EXHIBIT_CONTENT_MAX_BYTES:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-CONTENT-SIZE-001",
            f"Research Exhibit content exceeds {EXHIBIT_CONTENT_MAX_BYTES} bytes",
        )
    return normalized


def _validate_string_list(value: Any, field: str, *, required: bool = False) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
        or (required and not value)
    ):
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", f"Research Exhibit {field} is invalid"
        )


def _validate_snapshot_binding(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "lineage_ref", "snapshot_ref", "snapshot_digest"
    }:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "Research Exhibit snapshot binding is invalid"
        )
    if any(
        not isinstance(value.get(field), str) or not value[field].strip()
        for field in ("lineage_ref", "snapshot_ref", "snapshot_digest")
    ):
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "Research Exhibit snapshot binding is incomplete"
        )


def validate_exhibit_document(value: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "exhibit_id",
        "project_id",
        "kind",
        "title",
        "purpose",
        "rq_ids",
        "source_run_ids",
        "source_artifact_refs",
        "source_object_ids",
        "derived_from_exhibit_ids",
        "captured_against",
        "content",
        "content_digest",
        "provenance",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "stored Research Exhibit document shape is invalid"
        )
    if value.get("schema_version") != "0.1.0":
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "Research Exhibit schema version is incompatible"
        )
    for field in ("exhibit_id", "project_id", "title", "purpose"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-DOCUMENT-001", f"Research Exhibit {field} must be non-empty"
            )
    if value.get("kind") not in SUPPORTED_EXHIBIT_KINDS:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "stored Research Exhibit kind is unsupported"
        )
    for field in (
        "source_run_ids",
        "source_artifact_refs",
        "source_object_ids",
        "derived_from_exhibit_ids",
    ):
        _validate_string_list(value.get(field), field)
    _validate_string_list(value.get("rq_ids"), "rq_ids", required=True)
    _validate_snapshot_binding(value.get("captured_against"))

    content = value.get("content")
    if not isinstance(content, Mapping) or set(content) != {
        "representation", "media_type", "value"
    }:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "stored Research Exhibit content shape is invalid"
        )
    representation = content.get("representation")
    if representation not in SUPPORTED_EXHIBIT_REPRESENTATIONS:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "stored Research Exhibit representation is unsupported"
        )
    if content.get("media_type") != _MEDIA_TYPES[representation]:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "stored Research Exhibit media type is inconsistent"
        )
    encoded = content_bytes(content)
    if len(encoded) > EXHIBIT_CONTENT_MAX_BYTES:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-CONTENT-SIZE-001", "stored Research Exhibit content exceeds the local limit"
        )
    if value.get("content_digest") != "sha256:" + hashlib.sha256(encoded).hexdigest():
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DIGEST-001", "Research Exhibit content digest does not match stored content"
        )

    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping) or set(provenance) != {
        "captured_at", "capture_origin"
    }:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-DOCUMENT-001", "Research Exhibit provenance shape is invalid"
        )
    for field in ("captured_at", "capture_origin"):
        item = provenance.get(field)
        if not isinstance(item, str) or not item.strip():
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-DOCUMENT-001", f"Research Exhibit provenance {field} is invalid"
            )


def _metadata_from_document(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "exhibit_id": str(document["exhibit_id"]),
        "project_id": str(document["project_id"]),
        "kind": str(document["kind"]),
        "title": str(document["title"]),
        "purpose": str(document["purpose"]),
        "rq_ids": list(document["rq_ids"]),
        "source_run_ids": list(document["source_run_ids"]),
        "source_artifact_refs": list(document["source_artifact_refs"]),
        "source_object_ids": list(document["source_object_ids"]),
        "derived_from_exhibit_ids": list(document["derived_from_exhibit_ids"]),
        "content_representation": str(document["content"]["representation"]),
        "content_digest": str(document["content_digest"]),
        "captured_against": deepcopy(dict(document["captured_against"])),
        "captured_at": str(document["provenance"]["captured_at"]),
        "capture_origin": str(document["provenance"]["capture_origin"]),
    }


def _validate_exhibit_metadata(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != _METADATA_FIELDS:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-STORE-INTEGRITY-001", "stored Research Exhibit metadata shape is invalid"
        )
    for field in (
        "exhibit_id",
        "project_id",
        "kind",
        "title",
        "purpose",
        "content_representation",
        "content_digest",
        "captured_at",
        "capture_origin",
    ):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-INTEGRITY-001", f"stored Research Exhibit metadata {field} is invalid"
            )
    if value["kind"] not in SUPPORTED_EXHIBIT_KINDS:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-STORE-INTEGRITY-001", "stored Research Exhibit metadata kind is unsupported"
        )
    if value["content_representation"] not in SUPPORTED_EXHIBIT_REPRESENTATIONS:
        raise LocalResearchExhibitStoreError(
            "EXHIBIT-STORE-INTEGRITY-001", "stored Research Exhibit metadata representation is unsupported"
        )
    for field in (
        "source_run_ids",
        "source_artifact_refs",
        "source_object_ids",
        "derived_from_exhibit_ids",
    ):
        _validate_string_list(value.get(field), field)
    _validate_string_list(value.get("rq_ids"), "rq_ids", required=True)
    _validate_snapshot_binding(value.get("captured_against"))


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS exhibit_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS research_exhibits (
    exhibit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    document_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_exhibits_project_idx
    ON research_exhibits(project_id, captured_at, exhibit_id);
CREATE TABLE IF NOT EXISTS research_exhibit_rqs (
    exhibit_id TEXT NOT NULL,
    rq_id TEXT NOT NULL,
    PRIMARY KEY(exhibit_id, rq_id),
    FOREIGN KEY(exhibit_id) REFERENCES research_exhibits(exhibit_id)
);
CREATE INDEX IF NOT EXISTS research_exhibit_rq_idx
    ON research_exhibit_rqs(rq_id, exhibit_id);
"""


class LocalResearchExhibitStore:
    """Small immutable Research Exhibit registry. Reads never create the DB."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _read_schema_version(self, connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute(
                "SELECT schema_version FROM exhibit_store_meta"
            ).fetchone()
        except sqlite3.Error as exc:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-SCHEMA-001",
                "Research Exhibit store schema is missing or incompatible",
            ) from exc
        if row is None or str(row[0]) != EXHIBIT_STORE_SCHEMA_VERSION:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-SCHEMA-001",
                "Research Exhibit store schema version is incompatible",
            )

    def _connect_read(self) -> sqlite3.Connection | None:
        if not self.exists:
            return None
        try:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            self._read_schema_version(connection)
            return connection
        except LocalResearchExhibitStoreError:
            if "connection" in locals():
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.close()
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-DB-001", "Research Exhibit store is unreadable"
            ) from exc

    def _connect_write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA_SQL)
            connection.execute(
                "INSERT OR IGNORE INTO exhibit_store_meta(schema_version) VALUES (?)",
                (EXHIBIT_STORE_SCHEMA_VERSION,),
            )
            self._read_schema_version(connection)
            connection.commit()
            return connection
        except LocalResearchExhibitStoreError:
            if "connection" in locals():
                connection.close()
            raise
        except sqlite3.Error as exc:
            if "connection" in locals():
                connection.close()
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-DB-001", "Research Exhibit store could not be initialized"
            ) from exc

    @staticmethod
    def _decode_document(row: sqlite3.Row) -> Mapping[str, Any]:
        try:
            value = json.loads(str(row["document_json"]))
        except json.JSONDecodeError as exc:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-INTEGRITY-001",
                "stored Research Exhibit document is not valid JSON",
            ) from exc
        validate_exhibit_document(value)
        if (
            str(value["exhibit_id"]) != str(row["exhibit_id"])
            or str(value["project_id"]) != str(row["project_id"])
            or str(value["content_digest"]) != str(row["content_digest"])
            or str(value["provenance"]["captured_at"]) != str(row["captured_at"])
        ):
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-INTEGRITY-001",
                "stored Research Exhibit index metadata does not match immutable content",
            )
        return value

    @staticmethod
    def _decode_metadata(row: sqlite3.Row) -> Mapping[str, Any]:
        try:
            value = json.loads(str(row["metadata_json"]))
        except json.JSONDecodeError as exc:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-INTEGRITY-001",
                "stored Research Exhibit metadata is not valid JSON",
            ) from exc
        _validate_exhibit_metadata(value)
        if (
            str(value["exhibit_id"]) != str(row["exhibit_id"])
            or str(value["project_id"]) != str(row["project_id"])
            or str(value["content_digest"]) != str(row["content_digest"])
            or str(value["captured_at"]) != str(row["captured_at"])
        ):
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-INTEGRITY-001",
                "stored Research Exhibit metadata does not match index columns",
            )
        return value

    def capture(self, value: Mapping[str, Any]) -> None:
        document = deepcopy(dict(value))
        validate_exhibit_document(document)
        metadata = _metadata_from_document(document)
        _validate_exhibit_metadata(metadata)
        serialized = _canonical_json(document)
        metadata_serialized = _canonical_json(metadata)
        connection = self._connect_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM research_exhibits WHERE exhibit_id=?",
                (str(document["exhibit_id"]),),
            ).fetchone()
            if existing is not None:
                raise LocalResearchExhibitStoreError(
                    "EXHIBIT-IMMUTABLE-001",
                    "Research Exhibit ID already exists; overwrite is forbidden",
                )
            connection.execute(
                """
                INSERT INTO research_exhibits(
                    exhibit_id, project_id, captured_at, content_digest,
                    metadata_json, document_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    str(document["exhibit_id"]),
                    str(document["project_id"]),
                    str(document["provenance"]["captured_at"]),
                    str(document["content_digest"]),
                    metadata_serialized,
                    serialized,
                ),
            )
            connection.executemany(
                "INSERT INTO research_exhibit_rqs(exhibit_id, rq_id) VALUES (?,?)",
                [
                    (str(document["exhibit_id"]), str(rq_id))
                    for rq_id in document["rq_ids"]
                ],
            )
            connection.commit()
        except LocalResearchExhibitStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-IMMUTABLE-001", "Research Exhibit identity collision"
            ) from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-DB-001", "Research Exhibit could not be persisted"
            ) from exc
        finally:
            connection.close()

    def load(self, exhibit_id: str) -> Mapping[str, Any] | None:
        connection = self._connect_read()
        if connection is None:
            return None
        try:
            row = connection.execute(
                """
                SELECT exhibit_id, project_id, captured_at, content_digest, document_json
                FROM research_exhibits WHERE exhibit_id=?
                """,
                (str(exhibit_id),),
            ).fetchone()
            return None if row is None else self._decode_document(row)
        except LocalResearchExhibitStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-DB-001", "Research Exhibit could not be read"
            ) from exc
        finally:
            connection.close()

    def list_for_project(
        self,
        project_id: str,
        *,
        rq_id: str | None = None,
        limit: int,
    ) -> tuple[Mapping[str, Any], ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        connection = self._connect_read()
        if connection is None:
            return ()
        try:
            if rq_id is None:
                rows = connection.execute(
                    """
                    SELECT e.exhibit_id, e.project_id, e.captured_at,
                           e.content_digest, e.metadata_json
                    FROM research_exhibits e
                    WHERE e.project_id=?
                    ORDER BY e.captured_at DESC, e.exhibit_id DESC
                    LIMIT ?
                    """,
                    (str(project_id), int(limit)),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT e.exhibit_id, e.project_id, e.captured_at,
                           e.content_digest, e.metadata_json
                    FROM research_exhibits e
                    JOIN research_exhibit_rqs r ON r.exhibit_id=e.exhibit_id
                    WHERE e.project_id=? AND r.rq_id=?
                    ORDER BY e.captured_at DESC, e.exhibit_id DESC
                    LIMIT ?
                    """,
                    (str(project_id), str(rq_id), int(limit)),
                ).fetchall()
            return tuple(self._decode_metadata(row) for row in rows)
        except LocalResearchExhibitStoreError:
            raise
        except sqlite3.Error as exc:
            raise LocalResearchExhibitStoreError(
                "EXHIBIT-STORE-DB-001", "Research Exhibit list could not be read"
            ) from exc
        finally:
            connection.close()
