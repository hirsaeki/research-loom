from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from misco_harness.models import RunManifest, WorkerResult
from misco_harness.workers.base import WorkerAdapter, WorkerExecutionError


class MockWorkerAdapter(WorkerAdapter):
    def __init__(self, result: WorkerResult | dict[str, object], *, fail_times: int = 0):
        self._result = result
        self._remaining_failures = fail_times

    def run(self, manifest: RunManifest, context_pack: Path, run_dir: Path) -> WorkerResult:
        if self._remaining_failures:
            self._remaining_failures -= 1
            raise WorkerExecutionError("configured mock worker failure")
        if not (context_pack / "manifest.json").is_file():
            raise WorkerExecutionError("Context Pack manifest is missing")
        if isinstance(self._result, WorkerResult):
            payload = self._result.model_dump(mode="python")
        else:
            payload = deepcopy(self._result)
        payload["run_id"] = manifest.run_id
        return WorkerResult.model_validate(payload)


def discovery_mock_result(task_type: str, run_id: str, *, current_snapshot_id: str | None = None) -> WorkerResult:
    """Deterministic fixtures kept behind the explicitly selected mock backend."""
    if task_type == "INDEPENDENT_QUESTION_CANDIDATES":
        return WorkerResult(
            run_id=run_id, observed=["Mock inputs bounded"], interpreted=["Mock candidate generated"],
            counterevidence=["Mock feasibility not tested"], unknown=["Mock source availability"],
            scope_limits=["Mock question formation only"], question_overlaps=["Mock overlap"],
            evidence_gap_hypotheses=[{"gap_id": "mock-gap-q", "hypothesis": "Mock sources may be sparse", "why_material": "Mock feasibility is unknown"}],
            question_delta_candidate=[{
                "proposal_id": "mock-independent-question",
                "question": "Mock independent question",
                "reason": "deterministic mock formation",
            }],
            back_references=["theme", "expectations", "harness-contract", "constitution"],
        )
    if current_snapshot_id is None:
        raise WorkerExecutionError("mock task requires the current Research State snapshot")
    if task_type == "SEED_COMPARISON":
        return WorkerResult(
            run_id=run_id, observed=["Mock snapshot compared with Seed"], derived=["Mock comparison produced"],
            interpreted=["Mock baseline proposal prepared"], counterevidence=["Mock Seed bias"],
            unknown=["Mock human preference"], scope_limits=["No baseline adopted"], question_overlaps=["Mock partial overlap"],
            evidence_gap_hypotheses=[{"gap_id": "mock-gap-s", "hypothesis": "Mock context boundary is unknown", "why_material": "Could change mock scope"}],
            question_delta_candidate=[{
                "proposal_id": "mock-baseline", "question": "Mock independent question",
                "rationale": "deterministic mock comparison", "uncertainty": ["Mock human preference"],
                "scope_limits": ["Mock mode only"], "overlaps": ["Mock partial overlap"],
                "evidence_gap_hypotheses": [{"gap_id": "mock-gap-s", "hypothesis": "Mock context boundary is unknown", "why_material": "Could change mock scope"}],
            }], back_references=[current_snapshot_id, "rq-seed"],
        )
    return WorkerResult(
        run_id=run_id, observed=["Mock approved Question loaded"], derived=["Mock research plan prepared"],
        interpreted=["Mock protocol candidate"], counterevidence=["No real sources retrieved"],
        unknown=["Real source coverage"], scope_limits=["Mock preparation only"],
        back_references=[current_snapshot_id, "harness-contract", "constitution"],
    )
