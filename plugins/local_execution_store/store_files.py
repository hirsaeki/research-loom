"""Content-addressed blobs and controlled reads of imported files (#494)."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path

from plugins._infra.atomic_write import durable_staged_file, publish_staged

from .store_model import (
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
)


class StoreFileMixin:
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
        with durable_staged_file(self.staging_root, content, prefix="blob-") as staged:
            if target.exists():
                self._verify_blob_path(target, digest, len(content))
            else:
                if not publish_staged(staged, target, replace=False):
                    self._verify_blob_path(target, digest, len(content))
                self._fsync_directory(target_dir)
            return digest, f"{scheme}://sha256/{digest_hex}"

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
            locator.startswith("artifact://sha256/") or locator.startswith("resource://sha256/")
        ):
            raise LocalExecutionStoreIntegrityError("unsupported or non-local storage locator")
        digest_hex = locator.rsplit("/", 1)[-1]
        if expected_digest != f"sha256:{digest_hex}":
            raise LocalExecutionStoreIntegrityError(
                "storage locator digest disagrees with metadata"
            )
        if len(digest_hex) != 64 or any(ch not in "0123456789abcdef" for ch in digest_hex):
            raise LocalExecutionStoreIntegrityError("invalid content-addressed storage locator")
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
            raise PermissionError("file is outside configured artifact/resource intake roots")
        relative = candidate.relative_to(root)
        self._reject_reparse_components(root, relative)

        if (
            os.name != "nt"
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd
        ):
            return self._read_controlled_file_dirfd(
                root,
                relative,
                max_bytes=max_bytes,
            )
        return self._read_controlled_file_fallback(
            candidate,
            root,
            relative,
            max_bytes=max_bytes,
        )

    def _matching_import_root(self, candidate: Path) -> Path | None:
        matches = [
            root
            for root in self._allowed_import_roots
            if candidate == root or candidate.is_relative_to(root)
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: len(item.parts))

    @staticmethod
    def _reject_reparse_components(root: Path, relative: Path) -> None:
        current = root
        for part in relative.parts:
            if part in {"", ".", ".."}:
                raise PermissionError("invalid path component for file intake")
            current = current / part
            info = current.lstat()
            is_junction = getattr(current, "is_junction", None)
            if stat.S_ISLNK(info.st_mode) or (callable(is_junction) and is_junction()):
                raise PermissionError("symlink/reparse-point intake is forbidden")

    def _read_controlled_file_dirfd(
        self,
        root: Path,
        relative: Path,
        *,
        max_bytes: int,
    ) -> bytes:
        root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_fd = os.open(root, root_flags)
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
                        raise PermissionError("symlink/reparse-point intake is forbidden") from exc
                    raise
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd
            info = os.fstat(current_fd)
            if not stat.S_ISREG(info.st_mode):
                raise PermissionError("only regular files may be imported")
            if info.st_size > max_bytes:
                raise LocalExecutionStoreError("file exceeds configured intake size limit")
            return self._read_fd_limited(current_fd, max_bytes)
        finally:
            if current_fd != root_fd:
                os.close(current_fd)
            os.close(root_fd)

    def _read_controlled_file_fallback(
        self,
        candidate: Path,
        root: Path,
        relative: Path,
        *,
        max_bytes: int,
    ) -> bytes:
        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise PermissionError("only regular files may be imported")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(candidate, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise PermissionError("only regular files may be imported")
            if opened.st_size > max_bytes:
                raise LocalExecutionStoreError("file exceeds configured intake size limit")
            self._reject_reparse_components(root, relative)
            after = candidate.lstat()
            before_identity = (before.st_dev, before.st_ino)
            opened_identity = (opened.st_dev, opened.st_ino)
            after_identity = (after.st_dev, after.st_ino)
            if not (before_identity == opened_identity == after_identity):
                raise PermissionError("file changed during controlled intake")
            if os.name == "nt":
                final_path = self._windows_final_path_for_fd(fd)
                if os.path.normcase(os.path.abspath(final_path)) != os.path.normcase(
                    os.path.abspath(candidate)
                ):
                    raise PermissionError("symlink/reparse-point intake is forbidden")
            return self._read_fd_limited(fd, max_bytes)
        finally:
            os.close(fd)

    @staticmethod
    def _read_fd_limited(fd: int, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise LocalExecutionStoreError(
                "file exceeded configured intake size limit while reading"
            )
        return data

    @staticmethod
    def _windows_final_path_for_fd(fd: int) -> Path:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_final_path = kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        get_final_path.restype = ctypes.c_uint32
        size = get_final_path(handle, None, 0, 0)
        if size == 0:
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        buffer = ctypes.create_unicode_buffer(size + 1)
        written = get_final_path(handle, buffer, len(buffer), 0)
        if written == 0 or written >= len(buffer):
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
