"""Process-local, closed workspace seeds for explicitly opted-in test fixtures."""

from __future__ import annotations

import atexit
import hashlib
import shutil
import tempfile
from functools import cache
from pathlib import Path
from threading import Lock

from plugins.local_application import LocalWorkspace


class WorkspaceTemplateCache:
    """Build each exact Config/EPS pair once; copy files, never live connections."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="loom-test-workspace-seeds-")
        self._root = Path(self._temporary.name)
        self._entries: dict[tuple[bytes, bytes], Path] = {}
        self._lock = Lock()

    def close(self):
        self._temporary.cleanup()

    def initialize(self, workspace: Path, config: Path, profiles: Path):
        config_bytes, profiles_bytes = config.read_bytes(), profiles.read_bytes()
        key = (hashlib.sha256(config_bytes).digest(), hashlib.sha256(profiles_bytes).digest())
        with self._lock:
            source = self._entries.get(key)
            if source is None:
                entry = Path(tempfile.mkdtemp(prefix="seed-", dir=self._root))
                # Initialize from exactly the bytes used for the key, even if the
                # caller subsequently changes its own input files.
                config_copy, profiles_copy = entry / "config.json", entry / "profiles.json"
                config_copy.write_bytes(config_bytes)
                profiles_copy.write_bytes(profiles_bytes)
                source = entry / "workspace"
                with LocalWorkspace.init(source, config_copy, profiles_copy):
                    pass
                # Publish only a fully initialized seed after all DBs/leases close.
                self._entries[key] = source
            # copytree refuses an existing destination and uses ordinary copies.
            # No hardlinks, shared SQLite connections, or writable shared test state.
            shutil.copytree(source, workspace)


@cache
def _process_cache():
    templates = WorkspaceTemplateCache()
    atexit.register(templates.close)
    return templates


def initialize_workspace_from_template(workspace: Path, config: Path, profiles: Path):
    _process_cache().initialize(workspace, config, profiles)
