import sys
from pathlib import Path

import pytest

from misco_harness.models import (
    ArtifactRef,
    ContextPackManifest,
    Lane,
    RunManifest,
    WorkerResult,
)
from misco_harness.run_manager import RetryExhausted, RunManager
from misco_harness.trace_store import TraceStore
from misco_harness.workers import MockWorkerAdapter, SubprocessWorkerAdapter


def context_pack(tmp_path: Path, name: str, run_id: str) -> Path:
    pack = tmp_path / name
    pack.mkdir()
    manifest = ContextPackManifest(pack_id=name, run_id=run_id, event="QUESTION_FORMATION", lane=Lane.RESEARCH)
    (pack / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return pack


def run_manifest(run_id: str, attempt: int = 1) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        task_id="task-1",
        task_type="QUESTION_CANDIDATES",
        objective="Generate independent candidates",
        event="QUESTION_FORMATION",
        lane=Lane.RESEARCH,
        attempt=attempt,
    )


def test_mock_worker_is_deterministic_and_run_artifacts_are_immutable(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "store")
    manager = RunManager(store)
    adapter = MockWorkerAdapter(WorkerResult(run_id="template", observed=["candidate-a"]))
    execution = manager.execute(run_manifest("run-1"), context_pack(tmp_path, "pack-1", "run-1"), adapter)
    assert execution.succeeded
    assert store.read_json("runs/run-1/worker_result.json")["observed"] == ["candidate-a"]
    assert store.read_json("runs/run-1/completion.json")["status"] == "COMPLETED"


def test_bounded_retry_preserves_failed_run_and_uses_new_run_id(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "store")
    manager = RunManager(store)
    adapter = MockWorkerAdapter({"observed": ["ok"]}, fail_times=1)
    attempts = [
        (run_manifest("run-failed", 1), context_pack(tmp_path, "pack-failed", "run-failed")),
        (run_manifest("run-success", 2), context_pack(tmp_path, "pack-success", "run-success")),
    ]
    executions = manager.execute_bounded(attempts, adapter, retry_limit=1)
    assert [item.succeeded for item in executions] == [False, True]
    assert store.read_json("runs/run-failed/completion.json")["status"] == "FAILED"
    assert store.read_json("runs/run-success/completion.json")["status"] == "COMPLETED"
    assert (tmp_path / "store" / "runs" / "run-failed" / "manifest.json").is_file()


def test_retry_exhaustion_is_bounded(tmp_path: Path) -> None:
    manager = RunManager(TraceStore(tmp_path / "store"))
    adapter = MockWorkerAdapter({}, fail_times=2)
    attempts = [
        (run_manifest("run-1", 1), context_pack(tmp_path, "pack-1", "run-1")),
        (run_manifest("run-2", 2), context_pack(tmp_path, "pack-2", "run-2")),
    ]
    with pytest.raises(RetryExhausted) as caught:
        manager.execute_bounded(attempts, adapter, retry_limit=1)
    assert len(caught.value.executions) == 2


def test_subprocess_adapter_uses_structured_result_file(tmp_path: Path) -> None:
    worker_script = tmp_path / "worker.py"
    worker_script.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps({'schema_version': '0.1', 'run_id': sys.argv[3], "
        "'observed': ['subprocess'], 'derived': [], 'interpreted': [], 'counterevidence': [], 'unknown': [], "
        "'scope_limits': [], 'question_delta_candidate': [], 'next_evidence_request': [], "
        "'back_references': [], 'issues': []}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    manager = RunManager(TraceStore(tmp_path / "store"))
    adapter = SubprocessWorkerAdapter([sys.executable, str(worker_script)])
    execution = manager.execute(run_manifest("run-sub"), context_pack(tmp_path, "pack-sub", "run-sub"), adapter)
    assert execution.succeeded, execution.error
    assert execution.result is not None
    assert execution.result.observed == ["subprocess"]


def test_malformed_subprocess_output_cannot_commit_result(tmp_path: Path) -> None:
    worker_script = tmp_path / "bad_worker.py"
    worker_script.write_text(
        "import pathlib, sys\npathlib.Path(sys.argv[2]).write_text('{}', encoding='utf-8')\n",
        encoding="utf-8",
    )
    store = TraceStore(tmp_path / "store")
    execution = RunManager(store).execute(
        run_manifest("run-bad"), context_pack(tmp_path, "pack-bad", "run-bad"),
        SubprocessWorkerAdapter([sys.executable, str(worker_script)]),
    )
    assert not execution.succeeded
    assert not (tmp_path / "store" / "runs" / "run-bad" / "worker_result.json").exists()
    assert store.read_json("runs/run-bad/completion.json")["status"] == "FAILED"


def test_hash_mismatch_is_detected_before_worker_dispatch(tmp_path: Path) -> None:
    source = tmp_path / "retrieval.txt"
    source.write_text("before", encoding="utf-8")
    from misco_harness.trace_store import sha256_file
    pack = tmp_path / "pack-hash"
    pack.mkdir()
    context = ContextPackManifest(
        pack_id="pack-hash", run_id="run-hash", event="RESEARCH_RUN", lane=Lane.RESEARCH,
        retrieve_on_demand=[ArtifactRef(artifact_id="source", path=str(source), sha256=sha256_file(source))],
    )
    (pack / "manifest.json").write_text(context.model_dump_json(), encoding="utf-8")
    source.write_text("after", encoding="utf-8")
    adapter = MockWorkerAdapter({"observed": ["must not run"]})
    store = TraceStore(tmp_path / "store")
    execution = RunManager(store).execute(run_manifest("run-hash"), pack, adapter)
    assert not execution.succeeded
    assert "HashMismatch" in (execution.error or "")
    assert not (tmp_path / "store" / "runs" / "run-hash" / "worker_result.json").exists()
