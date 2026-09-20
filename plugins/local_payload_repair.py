"""Exact-byte repair primitives for the two managed content-addressed stores.

Callers own metadata/authority and controlled intake. This module only preserves
bad payload bytes and installs a verified replacement; it never repairs metadata.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Callable, Iterator
import uuid


REPAIRABLE = frozenset({
    "content_missing", "digest_mismatch", "size_mismatch", "digest_and_size_mismatch",
})


class PayloadRepairError(RuntimeError):
    pass


def checked_path(root: Path, path: Path) -> Path:
    """Reject links/reparse points and special files, including parent components."""
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PayloadRepairError("payload path escapes its store") from exc
    if ".." in relative.parts:
        raise PayloadRepairError("payload path contains traversal")
    # Normalize aliases of the trusted store's parent, not the child itself.
    root = root.parent.resolve(strict=True) / root.name
    current = root
    parts = relative.parts
    for index in range(len(parts) + 1):
        try:
            value = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise PayloadRepairError("payload path contains a link or reparse point")
        final = index == len(parts)
        if (final and not stat.S_ISREG(value.st_mode)) or (not final and not stat.S_ISDIR(value.st_mode)):
            raise PayloadRepairError("payload path is not a regular file/directory")
        if not final:
            current = current / parts[index]
    return root.joinpath(relative)


def inspect_payload(path: Path, digest: str, size: int) -> dict[str, object]:
    """Bound hashing by the expected size; an oversized bad file is not loaded."""
    base = {"expected_digest": digest, "expected_size": size,
            "actual_digest": None, "actual_size": None}
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                return {**base, "status": "locator_invalid"}
            if opened.st_size > size:
                return {**base, "status": "size_mismatch", "actual_size": opened.st_size}
            actual = hashlib.sha256()
            total = 0
            while total <= size:
                chunk = stream.read(min(1024 * 1024, size + 1 - total))
                if not chunk:
                    break
                actual.update(chunk)
                total += len(chunk)
    except FileNotFoundError:
        return {**base, "status": "content_missing"}
    except OSError:
        return {**base, "status": "content_unreadable"}
    actual_digest = "sha256:" + actual.hexdigest()
    if total > size:
        return {**base, "status": "size_mismatch", "actual_size": total}
    state = "verified"
    if actual_digest != digest and total != size:
        state = "digest_and_size_mismatch"
    elif actual_digest != digest:
        state = "digest_mismatch"
    elif total != size:
        state = "size_mismatch"
    return {**base, "status": state, "actual_digest": actual_digest, "actual_size": total}


def _fsync_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def payload_lock(root: Path, target: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Reserve one physical content address, not one artifact or Run identity."""
    target = checked_path(root, target)
    root = root.parent.resolve(strict=True) / root.name
    token = hashlib.sha256(str(target.relative_to(root)).encode("utf-8")).hexdigest()
    lock_path = checked_path(root, root / "repair-locks" / (token + ".lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise PayloadRepairError("content-addressed payload repair is busy; retry later") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def install_exact_payload(
    root: Path, target: Path, staged: Path, digest: str, size: int,
    *, verify: Callable[[Path, str, int], None],
) -> dict[str, object]:
    """Install under a blob lock; the caller removes its controlled staging file.

    Quarantine is a hard link created before atomic replacement, so an interruption
    never leaves the old payload unpreserved. Reads see either old or new bytes;
    ordinary store writers are no-clobber and cannot overwrite a repaired payload.
    """
    target = checked_path(root, target)
    root = root.parent.resolve(strict=True) / root.name
    with payload_lock(root, target):
        target = checked_path(root, target)
        before = inspect_payload(target, digest, size)
        # Validate actual staged bytes even when the target needs no repair.
        verify(staged, digest, size)
        if before["status"] == "verified":
            return {"status": "ALREADY_VERIFIED", "content_created": False,
                    "previous_status": "verified", "quarantine_ref": None}
        if before["status"] not in REPAIRABLE:
            raise PayloadRepairError("payload is unreadable or its locator is unsafe; restore access/metadata first")
        target.parent.mkdir(parents=True, exist_ok=True)
        checked_path(root, target)
        quarantine_ref = None
        repair_id = uuid.uuid4().hex
        if before["status"] != "content_missing":
            quarantine = checked_path(root, root / "quarantine" / (target.name + "-" + repair_id))
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            os.link(target, quarantine)
            _fsync_directory(quarantine.parent)
            quarantine_ref = quarantine.relative_to(root).as_posix()
            # No managed writer mutates a present blob in place. A concurrently
            # repaired equivalent blob may safely be replaced with identical bytes.
            os.replace(staged, target)
        else:
            try:
                os.link(staged, target)
            except FileExistsError:
                verify(target, digest, size)
                return {"status": "ALREADY_VERIFIED", "content_created": False,
                        "previous_status": before["status"], "quarantine_ref": None}
        _fsync_directory(target.parent)
        verify(target, digest, size)
        result = {"status": "RESTORED" if before["status"] == "content_missing" else "REPAIRED",
                  "content_created": True, "previous_status": before["status"],
                  "quarantine_ref": quarantine_ref,
                  "recovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        record = {"schema": "exact-payload-repair/v1", "target": target.relative_to(root).as_posix(),
                  "digest": digest, "byte_length": size, "before": before, **result}
        temporary = None
        fd = None
        try:
            receipt = checked_path(root, root / "repairs" / (repair_id + ".json"))
            receipt.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".repair-", dir=receipt.parent)
            temporary = Path(name)
            stream = os.fdopen(fd, "wb")
            fd = None
            with stream:
                stream.write((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, receipt)
            _fsync_directory(receipt.parent)
            result["recovery_record"] = receipt.relative_to(root).as_posix()
        except (OSError, PayloadRepairError):
            result["recovery_record_warning"] = "payload verified; repair receipt could not be persisted"
        finally:
            if fd is not None:
                os.close(fd)
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return result
