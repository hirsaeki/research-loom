"""Shared Workspace lifetimes and exclusive Profile updates, bounded by OS locks."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import math
import os
from pathlib import Path
import threading
import time

from .workspace import INTERNAL_DIR, LocalWorkspaceError, _safe_locator

ADVANCEMENT_LOCK = "profile-advancement.lock"
_LOCK_STATE = threading.local()


def _try_lock(handle, *, shared: bool) -> None:
    if os.name != "nt":
        import fcntl
        fcntl.flock(handle.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt

    # LockFileEx supports actual shared byte-range locks; CRT locking does not
    # provide this distinction. FAIL_IMMEDIATELY keeps every attempt bounded.
    # https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex
    class Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    lock = ctypes.WinDLL("kernel32", use_last_error=True).LockFileEx
    lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                     wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    lock.restype = wintypes.BOOL
    overlapped = Overlapped()
    if not lock(msvcrt.get_osfhandle(handle.fileno()), 1 | (0 if shared else 2),
                0, 1, 0, ctypes.byref(overlapped)):
        raise ctypes.WinError(ctypes.get_last_error())


def _contention(exc: OSError) -> bool:
    if os.name == "nt":
        return getattr(exc, "winerror", None) == 33  # ERROR_LOCK_VIOLATION, not access denied.
    # Some Python platforms emulate flock with fcntl record locking, whose
    # nonblocking conflict can be EACCES. File-open EACCES is handled separately.
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}


@contextmanager
def workspace_lock(root: Path, *, shared: bool = False, timeout: float = 5.0):
    """Never upgrade a live shared lifetime, or steal/unlink another OS lock.

    Same-thread exclusive nesting is needed by advancement's internal open and
    rollback; normal shared handles also remain reference-counted until closed.
    """
    if not math.isfinite(timeout) or not 0 <= timeout <= 5:
        raise ValueError("Workspace lock timeout must be between zero and five seconds")
    if not root.is_dir():
        raise LocalWorkspaceError("WORKSPACE-MISSING-001", "workspace directory does not exist")
    key = str(root.resolve(strict=True))
    leases = getattr(_LOCK_STATE, "leases", None)
    if leases is None:
        leases = {}
        _LOCK_STATE.leases = leases
    lease = leases.get(key)
    if lease is not None and lease["shared"] and not shared:
        raise LocalWorkspaceError("WORKSPACE-LOCK-BUSY-001", "Profile update requires exclusive access; close this thread's Workspace handles and retry")
    if lease is None:
        internal = _safe_locator(root, INTERNAL_DIR)
        if not internal.is_dir():
            raise LocalWorkspaceError("WORKSPACE-MISSING-001", "workspace internal directory is missing")
        lock_path = _safe_locator(root, f"{INTERNAL_DIR}/{ADVANCEMENT_LOCK}", require_exists=False)
        try:
            handle = lock_path.open("a+b")
        except OSError as exc:
            raise LocalWorkspaceError("WORKSPACE-LOCK-IO-001", "cannot open Workspace lock; resolve permissions or filesystem I/O, then retry") from exc
        try:
            # A byte-range past EOF is valid. Do not write a sentinel: a second
            # reader could otherwise race a shared lock on an initially empty file.
            deadline = time.monotonic() + timeout
            while True:
                try:
                    _try_lock(handle, shared=shared)
                    break
                except OSError as exc:
                    if not _contention(exc):
                        raise LocalWorkspaceError("WORKSPACE-LOCK-IO-001", "cannot acquire Workspace lock; resolve permissions, unsupported locking or filesystem I/O, then retry") from exc
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LocalWorkspaceError("WORKSPACE-LOCK-BUSY-001", "Workspace is in use; close active handles or finish Profile update, then retry. Do not delete the lock file") from exc
                    time.sleep(min(0.05, remaining))
        except BaseException:
            handle.close()
            raise
        lease = {"handle": handle, "count": 0, "shared": shared}
        leases[key] = lease
    lease["count"] += 1
    try:
        yield
    finally:
        lease["count"] -= 1
        if lease["count"] == 0:
            leases.pop(key, None)
            # Both flock and LockFileEx release the lock on final handle close;
            # process death also releases it without a stale lock-file protocol.
            lease["handle"].close()
