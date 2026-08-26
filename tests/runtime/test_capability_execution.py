from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

import rfc8785

from core.execution import (
    CanonicalCapabilityExecutionValidator,
    CapabilityExecutionError,
    CapabilityExecutionOutput,
    CapabilityExecutionService,
    CapabilityRegistry,
    ExecutionStyle,
    RunStatus,
)
from core.execution.testing import (
    AllowListedAuthorizationProvider,
    InMemoryExecutionTraceStore,
    InMemoryResourceProvider,
    StaticClock,
)
from core.runtime import (
    CapabilityNormalizationBoundary,
    LineageView,
    StateDeltaProposal,
    StateView,
)


ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "core/fixtures/capabilities/valid"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def refresh(document: dict, field: str) -> dict:
    body = deepcopy(document)
    body.pop(field, None)
    document[field] = "sha256:" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()
    return document


DESCRIPTOR = load("generic-capability-descriptor.json")
CONTEXT = load("generic-capability-context-pack.json")
INVOCATION = load("generic-capability-invocation.json")
HANDOFF = load("generic-capability-handoff.json")


class MutableStateProvider:
    def __init__(self, state: StateView) -> None:
        self.state = state

    def load_state_view(self, project_ref: str, lineage_ref: str) -> StateView:
        if (
            project_ref != self.state.project_ref
            or lineage_ref != self.state.lineage_ref
        ):
            raise KeyError((project_ref, lineage_ref))
        return self.state


def state_for_context(context: dict = CONTEXT) -> StateView:
    pin = context["pins"]["research_snapshot"]
    snapshot = {
        "id": pin["snapshot_id"],
        "revision": pin["revision"],
        "content_digest": pin["content_digest"],
        "mode": "virtual",
        "members": [],
    }
    lineage = LineageView(
        "LIN-1",
        "primary",
        pin["snapshot_id"],
        pin["content_digest"],
        pin["revision"],
        "virtual",
        project_config_ref="CFG-1",
        project_config_digest=context["pins"]["project_config"][
            "configuration_digest"
        ],
        effective_profile_set_ref="EPS-1",
        effective_profile_set_digest=context["pins"]["effective_profile_set"][
            "content_digest"
        ],
    )
    return StateView(
        context["project_id"],
        "LIN-1",
        snapshot,
        (),
        (),
        (),
        (lineage,),
        "LIN-1",
        "CFG-1",
        lineage.project_config_digest,
        "EPS-1",
        lineage.effective_profile_set_digest,
    )


class GenericNormalizer:
    def supports(
        self,
        capability_contract_id: str,
        function_id: str,
        contract_version: str,
    ) -> bool:
        return (
            capability_contract_id,
            function_id,
            contract_version,
        ) == ("fixture.research-support", "investigate", "1.0.0")

    def validate_extension(self, handoff, extension, context):
        return ()

    def normalize(self, handoff, extension, context):
        proposal = StateDeltaProposal(
            "SDP-EXEC-1",
            context["project_ref"],
            context["lineage_ref"],
            (handoff["handoff_id"],),
            (),
            (),
            "generic execution fixture",
            (),
            context["current_snapshot_ref"],
            context["current_snapshot_digest"],
            {"run_id": context["run_id"]},
        )
        return proposal.with_calculated_digest()


class Adapter:
    implementation_id = "plugin.fixture.research-support"
    implementation_version = "1.0.0"
    capability_id = "fixture.research-support"
    capability_version = "1.0.0"
    supported_functions = ("investigate",)
    supported_execution_modes = ("virtual",)
    execution_style = ExecutionStyle.MANAGED

    def __init__(self, handoff=None, hook=None, fail: bool = False) -> None:
        self.handoff = deepcopy(handoff or HANDOFF)
        self.hook = hook
        self.fail = fail
        self.cancelled: list[str] = []

    def execute(self, request):
        if self.hook:
            self.hook(request)
        if self.fail:
            raise RuntimeError("fixture adapter failure")
        return CapabilityExecutionOutput(deepcopy(self.handoff))

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


class ExternalAdapter(Adapter):
    execution_style = ExecutionStyle.EXTERNAL

    def execute(self, request):
        raise AssertionError("external adapter must not execute")


class CapabilityExecutionRuntimeTests(unittest.TestCase):
    def make_service(
        self,
        adapter,
        *,
        state=None,
        normalizers=None,
        auth: bool = True,
        descriptor=DESCRIPTOR,
        invocation=INVOCATION,
    ):
        registry = CapabilityRegistry()
        registry.register(adapter, descriptor)
        traces = InMemoryExecutionTraceStore()
        states = MutableStateProvider(state or state_for_context())
        authorization = AllowListedAuthorizationProvider(
            (invocation["runtime_authorization_evidence"]["authorization_digest"],)
            if auth
            else (),
            denied=not auth,
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
        return service, traces, states, registry

    def test_valid_managed_invocation_completes_and_returns_candidate_proposal(self):
        service, traces, _, _ = self.make_service(Adapter())
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)
        self.assertEqual(result.handoff_status, "valid")
        self.assertEqual(
            [event.to_status for event in traces.events_for("RUN-001")],
            [RunStatus.PREPARED, RunStatus.RUNNING, RunStatus.COMPLETED],
        )

    def test_external_prepare_collect_completes(self):
        service, _, _, _ = self.make_service(ExternalAdapter())
        prepared = service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(prepared.run.status, RunStatus.RUNNING)
        result = service.collect_external("RUN-001", HANDOFF)
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)

    def test_unknown_and_ambiguous_registry_bindings_fail_closed(self):
        registry = CapabilityRegistry()
        with self.assertRaises(CapabilityExecutionError) as cm:
            registry.resolve(
                "fixture.research-support",
                "1.0.0",
                "investigate",
                "virtual",
            )
        self.assertEqual(cm.exception.issue.code, "IMPLEMENTATION_NOT_FOUND")

        registry.register(Adapter(), DESCRIPTOR)
        registry.register(Adapter(), DESCRIPTOR)
        with self.assertRaises(CapabilityExecutionError) as cm:
            registry.resolve(
                "fixture.research-support",
                "1.0.0",
                "investigate",
                "virtual",
            )
        self.assertEqual(cm.exception.issue.code, "IMPLEMENTATION_AMBIGUOUS")

    def test_registry_registration_is_atomic_and_rejects_unsupported_modes(self):
        class LateInvalidFunctionAdapter(Adapter):
            supported_functions = ("investigate", "missing-function")

        registry = CapabilityRegistry()
        with self.assertRaises(CapabilityExecutionError) as cm:
            registry.register(LateInvalidFunctionAdapter(), DESCRIPTOR)
        self.assertEqual(cm.exception.issue.code, "DESCRIPTOR_INVALID")
        with self.assertRaises(CapabilityExecutionError) as cm:
            registry.resolve(
                "fixture.research-support",
                "1.0.0",
                "investigate",
                "virtual",
            )
        self.assertEqual(cm.exception.issue.code, "IMPLEMENTATION_NOT_FOUND")

        class UnsupportedModeAdapter(Adapter):
            supported_execution_modes = ("virtual", "not-declared")

        with self.assertRaises(CapabilityExecutionError) as cm:
            registry.register(UnsupportedModeAdapter(), DESCRIPTOR)
        self.assertEqual(cm.exception.issue.code, "DESCRIPTOR_INVALID")

    def test_invalid_descriptor_context_and_authorization_are_blocked_before_run(self):
        service, _, _, _ = self.make_service(Adapter())
        bad_descriptor = deepcopy(DESCRIPTOR)
        bad_descriptor["descriptor_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(CapabilityExecutionError):
            service.execute_managed(
                bad_descriptor,
                INVOCATION,
                CONTEXT,
                lineage_ref="LIN-1",
            )

        bad_context = deepcopy(CONTEXT)
        bad_context["context_pack_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(CapabilityExecutionError):
            service.execute_managed(
                DESCRIPTOR,
                INVOCATION,
                bad_context,
                lineage_ref="LIN-1",
            )

        denied, denied_traces, _, _ = self.make_service(Adapter(), auth=False)
        with self.assertRaises(CapabilityExecutionError) as cm:
            denied.execute_managed(
                DESCRIPTOR,
                INVOCATION,
                CONTEXT,
                lineage_ref="LIN-1",
            )
        self.assertEqual(cm.exception.issue.code, "AUTHORIZATION_DENIED")
        self.assertFalse(denied_traces.runs)

    def test_malformed_invocation_fails_before_state_provider_lookup(self):
        malformed = deepcopy(INVOCATION)
        malformed.pop("project_id")
        refresh(malformed, "invocation_digest")
        service, traces, _, _ = self.make_service(Adapter())
        with self.assertRaises(CapabilityExecutionError) as cm:
            service.execute_managed(
                DESCRIPTOR,
                malformed,
                CONTEXT,
                lineage_ref="LIN-1",
            )
        self.assertEqual(cm.exception.issue.code, "INVOCATION_INVALID")
        self.assertFalse(traces.runs)

    def test_stale_snapshot_before_execution_is_blocked(self):
        original = state_for_context()
        stale = replace(
            original,
            current_snapshot=dict(
                original.current_snapshot,
                content_digest="sha256:" + "9" * 64,
            ),
        )
        service, traces, _, _ = self.make_service(Adapter(), state=stale)
        with self.assertRaises(CapabilityExecutionError) as cm:
            service.execute_managed(
                DESCRIPTOR,
                INVOCATION,
                CONTEXT,
                lineage_ref="LIN-1",
            )
        self.assertEqual(cm.exception.issue.code, "STALE_STATE")
        self.assertFalse(traces.runs)

    def test_adapter_failure_marks_run_failed(self):
        service, _, _, _ = self.make_service(Adapter(fail=True))
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.issues[0].code, "EXECUTION_FAILED")

    def test_trace_capture_failure_marks_run_failed(self):
        service, traces, _, _ = self.make_service(Adapter())

        def fail_store(_handoff):
            raise ValueError("immutable Handoff collision")

        traces.store_handoff = fail_store
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.issues[0].code, "EXECUTION_FAILED")

    def test_mismatched_run_and_virtual_empirical_handoff_fail_but_remain_auditable(self):
        mismatch = deepcopy(HANDOFF)
        mismatch["run_id"] = "RUN-OTHER"
        refresh(mismatch, "handoff_digest")
        service, traces, _, _ = self.make_service(Adapter(mismatch))
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertIn(mismatch["handoff_id"], traces.handoffs)

        empirical = deepcopy(HANDOFF)
        empirical["outputs"]["observations"][0]["epistemic_mode"] = "empirical"
        refresh(empirical, "handoff_digest")
        service, _, _, _ = self.make_service(Adapter(empirical))
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.issues[0].code, "CAP-MODE-001")

    def test_handoff_implementation_provenance_must_match_pinned_adapter(self):
        mismatch = deepcopy(HANDOFF)
        mismatch["provenance"]["implementation_id"] = "plugin.other"
        refresh(mismatch, "handoff_digest")
        service, traces, _, _ = self.make_service(Adapter(mismatch))
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.issues[0].code, "CAP-HANDOFF-PROVENANCE-001")
        self.assertIn("HND-001", traces.handoffs)

    def test_rejected_handoff_is_completed_but_never_normalized(self):
        rejected = deepcopy(HANDOFF)
        rejected["validation"] = {
            "status": "rejected",
            "issues": [
                {
                    "code": "FIXTURE_REJECT",
                    "severity": "error",
                    "message": "fixture rejection",
                }
            ],
        }
        refresh(rejected, "handoff_digest")
        service, traces, _, _ = self.make_service(Adapter(rejected))
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNone(result.state_delta_proposal)
        self.assertEqual(result.issues[0].code, "HANDOFF_REJECTED")
        self.assertIn(rejected["handoff_id"], traces.handoffs)

    def test_partial_handoff_preserves_issues_and_normalizes(self):
        partial = deepcopy(HANDOFF)
        partial["validation"] = {
            "status": "partial",
            "issues": [
                {
                    "code": "FIXTURE_GAP",
                    "severity": "warning",
                    "message": "gap remains",
                }
            ],
        }
        refresh(partial, "handoff_digest")
        service, _, _, _ = self.make_service(Adapter(partial))
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.handoff_status, "partial")
        self.assertIsNotNone(result.state_delta_proposal)

    def test_head_change_during_execution_keeps_handoff_and_rejects_stale_normalization(self):
        holder = {}

        def advance(_request):
            state = holder["states"].state
            holder["states"].state = replace(
                state,
                current_snapshot=dict(
                    state.current_snapshot,
                    id="SNP-2",
                    content_digest="sha256:" + "8" * 64,
                ),
            )

        adapter = Adapter(hook=advance)
        service, traces, states, _ = self.make_service(adapter)
        holder["states"] = states
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNone(result.state_delta_proposal)
        self.assertEqual(result.issues[0].code, "STALE_STATE")
        self.assertIn("HND-001", traces.handoffs)

    def test_abort_keeps_late_external_result_diagnostic_only(self):
        adapter = ExternalAdapter()
        service, traces, _, _ = self.make_service(adapter)
        service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        aborted = service.abort("RUN-001")
        self.assertEqual(aborted.status, RunStatus.ABORTED)
        self.assertEqual(adapter.cancelled, ["RUN-001"])
        result = service.collect_external("RUN-001", HANDOFF)
        self.assertEqual(result.run.status, RunStatus.ABORTED)
        self.assertIsNone(result.state_delta_proposal)
        self.assertTrue(traces.diagnostics)
        self.assertFalse(traces.handoffs)

    def test_abort_during_managed_execution_cannot_be_overwritten_by_late_result(self):
        holder = {}

        def abort_during_execute(_request):
            holder["service"].abort("RUN-001")

        adapter = Adapter(hook=abort_during_execute)
        service, traces, _, _ = self.make_service(adapter)
        holder["service"] = service
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.ABORTED)
        self.assertIsNone(result.state_delta_proposal)
        self.assertTrue(
            any(kind == "late_or_racing_result" for _, kind, _ in traces.diagnostics)
        )
        self.assertEqual(
            [event.to_status for event in traces.events_for("RUN-001")],
            [RunStatus.PREPARED, RunStatus.RUNNING, RunStatus.ABORTED],
        )

    def test_retry_uses_new_run_id_and_explicit_parent_attempt(self):
        service, _, _, _ = self.make_service(ExternalAdapter())
        service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        service.abort("RUN-001")

        retry = deepcopy(INVOCATION)
        retry["invocation_id"] = "INV-002"
        retry["run_id"] = "RUN-002"
        retry["trace"]["trace_id"] = "TRACE-002"
        retry["trace"]["parent_run_id"] = "RUN-001"
        refresh(retry, "invocation_digest")
        prepared = service.prepare_external(
            DESCRIPTOR,
            retry,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(prepared.run.run_id, "RUN-002")
        self.assertEqual(prepared.run.parent_run_id, "RUN-001")
        self.assertEqual(prepared.run.attempt, 2)

    def test_run_id_and_invocation_identity_collisions_are_rejected(self):
        service, _, _, _ = self.make_service(ExternalAdapter())
        service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        with self.assertRaises((ValueError, CapabilityExecutionError)):
            service.prepare_external(
                DESCRIPTOR,
                INVOCATION,
                CONTEXT,
                lineage_ref="LIN-1",
            )

        changed = deepcopy(INVOCATION)
        changed["run_id"] = "RUN-COLLISION"
        refresh(changed, "invocation_digest")
        with self.assertRaises((ValueError, CapabilityExecutionError)):
            service.prepare_external(
                DESCRIPTOR,
                changed,
                CONTEXT,
                lineage_ref="LIN-1",
            )

    def test_bounded_resource_access_denies_out_of_context_reference(self):
        class ReadingAdapter(Adapter):
            def execute(self, request):
                request.resources.read("NOT-IN-CONTEXT")
                return CapabilityExecutionOutput(HANDOFF)

        service, _, _, _ = self.make_service(ReadingAdapter())
        result = service.execute_managed(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.issues[0].code, "RESOURCE_DENIED")

    def test_duplicate_guard_identity_fails_closed(self):
        duplicate = deepcopy(CONTEXT)
        duplicate["project_constraints"]["prohibitions"][0]["guard_id"] = (
            duplicate["project_constraints"]["requirements"][0]["guard_id"]
        )
        refresh(duplicate, "context_pack_digest")
        validator = CanonicalCapabilityExecutionValidator()
        with self.assertRaises(CapabilityExecutionError) as cm:
            validator.validate_documents(DESCRIPTOR, INVOCATION, duplicate)
        self.assertEqual(cm.exception.issue.code, "CAP-CONTEXT-IDENTITY-001")


class FutureCapabilityNormalizer(GenericNormalizer):
    def supports(
        self,
        capability_contract_id: str,
        function_id: str,
        contract_version: str,
    ) -> bool:
        return (
            capability_contract_id,
            function_id,
            contract_version,
        ) == ("fixture.future-execution", "evaluate", "9.9.0")


class FutureCapabilityAdapter(Adapter):
    implementation_id = "plugin.fixture.future-execution"
    implementation_version = "0.1.0"
    capability_id = "fixture.future-execution"
    capability_version = "9.9.0"
    supported_functions = ("evaluate",)


class FutureCapabilityExecutionTests(unittest.TestCase):
    def test_future_capability_runs_without_generic_runtime_changes(self):
        descriptor = deepcopy(DESCRIPTOR)
        descriptor["capability_id"] = "fixture.future-execution"
        descriptor["capability_version"] = "9.9.0"
        descriptor["declared_functions"][0]["function_id"] = "evaluate"
        refresh(descriptor, "descriptor_digest")

        invocation = deepcopy(INVOCATION)
        invocation["invocation_id"] = "INV-FUTURE"
        invocation["run_id"] = "RUN-FUTURE"
        invocation["capability"] = {
            "capability_id": descriptor["capability_id"],
            "capability_version": descriptor["capability_version"],
            "descriptor_digest": descriptor["descriptor_digest"],
            "function_id": "evaluate",
        }
        invocation["runtime_authorization_evidence"]["capability_id"] = (
            descriptor["capability_id"]
        )
        invocation["runtime_authorization_evidence"]["function_id"] = "evaluate"
        invocation["trace"]["trace_id"] = "TRACE-FUTURE"
        refresh(invocation, "invocation_digest")

        handoff = deepcopy(HANDOFF)
        handoff["handoff_id"] = "HND-FUTURE-EXEC"
        handoff["invocation_id"] = invocation["invocation_id"]
        handoff["run_id"] = invocation["run_id"]
        handoff["capability"] = deepcopy(invocation["capability"])
        handoff["input_pins"]["invocation_digest"] = invocation[
            "invocation_digest"
        ]
        handoff["provenance"]["trace_id"] = "TRACE-FUTURE"
        handoff["provenance"]["implementation_id"] = (
            FutureCapabilityAdapter.implementation_id
        )
        handoff["provenance"]["implementation_version"] = (
            FutureCapabilityAdapter.implementation_version
        )
        handoff["provenance"]["input_content_digests"] = [
            descriptor["descriptor_digest"],
            CONTEXT["context_pack_digest"],
            invocation["invocation_digest"],
        ]
        refresh(handoff, "handoff_digest")

        adapter = FutureCapabilityAdapter(handoff)
        registry = CapabilityRegistry()
        registry.register(adapter, descriptor)
        traces = InMemoryExecutionTraceStore()
        state = MutableStateProvider(state_for_context())
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
            state,
            authorization,
            resources,
            CapabilityNormalizationBoundary((FutureCapabilityNormalizer(),)),
            StaticClock(),
        )
        result = service.execute_managed(
            descriptor,
            invocation,
            CONTEXT,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)
        self.assertEqual(result.run.capability_id, "fixture.future-execution")


class DependencyBoundaryTests(unittest.TestCase):
    def test_execution_core_has_no_capability_specific_or_sqlite_dependency(self):
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "core/execution").glob("*.py")
        )
        for forbidden in (
            "import sqlite3",
            "plugins.sqlite",
            "survey",
            "delphi",
            "case_study",
            "desktop_research",
            "StateTransitionService",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
