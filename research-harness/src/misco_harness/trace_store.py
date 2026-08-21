from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from misco_harness.models import SAFE_IDENTIFIER_PATTERN


class TraceStoreError(RuntimeError):
    pass


class ImmutableArtifactExists(TraceStoreError):
    pass


class HashMismatch(TraceStoreError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash a frozen directory tree by relative path and file content."""
    digest = hashlib.sha256()
    entries = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for path in entries:
        if path.is_symlink():
            raise TraceStoreError(f"frozen tree must not contain symbolic links: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content_digest = bytes.fromhex(sha256_file(path))
        digest.update(b"F")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        digest.update(content_digest)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise HashMismatch(f"hash mismatch for {path}: expected {expected}, got {actual}")


def _json_bytes(value: BaseModel | dict[str, Any] | list[Any]) -> bytes:
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json")
    else:
        data = value
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(value)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


class TraceStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._resolved_root = self.root

    def _confine(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise TraceStoreError(f"Trace Store path must be a relative path without traversal: {relative_path!r}")
        target = (self.root / relative).resolve()
        if target != self._resolved_root and not target.is_relative_to(self._resolved_root):
            raise TraceStoreError(f"Trace Store path escapes the runtime root {self._resolved_root}: {target}")
        return target

    @staticmethod
    def _write_exclusive(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        binary_flag = getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags | binary_flag)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            _fsync_directory(path.parent)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    def write_immutable(self, relative_path: str | Path, value: BaseModel | dict[str, Any]) -> Path:
        target = self._confine(relative_path)
        try:
            self._write_exclusive(target, _json_bytes(value))
        except FileExistsError as error:
            raise ImmutableArtifactExists(str(target)) from error
        return target

    def write_head(self, relative_path: str | Path, value: BaseModel | dict[str, Any]) -> Path:
        target = self._confine(relative_path)
        atomic_write_json(target, value)
        return target

    def write_immutable_text(self, relative_path: str | Path, value: str) -> Path:
        target = self._confine(relative_path)
        try:
            self._write_exclusive(target, value.encode("utf-8"))
        except FileExistsError as error:
            raise ImmutableArtifactExists(str(target)) from error
        return target

    def copy_immutable_file(self, source: Path, relative_path: str | Path) -> Path:
        """Copy a verified file into the immutable Trace Store."""
        target = self._confine(relative_path)
        if source.is_symlink() or not source.is_file():
            raise TraceStoreError(f"immutable source must be a regular file: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        binary_flag = getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(target, flags | binary_flag)
        except FileExistsError as error:
            raise ImmutableArtifactExists(str(target)) from error
        try:
            with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target_stream:
                descriptor = -1
                shutil.copyfileobj(source_stream, target_stream)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            _fsync_directory(target.parent)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            target.unlink(missing_ok=True)
            raise
        return target

    def read_json(self, relative_path: str | Path) -> Any:
        with self._confine(relative_path).open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def create_run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(SAFE_IDENTIFIER_PATTERN, run_id):
            raise TraceStoreError(f"unsafe run identifier: {run_id!r}")
        run_dir = self._confine(Path("runs") / run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def snapshot(self, kind: str, snapshot_id: str, value: BaseModel) -> Path:
        return self.write_immutable(Path("state") / kind / "snapshots" / f"{snapshot_id}.json", value)


def _fsync_directory(path: Path) -> None:
    """Persist a rename's directory entry where the platform exposes it."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
