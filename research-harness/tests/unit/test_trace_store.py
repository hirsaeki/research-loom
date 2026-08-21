from pathlib import Path

import pytest

from misco_harness.models import ResearchState
from misco_harness.trace_store import (
    HashMismatch,
    ImmutableArtifactExists,
    TraceStore,
    TraceStoreError,
    sha256_file,
    verify_hash,
)


def test_snapshot_history_is_immutable(tmp_path: Path) -> None:
    store = TraceStore(tmp_path)
    first = ResearchState(state_id="rs-1")
    second = ResearchState(state_id="rs-2", prior_snapshot_id="rs-1")
    store.snapshot("research", "rs-1", first)
    store.snapshot("research", "rs-2", second)
    with pytest.raises(ImmutableArtifactExists):
        store.snapshot("research", "rs-1", second)
    assert store.read_json("state/research/snapshots/rs-1.json")["state_id"] == "rs-1"


def test_hash_mismatch_is_detected(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    expected = sha256_file(source)
    verify_hash(source, expected)
    source.write_text("after", encoding="utf-8")
    with pytest.raises(HashMismatch):
        verify_hash(source, expected)


def test_trace_store_rejects_traversal_without_writing_outside_root(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / ".rh")
    outside = tmp_path / "escape.json"

    with pytest.raises(TraceStoreError):
        store.write_immutable("../escape.json", {"blocked": True})
    with pytest.raises(TraceStoreError):
        store.create_run_dir("../escape-run")

    assert not outside.exists()
