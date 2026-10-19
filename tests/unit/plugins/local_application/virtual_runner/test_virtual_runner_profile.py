"""Characterization tests for ``plugins.local_application.virtual_runner.virtual_runner_profile`` (#507).

They pin how the Virtual Runner projects an Effective Profile Set into a
digest-checked pin (``_profile_set_pin``) and how it recognizes an approving
Human adoption Decision for a subject (``_approved_decision_for``).
"""

from __future__ import annotations

import unittest

from plugins.application_errors import LocalApplicationError
from plugins.local_application.virtual_runner.virtual_runner_profile import (
    _approved_decision_for,
    _profile_set_pin,
)
from tests.runtime.runtime_fixtures import decision

DIGEST = "sha256:" + "e" * 64
PIN_CODE = "APPLICATION-VIRTUAL-PIN-001"


def profile(profile_id: str = "P-1", **extra) -> dict:
    return {
        "profile_id": profile_id,
        "profile_type": "organization",
        "profile_version": "1.0.0",
        "manifest_sha256": "sha256:" + "1" * 64,
        **extra,
    }


def effective_set(**overrides) -> dict:
    value = {
        "schema_version": "0.1.0",
        "core_contracts": {"core": "0.1.0"},
        "profile_pins": [profile(source="extra-field")],
        "content_digest": DIGEST,
    }
    value.update(overrides)
    return value


class DecisionState:
    def __init__(self, *decisions: dict) -> None:
        self._decisions = {item["id"]: item for item in decisions}

    def decision(self, decision_id: str):
        return self._decisions.get(decision_id)


class ProfileSetPinTests(unittest.TestCase):
    def test_projects_only_pin_fields_and_expected_digest(self):
        source = effective_set()
        pin = _profile_set_pin(source, DIGEST)
        self.assertEqual(
            pin,
            {
                "schema_version": "0.1.0",
                "core_contracts": {"core": "0.1.0"},
                "profile_pins": [profile()],
                "content_digest": DIGEST,
            },
        )
        self.assertIsNot(pin["core_contracts"], source["core_contracts"])

    def test_falls_back_to_effective_profiles(self):
        source = effective_set(effective_profiles=[profile("P-2")])
        del source["profile_pins"]
        self.assertEqual(_profile_set_pin(source, DIGEST)["profile_pins"], [profile("P-2")])

    def test_profile_pins_take_precedence_over_effective_profiles(self):
        source = effective_set(effective_profiles=[profile("P-2")])
        self.assertEqual(_profile_set_pin(source, DIGEST)["profile_pins"], [profile()])

    def test_rejects_digest_mismatch(self):
        with self.assertRaises(LocalApplicationError) as caught:
            _profile_set_pin(effective_set(), "sha256:" + "f" * 64)
        self.assertEqual(caught.exception.code, PIN_CODE)
        self.assertEqual(
            caught.exception.message,
            "Effective Profile Set does not match current Research State digest",
        )

    def test_rejects_missing_or_non_list_profiles(self):
        missing = effective_set()
        del missing["profile_pins"]
        for source in (missing, effective_set(profile_pins={"P-1": profile()})):
            with self.subTest(source=source):
                with self.assertRaises(LocalApplicationError) as caught:
                    _profile_set_pin(source, DIGEST)
                self.assertEqual(caught.exception.code, PIN_CODE)
                self.assertEqual(
                    caught.exception.message,
                    "Effective Profile Set has no projectable profile pins",
                )

    def test_rejects_malformed_pins(self):
        incomplete = profile()
        del incomplete["manifest_sha256"]
        no_contracts = effective_set()
        del no_contracts["core_contracts"]
        for source in (
            effective_set(profile_pins=[incomplete]),
            effective_set(profile_pins=["P-1"]),
            no_contracts,
        ):
            with self.subTest(source=source):
                with self.assertRaises(LocalApplicationError) as caught:
                    _profile_set_pin(source, DIGEST)
                self.assertEqual(caught.exception.code, PIN_CODE)
                self.assertEqual(
                    caught.exception.message,
                    "Effective Profile Set profile pins are malformed",
                )
                self.assertIsInstance(caught.exception.__cause__, (KeyError, TypeError))


class ApprovedDecisionForTests(unittest.TestCase):
    def check(self, record, *, subject_kind="method", subject_id="METHOD-1") -> bool:
        state = DecisionState(record)
        return _approved_decision_for(
            state, record["id"], subject_kind=subject_kind, subject_id=subject_id
        )

    def test_accepts_human_research_adoption_approve_for_subject(self):
        self.assertTrue(
            self.check(decision("DEC-1", "research_adoption", "approve", "method", "METHOD-1"))
        )

    def test_unknown_decision_is_not_approved(self):
        self.assertFalse(
            _approved_decision_for(
                DecisionState(), "DEC-404", subject_kind="method", subject_id="METHOD-1"
            )
        )

    def test_rejects_non_human_wrong_kind_choice_or_subject(self):
        good = decision("DEC-1", "research_adoption", "approve", "method", "METHOD-1")
        cases = {
            "agent": {**good, "actor_type": "agent"},
            "kind": {**good, "decision_kind": "research_revision"},
            "choice": {**good, "choice": "reject"},
            "subject_id": {**good, "subjects": [{"kind": "method", "id": "METHOD-2"}]},
            "subject_kind": {**good, "subjects": [{"kind": "protocol", "id": "METHOD-1"}]},
            "no_subjects": {key: value for key, value in good.items() if key != "subjects"},
        }
        for name, record in cases.items():
            with self.subTest(name=name):
                self.assertFalse(self.check(record))

    def test_non_mapping_subjects_are_ignored(self):
        record = decision("DEC-1", "research_adoption", "approve", "method", "METHOD-1")
        record["subjects"] = ["method:METHOD-1", *record["subjects"]]
        self.assertTrue(self.check(record))


if __name__ == "__main__":
    unittest.main()
