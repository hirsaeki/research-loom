from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from core.execution import (
    CapabilityContextExtensionRegistry,
    CapabilityExecutionError,
    CapabilityExecutionService,
    CapabilityRegistry,
    ExecutionIssue,
    ExecutionStyle,
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
DESCRIPTOR = json.loads(
    (FIX / "generic-capability-descriptor.json").read_text()
)
CONTEXT = json.loads(
    (FIX / "generic-capability-context-pack.json").read_text()
)
INVOCATION = json.loads(
    (FIX / "generic-capability-invocation.json").read_text()
)
HANDOFF = json.loads(
    (FIX / "generic-capability-handoff.json").read_text()
)


class StateProvider:
    def __init__(self):
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
            project_config_digest=CONTEXT["pins"]["project_config"][
                "configuration_digest"
            ],
            effective_profile_set_ref="EPS-1",
            effective_profile_set_digest=CONTEXT["pins"]["effective_profile_set"][
                "content_digest"
            ],
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
        if (
            project_ref != self.state.project_ref
            or lineage_ref != self.state.lineage_ref
        ):
            raise KeyError((project_ref, lineage_ref))
        return self.state


class ExternalAdapter:
    implementation_id = "plugin.fixture.future"
    implementation_version = "1.0.0"
    capability_id = "fixture.research-support"
    capability_version = "1.0.0"
    supported_functions = ("investigate",)
    supported_execution_modes = ("virtual",)
    execution_style = ExecutionStyle.EXTERNAL
    requires_context_extension = True

    def execute(self, request):
        raise AssertionError

    def cancel(self, run_id):
        pass


class Validator:
    def __init__(self):
        self.calls = 0

    def supports(self, capability_id, capability_version, function_id):
        return (capability_id, capability_version, function_id) == (
            "fixture.research-support",
            "1.0.0",
            "investigate",
        )

    def validate(self, descriptor, invocation, context_pack, extension, state):
        self.calls += 1
        if extension != {"extension_type": "future_fixture", "value": 1}:
            return (
                ExecutionIssue(
                    "FUTURE-CONTEXT-001",
                    "future fixture rejected",
                ),
            )
        return ()


class Store:
    def __init__(self):
        self.items = {}

    def store(
        self,
        capability_id,
        capability_version,
        function_id,
        context_pack_id,
        extension,
    ):
        key = (
            capability_id,
            capability_version,
            function_id,
            context_pack_id,
        )
        prior = self.items.get(key)
        if prior is not None and prior != extension:
            raise ValueError("immutable collision")
        self.items[key] = deepcopy(dict(extension))
        return "fixture-ref"

    def load(
        self,
        capability_id,
        capability_version,
        function_id,
        context_pack_id,
    ):
        return deepcopy(
            self.items.get(
                (
                    capability_id,
                    capability_version,
                    function_id,
                    context_pack_id,
                )
            )
        )


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
            "SDP-FUTURE",
            context["project_ref"],
            context["lineage_ref"],
            (handoff["handoff_id"],),
            (),
            (),
            "future fixture",
            (),
            context["current_snapshot_ref"],
            context["current_snapshot_digest"],
            {"run_id": context["run_id"]},
        ).with_calculated_digest()


class GenericContextExtensionHookTests(unittest.TestCase):
    def make_service(self, validators):
        registry = CapabilityRegistry()
        registry.register(ExternalAdapter(), DESCRIPTOR)
        traces = InMemoryExecutionTraceStore()
        store = Store()
        service = CapabilityExecutionService(
            registry,
            traces,
            StateProvider(),
            AllowListedAuthorizationProvider(
                (
                    INVOCATION["runtime_authorization_evidence"]
                    ["authorization_digest"],
                )
            ),
            InMemoryResourceProvider(
                {
                    ref: b"fixture"
                    for ref in INVOCATION["runtime_authorization_evidence"]
                    ["resource_reference_ids"]
                }
            ),
            CapabilityNormalizationBoundary((Normalizer(),)),
            StaticClock(),
            context_extension_registry=CapabilityContextExtensionRegistry(
                validators
            ),
            context_extension_store=store,
        )
        return service, traces, store

    def test_required_extension_and_unknown_validator_fail_before_run(self):
        missing_service, missing_traces, _ = self.make_service(())
        with self.assertRaises(CapabilityExecutionError) as cm:
            missing_service.prepare_external(
                DESCRIPTOR,
                INVOCATION,
                CONTEXT,
                lineage_ref="LIN-1",
            )
        self.assertEqual(cm.exception.issue.code, "CONTEXT_INVALID")
        self.assertFalse(missing_traces.runs)

        unknown_service, unknown_traces, _ = self.make_service(())
        with self.assertRaises(CapabilityExecutionError) as cm:
            unknown_service.prepare_external(
                DESCRIPTOR,
                INVOCATION,
                CONTEXT,
                lineage_ref="LIN-1",
                context_extension={
                    "extension_type": "future_fixture",
                    "value": 1,
                },
            )
        self.assertEqual(cm.exception.issue.code, "CONTEXT_INVALID")
        self.assertFalse(unknown_traces.runs)

    def test_future_capability_preflight_requires_no_core_change(self):
        validator = Validator()
        service, traces, store = self.make_service((validator,))
        extension = {
            "extension_type": "future_fixture",
            "value": 1,
        }
        prepared = service.prepare_external(
            DESCRIPTOR,
            INVOCATION,
            CONTEXT,
            lineage_ref="LIN-1",
            context_extension=extension,
        )
        self.assertEqual(prepared.run.status.value, "RUNNING")
        self.assertEqual(validator.calls, 1)
        self.assertEqual(
            store.load(
                "fixture.research-support",
                "1.0.0",
                "investigate",
                CONTEXT["context_pack_id"],
            ),
            extension,
        )
        self.assertIn("RUN-001", traces.runs)
        generic_source = (ROOT / "core/execution/context_extensions.py").read_text()
        self.assertNotIn("desktop-research", generic_source)
        self.assertNotIn("DesktopResearch", generic_source)


if __name__ == "__main__":
    unittest.main()
