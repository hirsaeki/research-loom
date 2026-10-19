"""Characterization tests for ``plugins.local_application.virtual_runner.virtual_runner_resolve`` (#507).

They pin how ``resolve_virtual_inputs`` resolves the Instrument RQs, the exact
approved Core Method, its Human Decision and Protocol bindings, the Instrument
approval and provenance pins, and the project/effective constraints, and the
``LocalApplicationError`` raised when any binding fails. A small in-memory
state stand-in supplies exactly the attributes the resolver reads.
"""

from __future__ import annotations

import unittest
from copy import deepcopy
from types import SimpleNamespace

from plugins.application_errors import LocalApplicationError
from plugins.local_application.virtual_runner.virtual_runner_resolve import (
    _protocol_revision_decision_for,
    resolve_virtual_inputs,
)
from tests.runtime.runtime_fixtures import decision, rq
from tests.runtime.survey_virtual_runner_test_support import (
    METHOD_ID,
    PROTOCOL_ID,
    execution_payload,
    method_object,
)

EPS_DIGEST = "sha256:" + "e" * 64
CONFIG_DIGEST = "sha256:" + "c" * 64
SNAPSHOT = {"id": "SNP-1", "revision": 3, "content_digest": "sha256:" + "5" * 64}
LINEAGE = "LIN-1"
DESIGN_DIGEST = "sha256:" + "d" * 64


class FakeState:
    def __init__(self) -> None:
        self.objects = [rq(state="approved"), method_object()]
        self.decisions = {
            "DEC-METHOD-1": decision(
                "DEC-METHOD-1", "research_adoption", "approve", "method", METHOD_ID
            ),
            "DEC-PROTOCOL-MAT-1": decision(
                "DEC-PROTOCOL-MAT-1", "research_revision", "revise", "protocol", PROTOCOL_ID
            ),
        }
        self.current_snapshot = dict(SNAPSHOT)
        self.lineage_ref = LINEAGE
        self.project_config_digest = CONFIG_DIGEST
        self.effective_profile_set_digest = EPS_DIGEST
        self.project_config: dict = {}
        self.effective_constraints: object = []

    def effective_objects(self):
        return iter(self.objects)

    def exact_object(self, kind, object_id, revision):
        return next(
            (
                item
                for item in self.objects
                if item["kind"] == kind and item["id"] == object_id and item["revision"] == revision
            ),
            None,
        )

    def decision(self, decision_id):
        return self.decisions.get(decision_id)


class FakeFacade:
    def __init__(self, attention=()) -> None:
        self.profile_set = {
            "schema_version": "0.1.0",
            "core_contracts": {"core": "0.1.0"},
            "profile_pins": [
                {
                    "profile_id": "P-1",
                    "profile_type": "organization",
                    "profile_version": "1.0.0",
                    "manifest_sha256": "sha256:" + "1" * 64,
                }
            ],
            "content_digest": EPS_DIGEST,
        }
        self.attention = list(attention)
        self._application = SimpleNamespace(effective_attention=lambda state: self.attention)

    def _effective_profile_set(self, state):
        return self.profile_set


def captured() -> dict:
    return {
        "lineage_ref": LINEAGE,
        "snapshot_ref": SNAPSHOT["id"],
        "snapshot_digest": SNAPSHOT["content_digest"],
    }


def instrument_record() -> dict:
    return {
        "questionnaire": {
            "questionnaire_id": "QNR-1",
            "version": "1.0.0",
            "content_digest": "sha256:" + "a" * 64,
            "approval_status": "approved",
            "approval_decision_id": "DEC-QNR-1",
        },
        "rq_ids": ["RQ-1"],
        "captured_against": captured(),
        "project_config_digest": CONFIG_DIGEST,
        "effective_profile_set_digest": EPS_DIGEST,
        "design_ref": {
            "survey_design_id": "SD-1",
            "version": "1.0.0",
            "content_digest": DESIGN_DIGEST,
        },
    }


def design_record() -> dict:
    return {"captured_against": captured(), "design": {"content_digest": DESIGN_DIGEST}}


def payload() -> dict:
    return execution_payload(
        scenario="STANDARD", instrument_version="1.0.0", instrument_digest="sha256:" + "a" * 64
    )


class ResolveCase(unittest.TestCase):
    def setUp(self) -> None:
        self.state = FakeState()
        self.facade = FakeFacade(attention=[{"attention_id": "ATT-1"}])
        self.record = instrument_record()
        self.design = design_record()
        self.payload = payload()

    def resolve(self):
        return resolve_virtual_inputs(
            self.facade, self.state, self.record, self.design, self.payload
        )

    def assert_rejected(self, code, message):
        with self.assertRaises(LocalApplicationError) as caught:
            self.resolve()
        self.assertEqual((caught.exception.code, caught.exception.message), (code, message))


class ResolveAcceptTests(ResolveCase):
    def test_returns_resolved_bindings_in_order(self):
        (
            questionnaire,
            rq_ids,
            rq_objects,
            method,
            method_decisions,
            protocol,
            material_decisions,
            snapshot,
            effective,
            attention,
            project_constraints,
            effective_constraints,
        ) = self.resolve()
        self.assertEqual(questionnaire, self.record["questionnaire"])
        self.assertIsNot(questionnaire, self.record["questionnaire"])
        self.assertEqual(rq_ids, ["RQ-1"])
        self.assertEqual([item["id"] for item in rq_objects], ["RQ-1"])
        self.assertEqual(method["id"], METHOD_ID)
        self.assertEqual(method_decisions, ["DEC-METHOD-1"])
        self.assertEqual(protocol, self.payload["protocol"])
        self.assertEqual(material_decisions, [])
        self.assertIs(snapshot, self.state.current_snapshot)
        self.assertEqual(effective["content_digest"], EPS_DIGEST)
        self.assertEqual(effective["profile_pins"], self.facade.profile_set["profile_pins"])
        self.assertEqual(attention, [{"attention_id": "ATT-1"}])
        self.assertIsNot(attention[0], self.facade.attention[0])
        self.assertEqual(
            project_constraints, {"requirements": [], "prohibitions": [], "must_not_claim": []}
        )
        self.assertEqual(effective_constraints, [])

    def test_revised_rq_is_accepted(self):
        self.state.objects[0]["adoption_state"] = "revised"
        self.assertEqual(self.resolve()[1], ["RQ-1"])

    def test_unverifiable_method_decisions_are_filtered(self):
        method = self.state.objects[1]
        method["decision_ids"] = ["DEC-MISSING", "DEC-METHOD-1"]
        self.assertEqual(self.resolve()[4], ["DEC-METHOD-1"])

    def test_material_protocol_revision_decision_is_recorded(self):
        self.payload["protocol"].update(
            material_revision=True, material_revision_decision_id="DEC-PROTOCOL-MAT-1"
        )
        self.assertEqual(self.resolve()[6], ["DEC-PROTOCOL-MAT-1"])

    def test_material_instrument_revision_with_decision_is_accepted(self):
        self.record["questionnaire"].update(
            material_revision=True, material_revision_decision_id="DEC-QNR-MAT"
        )
        self.assertTrue(self.resolve()[0]["material_revision"])

    def test_guards_key_supplies_project_constraints(self):
        self.state.project_config = {
            "guards": {
                "requirements": [{"id": "REQ-1"}],
                "prohibitions": ["no real people"],
                "must_not_claim": ["from guards"],
            },
            "project_guards": {"requirements": [{"id": "IGNORED"}]},
        }
        self.assertEqual(
            self.resolve()[10],
            {
                "requirements": [{"id": "REQ-1"}],
                "prohibitions": ["no real people"],
                "must_not_claim": ["from guards"],
            },
        )

    def test_project_guards_and_top_level_must_not_claim(self):
        self.state.project_config = {
            "project_guards": {"requirements": ["R"], "must_not_claim": ["from guards"]},
            "must_not_claim": ["top level"],
        }
        self.assertEqual(
            self.resolve()[10],
            {"requirements": ["R"], "prohibitions": [], "must_not_claim": ["top level"]},
        )

    def test_non_mapping_guards_are_treated_as_empty(self):
        self.state.project_config = {"guards": ["R"]}
        self.assertEqual(
            self.resolve()[10], {"requirements": [], "prohibitions": [], "must_not_claim": []}
        )

    def test_effective_constraints_from_mapping_or_sequence_keep_only_mappings(self):
        self.state.effective_constraints = {"C-1": {"id": "C-1"}, "C-2": "skip"}
        self.assertEqual(self.resolve()[11], [{"id": "C-1"}])
        self.state.effective_constraints = ({"id": "C-3"}, "skip")
        self.assertEqual(self.resolve()[11], [{"id": "C-3"}])


class ResolveRejectTests(ResolveCase):
    def test_rq_must_be_current_and_adopted(self):
        message = "Instrument RQ is not current authoritative Research State: RQ-1"
        self.state.objects[0]["adoption_state"] = "candidate"
        self.assert_rejected("APPLICATION-VIRTUAL-RQ-001", message)
        self.state.objects[0]["adoption_state"] = "approved"
        self.record["rq_ids"] = ["RQ-1", "RQ-2"]
        self.assert_rejected(
            "APPLICATION-VIRTUAL-RQ-001",
            "Instrument RQ is not current authoritative Research State: RQ-2",
        )

    def test_method_must_resolve_exactly_and_be_approved(self):
        message = "exact approved Core Method does not resolve in Research State"
        self.payload["core_method_revision"] = 1
        self.assert_rejected("VR-METHOD-BINDING-001", message)
        self.payload["core_method_revision"] = 0
        self.state.objects[1]["adoption_state"] = "candidate"
        self.assert_rejected("VR-METHOD-BINDING-001", message)

    def test_method_must_cover_instrument_rqs(self):
        self.state.objects[1]["question_ids"] = ["RQ-9"]
        self.assert_rejected(
            "VR-METHOD-BINDING-001", "approved Core Method does not cover all Instrument RQs"
        )

    def test_method_needs_verifiable_human_decision(self):
        self.state.decisions["DEC-METHOD-1"]["actor_type"] = "agent"
        self.assert_rejected(
            "VR-HUMAN-DECISION-001",
            "approved Core Method lacks a verifiable Human Decision binding",
        )

    def test_protocol_ref_must_match_method(self):
        self.payload["protocol"]["version"] = "1.0.1"
        self.assert_rejected(
            "VR-METHOD-BINDING-001",
            "Protocol id/version/digest do not match the content-addressed protocol_ref "
            "approved with the exact Core Method",
        )

    def test_material_protocol_revision_needs_revise_decision(self):
        self.payload["protocol"].update(
            material_revision=True, material_revision_decision_id="DEC-METHOD-1"
        )
        self.assert_rejected(
            "VR-HUMAN-DECISION-001",
            "material Protocol revision decision does not resolve to an exact Human "
            "research_revision/revise Decision",
        )

    def test_instrument_must_be_approved_with_decision(self):
        message = (
            "Virtual Runner requires the PR40 canonical Instrument to be approved "
            "with its decision binding"
        )
        for change in ({"approval_status": "draft"}, {"approval_decision_id": ""}):
            with self.subTest(change=change):
                self.record = instrument_record()
                self.record["questionnaire"].update(change)
                self.assert_rejected("VR-HUMAN-DECISION-001", message)

    def test_material_instrument_revision_needs_decision(self):
        self.record["questionnaire"]["material_revision"] = True
        self.assert_rejected(
            "VR-HUMAN-DECISION-001",
            "material Instrument revision lacks material_revision_decision_id",
        )

    def test_stale_instrument_provenance(self):
        message = (
            "Instrument provenance is stale relative to the current Research "
            "Snapshot/Profile/Project Config"
        )
        mutations = (
            lambda: self.record["captured_against"].update(lineage_ref="LIN-OLD"),
            lambda: self.record["captured_against"].update(snapshot_ref="SNP-OLD"),
            lambda: self.record["captured_against"].update(snapshot_digest="sha256:old"),
            lambda: self.record.update(project_config_digest="sha256:old"),
            lambda: self.record.update(effective_profile_set_digest="sha256:old"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.record = instrument_record()
                mutate()
                self.assert_rejected("APPLICATION-VIRTUAL-PIN-001", message)

    def test_stale_design_binding(self):
        message = "Survey Design binding is stale or inconsistent"
        self.design["captured_against"] = {**captured(), "snapshot_ref": "SNP-OTHER"}
        self.assert_rejected("APPLICATION-VIRTUAL-PIN-001", message)
        self.design = design_record()
        self.design["design"]["content_digest"] = "sha256:other"
        self.assert_rejected("APPLICATION-VIRTUAL-PIN-001", message)

    def test_effective_profile_set_digest_is_checked(self):
        self.facade.profile_set = deepcopy(self.facade.profile_set)
        self.facade.profile_set["content_digest"] = "sha256:other"
        self.assert_rejected(
            "APPLICATION-VIRTUAL-PIN-001",
            "Effective Profile Set does not match current Research State digest",
        )


class ProtocolRevisionDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = FakeState()

    def check(self, record) -> bool:
        self.state.decisions[record["id"]] = record
        return _protocol_revision_decision_for(self.state, record["id"], protocol_id=PROTOCOL_ID)

    def test_accepts_human_revise_for_protocol(self):
        good = decision("DEC-P", "research_revision", "revise", "protocol", PROTOCOL_ID)
        good["subjects"].insert(0, "not-a-mapping")
        self.assertTrue(self.check(good))

    def test_rejects_missing_non_human_or_mismatched_decision(self):
        self.assertFalse(
            _protocol_revision_decision_for(self.state, "DEC-404", protocol_id=PROTOCOL_ID)
        )
        good = decision("DEC-P", "research_revision", "revise", "protocol", PROTOCOL_ID)
        for change in (
            {"actor_type": "agent"},
            {"decision_kind": "research_adoption"},
            {"choice": "approve"},
            {"subjects": [{"kind": "protocol", "id": "PROTOCOL-OTHER"}]},
            {"subjects": [{"kind": "method", "id": PROTOCOL_ID}]},
        ):
            with self.subTest(change=change):
                self.assertFalse(self.check({**good, **change}))


if __name__ == "__main__":
    unittest.main()
