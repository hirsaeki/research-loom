from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterator, Mapping

from core.execution.models import CapabilityRunRecord, ExecutionArtifactMetadata, RunStatus

from .atomic import LocalExecutionStore as _AtomicExecutionStore
from .store import LocalExecutionStoreError, LocalExecutionStoreIntegrityError, _now


_LARGE_ORIGINAL_SCHEME = "external-original"


class LocalExecutionStore(_AtomicExecutionStore):
    """Atomic store plus a managed streaming path for oversized external originals."""

    @property
    def _large_original_root(self) -> Path:
        return self.root / "large-originals" / "sha256"

    def _locator_path(self, locator: str, expected_digest: str) -> Path:
        prefix = f"{_LARGE_ORIGINAL_SCHEME}://sha256/"
        if not locator.startswith(prefix):
            return super()._locator_path(locator, expected_digest)
        digest_hex = locator[len(prefix):]
        if (
            len(digest_hex) != 64
            or any(ch not in "0123456789abcdef" for ch in digest_hex)
            or expected_digest != f"sha256:{digest_hex}"
        ):
            raise LocalExecutionStoreIntegrityError(
                "large original storage locator disagrees with metadata"
            )
        return self._large_original_root / digest_hex[:2] / digest_hex

    @contextmanager
    def _controlled_file_fd(
        self,
        source_path: str | Path,
        *,
        max_bytes: int,
    ) -> Iterator[tuple[int, int]]:
        """Open one controlled intake file without materializing it in Python bytes."""
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        if not self._allowed_import_roots:
            raise PermissionError(
                "file import is disabled until allowed_import_roots is configured"
            )
        raw = Path(source_path)
        if ".." in raw.parts:
            raise PermissionError("path traversal is not allowed for file intake")
        candidate = Path(os.path.abspath(raw))
        root = self._matching_import_root(candidate)
        if root is None:
            try:
                anchored = Path(os.path.realpath(candidate.parent)) / candidate.name
            except OSError:
                anchored = candidate
            if anchored != candidate:
                candidate = anchored
                root = self._matching_import_root(candidate)
        if root is None:
            raise PermissionError(
                "file is outside configured artifact/resource intake roots"
            )
        relative = candidate.relative_to(root)
        self._reject_reparse_components(root, relative)

        if (
            os.name != "nt"
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd
        ):
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            current_fd = root_fd
            try:
                parts = relative.parts
                if not parts:
                    raise PermissionError("only regular files may be imported")
                for index, part in enumerate(parts):
                    final = index == len(parts) - 1
                    flags = os.O_RDONLY | os.O_NOFOLLOW
                    if final:
                        flags |= getattr(os, "O_NONBLOCK", 0)
                    else:
                        flags |= os.O_DIRECTORY
                    try:
                        next_fd = os.open(part, flags, dir_fd=current_fd)
                    except OSError as exc:
                        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                            raise PermissionError(
                                "symlink/reparse-point intake is forbidden"
                            ) from exc
                        raise
                    if current_fd != root_fd:
                        os.close(current_fd)
                    current_fd = next_fd
                info = os.fstat(current_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise PermissionError("only regular files may be imported")
                if info.st_size > max_bytes:
                    raise LocalExecutionStoreError(
                        "file exceeds configured intake size limit"
                    )
                yield current_fd, int(info.st_size)
            finally:
                if current_fd != root_fd:
                    os.close(current_fd)
                os.close(root_fd)
            return

        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise PermissionError("only regular files may be imported")
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise PermissionError("only regular files may be imported")
            if opened.st_size > max_bytes:
                raise LocalExecutionStoreError(
                    "file exceeds configured intake size limit"
                )
            self._reject_reparse_components(root, relative)
            after = candidate.lstat()
            if not (
                (before.st_dev, before.st_ino)
                == (opened.st_dev, opened.st_ino)
                == (after.st_dev, after.st_ino)
            ):
                raise PermissionError("file changed during controlled intake")
            if os.name == "nt":
                final_path = self._windows_final_path_for_fd(fd)
                if os.path.normcase(os.path.abspath(final_path)) != os.path.normcase(
                    os.path.abspath(candidate)
                ):
                    raise PermissionError(
                        "symlink/reparse-point intake is forbidden"
                    )
            yield fd, int(opened.st_size)
        finally:
            os.close(fd)

    def _stage_controlled_original(
        self,
        source_path: str | Path,
        *,
        max_bytes: int,
    ) -> tuple[Path, str, int]:
        fd, temporary_name = tempfile.mkstemp(prefix="large-original-", dir=self.staging_root)
        os.close(fd)
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        total = 0
        try:
            with self._controlled_file_fd(source_path, max_bytes=max_bytes) as (source_fd, declared_size):
                with temporary.open("wb") as target:
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise LocalExecutionStoreError(
                                "file exceeded configured intake size limit while reading"
                            )
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if total != declared_size:
                    raise PermissionError("file changed during controlled intake")
            return temporary, f"sha256:{digest.hexdigest()}", total
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _verify_blob_streaming(path: Path, digest: str, size: int) -> None:
        actual = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                actual.update(chunk)
                total += len(chunk)
        if f"sha256:{actual.hexdigest()}" != digest or total != size:
            raise LocalExecutionStoreIntegrityError(
                "content-addressed blob failed digest/size verification"
            )

    def _install_staged_original(
        self,
        temporary: Path,
        *,
        digest: str,
        size: int,
        large: bool,
    ) -> tuple[str, Path, bool]:
        digest_hex = digest.removeprefix("sha256:")
        root = self._large_original_root if large else self.blob_root
        target_dir = root / digest_hex[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / digest_hex
        created = False
        if target.exists():
            self._verify_blob_streaming(target, digest, size)
        else:
            try:
                os.link(temporary, target)
                created = True
            except FileExistsError:
                self._verify_blob_streaming(target, digest, size)
            self._fsync_directory(target_dir)
        scheme = _LARGE_ORIGINAL_SCHEME if large else "artifact"
        return f"{scheme}://sha256/{digest_hex}", target, created

    def _validate_desktop_research_capture_pair(
        self,
        run: CapabilityRunRecord,
        *,
        original_size: int,
        text_size: int,
        original_artifact_id: str,
        text_artifact_id: str,
        role_byte_limits: Mapping[str, int],
        role_count_limits: Mapping[str, int],
        expected_status: RunStatus,
    ) -> None:
        """Validate pair guards inside a store transaction without touching payload bytes."""
        original_role = "desktop_research.original_capture"
        text_role = "desktop_research.text_rendition"
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
        if persisted.status is not expected_status:
            raise LocalExecutionStoreError(
                f"artifact Run must remain {expected_status.value}"
            )

        existing = self.artifacts_for(run.run_id)
        counts = Counter(item.role for item in existing)
        role_bytes = Counter()
        for artifact in existing:
            role_bytes[artifact.role] += artifact.size
        for role in (original_role, text_role):
            if counts[role] + 1 > int(role_count_limits[role]):
                raise LocalExecutionStoreError(
                    f"artifact role count limit exceeded: {role}"
                )
        if role_bytes[original_role] + original_size > int(role_byte_limits[original_role]):
            raise LocalExecutionStoreError(
                f"artifact role byte limit exceeded: {original_role}"
            )
        if role_bytes[text_role] + text_size > int(role_byte_limits[text_role]):
            raise LocalExecutionStoreError(
                f"artifact role byte limit exceeded: {text_role}"
            )

        generic_total_row = self._connection.execute(
            """
            SELECT COALESCE(SUM(size), 0) AS total
            FROM execution_artifacts
            WHERE run_id = ? AND storage_locator NOT LIKE 'external-original://%'
            """,
            (run.run_id,),
        ).fetchone()
        large = original_size > self.config.max_artifact_bytes
        generic_planned = text_size + (0 if large else original_size)
        if int(generic_total_row["total"]) + generic_planned > self.config.max_run_output_bytes:
            raise LocalExecutionStoreError(
                "Run output exceeds configured max_run_output_bytes"
            )

        collision = self._connection.execute(
            "SELECT artifact_id FROM execution_artifacts WHERE artifact_id IN (?,?)",
            (original_artifact_id, text_artifact_id),
        ).fetchone()
        if collision is not None:
            raise ValueError("immutable artifact identity collision")

    def put_desktop_research_capture_files(
        self,
        run: CapabilityRunRecord,
        *,
        original_path: str | Path,
        original_media_type: str,
        original_artifact_id: str,
        original_provenance: Mapping[str, Any],
        text_content: bytes,
        text_artifact_id: str,
        text_provenance: Mapping[str, Any],
        max_original_bytes: int,
        role_byte_limits: Mapping[str, int],
        role_count_limits: Mapping[str, int],
        expected_status: RunStatus,
    ) -> tuple[ExecutionArtifactMetadata, ExecutionArtifactMetadata]:
        """Persist one original/text capture pair; large originals bypass only generic output bounds."""
        if not isinstance(text_content, bytes):
            raise TypeError("text rendition content must be bytes")
        if len(text_content) > self.config.max_artifact_bytes:
            raise LocalExecutionStoreError(
                "text rendition exceeds configured max_artifact_bytes"
            )
        try:
            text_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalExecutionStoreError("text rendition must be valid UTF-8") from exc

        # Secure fstat gives us the size needed for deterministic guard checks
        # without reading or staging the large payload. Recheck after staging in
        # case the source changes between the two controlled opens.
        with self._controlled_file_fd(
            original_path,
            max_bytes=max_original_bytes,
        ) as (_source_fd, original_size_hint):
            pass
        with self._write_transaction():
            self._validate_desktop_research_capture_pair(
                run,
                original_size=original_size_hint,
                text_size=len(text_content),
                original_artifact_id=original_artifact_id,
                text_artifact_id=text_artifact_id,
                role_byte_limits=role_byte_limits,
                role_count_limits=role_count_limits,
                expected_status=expected_status,
            )

        staged, original_digest, original_size = self._stage_controlled_original(
            original_path,
            max_bytes=max_original_bytes,
        )
        large = original_size > self.config.max_artifact_bytes
        original_role = "desktop_research.original_capture"
        text_role = "desktop_research.text_rendition"
        original_target: Path | None = None
        original_created = False
        text_target: Path | None = None
        text_target_was_absent = False
        try:
            text_target = self._blob_target_for(text_content)
            text_target_was_absent = not text_target.exists()
            with self._write_transaction():
                self._validate_desktop_research_capture_pair(
                    run,
                    original_size=original_size,
                    text_size=len(text_content),
                    original_artifact_id=original_artifact_id,
                    text_artifact_id=text_artifact_id,
                    role_byte_limits=role_byte_limits,
                    role_count_limits=role_count_limits,
                    expected_status=expected_status,
                )

                original_locator, original_target, original_created = self._install_staged_original(
                    staged,
                    digest=original_digest,
                    size=original_size,
                    large=large,
                )
                text_digest, text_locator = self._store_blob(text_content, scheme="artifact")
                original_trusted = dict(original_provenance)
                original_trusted.update(
                    {
                        "source_run_id": run.run_id,
                        "execution_mode": run.execution_mode,
                        "stored_by": "plugins.local_execution_store",
                        "stored_at": _now(),
                        "parent_artifact_refs": [],
                    }
                )
                text_trusted = dict(text_provenance)
                text_trusted.update(
                    {
                        "source_run_id": run.run_id,
                        "execution_mode": run.execution_mode,
                        "stored_by": "plugins.local_execution_store",
                        "stored_at": _now(),
                        "parent_artifact_refs": [original_artifact_id],
                    }
                )
                original = ExecutionArtifactMetadata(
                    original_artifact_id,
                    run.run_id,
                    original_role,
                    str(original_media_type),
                    original_size,
                    original_digest,
                    original_locator,
                    run.execution_mode,
                    original_trusted,
                )
                text = ExecutionArtifactMetadata(
                    text_artifact_id,
                    run.run_id,
                    text_role,
                    "text/plain",
                    len(text_content),
                    text_digest,
                    text_locator,
                    run.execution_mode,
                    text_trusted,
                )
                self._register_output_artifact_in_transaction(original)
                self._register_output_artifact_in_transaction(text)
                return original, text
        except Exception:
            if original_created and original_target is not None:
                self._cleanup_new_blob_targets({original_target})
            if text_target_was_absent and text_target is not None:
                self._cleanup_new_blob_targets({text_target})
            raise
        finally:
            try:
                staged.unlink()
            except FileNotFoundError:
                pass

    def verify_artifact_integrity(self, artifact_id: str) -> None:
        with self._lock:
            row = self._connection.execute(
                "SELECT size, digest, storage_locator FROM execution_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        path = self._locator_path(str(row["storage_locator"]), str(row["digest"]))
        self._verify_blob_streaming(path, str(row["digest"]), int(row["size"]))
