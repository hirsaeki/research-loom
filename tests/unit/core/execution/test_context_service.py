"""Characterization tests for ``core.execution.context_service`` (#507).

They pin how the Context-extension ``CapabilityExecutionService`` prepares,
executes and collects Runs: the extension preflight and storage order (the extension is stored only after
authorization and retry checks pass), the
failure codes and messages it raises, retry/parent handling, and the
collection-time extension check.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import rfc8785

from core.execution.context_extensions import CapabilityContextExtensionRegistry
from core.execution.context_service import (
    CapabilityExecutionRequestWithContext,
    CapabilityExecutionService,
)
from core.execution.models import (
    CapabilityExecutionError,
    CapabilityExecutionOutput,
    CapabilityExecutionRequest,
    ExecutionIssue,
    ExecutionStyle,
    RunStatus,
)
from core.execution.registry import CapabilityRegistry
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
from plugins.local_execution_store.context_extensions import (
    LocalCapabilityContextExtensionStore,
)

ROOT = Path(__file__).resolve().parents[4]
FIX = ROOT / "core/fixtures/capabilities/valid"
DESCRIPTOR = json.loads((FIX / "generic-capability-descriptor.json").read_text(encoding="utf-8"))
CONTEXT = json.loads((FIX / "generic-capability-context-pack.json").read_text(encoding="utf-8"))
INVOCATION = json.loads((FIX / "generic-capability-invocation.json").read_text(encoding="utf-8"))
HANDOFF = json.loads((FIX / "generic-capability-handoff.json").read_text(encoding="utf-8"))
EXTENSION = {"extension_type": "fixture", "value": 1}
STORE_KEY = ("fixture.research-support", "1.0.0", "investigate", "CTX-001")


def refresh(document: dict, field: str) -> dict:
    body = deepcopy(document)
    body.pop(field, None)
    document[field] = "sha256:" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()
    return document


def retry_invocation(*, run_id: str = "RUN-002", parent: str = "RUN-001") -> dict:
    retry = deepcopy(INVOCATION)
    retry["invocation_id"] = f"INV-{run_id}"
    retry["run_id"] = run_id
    retry["trace"]["trace_id"] = f"TRACE-{run_id}"
    retry["trace"]["parent_run_id"] = parent
    return refresh(retry, "invocation_digest")


class StateProvider:
    def __init__(self) -> None:
        pin = CONTEXT["pins"]["research_snapshot"]
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
            project_config_digest=CONTEXT["pins"]["project_config"]["configuration_digest"],
            effective_profile_set_ref="EPS-1",
            effective_profile_set_digest=CONTEXT["pins"]["effective_profile_set"]["content_digest"],
        )
        self.state = StateView(
            CONTEXT["project_id"],
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

    def load_state_view(self, project_ref, lineage_ref):
        if project_ref != self.state.project_ref or lineage_ref != self.state.lineage_ref:
            raise KeyError((project_ref, lineage_ref))
        return self.state


class ManagedAdapter:
    implementation_id = "plugin.fixture.research-support"
    implementation_version = "1.0.0"
    capability_id = "fixture.research-support"
    capability_version = "1.0.0"
    supported_functions = ("investigate",)
    supported_execution_modes = ("virtual",)
    execution_style = ExecutionStyle.MANAGED
    requires_context_extension = False

    def __init__(self, raises: BaseException | None = None) -> None:
        self.raises = raises
        self.requests: list[CapabilityExecutionRequest] = []

    def execute(self, request):
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return CapabilityExecutionOutput(deepcopy(HANDOFF))

    def cancel(self, run_id):
        pass


class ExternalAdapter(ManagedAdapter):
    execution_style = ExecutionStyle.EXTERNAL

    def __init__(self, *, requires: bool = True) -> None:
        super().__init__()
        self.requires_context_extension = requires

    def execute(self, request):
        raise AssertionError("external adapter must not execute")


class Validator:
    def __init__(self, issues=()) -> None:
        self.issues = tuple(issues)
        self.seen: list = []

    def supports(self, capability_id, capability_version, function_id):
        return (capability_id, capability_version, function_id) == STORE_KEY[:3]

    def validate(self, descriptor, invocation, context_pack, extension, state):
        self.seen.append(extension)
        return self.issues


class Store:
    def __init__(self, raises: BaseException | None = None) -> None:
        self.items: dict = {}
        self.raises = raises

    def store(self, capability_id, capability_version, function_id, context_pack_id, extension):
        if self.raises is not None:
            raise self.raises
        self.items[(capability_id, capability_version, function_id, context_pack_id)] = extension
        return "fixture-ref"

    def load(self, capability_id, capability_version, function_id, context_pack_id):
        return self.items.get((capability_id, capability_version, function_id, context_pack_id))


class Normalizer:
    def supports(self, capability_contract_id, function_id, contract_version):
        return (capability_contract_id, function_id, contract_version) == (
            "fixture.research-support",
            "investigate",
            "1.0.0",
        )

    def validate_extension(self, handoff, extension, context):
        return ()

    def normalize(self, handoff, extension, context):
        return StateDeltaProposal(
            "SDP-CTX",
            context["project_ref"],
            context["lineage_ref"],
            (handoff["handoff_id"],),
            (),
            (),
            "context service fixture",
            (),
            context["current_snapshot_ref"],
            context["current_snapshot_digest"],
            {"run_id": context["run_id"]},
        ).with_calculated_digest()


def make_service(
    adapter,
    *,
    validators=None,
    store: Store | None = None,
    use_store: bool = True,
    auth: bool = True,
    traces: InMemoryExecutionTraceStore | None = None,
    registry: CapabilityRegistry | None = None,
    default_registry: bool = False,
):
    if registry is None:
        registry = CapabilityRegistry()
        registry.register(adapter, DESCRIPTOR)
    traces = traces if traces is not None else InMemoryExecutionTraceStore()
    if use_store and store is None:
        store = Store()
    evidence = INVOCATION["runtime_authorization_evidence"]
    kwargs = {}
    if not default_registry:
        kwargs["context_extension_registry"] = CapabilityContextExtensionRegistry(
            (Validator(),) if validators is None else validators
        )
    service = CapabilityExecutionService(
        registry,
        traces,
        StateProvider(),
        AllowListedAuthorizationProvider(
            (evidence["authorization_digest"],) if auth else (), denied=not auth
        ),
        InMemoryResourceProvider({ref: b"fixture" for ref in evidence["resource_reference_ids"]}),
        CapabilityNormalizationBoundary((Normalizer(),)),
        StaticClock(),
        context_extension_store=store if use_store else None,
        **kwargs,
    )
    return service, traces, store, registry


class RequestWithContextTests(unittest.TestCase):
    def test_is_a_capability_execution_request_with_optional_extension(self):
        self.assertTrue(
            issubclass(CapabilityExecutionRequestWithContext, CapabilityExecutionRequest)
        )
        service, traces, _, _ = make_service(ManagedAdapter())
        service.execute_managed(DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1")
        run = traces.runs["RUN-001"]
        request = CapabilityExecutionRequestWithContext(run, {}, {}, {}, None)
        self.assertIsNone(request.context_extension)
        self.assertIsNotNone(request.artifacts)


class ExecuteManagedTests(unittest.TestCase):
    def test_success_without_extension_passes_none_and_completes(self):
        adapter = ManagedAdapter()
        service, traces, store, _ = make_service(adapter)
        result = service.execute_managed(DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1")
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)
        self.assertEqual(result.issues, ())
        (request,) = adapter.requests
        self.assertIsInstance(request, CapabilityExecutionRequestWithContext)
        self.assertIsNone(request.context_extension)
        self.assertEqual(store.items, {})
        events = traces.events_for("RUN-001")
        self.assertEqual(
            [event.to_status for event in events],
            [RunStatus.PREPARED, RunStatus.RUNNING, RunStatus.COMPLETED],
        )
        self.assertEqual(
            events[0].reason,
            "validated immutable execution documents and capability Context extension",
        )
        self.assertEqual(events[1].reason, "managed execution started")

    def test_success_with_extension_stores_and_passes_a_copy(self):
        adapter = ManagedAdapter()
        validator = Validator()
        service, _, store, _ = make_service(adapter, validators=(validator,))
        extension = deepcopy(EXTENSION)
        result = service.execute_managed(
            DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1", context_extension=extension
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(validator.seen, [EXTENSION])
        self.assertEqual(store.items, {STORE_KEY: EXTENSION})
        self.assertIsNot(store.items[STORE_KEY], extension)
        (request,) = adapter.requests
        self.assertEqual(request.context_extension, EXTENSION)
        self.assertIsNot(request.context_extension, extension)
        self.assertIsNot(request.context_extension, store.items[STORE_KEY])

    def test_adapter_execution_error_fails_run_with_its_issue(self):
        error = CapabilityExecutionError("FIXTURE-CODE", "fixture said no", retryable=True)
        service, traces, _, _ = make_service(ManagedAdapter(raises=error))
        result = service.execute_managed(DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1")
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(result.issues, (ExecutionIssue("FIXTURE-CODE", "fixture said no", True),))
        self.assertEqual(traces.runs["RUN-001"].status, RunStatus.FAILED)

    def test_unexpected_adapter_exception_is_retryable_execution_failure(self):
        service, _, _, _ = make_service(ManagedAdapter(raises=RuntimeError("boom")))
        result = service.execute_managed(DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1")
        self.assertEqual(result.run.status, RunStatus.FAILED)
        self.assertEqual(
            result.issues,
            (ExecutionIssue("EXECUTION_FAILED", "capability adapter failed: boom", True),),
        )

    def test_external_adapter_is_rejected_for_managed_execution(self):
        service, traces, _, _ = make_service(ExternalAdapter(requires=False))
        with self.assertRaises(CapabilityExecutionError) as cm:
            service.execute_managed(DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1")
        self.assertEqual(cm.exception.issue.code, "IMPLEMENTATION_NOT_FOUND")
        self.assertEqual(cm.exception.issue.message, "resolved adapter is external, not managed")
        self.assertFalse(traces.runs)


class PreparePreflightTests(unittest.TestCase):
    def assert_rejected(self, service, traces, code, message, **kwargs):
        with self.assertRaises(CapabilityExecutionError) as cm:
            service.prepare_external(DESCRIPTOR, INVOCATION, CONTEXT, **kwargs)
        self.assertEqual(cm.exception.issue.code, code)
        self.assertEqual(cm.exception.issue.message, message)
        self.assertFalse(traces.runs)
        return cm.exception

    def test_success_records_run_fields_and_running_status(self):
        service, traces, store, _ = make_service(ExternalAdapter())
        prepared = service.prepare_external(
            DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1", context_extension=EXTENSION
        )
        run = prepared.run
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertEqual(prepared.invocation_digest, INVOCATION["invocation_digest"])
        self.assertEqual(prepared.context_pack_digest, CONTEXT["context_pack_digest"])
        self.assertEqual(run.attempt, 1)
        self.assertIsNone(run.parent_run_id)
        self.assertEqual(run.snapshot_ref, "SNP-1")
        self.assertEqual(run.lineage_ref, "LIN-1")
        self.assertEqual(run.provenance, {"trace_id": "TRACE-001"})
        self.assertEqual(run.started_at, "2026-08-26T00:00:00Z")
        self.assertIn(DESCRIPTOR["descriptor_digest"], traces.descriptors)
        self.assertIn("INV-001", traces.invocations)
        self.assertIn("CTX-001", traces.contexts)
        self.assertEqual(
            traces.events_for("RUN-001")[1].reason, "external/interactive execution prepared"
        )
        self.assertEqual(store.items, {STORE_KEY: EXTENSION})

    def test_managed_adapter_is_rejected_for_external_preparation(self):
        service, traces, _, _ = make_service(ManagedAdapter())
        self.assert_rejected(
            service,
            traces,
            "IMPLEMENTATION_NOT_FOUND",
            "resolved adapter is managed, not external",
            lineage_ref="LIN-1",
        )

    def test_unknown_lineage_is_stale_state(self):
        service, traces, _, _ = make_service(ExternalAdapter())
        error = self.assert_rejected(
            service,
            traces,
            "STALE_STATE",
            "Invocation project/lineage does not resolve to current Research State",
            lineage_ref="LIN-NOPE",
            context_extension=EXTENSION,
        )
        self.assertIsInstance(error.__cause__, KeyError)

    def test_required_extension_missing(self):
        service, traces, _, _ = make_service(ExternalAdapter())
        self.assert_rejected(
            service,
            traces,
            "CONTEXT_INVALID",
            "required capability Context extension is missing",
            lineage_ref="LIN-1",
        )

    def test_default_registry_has_no_validators(self):
        service, traces, _, _ = make_service(ExternalAdapter(), default_registry=True)
        self.assert_rejected(
            service,
            traces,
            "CONTEXT_INVALID",
            "unknown capability Context extension has no registered validator",
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )

    def test_validator_issues_are_raised_with_first_code(self):
        validator = Validator(
            (
                ExecutionIssue("CTX-FIX-001", "first"),
                ExecutionIssue("CTX-FIX-002", "second", True),
            )
        )
        service, traces, store, _ = make_service(ExternalAdapter(), validators=(validator,))
        error = self.assert_rejected(
            service,
            traces,
            "CTX-FIX-001",
            "first; second",
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )
        self.assertTrue(error.issue.retryable)
        self.assertEqual(store.items, {})

    def test_extension_without_store_is_rejected(self):
        service, traces, _, _ = make_service(ExternalAdapter(requires=False), use_store=False)
        self.assert_rejected(
            service,
            traces,
            "CONTEXT_INVALID",
            "validated capability Context extension has no immutable runtime store",
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )

    def test_no_extension_and_no_store_is_allowed_when_not_required(self):
        service, _, _, _ = make_service(ExternalAdapter(requires=False), use_store=False)
        prepared = service.prepare_external(DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1")
        self.assertEqual(prepared.run.status, RunStatus.RUNNING)

    def test_authorization_is_checked_before_extension_is_stored(self):
        service, traces, store, _ = make_service(ExternalAdapter(), auth=False)
        self.assert_rejected(
            service,
            traces,
            "AUTHORIZATION_DENIED",
            "authorization evidence is unknown, expired, stale, or denied",
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )
        self.assertEqual(store.items, {})

    def test_store_failure_is_wrapped_as_context_invalid(self):
        service, traces, _, _ = make_service(ExternalAdapter(), store=Store(ValueError("disk")))
        error = self.assert_rejected(
            service,
            traces,
            "CONTEXT_INVALID",
            "capability Context extension persistence failed: disk",
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )
        self.assertIsInstance(error.__cause__, ValueError)

    def test_store_execution_error_is_reraised_unchanged(self):
        original = CapabilityExecutionError("STORE-CODE", "store refused")
        service, traces, _, _ = make_service(ExternalAdapter(), store=Store(original))
        error = self.assert_rejected(
            service,
            traces,
            "STORE-CODE",
            "store refused",
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )
        self.assertIs(error, original)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.service, self.traces, self.store, _ = make_service(ExternalAdapter())
        self.service.prepare_external(
            DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1", context_extension=EXTENSION
        )
        # Forget the first Run's extension so a rejected retry can be seen not to store one.
        self.store.items.clear()

    def prepare(self, invocation):
        return self.service.prepare_external(
            DESCRIPTOR, invocation, CONTEXT, lineage_ref="LIN-1", context_extension=EXTENSION
        )

    def assert_invalid(self, invocation, message):
        with self.assertRaises(CapabilityExecutionError) as cm:
            self.prepare(invocation)
        self.assertEqual(cm.exception.issue.code, "INVOCATION_INVALID")
        self.assertEqual(cm.exception.issue.message, message)
        self.assertEqual(set(self.traces.runs), {"RUN-001"})
        self.assertEqual(self.store.items, {}, "a rejected retry must not store its extension")

    def test_retry_after_terminal_parent_increments_attempt(self):
        self.service.abort("RUN-001")
        prepared = self.prepare(retry_invocation())
        self.assertEqual(prepared.run.run_id, "RUN-002")
        self.assertEqual(prepared.run.parent_run_id, "RUN-001")
        self.assertEqual(prepared.run.attempt, 2)
        self.assertEqual(len(self.store.items), 1)

    def test_parent_must_be_terminal(self):
        self.assert_invalid(
            retry_invocation(),
            "retry parent Run must be terminal before a new attempt is prepared",
        )

    def test_unknown_parent(self):
        self.assert_invalid(retry_invocation(parent="RUN-404"), "unknown Run RUN-404")

    def test_retry_must_use_new_run_id(self):
        self.service.abort("RUN-001")
        self.assert_invalid(
            retry_invocation(run_id="RUN-001", parent="RUN-001"), "retry must use a new Run ID"
        )

    def test_reused_run_id_is_rejected_before_the_extension_is_stored(self):
        with self.assertRaisesRegex(ValueError, "^Run ID is single-use: RUN-001$"):
            self.prepare(INVOCATION)
        self.assertEqual(set(self.traces.runs), {"RUN-001"})
        self.assertEqual(self.store.items, {})

    def test_parent_must_preserve_capability_binding(self):
        self.service.abort("RUN-001")
        for field, value in (
            ("capability_id", "other"),
            ("capability_version", "9.9.9"),
            ("function_id", "other"),
            ("execution_mode", "real"),
        ):
            with self.subTest(field=field):
                original = self.traces.runs["RUN-001"]
                self.traces.runs["RUN-001"] = replace(original, **{field: value})
                try:
                    self.assert_invalid(
                        retry_invocation(),
                        "retry parent must preserve capability/function/execution mode",
                    )
                finally:
                    self.traces.runs["RUN-001"] = original


class ContextPackExtensionIdentityTests(unittest.TestCase):
    """One Context Pack carries exactly one extension (the store key has no Run)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = LocalCapabilityContextExtensionStore(temp.name)
        self.addCleanup(self.store.close)
        self.service, self.traces, _, _ = make_service(ExternalAdapter(), store=self.store)
        self.service.prepare_external(
            DESCRIPTOR, INVOCATION, CONTEXT, lineage_ref="LIN-1", context_extension=EXTENSION
        )
        self.service.abort("RUN-001")

    def test_retry_with_the_same_extension_reuses_the_stored_one(self):
        prepared = self.service.prepare_external(
            DESCRIPTOR,
            retry_invocation(),
            CONTEXT,
            lineage_ref="LIN-1",
            context_extension=EXTENSION,
        )
        self.assertEqual(prepared.run.attempt, 2)

    def test_retry_with_a_different_extension_needs_a_new_context_pack(self):
        with self.assertRaises(CapabilityExecutionError) as cm:
            self.service.prepare_external(
                DESCRIPTOR,
                retry_invocation(),
                CONTEXT,
                lineage_ref="LIN-1",
                context_extension={**EXTENSION, "value": 2},
            )
        self.assertEqual(cm.exception.issue.code, "CONTEXT_INVALID")
        self.assertEqual(
            cm.exception.issue.message,
            "capability Context extension persistence failed: "
            "immutable capability Context extension identity collision",
        )
        self.assertEqual(set(self.traces.runs), {"RUN-001"})


class CollectExternalTests(unittest.TestCase):
    def prepared(self, adapter):
        service, traces, store, registry = make_service(adapter)
        service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
            context_extension=EXTENSION if adapter.requires_context_extension else None,
        )
        return service, traces, store, registry

    def test_collect_with_stored_extension_completes(self):
        service, _, _, _ = self.prepared(ExternalAdapter())
        result = service.collect_external("RUN-001", HANDOFF)
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)

    def test_collect_without_store_is_rejected(self):
        adapter = ExternalAdapter()
        _, traces, _, registry = self.prepared(adapter)
        collector, _, _, _ = make_service(
            adapter, traces=traces, registry=registry, use_store=False
        )
        with self.assertRaises(CapabilityExecutionError) as cm:
            collector.collect_external("RUN-001", HANDOFF)
        self.assertEqual(cm.exception.issue.code, "CONTEXT_INVALID")
        self.assertEqual(
            cm.exception.issue.message,
            "required Context extension store is unavailable at collection",
        )
        self.assertEqual(traces.runs["RUN-001"].status, RunStatus.RUNNING)

    def test_collect_with_missing_stored_extension_is_rejected(self):
        adapter = ExternalAdapter()
        _, traces, _, registry = self.prepared(adapter)
        collector, _, _, _ = make_service(adapter, traces=traces, registry=registry, store=Store())
        with self.assertRaises(CapabilityExecutionError) as cm:
            collector.collect_external("RUN-001", HANDOFF)
        self.assertEqual(cm.exception.issue.code, "CONTEXT_INVALID")
        self.assertEqual(
            cm.exception.issue.message, "validated Context extension is missing at collection"
        )
        self.assertEqual(traces.runs["RUN-001"].status, RunStatus.RUNNING)

    def test_adapter_not_requiring_extension_skips_store_check(self):
        adapter = ExternalAdapter(requires=False)
        _, traces, _, registry = self.prepared(adapter)
        collector, _, _, _ = make_service(
            adapter, traces=traces, registry=registry, use_store=False
        )
        result = collector.collect_external("RUN-001", HANDOFF)
        self.assertEqual(result.run.status, RunStatus.COMPLETED)

    def test_terminal_run_skips_store_check_and_keeps_late_result_diagnostic(self):
        adapter = ExternalAdapter()
        service, traces, _, registry = self.prepared(adapter)
        service.abort("RUN-001")
        collector, _, _, _ = make_service(
            adapter, traces=traces, registry=registry, use_store=False
        )
        result = collector.collect_external("RUN-001", HANDOFF)
        self.assertEqual(result.run.status, RunStatus.ABORTED)
        self.assertEqual([issue.code for issue in result.issues], ["RUN_ABORTED"])
        self.assertEqual(traces.diagnostics[-1][1], "late_result")

    def test_unknown_run_is_rejected_by_base_service(self):
        service, _, _, _ = make_service(ExternalAdapter())
        with self.assertRaises(CapabilityExecutionError) as cm:
            service.collect_external("RUN-404", HANDOFF)
        self.assertEqual(cm.exception.issue.code, "INVOCATION_INVALID")
        self.assertEqual(cm.exception.issue.message, "unknown Run RUN-404")


if __name__ == "__main__":
    unittest.main()
