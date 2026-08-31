from __future__ import annotations

from pathlib import Path

from .store import LocalExecutionStore


def bind_controlled_import_root(store: LocalExecutionStore, root: str | Path) -> None:
    """Bind one production workspace root to the existing controlled file reader.

    The underlying traversal, containment, symlink/reparse-point, regular-file,
    and bounded-read checks remain owned by LocalExecutionStore.
    """
    resolved = Path(root).resolve(strict=True)
    configured = tuple(getattr(store, "_allowed_import_roots", ()))
    if configured and configured != (resolved,):
        raise PermissionError("controlled file intake root is already bound")
    store._allowed_import_roots = (resolved,)


def read_controlled_file(
    store: LocalExecutionStore,
    source_path: str | Path,
    *,
    max_bytes: int,
) -> bytes:
    """Read through LocalExecutionStore's single controlled-intake implementation."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    return store._read_controlled_file(source_path, max_bytes=max_bytes)
