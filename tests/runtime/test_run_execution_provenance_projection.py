from __future__ import annotations

from core.execution import CapabilityRunRecord, RunStatus
from plugins.local_application.run_inspection_facade import _run_projection


def test_run_projection_exposes_harness_owned_execution_trace() -> None:
    run = CapabilityRunRecord(
        run_id="RUN-CHILD",
        invocation_id="INV-CHILD",
        invocation_digest="sha256:" + "1" * 64,
        capability_id="desktop-research",
        capability_version="0.1.0",
        descriptor_digest="sha256:" + "2" * 64,
        implementation_id="plugin.desktop-research.external",
        implementation_version="0.1.0",
        function_id="investigate",
        execution_mode="real",
        context_pack_id="CTX-CHILD",
        context_pack_digest="sha256:" + "3" * 64,
        project_ref="PRJ-1",
        lineage_ref="LIN-1",
        snapshot_ref="SNP-1",
        snapshot_digest="sha256:" + "4" * 64,
        attempt=2,
        parent_run_id="RUN-PARENT",
        status=RunStatus.RUNNING,
        prepared_at="2026-09-03T00:00:00Z",
        started_at="2026-09-03T00:00:01Z",
        provenance={"trace_id": "TRACE-CHILD"},
    )

    projected = _run_projection(run)

    assert projected["execution_provenance"] == {"trace_id": "TRACE-CHILD"}
    assert projected["parent_run_id"] == "RUN-PARENT"
