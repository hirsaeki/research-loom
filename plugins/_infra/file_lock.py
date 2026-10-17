"""Exclusive byte-range locks on lock files, shared by the local stores and services.

Every lock here is an exclusive lock on byte 0 of a dedicated lock file. Windows
uses CRT ``msvcrt.locking``; POSIX uses ``flock``. Call sites choose their own
waiting policy and map failures to their own error codes.
"""

from __future__ import annotations

import errno
import os
import sys
import time

# errno values that mean "another holder has the lock" rather than an I/O failure.
CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK})


class LockTimeout(Exception):
    """The lock stayed contended past the deadline; ``__cause__`` is the last attempt."""


def write_sentinel_if_empty(fd: int, *, fsync: bool) -> None:
    """Give an empty lock file a byte to lock (CRT locking needs one on Windows)."""
    if os.fstat(fd).st_size == 0:
        os.write(fd, b"\0")
        if fsync:
            os.fsync(fd)


def lock_byte(fd: int, *, blocking: bool) -> None:
    """Lock byte 0 exclusively; nonblocking attempts raise ``OSError`` on contention.

    On Windows a blocking attempt uses ``LK_LOCK``, which retries for about ten
    seconds before raising.
    """
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_byte(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def acquire_byte_lock(
    fd: int,
    *,
    timeout: float | None,
    contention_errnos: frozenset[int] = CONTENTION_ERRNOS,
    poll_interval: float = 0.05,
) -> None:
    """Acquire the byte-0 lock, polling while it is contended.

    ``timeout=None`` waits indefinitely (a blocking ``flock`` on POSIX). Otherwise
    raise ``LockTimeout`` once the deadline passes. An ``OSError`` whose errno is
    not in ``contention_errnos`` is an I/O failure and propagates unchanged.
    """
    if timeout is None and sys.platform != "win32":
        lock_byte(fd, blocking=True)
        return
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        try:
            lock_byte(fd, blocking=False)
            return
        except OSError as exc:
            if exc.errno not in contention_errnos:
                raise
            if deadline is not None and time.monotonic() >= deadline:
                raise LockTimeout("lock is held by another holder") from exc
            time.sleep(poll_interval)
