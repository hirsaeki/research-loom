from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator

from .diagnosed_artifact_read import DiagnosedArtifactReadMixin
from .retention import LocalExecutionStore as _RetentionLocalExecutionStore
from .store import (
    _MIGRATION_RE,
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
)


class ReadOnlyLocalExecutionStore(
    DiagnosedArtifactReadMixin,
    _RetentionLocalExecutionStore,
):
    """Existing execution/material root opened strictly for verified reads."""

    def __init__(
        self,
        root: str | Path,
        *,
        config: LocalExecutionStoreConfig | None = None,
    ) -> None:
        self.root = Path(root)
        self.config = config or LocalExecutionStoreConfig()
        if self.config.busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        if not self.root.is_dir():
            raise LocalExecutionStoreError(
                "read-only execution/material store root does not exist"
            )

        self.blob_root = self.root / "blobs" / "sha256"
        self.staging_root = self.root / "staging"
        self.database = self.root / "execution.db"
        if not self.database.is_file():
            raise LocalExecutionStoreError(
                "read-only execution/material store is missing execution.db"
            )

        self._allowed_import_roots = ()
        self._lock = RLock()
        database_uri = self.database.resolve().as_uri() + "?mode=ro"
        try:
            self._connection = sqlite3.connect(
                database_uri,
                uri=True,
                isolation_level=None,
                timeout=max(self.config.busy_timeout_ms / 1000.0, 0.001),
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA query_only = ON")
            self._connection.execute(
                f"PRAGMA busy_timeout = {int(self.config.busy_timeout_ms)}"
            )
            self._validate_existing_schema()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise

    def _validate_existing_schema(self) -> None:
        migration_dir = Path(__file__).with_name("migrations")
        known: list[tuple[int, str]] = []
        for path in sorted(migration_dir.glob("*.sql")):
            match = _MIGRATION_RE.match(path.name)
            if match is None:
                raise LocalExecutionStoreError(
                    f"invalid execution-store migration name {path.name!r}"
                )
            known.append((int(match.group("version")), path.stem))
        versions = [version for version, _ in known]
        if versions != list(range(1, len(versions) + 1)):
            raise LocalExecutionStoreError(
                "execution-store migrations must be contiguous from 0001"
            )
        try:
            rows = self._connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        except sqlite3.Error as exc:
            raise LocalExecutionStoreError(
                "read-only execution/material store has no valid migration history"
            ) from exc
        applied = [(int(row["version"]), str(row["name"])) for row in rows]
        if applied != known:
            raise LocalExecutionStoreError(
                "read-only execution/material store schema does not match "
                "the current supported migration history"
            )

    def verified_artifact_path(self, artifact_id: str) -> Path:
        """Return the staged backing path only after exact digest/size verification."""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT storage_locator, digest
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise KeyError(str(artifact_id))
        diagnosis = self.diagnose_artifact_content(str(artifact_id))
        if diagnosis.get("status") != "verified":
            error = LocalExecutionStoreIntegrityError(
                "staged artifact backing content is not verified"
            )
            error.diagnosis = dict(diagnosis)
            raise error
        path = self._locator_path(str(row["storage_locator"]), str(row["digest"]))
        root = self.root.resolve()
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise LocalExecutionStoreIntegrityError(
                "staged artifact backing path escapes the staged source root"
            ) from exc
        current = root
        for part in relative.parts:
            current = current / part
            is_junction = getattr(current, "is_junction", lambda: False)
            if current.is_symlink() or is_junction():
                raise LocalExecutionStoreIntegrityError(
                    "staged artifact backing path contains a link or junction"
                )
        return path

    def cleanup_staging(self) -> int:
        raise self._read_only_error()

    def _read_only_error(self) -> LocalExecutionStoreError:
        return LocalExecutionStoreError(
            "execution/material source store was opened read-only"
        )

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        raise self._read_only_error()
        yield  # pragma: no cover

    def _store_blob(self, *args, **kwargs):
        raise self._read_only_error()

    def _stage_controlled_original(self, *args, **kwargs):
        raise self._read_only_error()

    def _install_staged_original(self, *args, **kwargs):
        raise self._read_only_error()

    @contextmanager
    def _large_capture_run_reservation(self, *args, **kwargs):
        raise self._read_only_error()
        yield  # pragma: no cover


def open_read_only_execution_store(
    root: str | Path,
    *,
    config: LocalExecutionStoreConfig | None = None,
) -> ReadOnlyLocalExecutionStore:
    """Open a portable execution/material child root without mutating it."""
    return ReadOnlyLocalExecutionStore(root, config=config)
