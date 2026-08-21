from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from misco_harness.models import ContextPackManifest, RunManifest, WorkerResult
from misco_harness.trace_store import TraceStore, TraceStoreError, verify_hash
from misco_harness.workers.base import WorkerAdapter, WorkerExecutionError


@dataclass(frozen=True)
class RunExecution:
    manifest: RunManifest
    result: WorkerResult | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.result is not None


class RetryExhausted(WorkerExecutionError):
    def __init__(self, executions: list[RunExecution]):
        super().__init__(f"worker failed after {len(executions)} bounded attempts")
        self.executions = executions


class RunManager:
    def __init__(self, store: TraceStore):
        self.store = store

    def execute(self, manifest: RunManifest, context_pack: Path, adapter: WorkerAdapter) -> RunExecution:
        run_dir = self.store.create_run_dir(manifest.run_id)
        self.store.write_immutable(Path("runs") / manifest.run_id / "manifest.json", manifest)
        try:
            self._verify_context_pack(manifest, context_pack)
            result = adapter.run(manifest, context_pack, run_dir)
            if result.run_id != manifest.run_id:
                raise WorkerExecutionError("worker result run_id does not match the run manifest")
            self.store.write_immutable(Path("runs") / manifest.run_id / "worker_result.json", result)
            self.store.write_immutable(
                Path("runs") / manifest.run_id / "completion.json",
                {"run_id": manifest.run_id, "status": "COMPLETED", "attempt": manifest.attempt},
            )
            return RunExecution(manifest=manifest, result=result, error=None)
        except (OSError, TraceStoreError, ValueError, WorkerExecutionError) as error:
            message = f"{type(error).__name__}: {error}"
            self.store.write_immutable(
                Path("runs") / manifest.run_id / "completion.json",
                {"run_id": manifest.run_id, "status": "FAILED", "attempt": manifest.attempt, "error": message},
            )
            return RunExecution(manifest=manifest, result=None, error=message)

    def validate_context_pack(self, manifest: RunManifest, context_pack: Path) -> None:
        self._verify_context_pack(manifest, context_pack)

    def execute_bounded(
        self,
        attempts: list[tuple[RunManifest, Path]],
        adapter: WorkerAdapter,
        *,
        retry_limit: int,
    ) -> list[RunExecution]:
        if retry_limit < 0:
            raise ValueError("retry_limit must be non-negative")
        allowed_attempts = retry_limit + 1
        if not attempts or len(attempts) > allowed_attempts:
            raise ValueError(f"provide between 1 and {allowed_attempts} attempts")
        run_ids = [manifest.run_id for manifest, _ in attempts]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("each retry must have a new run_id")
        executions: list[RunExecution] = []
        for manifest, context_pack in attempts:
            execution = self.execute(manifest, context_pack, adapter)
            executions.append(execution)
            if execution.succeeded:
                return executions
        raise RetryExhausted(executions)

    def collect(self, manifest: RunManifest, context_pack: Path, result: WorkerResult) -> RunExecution:
        run_dir = self.store.root / "runs" / manifest.run_id
        if not run_dir.is_dir():
            raise WorkerExecutionError(f"planned run does not exist: {manifest.run_id}")
        if (run_dir / "abort.json").exists() or (run_dir / "superseded.json").exists():
            raise WorkerExecutionError(f"late result rejected for aborted or superseded Run {manifest.run_id}")
        self._verify_context_pack(manifest, context_pack)
        if result.run_id != manifest.run_id:
            raise WorkerExecutionError("collected result run_id does not match the run manifest")
        self.store.write_immutable(Path("runs") / manifest.run_id / "worker_result.json", result)
        self.store.write_immutable(
            Path("runs") / manifest.run_id / "completion.json",
            {"run_id": manifest.run_id, "status": "COMPLETED", "attempt": manifest.attempt},
        )
        return RunExecution(manifest=manifest, result=result, error=None)

    @staticmethod
    def _verify_context_pack(run_manifest: RunManifest, context_pack: Path) -> None:
        manifest_path = context_pack / "manifest.json"
        context = ContextPackManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if context.run_id != run_manifest.run_id:
            raise WorkerExecutionError("Context Pack run_id does not match Run Manifest")
        for reference in context.must_include:
            verify_hash(context_pack / reference.path, reference.sha256)
        for reference in context.retrieve_on_demand:
            verify_hash(Path(reference.path), reference.sha256)
