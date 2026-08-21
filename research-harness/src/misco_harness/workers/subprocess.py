from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from misco_harness.models import RunManifest, WorkerResult
from misco_harness.workers.base import WorkerAdapter, WorkerExecutionError


class SubprocessWorkerAdapter(WorkerAdapter):
    def __init__(self, command: Sequence[str], *, timeout_seconds: float = 300):
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("command must be a non-empty argument sequence")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def run(self, manifest: RunManifest, context_pack: Path, run_dir: Path) -> WorkerResult:
        result_path = run_dir / "worker_result.pending.json"
        arguments = [*self.command, str(context_pack), str(result_path), manifest.run_id]
        try:
            completed = subprocess.run(
                arguments,
                cwd=run_dir,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkerExecutionError(f"worker process could not complete: {error}") from error
        if completed.returncode != 0:
            raise WorkerExecutionError(f"worker exited with code {completed.returncode}")
        if not result_path.is_file():
            raise WorkerExecutionError("worker did not produce its structured result file")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            result = WorkerResult.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise WorkerExecutionError(f"worker result failed validation: {error}") from error
        finally:
            result_path.unlink(missing_ok=True)
        if result.run_id != manifest.run_id:
            raise WorkerExecutionError(
                f"worker result run_id {result.run_id!r} does not match manifest {manifest.run_id!r}"
            )
        return result
