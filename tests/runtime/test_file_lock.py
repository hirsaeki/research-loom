"""Behavior of the shared byte-0 lock primitive (plugins/_infra/file_lock.py, #488)."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from plugins._infra.file_lock import (
    CONTENTION_ERRNOS,
    LockTimeout,
    acquire_byte_lock,
    lock_byte,
    unlock_byte,
    write_sentinel_if_empty,
)

CI_WINDOWS = True  # msvcrt and flock paths differ; exercise both lanes


class FileLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "x.lock"
        self.fds: list[int] = []

    def tearDown(self):
        for fd in self.fds:
            os.close(fd)
        self._tmp.cleanup()

    def _open(self) -> int:
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
        self.fds.append(fd)
        write_sentinel_if_empty(fd, fsync=False)
        return fd

    def test_sentinel_written_once(self):
        first = self._open()
        self._open()
        self.assertEqual(os.fstat(first).st_size, 1)

    def test_nonblocking_attempt_on_held_lock_raises_contention(self):
        holder, other = self._open(), self._open()
        lock_byte(holder, blocking=False)
        with self.assertRaises(OSError) as raised:
            lock_byte(other, blocking=False)
        self.assertIn(raised.exception.errno, CONTENTION_ERRNOS)
        unlock_byte(holder)
        lock_byte(other, blocking=False)
        unlock_byte(other)

    def test_bounded_wait_raises_lock_timeout_with_cause(self):
        holder, other = self._open(), self._open()
        lock_byte(holder, blocking=False)
        started = time.monotonic()
        with self.assertRaises(LockTimeout) as raised:
            acquire_byte_lock(other, timeout=0.2)
        self.assertGreaterEqual(time.monotonic() - started, 0.2)
        self.assertIsInstance(raised.exception.__cause__, OSError)
        unlock_byte(holder)

    def test_unbounded_wait_returns_once_released(self):
        holder, other = self._open(), self._open()
        lock_byte(holder, blocking=False)
        releaser = threading.Timer(0.2, unlock_byte, args=(holder,))
        releaser.start()
        try:
            acquire_byte_lock(other, timeout=None)
        finally:
            releaser.join()
        unlock_byte(other)

    def test_non_contention_error_propagates_immediately(self):
        holder, other = self._open(), self._open()
        lock_byte(holder, blocking=False)
        with self.assertRaises(OSError) as raised:
            acquire_byte_lock(other, timeout=5, contention_errnos=frozenset())
        self.assertNotIsInstance(raised.exception, LockTimeout)
        unlock_byte(holder)


if __name__ == "__main__":
    unittest.main()
