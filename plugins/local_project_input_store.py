from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Mapping

_SCHEMA_VERSION = 2
_BLOB_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_PAGE_SIZE = 100


class LocalProjectInputStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _encode_cursor(registered_at: str, input_id: str) -> str:
    raw = json.dumps([registered_at, input_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise LocalProjectInputStoreError(
            "APPLICATION-PROJECT-INPUT-CURSOR-001",
            "project input cursor is invalid",
        ) from exc
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise LocalProjectInputStoreError(
            "APPLICATION-PROJECT-INPUT-CURSOR-001",
            "project input cursor is invalid",
        )
    return value[0], value[1]


class LocalProjectInputStore:
    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root / ".research-loom" / "project-inputs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "project-inputs.sqlite3")
        self.db.row_factory = sqlite3.Row
        self._ensure_schema()

    @staticmethod
    def _create_table_sql(table: str = "project_inputs") -> str:
        return f"""
            CREATE TABLE {table}(
                input_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                media_type TEXT NOT NULL,
                byte_length INTEGER NOT NULL,
                content_digest TEXT NOT NULL,
                source_path TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                lineage_ref TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                snapshot_digest TEXT NOT NULL,
                UNIQUE(project_id, role, content_digest, lineage_ref, snapshot_id, snapshot_digest)
            )
        """

    def _has_current_unique_binding(self) -> bool:
        expected = [
            "project_id", "role", "content_digest",
            "lineage_ref", "snapshot_id", "snapshot_digest",
        ]
        for index in self.db.execute("PRAGMA index_list(project_inputs)").fetchall():
            if not bool(index[2]):
                continue
            columns = [
                row[2] for row in self.db.execute(
                    f"PRAGMA index_info({json.dumps(str(index[1]))})"
                ).fetchall()
            ]
            if columns == expected:
                return True
        return False

    def _ensure_page_index(self) -> None:
        self.db.execute(
            """CREATE INDEX IF NOT EXISTS project_inputs_page_idx
               ON project_inputs(project_id, registered_at, input_id)"""
        )

    def _ensure_schema(self) -> None:
        table = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_inputs'"
        ).fetchone()
        if table is None:
            self.db.execute(self._create_table_sql())
            self._ensure_page_index()
            self.db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            self.db.commit()
            return
        if self._has_current_unique_binding():
            self._ensure_page_index()
            if int(self.db.execute("PRAGMA user_version").fetchone()[0]) < _SCHEMA_VERSION:
                self.db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                self.db.commit()
            return
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("ALTER TABLE project_inputs RENAME TO project_inputs_legacy")
            self.db.execute(self._create_table_sql())
            self.db.execute(
                """INSERT INTO project_inputs(
                       input_id,project_id,role,media_type,byte_length,content_digest,
                       source_path,provenance_json,registered_at,lineage_ref,snapshot_id,snapshot_digest
                   )
                   SELECT input_id,project_id,role,media_type,byte_length,content_digest,
                          source_path,provenance_json,registered_at,lineage_ref,snapshot_id,snapshot_digest
                   FROM project_inputs_legacy"""
            )
            self.db.execute("DROP TABLE project_inputs_legacy")
            self._ensure_page_index()
            self.db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            self.db.commit()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def close(self) -> None:
        self.db.close()

    def register(
        self,
        *,
        project_id: str,
        role: str,
        media_type: str,
        content: bytes,
        source_path: str,
        provenance: Mapping[str, Any],
        lineage_ref: str,
        snapshot_id: str,
        snapshot_digest: str,
    ) -> dict[str, Any]:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        identity_seed = (
            f"{project_id}\0{role}\0{digest}\0{lineage_ref}\0{snapshot_id}\0{snapshot_digest}"
        ).encode("utf-8")
        input_id = "PIN-" + hashlib.sha256(identity_seed).hexdigest()[:24]
        registered_at = _now()
        self._store_verified_blob(content, digest)
        binding = (project_id, role, digest, lineage_ref, snapshot_id, snapshot_digest)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                """INSERT OR IGNORE INTO project_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    input_id,
                    project_id,
                    role,
                    media_type,
                    len(content),
                    digest,
                    source_path,
                    json.dumps(
                        dict(provenance),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    registered_at,
                    lineage_ref,
                    snapshot_id,
                    snapshot_digest,
                ),
            )
            row = self.db.execute(
                """SELECT * FROM project_inputs
                   WHERE project_id=? AND role=? AND content_digest=?
                     AND lineage_ref=? AND snapshot_id=? AND snapshot_digest=?""",
                binding,
            ).fetchone()
            if row is None:
                raise sqlite3.IntegrityError("project input registration was not persisted")
            self.db.commit()
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise
        return self._project(row)

    def _blob_path(self, digest: str) -> Path:
        prefix = "sha256:"
        if (
            not digest.startswith(prefix)
            or len(digest) != len(prefix) + 64
            or any(character not in "0123456789abcdef" for character in digest[len(prefix):])
        ):
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "project-input content digest is malformed",
            )
        hex_digest = digest[len(prefix):]
        return self.blobs / hex_digest[:2] / hex_digest

    def _store_verified_blob(self, content: bytes, digest: str) -> None:
        target = self._blob_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self._verify_blob(target, digest, len(content))
            return
        fd, temporary_name = tempfile.mkstemp(prefix="project-input-", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                self._verify_blob(target, digest, len(content))
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _verify_blob(path: Path, expected_digest: str, expected_size: int) -> None:
        try:
            actual_size = path.stat().st_size
        except OSError as exc:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "content-addressed project-input blob could not be inspected",
            ) from exc
        if actual_size != expected_size:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "content-addressed project-input blob failed digest/size verification",
            )
        hasher = hashlib.sha256()
        remaining = expected_size
        try:
            with path.open("rb") as stream:
                while remaining:
                    chunk = stream.read(min(_BLOB_HASH_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise LocalProjectInputStoreError(
                            "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                            "content-addressed project-input blob changed during verification",
                        )
                    hasher.update(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise LocalProjectInputStoreError(
                        "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                        "content-addressed project-input blob changed during verification",
                    )
        except OSError as exc:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "content-addressed project-input blob could not be verified",
            ) from exc
        if "sha256:" + hasher.hexdigest() != expected_digest:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "content-addressed project-input blob failed digest/size verification",
            )

    def get(self, input_id: str, project_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM project_inputs WHERE input_id=? AND project_id=?",
            (input_id, project_id),
        ).fetchone()
        return None if row is None else self._project(row)

    @staticmethod
    def _read_verified_blob(path: Path, expected_digest: str, expected_size: int) -> bytes:
        try:
            if path.stat().st_size != expected_size:
                raise LocalProjectInputStoreError(
                    "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                    "content-addressed project-input blob failed digest/size verification",
                )
            hasher = hashlib.sha256()
            content = bytearray()
            remaining = expected_size
            with path.open("rb") as stream:
                while remaining:
                    chunk = stream.read(min(_BLOB_HASH_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise LocalProjectInputStoreError(
                            "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                            "content-addressed project-input blob changed during retrieval",
                        )
                    content.extend(chunk)
                    hasher.update(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise LocalProjectInputStoreError(
                        "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                        "content-addressed project-input blob changed during retrieval",
                    )
        except OSError as exc:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "content-addressed project-input blob could not be read",
            ) from exc
        if "sha256:" + hasher.hexdigest() != expected_digest:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-INTEGRITY-001",
                "content-addressed project-input blob failed digest/size verification",
            )
        return bytes(content)

    def read_content(self, input_id: str, project_id: str) -> tuple[dict[str, Any], bytes] | None:
        row = self.db.execute(
            "SELECT * FROM project_inputs WHERE input_id=? AND project_id=?",
            (input_id, project_id),
        ).fetchone()
        if row is None:
            return None
        content = self._read_verified_blob(
            self._blob_path(str(row["content_digest"])),
            str(row["content_digest"]),
            int(row["byte_length"]),
        )
        return self._project(row), content

    def list_page(
        self,
        project_id: str,
        *,
        limit: int = _MAX_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > _MAX_PAGE_SIZE:
            raise LocalProjectInputStoreError(
                "APPLICATION-PROJECT-INPUT-PAGE-001",
                f"limit must be between 1 and {_MAX_PAGE_SIZE}",
            )
        params: list[Any] = [project_id]
        where = "project_id=?"
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor:
                raise LocalProjectInputStoreError(
                    "APPLICATION-PROJECT-INPUT-CURSOR-001",
                    "project input cursor is invalid",
                )
            registered_at, input_id = _decode_cursor(cursor)
            where += " AND (registered_at>? OR (registered_at=? AND input_id>?))"
            params.extend([registered_at, registered_at, input_id])
        params.append(limit + 1)
        rows = self.db.execute(
            f"SELECT * FROM project_inputs WHERE {where} "
            "ORDER BY registered_at ASC,input_id ASC LIMIT ?",
            params,
        ).fetchall()
        truncated = len(rows) > limit
        visible = rows[:limit]
        next_cursor = None
        if truncated and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(str(last["registered_at"]), str(last["input_id"]))
        return {
            "items": [self._project(row) for row in visible],
            "truncated": truncated,
            "next_cursor": next_cursor,
            "limit": limit,
        }

    @staticmethod
    def _project(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "input_id": row["input_id"],
            "project_id": row["project_id"],
            "role": row["role"],
            "media_type": row["media_type"],
            "byte_length": row["byte_length"],
            "content_digest": row["content_digest"],
            "source_path": row["source_path"],
            "provenance": json.loads(row["provenance_json"]),
            "registered_at": row["registered_at"],
            "lineage_ref": row["lineage_ref"],
            "snapshot_id": row["snapshot_id"],
            "snapshot_digest": row["snapshot_digest"],
        }
