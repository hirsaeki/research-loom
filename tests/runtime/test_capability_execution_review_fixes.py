from __future__ import annotations

from copy import deepcopy
import unittest

from core.execution import (
    CapabilityExecutionError,
    CapabilityExecutionService,
    CapabilityRegistry,
    RunStatus,
)
from core.execution.testing import (
    AllowListedAuthorizationProvider,
    InMemoryExecutionTraceStore,
    InMemoryResourceProvider,
    StaticClock,
)
from core.runtime import CapabilityNormalizationBoundary
from test_capability_execution import (
    Adapter,
    CONTEXT,
    DESCRIPTOR,
    ExternalAdapter,
    GenericNormalizer,
    HANDOFF,
    INVOCATION,
    MutableStateProvider,
    refresh,
    state_for_context,
)


class DisappearingStateProvider:
    """Resolve preflight once, then simulate lineage/state disappearance."""

    def __init__(self) -> None:
        self.state = state_for_context()
        self.calls = 0

    def load_state_view(self, project_ref: str, lineage_ref: str):
        self.calls += 1
        if self.calls == 1:
            if (
                project_ref != self.state.project_ref
                or lineage_ref != self.state.lineage_ref
            ):
                raise KeyError((project_ref, lineage_ref))
            return self.state
        raise KeyError((project_ref, lineage_ref))


class MisleadingStaleNormalizer(GenericNormalizer):
    def validate_extension(self, handoff, extension, context):
        return ("stale-looking capability-specific extension validation error",)


class CancelFailingExternalAdapter(ExternalAdapter):
    def cancel(self, run_id: str) -> None:
        raise RuntimeError(f"cancel failed for {run_id}")


class CapabilityExecutionReviewFixTests(unittest.TestCase):
    def make_service(
        self,
        adapter,
        *,
        state_provider=None,
        normalizers=None,
        invocation=INVOCATION,
    ):
        registry = CapabilityRegistry()
        registry.register(adapter, DESCRIPTOR)
        traces = InMemoryExecutionTraceStore()
        states = state_provider or MutableStateProvider(state_for_context())
        authorization = AllowListedAuthorizationProvider(
            (
                invocation["runtime_authorization_evidence"][
                    "authorization_digest"
                ],
            )
        )
        resources = InMemoryResourceProvider(
            {
                ref: b"fixture"
                for ref in invocation["runtime_authorization_evidence"][
                    "resource_reference_ids"
                ]
            }
        )
        service = CapabilityExecutionService(
            registry,
            traces,
            states,
            authorization,
            resources,
            CapabilityNormalizationBoundary(
                tuple(normalizers or (GenericNormalizer(),))
            ),
            StaticClock(),
        )
        return service, traces, states

    def test_retry_rejects_live_parent_run(self):
        service, traces, _ = self.make_service(ExternalAdapter())
        service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )

        retry = deepcopy(INVOCATION)
        retry["invocation_id"] = "INV-LIVE-RETRY"
        retry["run_id"] = "RUN-LIVE-RETRY"
        retry["trace"]["trace_id"] = "TRACE-LIVE-RETRY"
        retry["trace"]["parent_run_id"] = "RUN-001"
        refresh(retry, "invocation_digest")

        with self.assertRaises(CapabilityExecutionError) as cm:
            service.prepare_external(
                DESCRIPTOR,
                retry,
                CONTEXT,
                lineage_ref="LIN-1",
            )
        self.assertEqual(cm.exception.issue.code, "INVOCATION_INVALID")
        self.assertIsNone(traces.load_run("RUN-LIVE-RETRY"))
        self.assertEqual(traces.load_run("RUN-001").status, RunStatus.RUNNING)

    def test_completed_run_returns_stale_issue_when_state_no_longer_resolves(self):
        states = DisappearingStateProvider()
        service, traces, _ = self.make_service(
            Adapter(),
            state_provider=states,
        )
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )

        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(result.handoff_ref, HANDOFF["handoff_id"])
        self.assertIsNone(result.state_delta_proposal)
        self.assertEqual(result.issues[0].code, "STALE_STATE")
        self.assertIn(HANDOFF["handoff_id"], traces.handoffs)

    def test_normalizer_stale_word_does_not_fake_stale_state(self):
        service, _, _ = self.make_service(
            Adapter(),
            normalizers=(MisleadingStaleNormalizer(),),
        )
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )

        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNone(result.state_delta_proposal)
        self.assertEqual(result.issues[0].code, "NORMALIZATION_REJECTED")

    def test_abort_records_best_effort_cancellation_failure(self):
        service, traces, _ = self.make_service(CancelFailingExternalAdapter())
        service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        aborted = service.abort("RUN-001")

        self.assertEqual(aborted.status, RunStatus.ABORTED)
        diagnostics = [
            payload
            for run_id, kind, payload in traces.diagnostics
            if run_id == "RUN-001" and kind == "cancellation_failed"
        ]
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("cancel failed for RUN-001", diagnostics[0]["reason"])


if __name__ == "__main__":
    unittest.main()
