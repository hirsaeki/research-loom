from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from misco_harness.models import RunManifest, WorkerResult


class WorkerExecutionError(RuntimeError):
    pass


class WorkerAdapter(ABC):
    @abstractmethod
    def run(self, manifest: RunManifest, context_pack: Path, run_dir: Path) -> WorkerResult:
        """Execute one bounded worker attempt and return a validated result."""
