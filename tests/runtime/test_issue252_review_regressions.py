"""Regression controls for the first PR #280 review generation."""
from copy import deepcopy
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.delphi_analysis import analyze_round
from tests.runtime.test_delphi_two_round_production import (
    approve_instrument, design, instrument, make_app, response,
)
from tests.runtime.test_issue252_delphi_lifecycle import proposal, round_input


class DelphiReviewRegressions(unittest.TestCase):
    def test_late_revision_cannot_add_or_remove_expected_participants(self):
        with tempfile.TemporaryDirectory() as root:
            app = make_app(root)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
                inst = instrument(1)
                approve_instrument(facade, proposal(inst))
                initial = round_input(inst, [response("R1-P1", "P1", 1, 2, "first")])
                first = facade.capture_delphi_round(initial)
                before = facade.show_delphi_round(first["round_result_id"])["delphi_round"]
                for expected in (["P1", "P2", "P3", "P4"], ["P1", "P2"]):
                    with self.subTest(expected=expected):
                        changed = {**deepcopy(initial), "expected_participant_ids": expected}
                        with self.assertRaises(LocalApplicationError) as caught:
                            facade.capture_delphi_round(changed)
                        self.assertEqual(caught.exception.code, "DELPHI-STORE-CONFLICT-001")
                        self.assertEqual(len(facade.inspect_delphi_panel("PANEL-1")["rounds"]), 1)
                later = deepcopy(initial)
                later["expected_participant_ids"].reverse()
                later["responses"].append(response("R1-P2", "P2", 1, 4, "late"))
                second = facade.capture_delphi_round(later)
                self.assertEqual(second["round_result_version"], "2")
                self.assertEqual(facade.capture_delphi_round(later)["round_result_version"], "2")
                self.assertEqual(facade.capture_delphi_round(initial)["round_result_version"], "1")
                self.assertEqual(facade.show_delphi_round(first["round_result_id"])["delphi_round"], before)
            finally:
                app.close()

    def test_item_analysis_indexes_each_answer_array_once(self):
        class CountedAnswers(list):
            def __init__(self, values):
                super().__init__(values)
                self.visits = 0

            def __iter__(self):
                for value in super().__iter__():
                    self.visits += 1
                    yield value

        inst = instrument(1)
        inst["items"] = [{**deepcopy(inst["items"][0]), "item_id": f"I-{index}"} for index in range(20)]
        responses = []
        for index in range(4):
            row = response(f"R-{index}", f"P-{index}", 1, index + 1, "reason")
            row["answers"] = CountedAnswers([
                {**deepcopy(row["answers"][0]), "item_id": item["item_id"]} for item in inst["items"]
            ])
            responses.append(row)
        items, analysis = analyze_round(inst, responses, [row["participant_id"] for row in responses])
        self.assertEqual(len(items), 20)
        self.assertEqual([item["numeric_summary"]["median"] for item in items], [2.5] * 20)
        self.assertEqual(analysis["explicit_disagreement_item_count"], 20)
        self.assertEqual(sum(row["answers"].visits for row in responses), 4 * 20)
