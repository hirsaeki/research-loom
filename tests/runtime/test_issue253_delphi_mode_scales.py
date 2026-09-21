from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.delphi_analysis import ANALYSIS_CONTRACT
from tests.runtime.test_delphi_two_round_production import make_app, design, instrument, response, with_digest, approve_instrument
from tests.runtime.test_issue252_delphi_lifecycle import proposal, round_input, derived_from
from tests.runtime.test_survey_production import state_signature


class Issue253DelphiModeScaleTests(unittest.TestCase):
    def fixture(self, root, modes=None, configure=None):
        app = make_app(root)
        facade = LocalApplicationFacade(app, "PRJ-1")
        facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
        inst = instrument(1, response_modes=modes or ["rating", "probability", "free_text_rationale"])
        if configure:
            configure(inst)
        approve_instrument(facade, proposal(inst))
        return app, facade, inst

    def test_different_modes_never_share_a_median_or_false_disagreement(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, inst = self.fixture(temp)
            try:
                before = state_signature(app)
                result = facade.capture_delphi_round(round_input(inst, [response("A", "P1", 1, 5, "rating"), response("B", "P2", 1, 0.8, "probability", mode="probability")]))
                item = result["item_analysis"][0]
                self.assertIsNone(item["numeric_summary"])
                self.assertEqual({g["response_mode"]: g["numeric_summary"]["median"] for g in item["mode_summaries"]}, {"rating": 5, "probability": 0.8})
                self.assertFalse(item["explicit_disagreement"])
                self.assertEqual(result["analysis"]["missing_response_count"], 1)
                self.assertEqual(result["analysis"]["unassessed_disagreement_item_count"], 0)
                feedback = facade.build_delphi_feedback(result["round_result_id"])
                self.assertEqual(feedback["summaries"][0]["rationales"], ["rating", "probability"])
                self.assertNotIn("participant_id", json.dumps(feedback["summaries"]))
                self.assertEqual(state_signature(app), before)
            finally:
                app.close()

    def test_all_numeric_fields_and_ranking_survive_with_separate_denominators(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, inst = self.fixture(temp, ["rating", "probability", "confidence", "ranking", "free_text_rationale"])
            try:
                a = response("A", "P1", 1, 1, "minority view")
                a["answers"][0].update(probability=0.1, confidence=0.8, ranking=["A", "B"])
                b = response("B", "P2", 1, 5, "different view")
                b["answers"][0].update(probability=0.9, confidence=0.8, ranking=["B", "A"])
                c = {"response_id": "C", "participant_id": "P3", "answers": [{"item_id": "ITEM-1", "item_revision": 1, "state": "prefer_not_to_answer"}]}
                result = facade.capture_delphi_round(round_input(inst, [a, b, c]))
                item = result["item_analysis"][0]; groups = {g["response_mode"]: g for g in item["mode_summaries"]}
                self.assertEqual(set(groups), {"rating", "probability", "confidence", "ranking"})
                self.assertEqual([groups[m]["numeric_summary"]["median"] for m in ("rating", "probability", "confidence")], [3, 0.5, 0.8])
                self.assertEqual(groups["ranking"]["answered_count"], 2)
                self.assertTrue(groups["ranking"]["explicit_disagreement"])
                self.assertTrue(all(g["missing_value_count"] == 1 for g in groups.values()))
                self.assertEqual(item["missing_states"]["prefer_not_to_answer"], 1)
                feedback = facade.build_delphi_feedback(result["round_result_id"])["summaries"][0]
                self.assertEqual({p["response_mode"] for p in feedback["minority_positions"]}, {"rating", "probability"})
                self.assertNotIn("participant_id", json.dumps(feedback))
                self.assertEqual(feedback["rationales"], ["minority view", "different view"])
            finally:
                app.close()

    def test_unknown_scale_preserves_values_without_inventing_statistics(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, inst = self.fixture(temp, ["rating", "free_text_rationale"], lambda i: i["items"][0].pop("response_scales"))
            try:
                result = facade.capture_delphi_round(round_input(inst, [response("A", "P1", 1, 5, "scale unspecified")]))
                item = result["item_analysis"][0]
                self.assertIsNone(item["numeric_summary"])
                self.assertFalse(item["disagreement_assessed"])
                self.assertEqual(item["mode_summaries"][0]["status"], "scale_not_declared")
                self.assertEqual(item["mode_summaries"][0]["positions"][0]["value"], 5)
                self.assertEqual(result["analysis"]["unassessed_disagreement_item_count"], 1)
                fb = facade.build_delphi_feedback(result["round_result_id"])
                self.assertFalse(fb["summaries"][0]["disagreement_assessed"])
                r2 = instrument(2, feedback_id=fb["feedback_id"], feedback_digest=fb["content_digest"])
                r2["items"][0].pop("response_scales")
                approve_instrument(facade, proposal(r2, derived=derived_from(inst, result, fb)))
                second = facade.capture_delphi_round(round_input(r2, [response("B", "P1", 2, 5, "same unscaled number")]))
                self.assertIsNone(second["analysis"]["stability_ratio"])
                self.assertEqual(second["analysis"]["incomparable_opinions"][0]["reason"], "scale_not_declared")
                stop = facade.build_delphi_stopping_candidate("PANEL-1")
                self.assertIsNone(stop["basis"]["disagreement_goal_satisfied"])
            finally:
                app.close()

    def test_all_missing_is_not_measured_agreement(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, inst = self.fixture(temp)
            try:
                replies = [{"response_id": str(n), "participant_id": f"P{n}", "answers": [{"item_id": "ITEM-1", "item_revision": 1, "state": state}]} for n, state in enumerate(("missing", "not_applicable", "prefer_not_to_answer"), 1)]
                result = facade.capture_delphi_round(round_input(inst, replies))
                item = result["item_analysis"][0]
                self.assertEqual(item["answered_count"], 0)
                self.assertEqual(item["missing_states"], {"missing": 1, "not_applicable": 1, "prefer_not_to_answer": 1})
                self.assertTrue(all(g["status"] == "no_answers" and g["numeric_summary"] is None for g in item["mode_summaries"]))
                self.assertEqual(result["analysis"]["unassessed_disagreement_item_count"], 1)
            finally:
                app.close()

    def test_same_scale_normal_aggregation_is_not_overblocked(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, inst = self.fixture(temp, ["rating", "free_text_rationale"])
            try:
                result = facade.capture_delphi_round(round_input(inst, [response(str(n), f"P{n}", 1, val, "reason") for n, val in enumerate((1, 3, 5), 1)]))
                item = result["item_analysis"][0]
                self.assertEqual(item["numeric_summary"], {"median": 3, "minimum": 1, "maximum": 5, "distinct_count": 3})
                self.assertTrue(item["explicit_disagreement"])
                self.assertEqual([p["value"] for p in item["positions"] if p["minority"]], [1, 5])
            finally:
                app.close()

    def test_invalid_values_or_item_revision_commit_no_partial_result(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, inst = self.fixture(temp)
            try:
                good = response("A", "P1", 1, 3, "valid first")
                for field, value in [("rating", 0), ("rating", 6), ("probability", 1.1), ("rating", math.inf), ("rating", -math.inf), ("rating", math.nan), ("rating", True), ("rating", 2**54), ("item_revision", 1.5), ("item_revision", "1"), ("item_revision", True)]:
                    with self.subTest(field=field, value=value):
                        bad = response("B", "P2", 1, 3, "invalid second"); bad["answers"][0][field] = value
                        with self.assertRaises(LocalApplicationError) as error:
                            facade.capture_delphi_round(round_input(inst, [good, bad]))
                        self.assertEqual(error.exception.code, "APPLICATION-DELPHI-BINDING-001" if field == "item_revision" else "APPLICATION-DELPHI-RESPONSE-001")
                        self.assertEqual(facade.inspect_delphi_panel("PANEL-1")["rounds"], [])
                result = facade.capture_delphi_round(round_input(inst, [good]))
                self.assertEqual(result["round_result_version"], "1")
            finally:
                app.close()

    def test_scale_declaration_is_validated_before_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade, _ = self.fixture(temp)
            try:
                for scale in (None, {"other": {}}, {"rating": {"scale_id": "X", "minimum": 5, "maximum": 1}}, {"rating": {"scale_id": "X", "minimum": 0, "maximum": math.inf}}, {"rating": {"scale_id": "", "minimum": 0, "maximum": 5}}):
                    with self.subTest(scale=scale):
                        inst = instrument(1, version="2.0.0"); inst["items"][0]["response_scales"] = scale
                        # Finite JSON is a prerequisite of the canonical proposal.
                        with self.assertRaises((LocalApplicationError, ValueError)):
                            facade.request_delphi_instrument_approval({**proposal(inst), "human_actor_id": "operator"})
            finally:
                app.close()

    def test_comparison_requires_shared_mode_scale_and_item_meaning(self):
        for change, reason, comparable in (("scale", "scale_changed", 1), ("text", "item_meaning_changed", 0), ("none", None, 2)):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                app, facade, inst = self.fixture(temp)
                try:
                    before = response("A", "P1", 1, 5, "first"); before["answers"][0]["probability"] = 0.8
                    first = facade.capture_delphi_round(round_input(inst, [before])); fb = facade.build_delphi_feedback(first["round_result_id"])
                    r2 = instrument(2, response_modes=inst["items"][0]["response_modes"], feedback_id=fb["feedback_id"], feedback_digest=fb["content_digest"])
                    if change == "scale":
                        r2["items"][0]["response_scales"]["rating"].update(scale_id="likert7", maximum=7)
                    if change == "text":
                        r2["items"][0]["text"] = "A materially different statement."
                    approve_instrument(facade, proposal(r2, derived=derived_from(inst, first, fb)))
                    after = response("B", "P1", 2, 5, "second"); after["answers"][0]["probability"] = 0.4
                    second = facade.capture_delphi_round(round_input(r2, [after]))
                    analysis = second["analysis"]
                    self.assertEqual(analysis["comparable_opinion_count"], comparable)
                    self.assertEqual({item["reason"] for item in analysis["incomparable_opinions"]}, set() if reason is None else {reason})
                    self.assertEqual(analysis["comparison_basis"]["content_digest"], first["content_digest"])
                    if comparable:
                        self.assertEqual(analysis["changed_opinion_count"], 1)
                    self.assertTrue(facade.build_delphi_stopping_candidate("PANEL-1")["candidate_only"])
                finally:
                    app.close()

    def test_large_finite_and_subnormal_medians_remain_finite(self):
        for values, expected in (([1e308, 1.6e308], 1.3e308), ([-1.6e308, 1.6e308], 0), ([5e-324, 5e-324], 5e-324)):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as temp:
                app, facade, inst = self.fixture(temp, ["rating", "free_text_rationale"], lambda i: i["items"][0]["response_scales"]["rating"].update(scale_id="finite-custom", minimum=-1.7e308, maximum=1.7e308))
                try:
                    result = facade.capture_delphi_round(round_input(inst, [response(str(n), f"P{n}", 1, val, "numeric boundary") for n, val in enumerate(values, 1)]))
                    actual = result["item_analysis"][0]["numeric_summary"]["median"]
                    self.assertTrue(math.isfinite(actual))
                    self.assertEqual(actual, expected)
                finally:
                    app.close()

    def test_legacy_wrong_result_recalculates_as_new_revision_without_rewriting_facts(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/delphi-legacy-mixed-modes.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                # Restore exact legacy records from the old production fixture.
                # This is not an operator approval path or fabricated receipt.
                for document in fixture["documents"]:
                    facade._delphi_store().capture(document)
                before = state_signature(app)
                old = fixture["documents"][2]; feedback = fixture["documents"][3]
                self.assertEqual(facade.show_delphi_round(old["identity"])["delphi_round"], old)
                self.assertEqual(old["item_analysis"][0]["numeric_summary"]["median"], 2.9)
                with self.assertRaises(LocalApplicationError) as blocked:
                    facade.build_delphi_feedback(old["identity"])
                self.assertEqual(blocked.exception.code, "APPLICATION-DELPHI-ANALYSIS-001")
                revised = facade.recalculate_delphi_round(old["identity"])
                self.assertEqual(revised["round_result_version"], "2")
                self.assertIsNone(revised["item_analysis"][0]["numeric_summary"])
                self.assertEqual(revised["analysis"]["analysis_contract"], ANALYSIS_CONTRACT)
                groups = revised["item_analysis"][0]["mode_summaries"]
                self.assertEqual([g["numeric_summary"]["median"] for g in groups], [5, 0.8])
                stored = facade.show_delphi_round(old["identity"], "2")["delphi_round"]
                self.assertEqual(stored["responses"], old["responses"])
                self.assertEqual(stored["recalculated_from"]["content_digest"], old["content_digest"])
                self.assertEqual(facade.recalculate_delphi_round(old["identity"])["round_result_version"], "2")
                self.assertEqual(facade.recalculate_delphi_round(old["identity"], "2")["status"], "ALREADY_CALCULATED")
                new_fb = facade.build_delphi_feedback(old["identity"], "2")
                self.assertNotEqual(new_fb["feedback_id"], feedback["identity"])
                self.assertEqual(facade.show_delphi_feedback(feedback["identity"])["delphi_feedback"], feedback)
                self.assertEqual(facade.show_delphi_round(old["identity"])["delphi_round"], old)
                self.assertEqual(state_signature(app), before)
                with self.assertRaises(LocalApplicationError):
                    facade.capture_delphi_round(round_input(fixture["documents"][1]["instrument"], [response("C", "P3", 1, 3, "not covered by legacy approval")]))
                self.assertIsNone(facade._delphi_store().load("PRJ-1", "approval_receipt", "DEC-DL-I1"))
            finally:
                app.close()
