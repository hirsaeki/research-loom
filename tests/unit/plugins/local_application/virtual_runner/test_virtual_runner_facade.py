"""Characterization tests for ``plugins.local_application.virtual_runner.virtual_runner_facade`` (#507).

They pin the Virtual Runner facade stages (the advertised
``virtual_runner.survey.execute`` action and the ingress/authority checks that
route it to ``run_survey_virtual``), how ``VirtualRunnerMixin`` locates the
Effective Profile Set (workspace document, legacy workspace file, or the
materializer's profile provider), and that ``_build_context`` assembles the
context pack and Survey extension from a real local application.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from plugins.application_errors import LocalApplicationError
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.virtual_runner.virtual_runner_execute import (
    VirtualRunnerExecuteMixin,
)
from plugins.local_application.virtual_runner.virtual_runner_facade import (
    DESCRIPTOR_PATH,
    VirtualRunnerMixin,
    list_actions_stage,
    submit_action_stage,
)
from plugins.local_application.virtual_runner.virtual_runner_input import _payload
from plugins.local_application.virtual_runner.virtual_runner_inspection import (
    VirtualRunnerInspectionMixin,
)
from plugins.local_workspace_layout import (
    BINDING_NAME,
    INTERNAL_DIR,
    STORAGE,
    WORKSPACE_FORMAT,
    WORKSPACE_VERSION,
    LocalWorkspaceError,
)
from tests.runtime.survey_virtual_runner_test_support import (
    METHOD_ID,
    SurveyVirtualRunnerTestBase,
    execution_payload,
    make_virtual_app,
)

ACTION = "virtual_runner.survey.execute"


def valid_payload(**overrides) -> dict:
    payload = execution_payload(
        scenario="STANDARD", instrument_version="1.0.0", instrument_digest="sha256:" + "a" * 64
    )
    payload.update(overrides)
    return payload


class RecordingFacade:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_survey_virtual(self, payload):
        self.calls.append(payload)
        return {"status": "SUCCEEDED", "payload": payload}


class ListActionsStageTests(unittest.TestCase):
    def test_appends_virtual_runner_action_to_a_copy(self):
        original = {"actions": [{"action_type": "other"}], "project_id": "PRJ-1"}
        result = list_actions_stage(object(), lambda: original)
        self.assertEqual(
            result["actions"],
            [
                {"action_type": "other"},
                {
                    "action_type": ACTION,
                    "payload_contract": "survey-virtual-runner-execution@0.1.0",
                    "effect": "read_only",
                    "confirmation_required": False,
                    "route_category": "research_capability",
                },
            ],
        )
        self.assertEqual(result["project_id"], "PRJ-1")
        self.assertIsNot(result, original)

    def test_stage_table_and_composition(self):
        self.assertEqual(
            VirtualRunnerMixin._STAGES,
            {"list_actions": list_actions_stage, "submit_action": submit_action_stage},
        )
        self.assertTrue(issubclass(VirtualRunnerMixin, VirtualRunnerInspectionMixin))
        self.assertTrue(issubclass(VirtualRunnerMixin, VirtualRunnerExecuteMixin))
        self.assertTrue(DESCRIPTOR_PATH.is_file())


class SubmitActionStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = RecordingFacade()
        self.proceeded: list = []

    def proceed(self, draft_input, **kwargs):
        self.proceeded.append((draft_input, kwargs))
        return {"status": "PROCEEDED"}

    def submit(self, draft_input, **kwargs):
        return submit_action_stage(self.facade, self.proceed, draft_input, **kwargs)

    def assert_rejected(self, draft_input, code, message):
        with self.assertRaises(LocalApplicationError) as caught:
            self.submit(draft_input)
        self.assertEqual((caught.exception.code, caught.exception.message), (code, message))
        self.assertEqual(self.facade.calls, [])
        self.assertEqual(self.proceeded, [])

    def test_other_actions_and_non_mappings_proceed(self):
        for draft in ({"action_type": "research.capture"}, ["not", "mapping"], None):
            with self.subTest(draft=draft):
                self.assertEqual(self.submit(draft, view="full"), {"status": "PROCEEDED"})
        self.assertEqual(len(self.proceeded), 3)
        # The view keyword is accepted but not forwarded to proceed.
        self.assertEqual(self.proceeded[0][1], {})
        self.assertEqual(self.facade.calls, [])

    def test_valid_virtual_action_is_normalized_and_routed(self):
        payload = valid_payload()
        del payload["population_size"]
        result = self.submit(
            {
                "action_type": ACTION,
                "payload": payload,
                "rationale": "r",
                "actor_id": "HUMAN-1",
                "conversation_id": "CONV-1",
            }
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(len(self.facade.calls), 1)
        routed = self.facade.calls[0]
        self.assertEqual(routed["population_size"], 8)
        self.assertEqual(routed["generator_backend"], "structural")
        self.assertEqual(self.proceeded, [])

    def test_unknown_ingress_fields(self):
        self.assert_rejected(
            {"action_type": ACTION, "payload": valid_payload(), "zeta": 1, "project_id": "P"},
            "APPLICATION-INGRESS-001",
            "typed action input contains caller-controlled authority or unknown fields: "
            "project_id, zeta",
        )

    def test_payload_must_be_mapping(self):
        for draft in ({"action_type": ACTION}, {"action_type": ACTION, "payload": []}):
            with self.subTest(draft=draft):
                self.assert_rejected(draft, "APPLICATION-INGRESS-001", "payload must be an object")

    def test_authority_payload_fields(self):
        self.assert_rejected(
            {
                "action_type": ACTION,
                "payload": valid_payload(commit_id="C", runtime_authorization_evidence={}),
            },
            "APPLICATION-AUTHORITY-001",
            "caller may not supply Harness authority metadata: commit_id, "
            "runtime_authorization_evidence",
        )

    def test_payload_validation_errors_propagate(self):
        self.assert_rejected(
            {"action_type": ACTION, "payload": valid_payload(scenario_class="REAL")},
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "scenario_class must be STANDARD or STRESS",
        )
        self.assert_rejected(
            {
                "action_type": ACTION,
                "payload": valid_payload(prior_virtual_run_ids=[f"RUN-{i}" for i in range(17)]),
            },
            "APPLICATION-VIRTUAL-PAYLOAD-001",
            "prior_virtual_run_ids may contain at most 16 Run IDs",
        )


def profile_set(digest: str = "sha256:" + "e" * 64) -> dict:
    return {"schema_version": "0.1.0", "content_digest": digest, "profile_pins": []}


class EffectiveProfileSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.provider_calls: list = []

    def mixin(self, *, workspace_root=None, application=None):
        instance = VirtualRunnerMixin()
        instance._workspace_root = workspace_root
        instance._application = application if application is not None else self.application()
        return instance

    def application(self, *, value=None, error=None):
        def provider(project_ref, digest):
            self.provider_calls.append((project_ref, digest))
            if error is not None:
                raise error
            return value if value is not None else {"from": "provider"}

        def resolve(contract):
            self.assertEqual(contract, "desktop_research.investigate@0.1.0")
            return SimpleNamespace(_profiles=provider)

        return SimpleNamespace(
            coordinator=SimpleNamespace(_materializers=SimpleNamespace(resolve=resolve))
        )

    def state(self):
        return SimpleNamespace(project_ref="PRJ-1", effective_profile_set_digest="sha256:eps")

    def write_binding(self, locator: str = "profiles/eps.json") -> None:
        binding = {
            "workspace_format": WORKSPACE_FORMAT,
            "workspace_version": WORKSPACE_VERSION,
            "project_id": "PRJ-1",
            "project_config": {"locator": "project-config.json", "digest": "sha256:c"},
            "effective_profile_set": {"locator": locator, "digest": "sha256:e"},
            "storage": dict(STORAGE),
            "initialized_at": "2026-01-01T00:00:00Z",
        }
        (self.root / INTERNAL_DIR).mkdir(exist_ok=True)
        (self.root / INTERNAL_DIR / BINDING_NAME).write_text(json.dumps(binding), encoding="utf-8")

    def test_without_workspace_uses_materializer_provider(self):
        result = self.mixin()._effective_profile_set(self.state())
        self.assertEqual(result, {"from": "provider"})
        self.assertEqual(self.provider_calls, [("PRJ-1", "sha256:eps")])

    def test_provider_failure_is_wrapped(self):
        for application in (
            self.application(error=RuntimeError("boom")),
            SimpleNamespace(coordinator=None),
        ):
            with self.subTest(application=application):
                with self.assertRaises(LocalApplicationError) as caught:
                    self.mixin(application=application)._effective_profile_set(self.state())
                self.assertEqual(caught.exception.code, "APPLICATION-VIRTUAL-PIN-001")
                self.assertEqual(
                    caught.exception.message,
                    "current Effective Profile Set cannot be projected without creating a "
                    "second authority",
                )

    def test_legacy_workspace_file_is_preferred_without_binding(self):
        (self.root / "effective-profile-set.json").write_text(
            json.dumps(profile_set()), encoding="utf-8"
        )
        result = self.mixin(workspace_root=self.root)._effective_profile_set(self.state())
        self.assertEqual(result, profile_set())
        self.assertEqual(self.provider_calls, [])

    def test_bound_workspace_document_is_read_from_binding_locator(self):
        self.write_binding()
        (self.root / "profiles").mkdir()
        (self.root / "profiles" / "eps.json").write_text(
            json.dumps(profile_set("sha256:bound")), encoding="utf-8"
        )
        # A legacy root file is ignored once a binding exists.
        (self.root / "effective-profile-set.json").write_text(
            json.dumps(profile_set("sha256:legacy")), encoding="utf-8"
        )
        result = self.mixin(workspace_root=self.root)._effective_profile_set(self.state())
        self.assertEqual(result["content_digest"], "sha256:bound")

    def test_missing_or_non_object_workspace_document_falls_back_to_provider(self):
        mixin = self.mixin(workspace_root=self.root)
        self.assertEqual(mixin._effective_profile_set(self.state()), {"from": "provider"})
        (self.root / "effective-profile-set.json").write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(mixin._effective_profile_set(self.state()), {"from": "provider"})
        self.assertEqual(len(self.provider_calls), 2)

    def test_unreadable_workspace_document(self):
        for content in (b"{broken", b"\xff\xfe\x00"):
            with self.subTest(content=content):
                (self.root / "effective-profile-set.json").write_bytes(content)
                with self.assertRaises(LocalApplicationError) as caught:
                    self.mixin(workspace_root=self.root)._effective_profile_set(self.state())
                self.assertEqual(caught.exception.code, "APPLICATION-VIRTUAL-PIN-001")
                self.assertEqual(
                    caught.exception.message, "workspace Effective Profile Set is unreadable"
                )

    def test_malformed_binding_error_is_not_wrapped(self):
        # By design (#577): the Workspace error keeps its own code, which the CLI
        # reports as an ERROR envelope like any LocalApplicationError.
        (self.root / INTERNAL_DIR).mkdir()
        (self.root / INTERNAL_DIR / BINDING_NAME).write_text("{}", encoding="utf-8")
        with self.assertRaises(LocalWorkspaceError) as caught:
            self.mixin(workspace_root=self.root)._effective_profile_set(self.state())
        self.assertEqual(caught.exception.code, "WORKSPACE-BINDING-001")


class BuildContextTests(SurveyVirtualRunnerTestBase):
    def test_build_context_from_real_application(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            try:
                questionnaire = self._capture(facade)
                payload = _payload(
                    valid_payload(
                        instrument_version=questionnaire["version"],
                        instrument_digest=questionnaire["content_digest"],
                    )
                )
                state = facade._state()
                record = facade._survey_store().load_instrument(
                    "PRJ-1", "QNR-1", questionnaire["version"]
                )
                design_ref = record["design_ref"]
                design_record = facade._survey_store().load_design(
                    "PRJ-1", design_ref["survey_design_id"], design_ref["version"]
                )
                context, extension, method = facade._build_context(
                    state, record, design_record, payload, context_pack_id="CTX-VR-UNIT"
                )
            finally:
                app.close()
        self.assertEqual(method["id"], METHOD_ID)
        self.assertEqual(context["context_pack_id"], "CTX-VR-UNIT")
        self.assertEqual(context["question_ids"], ["RQ-1"])
        self.assertEqual(
            extension["context_pack_binding"],
            {
                "context_pack_id": "CTX-VR-UNIT",
                "context_pack_digest": context["context_pack_digest"],
                "project_id": context["project_id"],
            },
        )
        self.assertEqual(
            extension["instrument_ref"]["content_digest"], questionnaire["content_digest"]
        )
        self.assertEqual(extension["core_method_ref"], {"method_id": METHOD_ID, "revision": 0})
        self.assertEqual(extension["scenario_class"], "STANDARD")
        self.assertEqual(extension["generator_backend"], "structural")


if __name__ == "__main__":
    unittest.main()
