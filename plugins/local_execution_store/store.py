from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from threading import RLock
from typing import Any, Iterator, Mapping
import uuid

import rfc8785

from core.execution.models import (
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ExecutionIssue,
    ResourcePayload,
    RunLifecycleEvent,
    RunStatus,
)
from core.runtime.transition_models import canonical_digest


_MIGRATION_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_ALLOWED_JOURNAL_MODES = {"DELETE", "WAL"}
_ALLOWED_SYNCHRONOUS = {"FULL", "NORMAL", "EXTRA"}
_ALLOWED_TRANSITIONS = {
    RunStatus.PREPARED: {
        RunStatus.RUNNING,
        RunStatus.ABORTED,
        RunStatus.SUPERSEDED,
    },
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.ABORTED,
        RunStatus.SUPERSEDED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.ABORTED: set(),
    RunStatus.SUPERSEDED: set(),
}
_DOCUMENT_DIGEST_FIELDS = {
    "descriptor": "descriptor_digest",
    "invocation": "invocation_digest",
    "context_pack": "context_pack_digest",
    "handoff": "handoff_digest",
}
_RUN_IMMUTABLE_FIELDS = (
    "run_id",
    "invocation_id",
    "invocation_digest",
    "capability_id",
    "capability_version",
    "descriptor_digest",
    "implementation_id",
    "implementation_version",
    "function_id",
    "execution_mode",
    "context_pack_id",
    "context_pack_digest",
    "project_ref",
    "lineage_ref",
    "snapshot_ref",
    "snapshot_digest",
    "attempt",
    "parent_run_id",
    "prepared_at",
    "provenance",
)


class LocalExecutionStoreError(RuntimeError):
    """Base error for local execution persistence failures."""


class LocalExecutionStoreIntegrityError(LocalExecutionStoreError):
    """Raised when persisted execution bytes or metadata fail verification."""


@dataclass(frozen=True)
class LocalExecutionStoreConfig:
    max_artifact_bytes: int = 64 * 1024 * 1024
    max_run_output_bytes: int = 256 * 1024 * 1024
    max_resource_bytes: int = 256 * 1024 * 1024
    busy_timeout_ms: int = 5_000
    journal_mode: str = "DELETE"
    synchronous: str = "FULL"


@dataclass(frozen=True)
class RegisteredResource:
    reference_id: str
    media_type: str | None
    size: int
    digest: str
    storage_locator: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class StoreIntegrityDiagnostic:
    code: str
    message: str
    run_id: str | None = None
    artifact_id: str | None = None
    reference_id: str | None = None


def _canonical_json(value: Any) -> str:
    return rfc8785.dumps(value).decode("utf-8")


def _payload_sha256(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(dict(value))).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _failure_json(issue: ExecutionIssue | None) -> str | None:
    if issue is None:
        return None
    return _canonical_json(asdict(issue))


class LocalExecutionStore:
    """Production local ExecutionTraceStore + ArtifactStore + ResourceProvider.

    The SQLite database is non-authoritative execution history. Artifact and
    registered input bytes live in an immutable content-addressed filesystem
    rooted beside that database. No Research State transition is performed
    here.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        config: LocalExecutionStoreConfig | None = None,
        allowed_import_roots: tuple[str | Path, ...] = (),
    ) -> None:
        self.root = Path(root)
        self.config = config or LocalExecutionStoreConfig()
        if self.config.max_artifact_bytes <= 0:
            raise ValueError("max_artifact_bytes must be positive")
        if self.config.max_run_output_bytes <= 0:
            raise ValueError("max_run_output_bytes must be positive")
        if self.config.max_resource_bytes <= 0:
            raise ValueError("max_resource_bytes must be positive")
        if self.config.busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        journal_mode = self.config.journal_mode.upper()
        synchronous = self.config.synchronous.upper()
        if journal_mode not in _ALLOWED_JOURNAL_MODES:
            raise ValueError(f"unsupported journal_mode {journal_mode!r}")
        if synchronous not in _ALLOWED_SYNCHRONOUS:
            raise ValueError(f"unsupported synchronous setting {synchronous!r}")

        self.root.mkdir(parents=True, exist_ok=True)
        self.blob_root = self.root / "blobs" / "sha256"
        self.staging_root = self.root / "staging"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "execution.db"
        self._allowed_import_roots = tuple(
            Path(item).resolve(strict=True)
            for item in allowed_import_roots
        )
        self._lock = RLock()
        try:
            self._connection = sqlite3.connect(
                str(self.database),
                isolation_level=None,
                timeout=max(self.config.busy_timeout_ms / 1000.0, 0.001),
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                f"PRAGMA busy_timeout = {int(self.config.busy_timeout_ms)}"
            )
            actual_journal = str(
                self._connection.execute(
                    f"PRAGMA journal_mode = {journal_mode}"
                ).fetchone()[0]
            ).upper()
            self._connection.execute(
                f"PRAGMA synchronous = {synchronous}"
            )
            if actual_journal != journal_mode:
                raise LocalExecutionStoreError(
                    "SQLite refused requested journal_mode "
                    f"{journal_mode!r}; got {actual_journal!r}"
                )
            if int(
                self._connection.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0]
            ) != 1:
                raise LocalExecutionStoreError(
                    "SQLite foreign_keys pragma is not enabled"
                )
            self._migrate()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "LocalExecutionStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            return int(row["version"]) if row is not None else 0

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                self._connection.execute("COMMIT")
            except Exception:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def _migrate(self) -> None:
        migration_dir = Path(__file__).with_name("migrations")
        migrations: list[tuple[int, str, str]] = []
        for path in sorted(migration_dir.glob("*.sql")):
            match = _MIGRATION_RE.match(path.name)
            if match is None:
                raise LocalExecutionStoreError(
                    f"invalid execution-store migration name {path.name!r}"
                )
            migrations.append(
                (
                    int(match.group("version")),
                    path.stem,
                    path.read_text(encoding="utf-8"),
                )
            )
        versions = [item[0] for item in migrations]
        if versions != list(range(1, len(versions) + 1)):
            raise LocalExecutionStoreError(
                "execution-store migrations must be contiguous from 0001"
            )
        latest = versions[-1] if versions else 0

        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations(
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                applied = {
                    int(row["version"]): str(row["name"])
                    for row in self._connection.execute(
                        "SELECT version, name FROM schema_migrations ORDER BY version"
                    )
                }
                if applied and max(applied) > latest:
                    raise LocalExecutionStoreError(
                        f"execution-store schema version {max(applied)} is newer "
                        f"than supported version {latest}"
                    )
                if sorted(applied) != versions[: len(applied)]:
                    raise LocalExecutionStoreError(
                        "applied execution-store migration history is not a "
                        "contiguous known prefix"
                    )
                for version, name, _sql in migrations:
                    if version in applied and applied[version] != name:
                        raise LocalExecutionStoreError(
                            f"migration {version:04d} name mismatch"
                        )
                for version, name, sql in migrations:
                    if version in applied:
                        continue
                    for statement in (
                        part.strip() for part in sql.split(";") if part.strip()
                    ):
                        self._connection.execute(statement)
                    self._connection.execute(
                        "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                        (version, name),
                    )
                self._connection.execute("COMMIT")
            except Exception:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    # ---- ExecutionTraceStore -------------------------------------------------

    def create_run(self, run: CapabilityRunRecord) -> None:
        values = self._encode_run(run)
        try:
            with self._write_transaction():
                self._connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, invocation_id, invocation_digest,
                        capability_id, capability_version, descriptor_digest,
                        implementation_id, implementation_version, function_id,
                        execution_mode, context_pack_id, context_pack_digest,
                        project_ref, lineage_ref, snapshot_ref, snapshot_digest,
                        attempt, parent_run_id, status, prepared_at, started_at,
                        completed_at, handoff_ref, handoff_digest, failure_json,
                        provenance_json
                    ) VALUES (
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                    """,
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Run ID is single-use: {run.run_id}") from exc

    def load_run(self, run_id: str) -> CapabilityRunRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._decode_run(row) if row is not None else None

    def append_run_event(self, event: RunLifecycleEvent) -> None:
        with self._write_transaction():
            row = self._connection.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown Run {event.run_id}")
            count = int(
                self._connection.execute(
                    "SELECT COUNT(*) AS n FROM run_events WHERE run_id = ?",
                    (event.run_id,),
                ).fetchone()["n"]
            )
            if (
                count != 0
                or event.sequence != 1
                or event.from_status is not None
                or event.to_status is not RunStatus.PREPARED
                or str(row["status"]) != RunStatus.PREPARED.value
            ):
                raise ValueError(
                    "initial lifecycle event must be sequence 1, "
                    "None -> PREPARED, and append-only"
                )
            self._insert_event(event)

    def transition_run(
        self,
        expected_status: RunStatus,
        updated_run: CapabilityRunRecord,
        event: RunLifecycleEvent,
    ) -> bool:
        if updated_run.status not in _ALLOWED_TRANSITIONS[expected_status]:
            raise ValueError(
                f"illegal Run lifecycle transition "
                f"{expected_status.value} -> {updated_run.status.value}"
            )
        if (
            event.run_id != updated_run.run_id
            or event.from_status is not expected_status
            or event.to_status is not updated_run.status
        ):
            raise ValueError("Run lifecycle event does not match projection update")

        with self._write_transaction():
            current = self._connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (updated_run.run_id,),
            ).fetchone()
            if (
                current is None
                or str(current["status"]) != expected_status.value
            ):
                return False
            persisted = self._decode_run(current)
            for name in _RUN_IMMUTABLE_FIELDS:
                if getattr(persisted, name) != getattr(updated_run, name):
                    raise LocalExecutionStoreIntegrityError(
                        f"immutable Run field {name} cannot change on transition"
                    )
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS sequence
                FROM run_events WHERE run_id = ?
                """,
                (updated_run.run_id,),
            ).fetchone()
            expected_sequence = int(row["sequence"]) + 1
            if event.sequence != expected_sequence:
                raise ValueError(
                    "lifecycle sequence must be contiguous and never reused"
                )
            update = self._connection.execute(
                """
                UPDATE runs SET
                    status=?, started_at=?, completed_at=?, handoff_ref=?,
                    handoff_digest=?, failure_json=?
                WHERE run_id=? AND status=?
                """,
                (
                    updated_run.status.value,
                    updated_run.started_at,
                    updated_run.completed_at,
                    updated_run.handoff_ref,
                    updated_run.handoff_digest,
                    _failure_json(updated_run.failure),
                    updated_run.run_id,
                    expected_status.value,
                ),
            )
            if update.rowcount != 1:
                return False
            self._insert_event(event)
            return True

    def events_for(self, run_id: str) -> tuple[RunLifecycleEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? ORDER BY sequence
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            RunLifecycleEvent(
                str(row["run_id"]),
                int(row["sequence"]),
                RunStatus(str(row["from_status"]))
                if row["from_status"] is not None
                else None,
                RunStatus(str(row["to_status"])),
                str(row["occurred_at"]),
                str(row["reason"]),
            )
            for row in rows
        )

    def store_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        self._store_document(
            "descriptor",
            str(descriptor["descriptor_digest"]),
            descriptor,
            run_id=None,
        )

    def store_invocation(self, invocation: Mapping[str, Any]) -> None:
        self._store_document(
            "invocation",
            str(invocation["invocation_id"]),
            invocation,
            run_id=str(invocation.get("run_id") or "") or None,
        )

    def store_context_pack(self, context_pack: Mapping[str, Any]) -> None:
        self._store_document(
            "context_pack",
            str(context_pack["context_pack_id"]),
            context_pack,
            run_id=None,
        )

    def store_handoff(self, handoff: Mapping[str, Any]) -> None:
        full_hash = _payload_sha256(handoff)
        identity = str(handoff.get("handoff_id") or f"raw:{full_hash}")
        self._store_document(
            "handoff",
            identity,
            handoff,
            run_id=str(handoff.get("run_id") or "") or None,
        )

    def store_result_extension(
        self,
        run_id: str,
        extension: Mapping[str, Any],
    ) -> str:
        identity = str(
            extension.get("extension_digest")
            or canonical_digest(extension)
        )
        self._store_document(
            "extension",
            identity,
            extension,
            run_id=run_id,
        )
        return identity

    def register_output_artifact(
        self,
        artifact: ExecutionArtifactMetadata,
    ) -> None:
        payload = (
            artifact.artifact_id,
            artifact.run_id,
            artifact.role,
            artifact.media_type,
            artifact.size,
            artifact.digest,
            artifact.storage_locator,
            artifact.execution_mode,
            _canonical_json(dict(artifact.provenance)),
        )
        with self._write_transaction():
            prior = self._connection.execute(
                """
                SELECT artifact_id, run_id, role, media_type, size, digest,
                       storage_locator, execution_mode, provenance_json
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact.artifact_id,),
            ).fetchone()
            if prior is not None:
                prior_tuple = tuple(prior[key] for key in prior.keys())
                if prior_tuple != payload:
                    raise ValueError("immutable artifact identity collision")
                return
            self._connection.execute(
                """
                INSERT INTO execution_artifacts(
                    artifact_id, run_id, role, media_type, size, digest,
                    storage_locator, execution_mode, provenance_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )

    def load_invocation(
        self,
        invocation_id: str,
    ) -> Mapping[str, Any] | None:
        return self._load_document("invocation", invocation_id)

    def load_context_pack(
        self,
        context_pack_id: str,
    ) -> Mapping[str, Any] | None:
        return self._load_document("context_pack", context_pack_id)

    def load_descriptor(
        self,
        descriptor_digest: str,
    ) -> Mapping[str, Any] | None:
        return self._load_document("descriptor", descriptor_digest)

    def store_diagnostic(
        self,
        run_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        with self._write_transaction():
            exists = self._connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if exists is None:
                raise ValueError(f"unknown Run {run_id}")
            self._connection.execute(
                """
                INSERT INTO diagnostics(run_id, kind, payload_json)
                VALUES (?, ?, ?)
                """,
                (run_id, str(kind), _canonical_json(dict(payload))),
            )

    # ---- ArtifactStore -------------------------------------------------------

    def put_bytes(
        self,
        run: CapabilityRunRecord,
        *,
        role: str,
        media_type: str,
        content: bytes,
        artifact_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        parent_artifact_refs: tuple[str, ...] = (),
    ) -> ExecutionArtifactMetadata:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        if len(content) > self.config.max_artifact_bytes:
            raise LocalExecutionStoreError(
                "artifact exceeds configured max_artifact_bytes"
            )
        persisted = self.load_run(run.run_id)
        if persisted is None:
            raise LocalExecutionStoreError(
                "artifact Run must already exist in the execution trace"
            )
        if (
            persisted.execution_mode != run.execution_mode
            or persisted.capability_id != run.capability_id
        ):
            raise LocalExecutionStoreIntegrityError(
                "artifact Run binding does not match persisted Run"
            )
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(SUM(size), 0) AS total
                FROM execution_artifacts WHERE run_id = ?
                """,
                (run.run_id,),
            ).fetchone()
            current_total = int(row["total"])
        if current_total + len(content) > self.config.max_run_output_bytes:
            raise LocalExecutionStoreError(
                "Run output exceeds configured max_run_output_bytes"
            )

        digest, locator = self._store_blob(content, scheme="artifact")
        trusted_provenance = dict(provenance or {})
        trusted_provenance.update(
            {
                "source_run_id": run.run_id,
                "execution_mode": run.execution_mode,
                "stored_by": "plugins.local_execution_store",
                "stored_at": _now(),
                "parent_artifact_refs": list(parent_artifact_refs),
            }
        )
        metadata = ExecutionArtifactMetadata(
            artifact_id
            or f"ART-{uuid.uuid4().hex}",
            run.run_id,
            str(role),
            str(media_type),
            len(content),
            digest,
            locator,
            run.execution_mode,
            trusted_provenance,
        )
        self.register_output_artifact(metadata)
        return metadata

    def import_output_file(
        self,
        run: CapabilityRunRecord,
        source_path: str | Path,
        *,
        role: str,
        media_type: str,
        artifact_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        parent_artifact_refs: tuple[str, ...] = (),
    ) -> ExecutionArtifactMetadata:
        content = self._read_controlled_file(
            source_path,
            max_bytes=self.config.max_artifact_bytes,
        )
        return self.put_bytes(
            run,
            role=role,
            media_type=media_type,
            content=content,
            artifact_id=artifact_id,
            provenance=provenance,
            parent_artifact_refs=parent_artifact_refs,
        )

    def load_artifact(self, artifact_id: str) -> ResourcePayload:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_id, media_type, size, digest, storage_locator
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        content = self._load_verified_blob(
            str(row["storage_locator"]),
            str(row["digest"]),
            int(row["size"]),
        )
        return ResourcePayload(
            str(row["artifact_id"]),
            content,
            str(row["digest"]),
            str(row["media_type"]),
        )

    def artifacts_for(
        self,
        run_id: str,
    ) -> tuple[ExecutionArtifactMetadata, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT artifact_id, run_id, role, media_type, size, digest,
                       storage_locator, execution_mode, provenance_json
                FROM execution_artifacts
                WHERE run_id = ?
                ORDER BY artifact_id
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            ExecutionArtifactMetadata(
                str(row["artifact_id"]),
                str(row["run_id"]),
                str(row["role"]),
                str(row["media_type"]),
                int(row["size"]),
                str(row["digest"]),
                str(row["storage_locator"]),
                str(row["execution_mode"]),
                json.loads(str(row["provenance_json"])),
            )
            for row in rows
        )

    # ---- ResourceProvider ----------------------------------------------------

    def register_input_bytes(
        self,
        reference_id: str,
        content: bytes,
        *,
        media_type: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> RegisteredResource:
        if not isinstance(content, bytes):
            raise TypeError("resource content must be bytes")
        if len(content) > self.config.max_resource_bytes:
            raise LocalExecutionStoreError(
                "resource exceeds configured max_resource_bytes"
            )
        digest, locator = self._store_blob(content, scheme="resource")
        trusted_provenance = dict(provenance or {})
        trusted_provenance.update(
            {
                "registered_by": "plugins.local_execution_store",
                "registered_at": _now(),
            }
        )
        record = RegisteredResource(
            str(reference_id),
            str(media_type) if media_type is not None else None,
            len(content),
            digest,
            locator,
            trusted_provenance,
        )
        payload = (
            record.reference_id,
            record.media_type,
            record.size,
            record.digest,
            record.storage_locator,
            _canonical_json(dict(record.provenance)),
        )
        with self._write_transaction():
            prior = self._connection.execute(
                """
                SELECT reference_id, media_type, size, digest, storage_locator,
                       provenance_json
                FROM input_resources WHERE reference_id = ?
                """,
                (record.reference_id,),
            ).fetchone()
            if prior is not None:
                prior_tuple = tuple(prior[key] for key in prior.keys())
                if prior_tuple != payload:
                    raise ValueError("immutable resource identity collision")
                return record
            self._connection.execute(
                """
                INSERT INTO input_resources(
                    reference_id, media_type, size, digest, storage_locator,
                    provenance_json
                ) VALUES (?,?,?,?,?,?)
                """,
                payload,
            )
        return record

    def register_input_file(
        self,
        reference_id: str,
        source_path: str | Path,
        *,
        media_type: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> RegisteredResource:
        content = self._read_controlled_file(
            source_path,
            max_bytes=self.config.max_resource_bytes,
        )
        return self.register_input_bytes(
            reference_id,
            content,
            media_type=media_type,
            provenance=provenance,
        )

    def load(self, resource: Mapping[str, Any]) -> ResourcePayload:
        reference_id = str(resource["reference_id"])
        with self._lock:
            row = self._connection.execute(
                """
                SELECT reference_id, media_type, size, digest, storage_locator
                FROM input_resources WHERE reference_id = ?
                """,
                (reference_id,),
            ).fetchone()
        if row is None:
            raise KeyError(reference_id)
        locator = resource.get("locator")
        if locator is not None and str(locator) != str(row["storage_locator"]):
            raise LocalExecutionStoreIntegrityError(
                "Context Pack resource locator does not match registered locator"
            )
        expected_digest = resource.get("digest")
        if (
            expected_digest is not None
            and str(expected_digest) != str(row["digest"])
        ):
            raise LocalExecutionStoreIntegrityError(
                "Context Pack resource digest does not match registered digest"
            )
        content = self._load_verified_blob(
            str(row["storage_locator"]),
            str(row["digest"]),
            int(row["size"]),
        )
        return ResourcePayload(
            reference_id,
            content,
            str(row["digest"]),
            str(row["media_type"]) if row["media_type"] is not None else None,
        )

    # ---- Diagnostics ---------------------------------------------------------

    def diagnose_integrity(
        self,
        run_id: str | None = None,
    ) -> tuple[StoreIntegrityDiagnostic, ...]:
        diagnostics: list[StoreIntegrityDiagnostic] = []
        with self._lock:
            if run_id is not None:
                exists = self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if exists is None:
                    return (
                        StoreIntegrityDiagnostic(
                            "MISSING_RUN",
                            f"Run {run_id} is missing",
                            run_id=run_id,
                        ),
                    )
            run_rows = self._connection.execute(
                "SELECT * FROM runs"
                + (" WHERE run_id = ?" if run_id is not None else ""),
                (run_id,) if run_id is not None else (),
            ).fetchall()
            if run_id is None:
                document_rows = self._connection.execute(
                    "SELECT * FROM execution_documents"
                ).fetchall()
                diagnostic_rows = self._connection.execute(
                    "SELECT run_id FROM diagnostics"
                ).fetchall()
            else:
                run_row = run_rows[0]
                clauses = ["run_id = ?"]
                args: list[Any] = [run_id]
                for doc_type, identity in (
                    ("descriptor", str(run_row["descriptor_digest"])),
                    ("invocation", str(run_row["invocation_id"])),
                    ("context_pack", str(run_row["context_pack_id"])),
                ):
                    clauses.append("(document_type = ? AND identity = ?)")
                    args.extend((doc_type, identity))
                if run_row["handoff_ref"] is not None:
                    clauses.append("(document_type = ? AND identity = ?)")
                    args.extend(("handoff", str(run_row["handoff_ref"])))
                document_rows = self._connection.execute(
                    "SELECT * FROM execution_documents WHERE "
                    + " OR ".join(clauses),
                    tuple(args),
                ).fetchall()
                diagnostic_rows = self._connection.execute(
                    "SELECT run_id FROM diagnostics WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
            artifact_rows = self._connection.execute(
                "SELECT * FROM execution_artifacts"
                + (" WHERE run_id = ?" if run_id is not None else ""),
                (run_id,) if run_id is not None else (),
            ).fetchall()

        docs = {
            (str(row["document_type"]), str(row["identity"])): row
            for row in document_rows
        }
        for row in document_rows:
            document_run_id = str(row["run_id"]) if row["run_id"] else None
            if document_run_id is not None:
                with self._lock:
                    run_exists = self._connection.execute(
                        "SELECT 1 FROM runs WHERE run_id = ?",
                        (document_run_id,),
                    ).fetchone()
                if run_exists is None:
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "DANGLING_DOCUMENT_RUN_REF",
                            "execution document references a missing Run",
                            run_id=document_run_id,
                        )
                    )
            try:
                payload = json.loads(str(row["payload_json"]))
                if _payload_sha256(payload) != str(row["payload_sha256"]):
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "DOCUMENT_PAYLOAD_DIGEST_MISMATCH",
                            "immutable execution document payload hash mismatch",
                            run_id=document_run_id,
                        )
                    )
            except (TypeError, ValueError, json.JSONDecodeError):
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "DOCUMENT_INVALID_JSON",
                        "immutable execution document is not valid canonical JSON",
                        run_id=document_run_id,
                    )
                )

        for row in diagnostic_rows:
            diagnostic_run_id = str(row["run_id"])
            with self._lock:
                run_exists = self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (diagnostic_run_id,),
                ).fetchone()
            if run_exists is None:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "DANGLING_DIAGNOSTIC_RUN_REF",
                        "diagnostic record references a missing Run",
                        run_id=diagnostic_run_id,
                    )
                )

        for run_row in run_rows:
            rid = str(run_row["run_id"])
            required = (
                ("descriptor", str(run_row["descriptor_digest"])),
                ("invocation", str(run_row["invocation_id"])),
                ("context_pack", str(run_row["context_pack_id"])),
            )
            for doc_type, identity in required:
                if (doc_type, identity) not in docs:
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            f"MISSING_{doc_type.upper()}",
                            f"Run references missing {doc_type} {identity}",
                            run_id=rid,
                        )
                    )
            if run_row["handoff_ref"] is not None and (
                "handoff",
                str(run_row["handoff_ref"]),
            ) not in docs:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "MISSING_HANDOFF",
                        "Run projection references a missing Handoff",
                        run_id=rid,
                    )
                )

            events = self.events_for(rid)
            if not events:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "INVALID_LIFECYCLE_SEQUENCE",
                        "Run has no lifecycle events",
                        run_id=rid,
                    )
                )
                continue
            prior: RunStatus | None = None
            for index, event in enumerate(events, start=1):
                if event.sequence != index:
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "INVALID_LIFECYCLE_SEQUENCE",
                            "Run lifecycle sequence is not contiguous",
                            run_id=rid,
                        )
                    )
                    break
                if index == 1:
                    if (
                        event.from_status is not None
                        or event.to_status is not RunStatus.PREPARED
                    ):
                        diagnostics.append(
                            StoreIntegrityDiagnostic(
                                "ILLEGAL_LIFECYCLE_TRANSITION",
                                "first lifecycle event must be None -> PREPARED",
                                run_id=rid,
                            )
                        )
                    prior = event.to_status
                    continue
                if (
                    event.from_status is not prior
                    or event.to_status not in _ALLOWED_TRANSITIONS[prior]
                ):
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "ILLEGAL_LIFECYCLE_TRANSITION",
                            "lifecycle event does not follow canonical transition graph",
                            run_id=rid,
                        )
                    )
                    break
                prior = event.to_status
            if prior is not None and prior.value != str(run_row["status"]):
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "RUN_EVENT_PROJECTION_MISMATCH",
                        "current Run status disagrees with append-only lifecycle history",
                        run_id=rid,
                    )
                )

        for row in artifact_rows:
            aid = str(row["artifact_id"])
            rid = str(row["run_id"])
            with self._lock:
                run_exists = self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (rid,),
                ).fetchone()
            if run_exists is None:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "DANGLING_ARTIFACT_RUN_REF",
                        "artifact metadata references a missing Run",
                        run_id=rid,
                        artifact_id=aid,
                    )
                )
            try:
                self._load_verified_blob(
                    str(row["storage_locator"]),
                    str(row["digest"]),
                    int(row["size"]),
                )
            except FileNotFoundError:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "ARTIFACT_BLOB_MISSING",
                        "artifact metadata has no backing blob",
                        run_id=rid,
                        artifact_id=aid,
                    )
                )
            except LocalExecutionStoreIntegrityError:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "ARTIFACT_BLOB_DIGEST_MISMATCH",
                        "artifact blob digest/size does not match metadata",
                        run_id=rid,
                        artifact_id=aid,
                    )
                )
        return tuple(diagnostics)

    def describe_run(self, run_id: str) -> Mapping[str, Any]:
        run = self.load_run(run_id)
        if run is None:
            raise KeyError(run_id)
        events = self.events_for(run_id)
        return {
            "run": run,
            "last_event": events[-1] if events else None,
            "status": run.status.value,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }

    def cleanup_staging(self) -> int:
        removed = 0
        for path in self.staging_root.iterdir():
            if not path.is_file() or path.is_symlink():
                continue
            path.unlink()
            removed += 1
        return removed

    # ---- internals -----------------------------------------------------------

    def _encode_run(self, run: CapabilityRunRecord) -> tuple[Any, ...]:
        return (
            run.run_id,
            run.invocation_id,
            run.invocation_digest,
            run.capability_id,
            run.capability_version,
            run.descriptor_digest,
            run.implementation_id,
            run.implementation_version,
            run.function_id,
            run.execution_mode,
            run.context_pack_id,
            run.context_pack_digest,
            run.project_ref,
            run.lineage_ref,
            run.snapshot_ref,
            run.snapshot_digest,
            run.attempt,
            run.parent_run_id,
            run.status.value,
            run.prepared_at,
            run.started_at,
            run.completed_at,
            run.handoff_ref,
            run.handoff_digest,
            _failure_json(run.failure),
            _canonical_json(dict(run.provenance)),
        )

    @staticmethod
    def _decode_run(row: sqlite3.Row) -> CapabilityRunRecord:
        failure = None
        if row["failure_json"] is not None:
            data = json.loads(str(row["failure_json"]))
            failure = ExecutionIssue(
                str(data["code"]),
                str(data["message"]),
                bool(data.get("retryable", False)),
            )
        return CapabilityRunRecord(
            str(row["run_id"]),
            str(row["invocation_id"]),
            str(row["invocation_digest"]),
            str(row["capability_id"]),
            str(row["capability_version"]),
            str(row["descriptor_digest"]),
            str(row["implementation_id"]),
            str(row["implementation_version"]),
            str(row["function_id"]),
            str(row["execution_mode"]),
            str(row["context_pack_id"]),
            str(row["context_pack_digest"]),
            str(row["project_ref"]),
            str(row["lineage_ref"]),
            str(row["snapshot_ref"]),
            str(row["snapshot_digest"]),
            int(row["attempt"]),
            str(row["parent_run_id"]) if row["parent_run_id"] is not None else None,
            RunStatus(str(row["status"])),
            str(row["prepared_at"]),
            str(row["started_at"]) if row["started_at"] is not None else None,
            str(row["completed_at"]) if row["completed_at"] is not None else None,
            str(row["handoff_ref"]) if row["handoff_ref"] is not None else None,
            str(row["handoff_digest"]) if row["handoff_digest"] is not None else None,
            failure,
            json.loads(str(row["provenance_json"])),
        )

    def _insert_event(self, event: RunLifecycleEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO run_events(
                run_id, sequence, from_status, to_status, occurred_at, reason
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.sequence,
                event.from_status.value if event.from_status is not None else None,
                event.to_status.value,
                event.occurred_at,
                event.reason,
            ),
        )

    def _store_document(
        self,
        document_type: str,
        identity: str,
        document: Mapping[str, Any],
        *,
        run_id: str | None,
    ) -> None:
        frozen = dict(document)
        payload_json = _canonical_json(frozen)
        payload_hash = _payload_sha256(frozen)
        with self._write_transaction():
            prior = self._connection.execute(
                """
                SELECT payload_sha256, payload_json
                FROM execution_documents
                WHERE document_type = ? AND identity = ?
                """,
                (document_type, identity),
            ).fetchone()
            if prior is not None:
                if (
                    str(prior["payload_sha256"]) != payload_hash
                    or str(prior["payload_json"]) != payload_json
                ):
                    raise ValueError(
                        f"immutable execution identity collision: "
                        f"{document_type}:{identity}"
                    )
                return
            self._connection.execute(
                """
                INSERT INTO execution_documents(
                    document_type, identity, payload_sha256, payload_json, run_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    document_type,
                    identity,
                    payload_hash,
                    payload_json,
                    run_id,
                ),
            )

    def _load_document(
        self,
        document_type: str,
        identity: str,
    ) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_sha256, payload_json
                FROM execution_documents
                WHERE document_type = ? AND identity = ?
                """,
                (document_type, identity),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as exc:
            raise LocalExecutionStoreIntegrityError(
                "stored execution document is invalid JSON"
            ) from exc
        if _payload_sha256(payload) != str(row["payload_sha256"]):
            raise LocalExecutionStoreIntegrityError(
                "stored execution document payload digest mismatch"
            )
        digest_field = _DOCUMENT_DIGEST_FIELDS.get(document_type)
        if digest_field is not None:
            declared = payload.get(digest_field)
            if declared is None:
                raise LocalExecutionStoreIntegrityError(
                    f"stored {document_type} is missing {digest_field}"
                )
            body = dict(payload)
            body.pop(digest_field, None)
            calculated = canonical_digest(body)
            if str(declared) != calculated:
                raise LocalExecutionStoreIntegrityError(
                    f"stored {document_type} declared digest mismatch"
                )
            if (
                document_type == "descriptor"
                and str(declared) != identity
            ):
                raise LocalExecutionStoreIntegrityError(
                    "stored descriptor identity disagrees with descriptor digest"
                )
        return payload

    def _store_blob(
        self,
        content: bytes,
        *,
        scheme: str,
    ) -> tuple[str, str]:
        digest_hex = hashlib.sha256(content).hexdigest()
        digest = f"sha256:{digest_hex}"
        target_dir = self.blob_root / digest_hex[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / digest_hex
        fd, temporary_name = tempfile.mkstemp(
            prefix="blob-",
            dir=self.staging_root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                self._verify_blob_path(target, digest, len(content))
            else:
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    self._verify_blob_path(target, digest, len(content))
                self._fsync_directory(target_dir)
            return digest, f"{scheme}://sha256/{digest_hex}"
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _load_verified_blob(
        self,
        locator: str,
        expected_digest: str,
        expected_size: int,
    ) -> bytes:
        target = self._locator_path(locator, expected_digest)
        if not target.exists():
            raise FileNotFoundError(target)
        self._verify_blob_path(target, expected_digest, expected_size)
        return target.read_bytes()

    def _verify_blob_path(
        self,
        path: Path,
        expected_digest: str,
        expected_size: int,
    ) -> None:
        data = path.read_bytes()
        actual_digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual_digest != expected_digest or len(data) != expected_size:
            raise LocalExecutionStoreIntegrityError(
                "content-addressed blob failed digest/size verification"
            )

    def _locator_path(self, locator: str, expected_digest: str) -> Path:
        if not (
            locator.startswith("artifact://sha256/")
            or locator.startswith("resource://sha256/")
        ):
            raise LocalExecutionStoreIntegrityError(
                "unsupported or non-local storage locator"
            )
        digest_hex = locator.rsplit("/", 1)[-1]
        if expected_digest != f"sha256:{digest_hex}":
            raise LocalExecutionStoreIntegrityError(
                "storage locator digest disagrees with metadata"
            )
        if (
            len(digest_hex) != 64
            or any(ch not in "0123456789abcdef" for ch in digest_hex)
        ):
            raise LocalExecutionStoreIntegrityError(
                "invalid content-addressed storage locator"
            )
        return self.blob_root / digest_hex[:2] / digest_hex

    def _read_controlled_file(
        self,
        source_path: str | Path,
        *,
        max_bytes: int,
    ) -> bytes:
        if not self._allowed_import_roots:
            raise PermissionError(
                "file import is disabled until allowed_import_roots is configured"
            )
        raw = Path(source_path)
        if ".." in raw.parts:
            raise PermissionError("path traversal is not allowed for file intake")
        try:
            info = raw.lstat()
        except FileNotFoundError:
            raise
        if raw.is_symlink():
            raise PermissionError("symlink intake is forbidden")
        if not stat.S_ISREG(info.st_mode):
            raise PermissionError("only regular files may be imported")
        resolved = raw.resolve(strict=True)
        if not any(
            resolved == root or resolved.is_relative_to(root)
            for root in self._allowed_import_roots
        ):
            raise PermissionError(
                "file is outside configured artifact/resource intake roots"
            )
        if info.st_size > max_bytes:
            raise LocalExecutionStoreError(
                "file exceeds configured intake size limit"
            )
        with resolved.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise LocalExecutionStoreError(
                "file exceeded configured intake size limit while reading"
            )
        return data

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
