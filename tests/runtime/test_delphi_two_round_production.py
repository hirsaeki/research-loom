from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_survey_store import canonical_document_digest
from runtime_fixtures import decision, project, rq, seed_state
from test_survey_production import NullResolver, profile_provider

ROOT = Path(__file__).resolve().parents[2]


def make_app(root: str | Path, *, decisions_override: list[dict] | None = None) -> LocalResearchApplication:
    decisions = [] if decisions_override is None else decisions_override
    seed = seed_state(
        objects=[project(), rq(state="approved")],
        decisions=decisions,
        snapshot_id="SNP-DL-0",
    )
    return LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=seed,
    )


def with_digest(value: dict) -> dict:
    value = deepcopy(value)
    value["content_digest"] = canonical_document_digest(value, "content_digest")
    return value


def design(*, version: str = "1.0.0", maximum_rounds: int = 2) -> dict:
    return with_digest({
        "schema_version": "0.1.0",
        "delphi_design_id": "DLD-1",
        "version": version,
        "method_design_ref": {"method_id": "METHOD-DL-1"},
        "purpose": {"target_question": "What remains contested?", "intended_use": "two-round fixture"},
        "panel_population": {"definition": "fixture experts", "unit_of_analysis": "expert judgement"},
        "selection": {
            "selection_criteria": ["relevant expertise"],
            "inclusion_criteria": ["fixture panel"],
            "exclusion_criteria": ["none"],
        },
        "coverage_dimensions": ["governance"],
        "participation_targets": {
            "target_panel_size": 3,
            "minimum_viable_participation": 1,
            "target_is_research_sufficiency": False,
        },
        "identity_policy": {
            "mode": "pseudonymous",
            "cross_round_linkage": True,
            "identity_disclosure_policy": "researcher_only",
        },
        "facilitator_boundary": {
            "facilitator_role": "summarize",
            "researcher_role": "inspect",
            "may_modify_panel_responses": False,
        },
        "conflict_of_interest": {"capture": True},
        "panel_change_policy": {"late_join": "record", "replacement": "record"},
        "planned_rounds": {
            "minimum_rounds": 2,
            "maximum_approved_rounds": maximum_rounds,
            "round_plan": [{"sequence": sequence} for sequence in range(1, maximum_rounds + 1)],
        },
        "stopping": {
            "criteria": ["stability", "disagreement", "approved_round_limit"],
            "consensus_goal": {"maximum_disagreement_item_count": 0},
            "stability_goal": {"minimum_ratio": 0.75},
            "no_universal_numeric_threshold": True,
            "stopping_is_research_completion": False,
        },
        "representativeness": {
            "assumptions": ["fixture only"],
            "limitations": ["small panel"],
        },
        "candidate_only": True,
    })


def instrument(
    round_sequence: int,
    *,
    version: str = "1.0.0",
    response_modes: list[str] | None = None,
    feedback_id: str | None = None,
    feedback_digest: str | None = None,
) -> dict:
    round2 = round_sequence == 2
    value = {
        "schema_version": "0.1.0",
        "object_type": "delphi_round_instrument",
        "instrument_id": f"DLI-R{round_sequence}",
        "version": version,
        "round_sequence": round_sequence,
        "approval_status": "approved",
        "approval_decision_id": f"DEC-DL-I{round_sequence}",
        "material_revision": round2,
        "retired_item_ids": [],
        "revision_changes": [] if not round2 else [{"item_id": "ITEM-1", "change": "feedback-context-added"}],
        "items": [{
            "item_id": "ITEM-1",
            "item_revision": round_sequence,
            "text": "AI delegation should remain bounded.",
            "item_type": "statement",
            "response_modes": response_modes or ["rating", "free_text_rationale"],
            "response_scales": {
                mode: {"scale_id": "likert5" if mode == "rating" else mode,
                       "minimum": 1 if mode == "rating" else 0, "maximum": 5 if mode == "rating" else 1}
                for mode in (response_modes or ["rating", "free_text_rationale"])
                if mode in ("rating", "probability", "confidence")
            },
            "traceability": {"research_question_ids": ["RQ-1"]},
            "controlled_feedback": {} if not round2 else {"feedback_id": feedback_id, "feedback_digest": feedback_digest},
            "lineage": {"lifecycle": "new"} if not round2 else {"prior_item_id": "ITEM-1", "prior_item_revision": 1},
        }],
    }
    if round2:
        value["material_revision_decision_id"] = "DEC-DL-R2"
    return with_digest(value)


def response(
    response_id: str,
    participant_id: str,
    revision: int,
    value: int | float,
    rationale: str,
    *,
    mode: str = "rating",
) -> dict:
    answer = {
        "item_id": "ITEM-1",
        "item_revision": revision,
        "state": "answered",
        "rationale": rationale,
    }
    answer[mode] = value
    return {
        "response_id": response_id,
        "participant_id": participant_id,
        "answers": [answer],
    }


def approve_instrument(facade, payload):
    """Public request/human response only; no approval records are seeded."""
    request = facade.request_delphi_instrument_approval({**payload, "human_actor_id": "operator"})
    result = facade.resolve_delphi_instrument_approval({
        "request_id": request["request_id"], "request_digest": request["request_digest"],
        "actor": {"actor_id": "operator", "actor_type": "human"}, "choice": "approve_exact",
    })
    instrument = payload["instrument"]
    instrument.clear()
    instrument.update(deepcopy(request["request"]["target_document"]["instrument"]))
    return result


class DelphiTwoRoundProductionTests(unittest.TestCase):
    def test_two_round_vertical_slice_preserves_lineage_dissent_attrition_and_authority_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                d = design()
                captured_design = facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": d})
                self.assertEqual(captured_design["status"], "CAPTURED")

                r1i = instrument(1)
                approve_instrument(facade, {
                    "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                    "panel_id": "PANEL-1", "instrument": r1i,
                })
                round1 = facade.capture_delphi_round({
                    "panel_id": "PANEL-1", "instrument_id": "DLI-R1", "instrument_version": "1.0.0",
                    "instrument_digest": r1i["content_digest"],
                    "expected_participant_ids": ["P1", "P2", "P3"],
                    "responses": [
                        response("R1-P1", "P1", 1, 1, "keep human approval"),
                        response("R1-P2", "P2", 1, 5, "delegate aggressively"),
                    ],
                })
                self.assertEqual(round1["analysis"]["missing_response_count"], 1)
                self.assertEqual(round1["analysis"]["attrition_count"], 0)
                self.assertEqual(round1["analysis"]["explicit_disagreement_item_count"], 1)
                round1_before = facade.show_delphi_round(round1["round_result_id"])["delphi_round"]

                stored_r1 = facade.show_delphi_round(round1["round_result_id"])["delphi_round"]
                self.assertEqual(stored_r1["responses"][0]["binding"]["instrument_digest"], r1i["content_digest"])
                self.assertEqual(stored_r1["responses"][0]["binding"]["round_sequence"], 1)

                feedback = facade.build_delphi_feedback(round1["round_result_id"])
                self.assertEqual(len(feedback["summaries"][0]["minority_positions"]), 2)
                self.assertEqual(feedback["source_round_result_id"], round1["round_result_id"])
                self.assertTrue(feedback["content_digest"].startswith("sha256:"))
                repeated_feedback = facade.build_delphi_feedback(round1["round_result_id"])
                self.assertEqual(repeated_feedback["status"], "ALREADY_CAPTURED")

                r2i = instrument(2, feedback_id=feedback["feedback_id"], feedback_digest=feedback["content_digest"])
                approve_instrument(facade, {
                    "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                    "panel_id": "PANEL-1", "instrument": r2i,
                    "derived_from": {
                        "prior_instrument_id": "DLI-R1",
                        "prior_instrument_version": "1.0.0",
                        "prior_instrument_digest": r1i["content_digest"],
                        "prior_round_result_id": round1["round_result_id"],
                        "prior_round_result_digest": round1["content_digest"],
                        "feedback_id": feedback["feedback_id"],
                        "feedback_digest": feedback["content_digest"],
                    },
                })
                round2 = facade.capture_delphi_round({
                    "panel_id": "PANEL-1", "instrument_id": "DLI-R2", "instrument_version": "1.0.0",
                    "instrument_digest": r2i["content_digest"],
                    "expected_participant_ids": ["P1", "P2", "P3"],
                    "responses": [response("R2-P1", "P1", 2, 2, "still cautious")],
                })
                self.assertEqual(round2["analysis"]["missing_response_count"], 2)
                self.assertEqual(round2["analysis"]["attrition_count"], 1)
                self.assertEqual(round2["analysis"]["attrited_participant_ids"], ["P2"])
                self.assertEqual(round2["analysis"]["changed_opinion_count"], 1)
                self.assertEqual(round2["analysis"]["stability_ratio"], 0.0)

                # A later immutable Design revision must not make stopping ambiguous:
                # the candidate follows the Design bound by the Round 2 Instrument.
                facade.capture_delphi_design({
                    "rq_ids": ["RQ-1"],
                    "panel_id": "PANEL-1",
                    "design": design(version="1.1.0"),
                })
                stopping = facade.build_delphi_stopping_candidate("PANEL-1")
                self.assertEqual(stopping["recommendation"], "stop")
                self.assertTrue(stopping["human_decision_required"])
                self.assertTrue(stopping["candidate_only"])
                self.assertFalse(stopping["research_state_mutation_performed"])

                round1_after = facade.show_delphi_round(round1["round_result_id"])["delphi_round"]
                self.assertEqual(round1_after, round1_before)
                inspected = facade.inspect_delphi_panel("PANEL-1")
                self.assertEqual(len(inspected["rounds"]), 2)
                self.assertEqual(len(inspected["feedback_artifacts"]), 1)
                self.assertEqual(len(inspected["stopping_candidates"]), 1)
            finally:
                app.close()

    def test_mismatched_round_instrument_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
                r1i = instrument(1)
                approve_instrument(facade, {
                    "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                    "panel_id": "PANEL-1", "instrument": r1i,
                })
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.capture_delphi_round({
                        "panel_id": "PANEL-1", "instrument_id": "DLI-R1", "instrument_version": "1.0.0",
                        "instrument_digest": "sha256:" + "0" * 64,
                        "expected_participant_ids": ["P1"],
                        "responses": [response("R1-P1", "P1", 1, 3, "fixture")],
                    })
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-BINDING-001")
            finally:
                app.close()

    def test_round2_requires_explicit_feedback_and_prior_result_lineage(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.capture_delphi_instrument({
                        "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                        "panel_id": "PANEL-1", "instrument": instrument(2),
                    })
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-LINEAGE-001")
            finally:
                app.close()


    def test_instrument_authority_requires_human_research_revision_decision(self):
        for field, value in (("actor_type", "service"), ("decision_kind", "method_selection")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                invalid = decision("DEC-DL-I1", "research_revision", "approve", "instrument", "DLI-R1")
                invalid[field] = value
                app = make_app(temp, decisions_override=[invalid])
                try:
                    facade = LocalApplicationFacade(app, "PRJ-1")
                    facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
                    with self.assertRaises(LocalApplicationError) as caught:
                        facade.capture_delphi_instrument({
                            "delphi_design_id": "DLD-1",
                            "delphi_design_version": "1.0.0",
                            "panel_id": "PANEL-1",
                            "instrument": instrument(1),
                        })
                    self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-AUTHORITY-001")
                finally:
                    app.close()

    def test_two_round_slice_rejects_designs_that_approve_later_rounds(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.capture_delphi_design({
                        "rq_ids": ["RQ-1"],
                        "panel_id": "PANEL-1",
                        "design": design(maximum_rounds=3),
                    })
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-ROUND-001")
            finally:
                app.close()

    def test_response_modes_are_enforced_and_cross_round_stability_compares_like_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})

                rating_only = instrument(1)
                approve_instrument(facade, {
                    "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                    "panel_id": "PANEL-1", "instrument": rating_only,
                })
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.capture_delphi_round({
                        "panel_id": "PANEL-1", "instrument_id": "DLI-R1", "instrument_version": "1.0.0",
                        "instrument_digest": rating_only["content_digest"],
                        "expected_participant_ids": ["P1"],
                        "responses": [response("R1-BAD", "P1", 1, 0.5, "wrong mode", mode="probability")],
                    })
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-RESPONSE-001")
            finally:
                app.close()

        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
                modes = ["rating", "probability", "free_text_rationale"]
                r1i = instrument(1, response_modes=modes)
                approve_instrument(facade, {
                    "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                    "panel_id": "PANEL-1", "instrument": r1i,
                })
                round1 = facade.capture_delphi_round({
                    "panel_id": "PANEL-1", "instrument_id": "DLI-R1", "instrument_version": "1.0.0",
                    "instrument_digest": r1i["content_digest"],
                    "expected_participant_ids": ["P1"],
                    "responses": [response("R1-P1", "P1", 1, 5, "rating")],
                })
                feedback = facade.build_delphi_feedback(round1["round_result_id"])
                r2i = instrument(
                    2, response_modes=modes,
                    feedback_id=feedback["feedback_id"], feedback_digest=feedback["content_digest"],
                )
                approve_instrument(facade, {
                    "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                    "panel_id": "PANEL-1", "instrument": r2i,
                    "derived_from": {
                        "prior_instrument_id": "DLI-R1",
                        "prior_instrument_version": "1.0.0",
                        "prior_instrument_digest": r1i["content_digest"],
                        "prior_round_result_id": round1["round_result_id"],
                        "prior_round_result_digest": round1["content_digest"],
                        "feedback_id": feedback["feedback_id"],
                        "feedback_digest": feedback["content_digest"],
                    },
                })
                round2 = facade.capture_delphi_round({
                    "panel_id": "PANEL-1", "instrument_id": "DLI-R2", "instrument_version": "1.0.0",
                    "instrument_digest": r2i["content_digest"],
                    "expected_participant_ids": ["P1"],
                    "responses": [response("R2-P1", "P1", 2, 0.5, "probability", mode="probability")],
                })
                self.assertEqual(round2["analysis"]["comparable_opinion_count"], 0)
                self.assertEqual(round2["analysis"]["changed_opinion_count"], 0)
                self.assertIsNone(round2["analysis"]["stability_ratio"])
            finally:
                app.close()

    def test_round2_lineage_must_match_the_instrument_that_produced_round1(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
                r1a = instrument(1, version="1.0.0")
                r1b = instrument(1, version="1.1.0")
                for row in (r1a, r1b):
                    approve_instrument(facade, {
                        "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                        "panel_id": "PANEL-1", "instrument": row,
                    })
                round1 = facade.capture_delphi_round({
                    "panel_id": "PANEL-1", "instrument_id": "DLI-R1", "instrument_version": "1.0.0",
                    "instrument_digest": r1a["content_digest"],
                    "expected_participant_ids": ["P1"],
                    "responses": [response("R1-P1", "P1", 1, 3, "fixture")],
                })
                feedback = facade.build_delphi_feedback(round1["round_result_id"])
                r2i = instrument(2, feedback_id=feedback["feedback_id"], feedback_digest=feedback["content_digest"])
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.capture_delphi_instrument({
                        "delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0",
                        "panel_id": "PANEL-1", "instrument": r2i,
                        "derived_from": {
                            "prior_instrument_id": "DLI-R1",
                            "prior_instrument_version": "1.1.0",
                            "prior_instrument_digest": r1b["content_digest"],
                            "prior_round_result_id": round1["round_result_id"],
                            "prior_round_result_digest": round1["content_digest"],
                            "feedback_id": feedback["feedback_id"],
                            "feedback_digest": feedback["content_digest"],
                        },
                    })
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-LINEAGE-001")
            finally:
                app.close()

    def test_repository_launcher_exposes_delphi_namespace(self):
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, "-m", "plugins.local_application.cli", "delphi", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("design", "instrument", "round", "feedback", "inspect", "stopping"):
            self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
