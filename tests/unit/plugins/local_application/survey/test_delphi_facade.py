"""Characterization tests for ``plugins/local_application/survey/delphi_facade.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They pin the module validators and ``DelphiMixin``: Design, Instrument and
Round capture (accept and reject branches), Round 2 lineage, controlled
feedback, legacy recalculation, bounded panel inspection and stopping
candidates. The flows reuse the two-round production fixtures in
``tests.runtime.test_delphi_two_round_production`` and the lifecycle helpers
in ``tests.runtime.test_issue252_delphi_lifecycle``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.survey.delphi_analysis import ANALYSIS_CONTRACT
from plugins.local_application.survey.delphi_facade import (
    DelphiMixin,
    _item_map,
    _revision,
    _schema_instrument,
    _str,
    _str_list,
)
from plugins.local_delphi_store import LocalDelphiStoreError
from tests.runtime.test_delphi_two_round_production import (
    approve_instrument,
    design,
    instrument,
    make_app,
    response,
    with_digest,
)
from tests.runtime.test_issue252_delphi_lifecycle import derived_from, proposal, round_input
from tests.runtime.test_survey_production import state_signature

INPUT = "APPLICATION-DELPHI-INPUT-001"
BINDING = "APPLICATION-DELPHI-BINDING-001"
LINEAGE = "APPLICATION-DELPHI-LINEAGE-001"
ROUND = "APPLICATION-DELPHI-ROUND-001"
RESPONSE = "APPLICATION-DELPHI-RESPONSE-001"
AUTHORITY = "APPLICATION-DELPHI-AUTHORITY-001"
FEEDBACK = "APPLICATION-DELPHI-FEEDBACK-001"
STOPPING = "APPLICATION-DELPHI-STOPPING-001"
ZERO = "sha256:" + "0" * 64
LEGACY_FIXTURE = (
    Path(__file__).resolve().parents[4] / "runtime" / "fixtures" / "delphi-legacy-mixed-modes.json"
)


def _assert_code(case: unittest.TestCase, code, call, *args, **kwargs):
    with case.assertRaises(LocalApplicationError) as caught:
        call(*args, **kwargs)
    case.assertEqual(caught.exception.code, code)
    return caught.exception


class ValidatorTests(unittest.TestCase):
    def test_str_requires_non_blank_text(self) -> None:
        self.assertEqual(_str("x", "field"), "x")
        for value in ("", "  ", None, 3):
            with self.subTest(value=value):
                error = _assert_code(self, INPUT, _str, value, "field")
                self.assertEqual(error.message, "field must be a non-empty string")

    def test_str_list_requires_unique_non_empty_strings(self) -> None:
        self.assertEqual(_str_list(["a", "b"], "ids"), ["a", "b"])
        self.assertEqual(_str_list([], "ids", allow_empty=True), [])
        for value in ([], ["a", "a"], ["a", ""], [1], "a", None):
            with self.subTest(value=value):
                error = _assert_code(self, INPUT, _str_list, value, "ids")
                self.assertEqual(error.message, "ids must be a unique string array")

    def test_revision_accepts_positive_ascii_integer_strings(self) -> None:
        self.assertEqual(_revision("1"), "1")
        self.assertEqual(_revision("12"), "12")
        for value in ("0", "01", "-1", "x", "", "١", 1, True, None):
            with self.subTest(value=value):
                error = _assert_code(self, INPUT, _revision, value)
                self.assertEqual(error.message, "result version must be a positive integer string")

    def test_item_map_indexes_unique_items(self) -> None:
        item = {"item_id": "ITEM-1"}
        self.assertEqual(_item_map({"items": [item]}), {"ITEM-1": item})
        cases = (
            ({"items": None}, "APPLICATION-DELPHI-INSTRUMENT-001"),
            ({"items": ["x"]}, "APPLICATION-DELPHI-INSTRUMENT-001"),
            ({"items": [item, dict(item)]}, "APPLICATION-DELPHI-INSTRUMENT-001"),
            ({"items": [{"item_id": ""}]}, INPUT),
        )
        for value, code in cases:
            with self.subTest(value=value):
                _assert_code(self, code, _item_map, value)

    def test_schema_instrument_checks_schema_and_digest(self) -> None:
        _schema_instrument(instrument(1))
        tampered = instrument(1)
        tampered["items"][0]["text"] = "changed without a new digest"
        _assert_code(self, "APPLICATION-DELPHI-INSTRUMENT-DIGEST-001", _schema_instrument, tampered)
        broken = instrument(1)
        del broken["items"]
        _assert_code(self, "APPLICATION-DELPHI-INSTRUMENT-SCHEMA-001", _schema_instrument, broken)


class StoreLocationTests(unittest.TestCase):
    def test_workspace_root_wins_over_application_root(self) -> None:
        fake = SimpleNamespace(_workspace_root=Path("/ws"), _application=SimpleNamespace(root="/a"))
        self.assertEqual(
            DelphiMixin._delphi_store(fake).path,
            Path("/ws") / ".research-loom" / "delphi-registry.sqlite3",
        )

    def test_application_root_without_workspace(self) -> None:
        fake = SimpleNamespace(_workspace_root=None, _application=SimpleNamespace(root="/a"))
        self.assertEqual(
            DelphiMixin._delphi_store(fake).path, Path("/a") / "delphi-registry.sqlite3"
        )

    def test_missing_root_fails_closed(self) -> None:
        fake = SimpleNamespace(_workspace_root=None, _application=SimpleNamespace())
        _assert_code(self, "APPLICATION-DELPHI-STORE-001", DelphiMixin._delphi_store, fake)


class _Base(unittest.TestCase):
    capture_design = True

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = make_app(temp.name)
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")
        if self.capture_design:
            self.facade.capture_delphi_design(
                {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()}
            )

    def assertCode(self, code, call, *args, **kwargs):
        return _assert_code(self, code, call, *args, **kwargs)

    def _round1(self, responses=None, inst=None):
        inst = inst or instrument(1)
        approve_instrument(self.facade, proposal(inst))
        result = self.facade.capture_delphi_round(
            round_input(
                inst,
                responses
                or [
                    response("R1-P1", "P1", 1, 1, "cautious"),
                    response("R1-P2", "P2", 1, 5, "bold"),
                ],
            )
        )
        return inst, result

    def _round2(self, inst1, result1, *, responses=None):
        feedback = self.facade.build_delphi_feedback(result1["round_result_id"])
        inst2 = instrument(
            2, feedback_id=feedback["feedback_id"], feedback_digest=feedback["content_digest"]
        )
        approve_instrument(
            self.facade, proposal(inst2, derived=derived_from(inst1, result1, feedback))
        )
        result2 = self.facade.capture_delphi_round(
            round_input(inst2, responses or [response("R2-P1", "P1", 2, 1, "still cautious")])
        )
        return feedback, inst2, result2


class _StoreProxy:
    """Real Delphi store whose ``load`` can be rewritten for one document kind."""

    def __init__(self, store, rewrite) -> None:
        self._store = store
        self._rewrite = rewrite

    def load(self, project_id, kind, identity, version="1"):
        record = self._store.load(project_id, kind, identity, version)
        return self._rewrite(kind, deepcopy(record))

    def __getattr__(self, name):
        return getattr(self._store, name)


class DesignTests(_Base):
    capture_design = False

    def test_capture_show_and_idempotent_recapture(self) -> None:
        before = state_signature(self.app)
        value = {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()}
        captured = self.facade.capture_delphi_design(value)
        self.assertEqual(
            captured,
            {
                "status": "CAPTURED",
                "delphi_design_id": "DLD-1",
                "version": "1.0.0",
                "panel_id": "PANEL-1",
                "content_digest": design()["content_digest"],
            },
        )
        self.assertEqual(self.facade.capture_delphi_design(value)["status"], "ALREADY_CAPTURED")
        shown = self.facade.show_delphi_design("DLD-1", "1.0.0")
        self.assertEqual(shown["status"], "OK")
        record = shown["delphi_design"]
        self.assertEqual(record["document_kind"], "design")
        self.assertEqual(record["rq_ids"], ["RQ-1"])
        self.assertIsNone(record["round_sequence"])
        self.assertEqual(record["captured_against"]["snapshot_ref"], "SNP-DL-0")
        self.assertEqual(state_signature(self.app), before)

    def test_show_unknown_design(self) -> None:
        error = self.assertCode(
            "APPLICATION-DELPHI-DESIGN-001", self.facade.show_delphi_design, "DLD-1", "9"
        )
        self.assertEqual(error.message, "unknown Delphi Design revision")
        self.assertCode(INPUT, self.facade.show_delphi_design, "", "1")

    def test_input_shape_errors(self) -> None:
        good = {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()}
        for value in (
            [],
            {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1"},
            {**good, "extra": 1},
            {**good, "rq_ids": []},
            {**good, "panel_id": " "},
            {**good, "design": "not an object"},
        ):
            with self.subTest(value=value if not isinstance(value, dict) else sorted(value)):
                self.assertCode(INPUT, self.facade.capture_delphi_design, value)

    def test_schema_and_digest_errors(self) -> None:
        broken = design()
        del broken["planned_rounds"]
        self.assertCode(
            "APPLICATION-DELPHI-DESIGN-SCHEMA-001",
            self.facade.capture_delphi_design,
            {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": broken},
        )
        tampered = design()
        tampered["purpose"]["intended_use"] = "changed without a new digest"
        self.assertCode(
            "APPLICATION-DELPHI-DESIGN-DIGEST-001",
            self.facade.capture_delphi_design,
            {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": tampered},
        )

    def test_only_exact_two_round_plans_are_accepted(self) -> None:
        one_extra = design()
        one_extra["planned_rounds"]["round_plan"] = [{"sequence": 1}, {"sequence": 3}]
        for value in (design(maximum_rounds=3), with_digest(one_extra)):
            with self.subTest():
                error = self.assertCode(
                    ROUND,
                    self.facade.capture_delphi_design,
                    {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": value},
                )
                self.assertEqual(
                    error.message,
                    "the production slice requires exactly approved Round 1 and Round 2 plans",
                )

    def test_unknown_research_question_is_rejected(self) -> None:
        self.assertCode(
            "APPLICATION-SURVEY-RQ-001",
            self.facade.capture_delphi_design,
            {"rq_ids": ["RQ-UNKNOWN"], "panel_id": "PANEL-1", "design": design()},
        )

    def test_store_error_is_translated(self) -> None:
        store = self.facade._delphi_store()

        def fail(_document):
            raise LocalDelphiStoreError("DELPHI-X", "denied")

        with patch.object(self.facade, "_delphi_store", return_value=store):
            with patch.object(store, "capture", side_effect=fail):
                error = self.assertCode(
                    "DELPHI-X",
                    self.facade.capture_delphi_design,
                    {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()},
                )
        self.assertEqual(error.message, "denied")


class InstrumentTests(_Base):
    def _candidate(self, round_sequence=1, **changes):
        value = instrument(round_sequence)
        value["approval_status"] = "candidate"
        value.pop("approval_decision_id", None)
        value.update(changes)
        return with_digest(value)

    def test_candidate_instrument_is_captured_without_approval(self) -> None:
        inst = self._candidate(material_revision=False)
        captured = self.facade.capture_delphi_instrument(proposal(inst))
        self.assertEqual(
            captured,
            {
                "status": "CAPTURED",
                "instrument_id": "DLI-R1",
                "version": "1.0.0",
                "panel_id": "PANEL-1",
                "round_sequence": 1,
                "content_digest": inst["content_digest"],
            },
        )
        record = self.facade.show_delphi_instrument("DLI-R1", "1.0.0")["delphi_instrument"]
        self.assertEqual(record["design_ref"]["delphi_design_id"], "DLD-1")
        self.assertIsNone(record["derived_from"])
        self.assertEqual(
            self.facade.capture_delphi_instrument(proposal(inst))["status"], "ALREADY_CAPTURED"
        )

    def test_candidate_material_revision_requires_approval(self) -> None:
        inst = self._candidate(material_revision=True, material_revision_decision_id="DEC-X")
        error = self.assertCode(AUTHORITY, self.facade.capture_delphi_instrument, proposal(inst))
        self.assertEqual(error.message, "material revision requires exact Instrument approval")

    def test_approved_label_without_receipt_is_rejected(self) -> None:
        self.assertCode(AUTHORITY, self.facade.capture_delphi_instrument, proposal(instrument(1)))

    def test_approved_instrument_is_returned_from_the_approval_request(self) -> None:
        inst = instrument(1)
        approve_instrument(self.facade, proposal(inst))
        recaptured = self.facade.capture_delphi_instrument(proposal(inst))
        self.assertEqual(recaptured["status"], "ALREADY_CAPTURED")
        self.assertEqual(recaptured["content_digest"], inst["content_digest"])

    def test_approval_request_is_delegated_and_inspectable(self) -> None:
        request = self.facade.request_delphi_instrument_approval(
            {**proposal(instrument(1)), "human_actor_id": "operator"}
        )
        shown = self.facade.show_delphi_instrument_approval(request["request_id"])
        self.assertEqual(shown["status"], "PENDING")
        self.assertIn(request["request_id"], json.dumps(shown))

    def test_show_unknown_instrument(self) -> None:
        error = self.assertCode(
            "APPLICATION-DELPHI-INSTRUMENT-001",
            self.facade.show_delphi_instrument,
            "DLI-R1",
            "1.0.0",
        )
        self.assertEqual(error.message, "unknown Delphi Instrument revision")

    def test_input_and_binding_errors(self) -> None:
        inst = self._candidate()
        cases = (
            ([], INPUT),
            ({**proposal(inst), "extra": 1}, INPUT),
            ({**proposal(inst), "delphi_design_id": ""}, INPUT),
            ({**proposal(inst), "panel_id": "PANEL-2"}, BINDING),
            ({**proposal(inst), "delphi_design_version": "9.9.9"}, BINDING),
            ({**proposal(inst), "instrument": "not an object"}, INPUT),
        )
        for value, code in cases:
            with self.subTest(code=code):
                self.assertCode(code, self.facade.capture_delphi_instrument, value)

    def test_round_sequence_outside_slice_is_rejected(self) -> None:
        inst = self._candidate(round_sequence=3)
        error = self.assertCode(ROUND, self.facade.capture_delphi_instrument, proposal(inst))
        self.assertEqual(error.message, "production slice supports exactly Round 1 and Round 2")

    def test_round1_must_not_claim_derivation(self) -> None:
        error = self.assertCode(
            LINEAGE,
            self.facade.capture_delphi_instrument,
            proposal(self._candidate(), derived={"prior_instrument_id": "X"}),
        )
        self.assertEqual(error.message, "Round 1 must not claim prior-round derivation")


class Round2LineageTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.inst1, self.result1 = self._round1()
        self.feedback = self.facade.build_delphi_feedback(self.result1["round_result_id"])
        self.derived = derived_from(self.inst1, self.result1, self.feedback)

    def _inst2(self, mutate=None):
        value = instrument(
            2,
            feedback_id=self.feedback["feedback_id"],
            feedback_digest=self.feedback["content_digest"],
        )
        if mutate is not None:
            mutate(value)
        return with_digest(value)

    def _lineage_error(self, inst, derived):
        return self.assertCode(
            LINEAGE, self.facade.capture_delphi_instrument, proposal(inst, derived=derived)
        )

    def test_derivation_shape_is_exact(self) -> None:
        message = "Round 2 requires exact prior Instrument, Round 1 result, and feedback bindings"
        incomplete = dict(self.derived)
        incomplete.pop("feedback_digest")
        for derived in (None, "x", incomplete, {**self.derived, "extra": 1}):
            with self.subTest(
                derived=derived if not isinstance(derived, dict) else sorted(derived)
            ):
                value = proposal(self._inst2())
                if derived is not None:
                    value["derived_from"] = derived
                error = self.assertCode(LINEAGE, self.facade.capture_delphi_instrument, value)
                self.assertEqual(error.message, message)

    def test_stale_or_mismatched_bindings(self) -> None:
        for field, value in (
            ("prior_instrument_digest", ZERO),
            ("prior_round_result_digest", ZERO),
            ("feedback_digest", ZERO),
            ("feedback_id", "DLF-UNKNOWN"),
            ("prior_round_result_version", "2"),
        ):
            with self.subTest(field=field):
                error = self._lineage_error(self._inst2(), {**self.derived, field: value})
                self.assertEqual(error.message, "Round 2 derivation binding is stale or mismatched")

    def test_invalid_prior_result_version_is_input_error(self) -> None:
        self.assertCode(
            INPUT,
            self.facade.capture_delphi_instrument,
            proposal(self._inst2(), derived={**self.derived, "prior_round_result_version": "01"}),
        )

    def test_revision_changes_are_required(self) -> None:
        inst = self._inst2(lambda value: value.update({"revision_changes": []}))
        error = self._lineage_error(inst, self.derived)
        self.assertEqual(error.message, "Round 2 must record explicit revision changes")

    def test_retained_items_need_prior_item_and_feedback_lineage(self) -> None:
        mutations = (
            lambda value: value["items"][0].update({"lineage": {"lifecycle": "new"}}),
            lambda value: value["items"][0]["lineage"].update({"prior_item_revision": 7}),
            lambda value: value["items"][0].update({"controlled_feedback": {}}),
        )
        for mutate in mutations:
            with self.subTest():
                error = self._lineage_error(self._inst2(mutate), self.derived)
                self.assertEqual(
                    error.message,
                    "retained Round 2 items require explicit prior-item and controlled-feedback lineage",
                )

    def test_new_items_do_not_need_lineage(self) -> None:
        def add_item(value):
            extra = deepcopy(value["items"][0])
            extra.update(
                {
                    "item_id": "ITEM-NEW",
                    "item_revision": 1,
                    "lineage": {"lifecycle": "new"},
                    "controlled_feedback": {},
                }
            )
            value["items"].append(extra)
            value["approval_status"] = "candidate"
            value["material_revision"] = False
            value.pop("approval_decision_id")

        captured = self.facade.capture_delphi_instrument(
            proposal(self._inst2(add_item), derived=self.derived)
        )
        self.assertEqual(captured["round_sequence"], 2)
        record = self.facade.show_delphi_instrument("DLI-R2", "1.0.0")["delphi_instrument"]
        self.assertEqual(record["derived_from"], self.derived)

    def test_round2_capture_rejects_a_stale_bound_round1(self) -> None:
        inst2 = self._inst2()
        approve_instrument(self.facade, proposal(inst2, derived=self.derived))
        store = self.facade._delphi_store()

        def stale(kind, record):
            if kind == "round" and record is not None:
                record["content_digest"] = ZERO
            return record

        with patch.object(self.facade, "_delphi_store", return_value=_StoreProxy(store, stale)):
            error = self.assertCode(
                LINEAGE,
                self.facade.capture_delphi_round,
                round_input(inst2, [response("R2-P1", "P1", 2, 1, "x")]),
            )
        self.assertEqual(
            error.message, "Round 2 requires its exact bound Round 1 revision and Instrument"
        )


class RoundCaptureTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.inst = instrument(1, response_modes=["rating", "ranking", "free_text_rationale"])
        approve_instrument(self.facade, proposal(self.inst))

    def _answer(self, **fields):
        return {"item_id": "ITEM-1", "item_revision": 1, "state": "answered", "rating": 3, **fields}

    def _submit(self, answers=None, *, responses=None, expected=None, **overrides):
        if responses is None:
            responses = [
                {
                    "response_id": "R1-P1",
                    "participant_id": "P1",
                    "answers": [self._answer()] if answers is None else answers,
                }
            ]
        value = round_input(self.inst, responses, expected=expected)
        value.update(overrides)
        return self.facade.capture_delphi_round(value)

    def test_capture_and_idempotent_recapture(self) -> None:
        before = state_signature(self.app)
        first = self._submit()
        self.assertEqual(first["status"], "CAPTURED")
        self.assertEqual(first["round_result_id"], "DLR-PANEL-1-R1")
        self.assertEqual(first["round_result_version"], "1")
        self.assertEqual(first["round_sequence"], 1)
        self.assertEqual(first["analysis"]["analysis_contract"], ANALYSIS_CONTRACT)
        self.assertEqual(first["analysis"]["missing_response_count"], 2)
        again = self._submit()
        self.assertEqual(again["status"], "ALREADY_CAPTURED")
        self.assertEqual(again["content_digest"], first["content_digest"])
        stored = self.facade.show_delphi_round("DLR-PANEL-1-R1")["delphi_round"]
        self.assertTrue(stored["candidate_only"])
        self.assertFalse(stored["research_state_mutation_performed"])
        self.assertEqual(
            stored["responses"][0]["binding"],
            {
                "panel_id": "PANEL-1",
                "round_sequence": 1,
                "instrument_id": "DLI-R1",
                "instrument_version": "1.0.0",
                "instrument_digest": self.inst["content_digest"],
            },
        )
        self.assertEqual(state_signature(self.app), before)

    def test_non_answered_states_are_preserved(self) -> None:
        answers = [{"item_id": "ITEM-1", "item_revision": 1, "state": "prefer_not_to_answer"}]
        result = self._submit(answers)
        self.assertEqual(result["status"], "CAPTURED")

    def test_input_shape_and_binding_errors(self) -> None:
        self.assertCode(INPUT, self.facade.capture_delphi_round, [])
        self.assertCode(INPUT, self.facade.capture_delphi_round, {"panel_id": "PANEL-1"})
        for overrides in (
            {"panel_id": "PANEL-2"},
            {"instrument_digest": ZERO},
            {"instrument_version": "9.9.9"},
        ):
            with self.subTest(overrides=overrides):
                error = self.assertCode(BINDING, self._submit, **overrides)
                self.assertEqual(
                    error.message, "Round response Instrument/panel binding is invalid"
                )
        self.assertCode(INPUT, self._submit, expected_participant_ids=[])
        self.assertCode(INPUT, self._submit, responses="not a list")

    def test_candidate_instrument_cannot_take_responses(self) -> None:
        candidate = instrument(1, version="2.0.0")
        candidate["approval_status"] = "candidate"
        candidate.pop("approval_decision_id")
        candidate = with_digest(candidate)
        self.facade.capture_delphi_instrument(proposal(candidate))
        self.assertCode(
            AUTHORITY,
            self.facade.capture_delphi_round,
            round_input(candidate, [response("R1-P1", "P1", 1, 3, "x")]),
        )

    def test_response_identity_errors(self) -> None:
        ok = {"response_id": "R1-P1", "participant_id": "P1", "answers": [self._answer()]}
        cases = (
            ([["not a mapping"]], "Delphi response shape is invalid"),
            ([{**ok, "extra": 1}], "Delphi response shape is invalid"),
            (
                [ok, {**ok, "participant_id": "P2"}],
                "duplicate or unexpected Delphi response identity",
            ),
            (
                [ok, {**ok, "response_id": "R1-P1b"}],
                "duplicate or unexpected Delphi response identity",
            ),
            ([{**ok, "participant_id": "P9"}], "duplicate or unexpected Delphi response identity"),
            ([{**ok, "answers": "x"}], "answers must be an array"),
        )
        for responses, message in cases:
            with self.subTest(message=message):
                responses = [item[0] if isinstance(item, list) else item for item in responses]
                error = self.assertCode(RESPONSE, self._submit, responses=responses)
                self.assertEqual(error.message, message)

    def test_answer_binding_errors(self) -> None:
        message = "answer item revision does not match the bound Instrument"
        for answers in (
            [self._answer(item_id="ITEM-X")],
            [self._answer(item_revision=2)],
            [self._answer(item_revision=True)],
            [self._answer(), self._answer()],
        ):
            with self.subTest(answers=answers):
                error = self.assertCode(BINDING, self._submit, answers)
                self.assertEqual(error.message, message)

    def test_answer_value_errors(self) -> None:
        missing_state = {"item_id": "ITEM-1", "item_revision": 1, "state": "missing"}
        cases = (
            (["x"], "answer must be an object"),
            ([self._answer(extra=1)], "answer contains unknown fields"),
            ([self._answer(state="skipped")], "unsupported Delphi answer state"),
            (
                [self._answer(probability=0.5)],
                "answer uses a response mode not allowed by the Instrument",
            ),
            (
                [{"item_id": "ITEM-1", "item_revision": 1, "state": "answered"}],
                "answered Delphi item requires a response value",
            ),
            (
                [{**missing_state, "rating": 3}],
                "non-answered Delphi item must not carry response values",
            ),
            ([self._answer(ranking="a")], "ranking must be a string array"),
            ([self._answer(ranking=["a", ""])], "ranking must be a string array"),
            ([self._answer(rationale=" ")], "rationale must be non-empty"),
            ([], "each submitted response must preserve an answer state for every Instrument item"),
        )
        for answers, message in cases:
            with self.subTest(message=message):
                error = self.assertCode(RESPONSE, self._submit, answers)
                self.assertEqual(error.message, message)

    def test_answer_item_id_must_be_a_string(self) -> None:
        self.assertCode(INPUT, self._submit, [self._answer(item_id="")])

    def test_round_store_error_is_translated(self) -> None:
        store = self.facade._delphi_store()

        def fail(_document):
            raise LocalDelphiStoreError("ROUND-X", "denied")

        with patch.object(self.facade, "_delphi_store", return_value=store):
            with patch.object(store, "capture_round_revision", side_effect=fail):
                self.assertCode("ROUND-X", self._submit)


class RoundInspectionTests(_Base):
    def test_show_round_versions_and_unknown(self) -> None:
        _, result = self._round1()
        shown = self.facade.show_delphi_round(result["round_result_id"], "1")
        self.assertEqual(shown["status"], "OK")
        self.assertEqual(shown["delphi_round"]["content_digest"], result["content_digest"])
        error = self.assertCode(ROUND, self.facade.show_delphi_round, "DLR-UNKNOWN")
        self.assertEqual(error.message, "unknown Delphi Round result")
        self.assertCode(INPUT, self.facade.show_delphi_round, result["round_result_id"], "0")

    def test_recalculate_current_round_is_already_calculated(self) -> None:
        _, result = self._round1()
        recalculated = self.facade.recalculate_delphi_round(result["round_result_id"])
        self.assertEqual(recalculated["status"], "ALREADY_CALCULATED")
        self.assertEqual(recalculated["round_result_version"], "1")
        self.assertEqual(recalculated["content_digest"], result["content_digest"])
        self.assertEqual(recalculated["analysis"], result["analysis"])

    def test_inspect_panel_pages_and_groups_documents(self) -> None:
        inst1, result1 = self._round1()
        self._round2(inst1, result1)
        self.facade.build_delphi_stopping_candidate("PANEL-1")
        full = self.facade.inspect_delphi_panel("PANEL-1", limit=100)
        self.assertEqual(full["status"], "OK")
        self.assertFalse(full["truncated"])
        self.assertIsNone(full["next_offset"])
        self.assertEqual(len(full["documents"]), 11)
        self.assertEqual(len(full["rounds"]), 2)
        self.assertEqual(len(full["instruments"]), 2)
        self.assertEqual(len(full["feedback_artifacts"]), 1)
        self.assertEqual(len(full["stopping_candidates"]), 1)
        page = self.facade.inspect_delphi_panel("PANEL-1", limit=3, offset=3)
        self.assertEqual((page["limit"], page["offset"]), (3, 3))
        self.assertTrue(page["truncated"])
        self.assertEqual(page["next_offset"], 6)
        self.assertEqual(page["documents"], full["documents"][3:6])
        self.assertEqual(self.facade.inspect_delphi_panel("PANEL-NONE")["documents"], [])

    def test_inspect_panel_rejects_bad_bounds(self) -> None:
        for kwargs in (
            {"limit": 0},
            {"limit": 101},
            {"limit": True},
            {"offset": -1},
            {"offset": 1.0},
        ):
            with self.subTest(kwargs=kwargs):
                error = self.assertCode(
                    INPUT, self.facade.inspect_delphi_panel, "PANEL-1", **kwargs
                )
                self.assertEqual(
                    error.message, "inspection requires limit 1..100 and a non-negative offset"
                )
        self.assertCode(INPUT, self.facade.inspect_delphi_panel, "")


class FeedbackTests(_Base):
    def test_build_show_and_rebuild_feedback(self) -> None:
        _, result = self._round1()
        feedback = self.facade.build_delphi_feedback(result["round_result_id"])
        self.assertEqual(feedback["status"], "CAPTURED")
        self.assertEqual(
            feedback["feedback_id"],
            "DLF-" + feedback["content_digest"].removeprefix("sha256:")[:24],
        )
        self.assertEqual(feedback["source_round_result_id"], result["round_result_id"])
        self.assertEqual(feedback["source_round_result_version"], "1")
        self.assertEqual(len(feedback["summaries"]), 1)
        again = self.facade.build_delphi_feedback(result["round_result_id"])
        self.assertEqual(again["status"], "ALREADY_CAPTURED")
        stored = self.facade.show_delphi_feedback(feedback["feedback_id"])["delphi_feedback"]
        self.assertTrue(stored["immutable"])
        self.assertTrue(stored["candidate_only"])
        self.assertEqual(stored["source_round_result_digest"], result["content_digest"])

    def test_feedback_requires_a_stored_round1(self) -> None:
        inst1, result1 = self._round1()
        _, _, result2 = self._round2(inst1, result1)
        for round_id in ("DLR-UNKNOWN", result2["round_result_id"]):
            with self.subTest(round_id=round_id):
                error = self.assertCode(FEEDBACK, self.facade.build_delphi_feedback, round_id)
                self.assertEqual(
                    error.message, "controlled feedback requires a stored Round 1 result"
                )
        self.assertCode(INPUT, self.facade.build_delphi_feedback, result1["round_result_id"], "x")

    def test_show_unknown_feedback(self) -> None:
        error = self.assertCode(FEEDBACK, self.facade.show_delphi_feedback, "DLF-UNKNOWN")
        self.assertEqual(error.message, "unknown Delphi feedback artifact")


class LegacyRecalculationTests(_Base):
    capture_design = False

    def test_legacy_round_recalculates_into_a_new_revision(self) -> None:
        fixture = json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8"))
        for document in fixture["documents"]:
            self.facade._delphi_store().capture(document)
        old = fixture["documents"][2]
        self.assertCode(
            "APPLICATION-DELPHI-ANALYSIS-001", self.facade.build_delphi_feedback, old["identity"]
        )
        revised = self.facade.recalculate_delphi_round(old["identity"])
        self.assertEqual(revised["status"], "CAPTURED")
        self.assertEqual(revised["round_result_version"], "2")
        self.assertEqual(revised["analysis"]["analysis_contract"], ANALYSIS_CONTRACT)
        stored = self.facade.show_delphi_round(old["identity"], "2")["delphi_round"]
        self.assertEqual(
            stored["recalculated_from"],
            {
                "round_result_id": old["identity"],
                "version": old["version"],
                "content_digest": old["content_digest"],
            },
        )
        self.assertEqual(stored["responses"], old["responses"])
        self.assertEqual(
            self.facade.recalculate_delphi_round(old["identity"], "2")["status"],
            "ALREADY_CALCULATED",
        )


class StoppingCandidateTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.inst1, self.result1 = self._round1()

    def test_selection_errors(self) -> None:
        error = self.assertCode(
            INPUT, self.facade.build_delphi_stopping_candidate, "PANEL-1", version="1"
        )
        self.assertEqual(error.message, "result version requires round_result_id")
        error = self.assertCode(STOPPING, self.facade.build_delphi_stopping_candidate, "PANEL-1")
        self.assertEqual(
            error.message,
            "select an exact Round 2 result ID and version when results are absent or ambiguous",
        )
        error = self.assertCode(
            STOPPING,
            self.facade.build_delphi_stopping_candidate,
            "PANEL-1",
            round_result_id=self.result1["round_result_id"],
        )
        self.assertEqual(
            error.message, "stopping assessment requires the bound panel's Round 2 result"
        )
        self.assertCode(INPUT, self.facade.build_delphi_stopping_candidate, " ")

    def test_candidate_is_captured_and_shown(self) -> None:
        _, _, result2 = self._round2(self.inst1, self.result1)
        before = state_signature(self.app)
        candidate = self.facade.build_delphi_stopping_candidate("PANEL-1")
        self.assertEqual(candidate["status"], "CAPTURED")
        self.assertEqual(
            candidate["stopping_candidate_id"],
            "DLS-" + candidate["content_digest"].removeprefix("sha256:")[:24],
        )
        self.assertEqual(candidate["round2_result_id"], result2["round_result_id"])
        self.assertEqual(candidate["round2_result_version"], "1")
        self.assertEqual(candidate["recommendation"], "stop")
        self.assertEqual(candidate["rationale"], "maximum approved round count has been reached")
        self.assertEqual(
            candidate["basis"],
            {
                "maximum_approved_rounds": 2,
                "maximum_approved_rounds_reached": True,
                "stability_ratio": 1.0,
                "configured_minimum_stability_ratio": 0.75,
                "stability_goal_satisfied": True,
                "explicit_disagreement_item_count": 0,
                "unassessed_disagreement_item_count": 0,
                "configured_maximum_disagreement_item_count": 0,
                "disagreement_goal_satisfied": True,
                "attrition_count": 1,
                "missing_response_count": 2,
            },
        )
        self.assertTrue(candidate["candidate_only"])
        self.assertTrue(candidate["human_decision_required"])
        self.assertFalse(candidate["research_state_mutation_performed"])
        self.assertEqual(len(candidate["limitations"]), 3)
        explicit = self.facade.build_delphi_stopping_candidate(
            "PANEL-1", round_result_id=result2["round_result_id"], version="1"
        )
        self.assertEqual(explicit["status"], "ALREADY_CAPTURED")
        shown = self.facade.show_delphi_stopping_candidate(candidate["stopping_candidate_id"])
        self.assertEqual(shown["status"], "OK")
        self.assertEqual(
            shown["delphi_stopping_candidate"]["content_digest"], candidate["content_digest"]
        )
        self.assertEqual(state_signature(self.app), before)

    def test_show_unknown_candidate(self) -> None:
        error = self.assertCode(STOPPING, self.facade.show_delphi_stopping_candidate, "DLS-UNKNOWN")
        self.assertEqual(error.message, "unknown Delphi stopping candidate")

    def _with_rewrite(self, rewrite):
        _, _, result2 = self._round2(self.inst1, self.result1)
        store = self.facade._delphi_store()
        return result2, patch.object(
            self.facade, "_delphi_store", return_value=_StoreProxy(store, rewrite)
        )

    def _stopping_error(self, rewrite):
        _, patched = self._with_rewrite(rewrite)
        with patched:
            return self.assertCode(STOPPING, self.facade.build_delphi_stopping_candidate, "PANEL-1")

    def test_stale_round2_bindings_are_rejected(self) -> None:
        def rewriter(kind_name, mutate):
            def rewrite(kind, record):
                if kind == kind_name and record is not None:
                    mutate(record)
                return record

            return rewrite

        cases = (
            (
                "instrument",
                lambda record: record.update({"content_digest": ZERO}),
                "Round 2 Instrument binding is stale or mismatched",
            ),
            (
                "instrument",
                lambda record: record.update({"design_ref": None}),
                "Round 2 Design binding is missing",
            ),
            (
                "design",
                lambda record: record.update({"content_digest": ZERO}),
                "bound Delphi Design is stale or mismatched",
            ),
        )
        for kind, mutate, message in cases:
            with self.subTest(message=message):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                self.app = make_app(temp.name)
                self.addCleanup(self.app.close)
                self.facade = LocalApplicationFacade(self.app, "PRJ-1")
                self.facade.capture_delphi_design(
                    {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()}
                )
                self.inst1, self.result1 = self._round1()
                error = self._stopping_error(rewriter(kind, mutate))
                self.assertEqual(error.message, message)

    def test_round2_without_instrument_binding_is_rejected(self) -> None:
        def rewrite(kind, record):
            if kind == "round" and record is not None:
                record["instrument_ref"] = None
            return record

        result2, patched = self._with_rewrite(rewrite)
        with patched:
            error = self.assertCode(
                STOPPING,
                self.facade.build_delphi_stopping_candidate,
                "PANEL-1",
                round_result_id=result2["round_result_id"],
            )
        self.assertEqual(error.message, "Round 2 Instrument binding is missing")

    def _candidate_with_design(self, mutate_design):
        def rewrite(kind, record):
            if kind == "design" and record is not None:
                mutate_design(record["design"])
            return record

        _, patched = self._with_rewrite(rewrite)
        with patched:
            return self.facade.build_delphi_stopping_candidate("PANEL-1")

    def test_goal_evaluation_when_more_rounds_remain(self) -> None:
        # Design capture only admits two-round plans, so a stored three-round
        # plan is reached only by rewriting the loaded record.
        def three_rounds(value):
            value["planned_rounds"]["maximum_approved_rounds"] = 3

        candidate = self._candidate_with_design(three_rounds)
        self.assertEqual(candidate["recommendation"], "stop")
        self.assertEqual(
            candidate["rationale"], "configured stability and disagreement goals are satisfied"
        )
        self.assertFalse(candidate["basis"]["maximum_approved_rounds_reached"])

    def test_unconfigured_goals_continue_when_more_rounds_remain(self) -> None:
        def no_goals(value):
            value["planned_rounds"]["maximum_approved_rounds"] = 3
            value["stopping"]["stability_goal"] = {"minimum_ratio": True}
            value["stopping"]["consensus_goal"] = "not a mapping"

        candidate = self._candidate_with_design(no_goals)
        self.assertEqual(candidate["recommendation"], "continue")
        self.assertEqual(
            candidate["rationale"],
            "approved rounds remain and configured stopping goals are not both satisfied",
        )
        self.assertIsNone(candidate["basis"]["stability_goal_satisfied"])
        self.assertIsNone(candidate["basis"]["disagreement_goal_satisfied"])
        self.assertIsNone(candidate["basis"]["configured_maximum_disagreement_item_count"])


if __name__ == "__main__":
    unittest.main()
