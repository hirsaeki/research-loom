"""Locate resources shipped with the repository (#496).

Profile, Project and Core contracts, schemas and catalogs live next to the code
in the repository tree. Every module that reads one resolves its path here, so a
change in how the code is installed or packaged moves one place, not twenty.

The project is installed in editable mode (`uv sync`), so `core` is imported
from the checkout and the root below is the repository. A standalone wheel that
does not ship with the repository is not a supported install.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]


def resource_path(relative: str) -> Path:
    """Absolute path of a repository resource, given as a POSIX path from the repository root."""
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"resource path must be relative and inside the repository: {relative!r}")
    return REPOSITORY_ROOT.joinpath(*path.parts)
