"""Atomic file publication shared by the local stores and services.

Two styles exist and are kept distinct because call sites rely on their
different durability and permission semantics:

* ``replace_text`` writes a sibling temporary with ``Path.write_text`` (default
  permissions, native newlines, no fsync) and ``os.replace``s it into place.
* ``durable_staged_file`` / ``publish_staged`` / ``write_durable`` stage bytes in
  an fsynced ``mkstemp`` file (owner-only permissions) and publish it either by
  ``os.replace`` or by a no-clobber ``os.link``.

``OSError`` propagates unchanged; call sites map it to their own error codes.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path


def replace_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Replace ``path`` with ``text`` via a sibling temporary; the temporary never outlives a failure."""
    temporary = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(text, encoding=encoding)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def durable_staged_file(
    directory: Path, data: bytes, *, prefix: str, suffix: str = ""
) -> Iterator[Path]:
    """Yield an fsynced ``mkstemp`` file in ``directory`` holding ``data``; remove it on exit."""
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    staged = Path(name)
    try:
        try:
            stream = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        yield staged
    finally:
        staged.unlink(missing_ok=True)


def publish_staged(staged: Path, target: Path, *, replace: bool) -> bool:
    """Publish ``staged`` at ``target``.

    With ``replace`` the target is atomically replaced. Without it the target is
    created by hard link and never clobbered; ``False`` means it already existed
    and the caller decides whether the existing content is acceptable.
    """
    if replace:
        os.replace(staged, target)
        return True
    try:
        os.link(staged, target)
    except FileExistsError:
        return False
    return True


def write_durable(path: Path, data: bytes, *, prefix: str, suffix: str = "", replace: bool) -> bool:
    """Stage ``data`` next to ``path`` and publish it; see ``publish_staged``."""
    with durable_staged_file(path.parent, data, prefix=prefix, suffix=suffix) as staged:
        return publish_staged(staged, path, replace=replace)
