from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from core.execution.models import (
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ExecutionIssue,
    RunLifecycleEvent,
    RunStatus,
)
from core.runtime.transition_models import canonical_digest
from plugins._infra.sqlite import (
    ALLOWED_JOURNAL_MODES,
    ALLOWED_SYNCHRONOUS,
    apply_pragmas,
    foreign_keys_enabled,
)

from .store_files import StoreFileMixin
from .store_integrity import StoreIntegrityMixin
from .store_model import (
    _ALLOWED_TRANSITIONS,
    _DOCUMENT_DIGEST_FIELDS,
    _MIGRATION_RE,
    _RUN_IMMUTABLE_FIELDS,
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
    _canonical_json,
    _failure_json,
    _payload_sha256,
)
from .store_resources import StoreResourceMixin


class LocalExecutionStore(StoreResourceMixin, StoreIntegrityMixin, StoreFileMixin):
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
        if journal_mode not in ALLOWED_JOURNAL_MODES:
            raise ValueError(f"unsupported journal_mode {journal_mode!r}")
        if synchronous not in ALLOWED_SYNCHRONOUS:
            raise ValueError(f"unsupported synchronous setting {synchronous!r}")

        self.root.mkdir(parents=True, exist_ok=True)
        self.blob_root = self.root / "blobs" / "sha256"
        self.staging_root = self.root / "staging"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "execution.db"
        self._allowed_import_roots = tuple(
            Path(item).resolve(strict=True) for item in allowed_import_roots
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
            actual_journal = apply_pragmas(
                self._connection,
                foreign_keys=True,
                busy_timeout_ms=self.config.busy_timeout_ms,
                journal_mode=journal_mode,
                synchronous=synchronous,
            )
            if actual_journal != journal_mode:
                raise LocalExecutionStoreError(
                    "SQLite refused requested journal_mode "
                    f"{journal_mode!r}; got {actual_journal!r}"
                )
            if not foreign_keys_enabled(self._connection):
                raise LocalExecutionStoreError("SQLite foreign_keys pragma is not enabled")
            self._migrate()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> LocalExecutionStore:
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
                        "applied execution-store migration history is not a contiguous known prefix"
                    )
                for version, name, _sql in migrations:
                    if version in applied and applied[version] != name:
                        raise LocalExecutionStoreError(f"migration {version:04d} name mismatch")
                for version, name, sql in migrations:
                    if version in applied:
                        continue
                    for statement in (part.strip() for part in sql.split(";") if part.strip()):
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
                    "initial lifecycle event must be sequence 1, None -> PREPARED, and append-only"
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
            if current is None or str(current["status"]) != expected_status.value:
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
                raise ValueError("lifecycle sequence must be contiguous and never reused")
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
                RunStatus(str(row["from_status"])) if row["from_status"] is not None else None,
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
        identity = str(extension.get("extension_digest") or canonical_digest(extension))
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
        with self._write_transaction():
            self._register_output_artifact_in_transaction(artifact)

    def _register_output_artifact_in_transaction(
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
                        f"immutable execution identity collision: {document_type}:{identity}"
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
            if document_type == "descriptor" and str(declared) != identity:
                raise LocalExecutionStoreIntegrityError(
                    "stored descriptor identity disagrees with descriptor digest"
                )
        return payload
