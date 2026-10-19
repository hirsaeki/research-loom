"""Characterization tests for ``core.runtime.authority_validation`` (#507).

They pin which Human Decisions each typed action requires, the Decision,
lineage and epistemic-firewall preconditions and their RT-* error codes, and
the small helpers that ``state_validation`` imports from this module.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from core.runtime import authority_validation as av
from core.runtime.authority_validation import (
    DecisionRequirement,
    required_decisions_for_action,
    resolving_decision_refs,
)
from core.runtime.transition_models import (
    TransitionAction,
    TransitionKind,
    ValidationStage,
)
from tests.runtime.runtime_fixtures import (
    decision,
    evidence,
    finding,
    make_request,
    project,
    rq,
    seed_state,
    source,
)

CREATE = TransitionKind.CREATE_OBJECT
REVISE = TransitionKind.REVISE_OBJECT
PLAN = TransitionKind.APPLY_LINEAGE_PLAN
SWITCH = TransitionKind.SWITCH_ACTIVE_LINEAGE


def codes(issues) -> list[str]:
    return [issue.error_code for issue in issues]


def obj_action(obj, *, kind=CREATE, decision_refs=(), source_refs=()):
    return TransitionAction(
        kind, {"object": obj}, decision_refs=tuple(decision_refs), source_refs=tuple(source_refs)
    )


class RequiredDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.empty = seed_state()
        self.with_rq = seed_state(objects=[project(), rq()])
        self.with_evidence = seed_state(objects=[project(), source(), evidence()])

    def test_new_candidate_object_requires_nothing(self):
        self.assertEqual(required_decisions_for_action(self.empty, obj_action(rq())), ())

    def test_action_without_object_or_special_kind_requires_nothing(self):
        action = TransitionAction(TransitionKind.RECORD_RUN_RESULT_ADOPTION, {"x": 1})
        self.assertEqual(required_decisions_for_action(self.empty, action), ())

    def test_new_approved_protected_object_requires_adoption_approve(self):
        self.assertEqual(
            required_decisions_for_action(self.empty, obj_action(rq(state="approved"))),
            (DecisionRequirement("research_adoption", "approve", "research_question", "RQ-1"),),
        )

    def test_reject_like_adoption_states_require_adoption_reject(self):
        for state in ("rejected", "closed", "out_of_scope"):
            with self.subTest(state=state):
                self.assertEqual(
                    required_decisions_for_action(self.empty, obj_action(rq(state=state))),
                    (
                        DecisionRequirement(
                            "research_adoption", "reject", "research_question", "RQ-1"
                        ),
                    ),
                )

    def test_other_adoption_change_requires_nothing(self):
        obj = rq(revision=1, state="needs_review")
        self.assertEqual(required_decisions_for_action(self.with_rq, obj_action(obj)), ())

    def test_unchanged_approved_state_does_not_require_adoption_again(self):
        state = seed_state(objects=[project(), rq(state="approved")])
        obj = rq(revision=1, state="approved", decision_ids=["DEC-X"])
        self.assertEqual(required_decisions_for_action(state, obj_action(obj)), ())

    def test_material_change_of_existing_protected_object_requires_revision(self):
        obj = rq(revision=1)
        obj["text"] = "Changed question"
        self.assertEqual(
            required_decisions_for_action(self.with_rq, obj_action(obj, kind=REVISE)),
            (DecisionRequirement("research_revision", "revise", "research_question", "RQ-1"),),
        )

    def test_approval_and_material_change_both_required_in_order(self):
        obj = rq(revision=1, state="approved")
        obj["text"] = "Changed question"
        self.assertEqual(
            required_decisions_for_action(self.with_rq, obj_action(obj)),
            (
                DecisionRequirement("research_adoption", "approve", "research_question", "RQ-1"),
                DecisionRequirement("research_revision", "revise", "research_question", "RQ-1"),
            ),
        )

    def test_non_protected_kind_has_no_adoption_requirement(self):
        claim = {"kind": "claim", "id": "CLM-1", "adoption_state": "approved"}
        self.assertEqual(required_decisions_for_action(self.empty, obj_action(claim)), ())

    def test_newly_verified_evidence_requires_qualification(self):
        self.assertEqual(
            required_decisions_for_action(
                self.empty, obj_action(evidence(verification="verified"))
            ),
            (DecisionRequirement("evidence_qualification", "verify", "evidence", "EVD-1"),),
        )

    def test_already_verified_evidence_requires_no_qualification(self):
        state = seed_state(objects=[project(), source(), evidence(verification="verified")])
        obj = evidence(revision=1, verification="verified")
        self.assertEqual(required_decisions_for_action(state, obj_action(obj)), ())

    def test_evidence_reclassification_requires_decision_only_with_prior(self):
        reclassified = evidence(revision=1, evidence_kind="supporting")
        self.assertEqual(
            required_decisions_for_action(self.with_evidence, obj_action(reclassified)),
            (DecisionRequirement("evidence_reclassification", "reclassify", "evidence", "EVD-1"),),
        )
        self.assertEqual(required_decisions_for_action(self.empty, obj_action(reclassified)), ())

    def test_lineage_plan_requires_plan_and_reconfirm_decisions(self):
        action = TransitionAction(
            PLAN,
            {
                "plan_ref": "PLAN-1",
                "treatments": [
                    {"treatment": "RECONFIRM", "derived_object": {"kind": "finding", "id": "F2"}},
                    {"treatment": "RECONFIRM", "derived_object": "not-a-mapping"},
                    {"treatment": "PRESERVE", "derived_object": {"kind": "finding", "id": "F3"}},
                    "garbage",
                    {"treatment": "RECONFIRM", "derived_object": {"kind": "finding", "id": "F2"}},
                ],
            },
        )
        self.assertEqual(
            required_decisions_for_action(self.empty, action),
            (
                DecisionRequirement("lineage_plan", "apply", "lineage_plan", "PLAN-1"),
                DecisionRequirement("lineage_reconfirmation", "reconfirm", "finding", "F2"),
            ),
        )

    def test_lineage_plan_with_missing_or_string_treatments(self):
        for payload in ({}, {"treatments": "RECONFIRM"}, {"treatments": b"x"}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    required_decisions_for_action(self.empty, TransitionAction(PLAN, payload)),
                    (DecisionRequirement("lineage_plan", "apply", "lineage_plan", ""),),
                )

    def test_switch_active_lineage_requires_selection_decision(self):
        action = TransitionAction(SWITCH, {"target_lineage_ref": "LIN-2"})
        self.assertEqual(
            required_decisions_for_action(self.empty, action),
            (
                DecisionRequirement(
                    "active_lineage_selection", "switch", "research_lineage", "LIN-2"
                ),
            ),
        )


class ResolvingDecisionRefsTests(unittest.TestCase):
    def test_only_actions_with_requirements_contribute_deduplicated_refs(self):
        state = seed_state()
        actions = [
            obj_action(rq(state="approved"), decision_refs=("DEC-1", "DEC-2")),
            obj_action(project(), decision_refs=("DEC-IGNORED",)),
            TransitionAction(SWITCH, {"target_lineage_ref": "LIN-1"}, decision_refs=("DEC-2",)),
        ]
        request = make_request(state, actions)
        self.assertEqual(resolving_decision_refs(state, request), ("DEC-1", "DEC-2"))


class HumanDecisionValidationTests(unittest.TestCase):
    def approve(self, decision_id="DEC-1", **overrides):
        value = decision(decision_id, "research_adoption", "approve", "research_question", "RQ-1")
        value.update(overrides)
        return value

    def check(self, decisions, actions, *, used=()):
        state = seed_state(decisions=decisions)
        state = replace(state, used_decision_ids=tuple(used))
        return av._validate_human_decisions(state, make_request(state, actions))

    def test_matching_unused_human_decision_passes(self):
        action = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        self.assertEqual(self.check([self.approve()], [action]), [])

    def test_missing_decision_ref_reports_001_and_002(self):
        action = obj_action(rq(state="approved"), decision_refs=("DEC-MISSING",))
        issues = self.check([], [action])
        self.assertEqual(codes(issues), ["RT-DECISION-001", "RT-DECISION-002"])
        self.assertEqual(issues[0].stage, ValidationStage.HUMAN_DECISION)
        self.assertEqual(
            issues[0].message,
            "Authoritative transition requires an unused human Decision bound as "
            "research_adoption/approve to research_question:RQ-1.",
        )
        self.assertEqual(issues[0].affected_refs, ("RQ-1",))
        self.assertEqual(issues[1].affected_refs, ("DEC-MISSING",))

    def test_no_decision_refs_reports_only_001(self):
        issues = self.check([], [obj_action(rq(state="approved"))])
        self.assertEqual(codes(issues), ["RT-DECISION-001"])

    def test_used_decision_is_replay(self):
        action = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        issues = self.check([self.approve()], [action], used=("DEC-1",))
        self.assertEqual(codes(issues), ["RT-DECISION-001", "RT-DECISION-005"])

    def test_non_human_decision(self):
        action = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        issues = self.check([self.approve(actor_type="agent")], [action])
        self.assertEqual(codes(issues), ["RT-DECISION-001", "RT-DECISION-003"])

    def test_decision_from_other_project_does_not_match(self):
        action = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        issues = self.check([self.approve(project_id="PRJ-OTHER")], [action])
        self.assertEqual(codes(issues), ["RT-DECISION-001"])

    def test_wrong_kind_or_choice_does_not_match(self):
        action = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        for overrides in ({"choice": "reject"}, {"decision_kind": "research_revision"}):
            with self.subTest(overrides=overrides):
                issues = self.check([self.approve(**overrides)], [action])
                self.assertEqual(codes(issues), ["RT-DECISION-001"])

    def test_subject_mismatch_reports_001_and_004(self):
        action = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        wrong = self.approve(subjects=[{"kind": "research_question", "id": "RQ-OTHER"}])
        issues = self.check([wrong], [action])
        self.assertEqual(codes(issues), ["RT-DECISION-001", "RT-DECISION-004"])
        self.assertEqual(issues[1].affected_refs, ("DEC-1", "RQ-1"))

    def test_decision_not_in_object_decision_ids_does_not_match(self):
        action = obj_action(rq(state="approved"), decision_refs=("DEC-1",))
        issues = self.check([self.approve()], [action])
        self.assertEqual(codes(issues), ["RT-DECISION-001"])

    def test_decision_recorded_in_same_request_is_in_pool(self):
        record = TransitionAction(TransitionKind.RECORD_DECISION, {"object": self.approve()})
        adopt = obj_action(rq(state="approved", decision_ids=["DEC-1"]), decision_refs=("DEC-1",))
        self.assertEqual(self.check([], [record, adopt]), [])

    def test_unrelated_action_with_unresolved_ref_still_reports_002(self):
        action = obj_action(project(), decision_refs=("DEC-NOPE",))
        self.assertEqual(codes(self.check([], [action])), ["RT-DECISION-002"])

    def test_lineage_actions_do_not_report_subject_mismatch(self):
        switch_decision = decision(
            "DEC-S", "active_lineage_selection", "switch", "research_lineage", "LIN-1"
        )
        action = TransitionAction(
            SWITCH,
            {"target_lineage_ref": "LIN-1", "target": {"kind": "research_lineage", "id": "X"}},
            decision_refs=("DEC-S",),
        )
        self.assertEqual(self.check([switch_decision], [action]), [])

    def test_issues_are_deduplicated(self):
        action = obj_action(rq(state="approved"), decision_refs=("DEC-MISSING", "DEC-MISSING"))
        issues = self.check([], [action])
        self.assertEqual(codes(issues), ["RT-DECISION-001", "RT-DECISION-002"])


class LineagePreconditionTests(unittest.TestCase):
    def setUp(self):
        self.state = seed_state()
        self.head_ref = str(self.state.current_snapshot["id"])
        self.head_digest = str(self.state.current_snapshot["content_digest"])

    def plan(self, **overrides):
        payload = {
            "plan_ref": "PLAN-1",
            "target_lineage_id": "LIN-2",
            "lineage_kind": "exploratory_fork",
            "baseline_snapshot_ref": self.head_ref,
            "baseline_snapshot_digest": self.head_digest,
            "treatments": [
                {"object_kind": "project", "source_ref": "PRJ-1", "treatment": "PRESERVE"}
            ],
        }
        payload.update(overrides)
        return payload

    def check(self, *actions, request=None, state=None):
        state = state or self.state
        request = request or make_request(state, actions)
        return av._validate_lineage_preconditions(state, request)

    def test_valid_plan_passes(self):
        self.assertEqual(self.check(TransitionAction(PLAN, self.plan())), [])

    def test_unknown_source_lineage(self):
        request = replace(make_request(self.state, ()), lineage_ref="LIN-NOPE")
        issues = self.check(request=request)
        self.assertEqual(codes(issues), ["RT-LINEAGE-001"])
        self.assertEqual(issues[0].affected_refs, ("LIN-NOPE",))
        self.assertEqual(issues[0].stage, ValidationStage.LINEAGE)

    def test_incomplete_payload_stops_further_checks(self):
        payload = self.plan()
        del payload["treatments"]
        del payload["plan_ref"]
        payload["lineage_kind"] = "bogus"
        issues = self.check(TransitionAction(PLAN, payload))
        self.assertEqual(codes(issues), ["RT-LINEAGE-002"])
        self.assertEqual(
            issues[0].message, "Lineage plan payload is incomplete: plan_ref, treatments."
        )

    def test_bad_kind_baseline_and_existing_target(self):
        payload = self.plan(
            lineage_kind="bogus", baseline_snapshot_digest="sha256:0", target_lineage_id="LIN-1"
        )
        issues = self.check(TransitionAction(PLAN, payload))
        self.assertEqual(codes(issues), ["RT-LINEAGE-003", "RT-LINEAGE-004", "RT-LINEAGE-005"])
        self.assertEqual(issues[2].affected_refs, ("LIN-1",))

    def test_baseline_ref_mismatch(self):
        issues = self.check(TransitionAction(PLAN, self.plan(baseline_snapshot_ref="SNP-X")))
        self.assertEqual(codes(issues), ["RT-LINEAGE-004"])

    def test_non_sequence_treatments(self):
        for value in ("PRESERVE", {"treatment": "PRESERVE"}, None):
            with self.subTest(value=value):
                issues = self.check(TransitionAction(PLAN, self.plan(treatments=value)))
                self.assertEqual(codes(issues), ["RT-LINEAGE-006"])

    def test_missing_treatment_for_baseline_member(self):
        state = seed_state(objects=[project(), rq()])
        payload = self.plan(
            baseline_snapshot_ref=str(state.current_snapshot["id"]),
            baseline_snapshot_digest=str(state.current_snapshot["content_digest"]),
        )
        issues = self.check(TransitionAction(PLAN, payload), state=state)
        self.assertEqual(codes(issues), ["RT-LINEAGE-007"])
        self.assertEqual(issues[0].affected_refs, ("research_question:RQ-1",))

    def test_invalid_treatment_values(self):
        treatments = [
            {"object_kind": "project", "source_ref": "PRJ-1", "treatment": "PRESERVE"},
            {"object_kind": "x", "source_ref": "y", "treatment": "COPY"},
            "garbage",
        ]
        issues = self.check(TransitionAction(PLAN, self.plan(treatments=treatments)))
        self.assertEqual(codes(issues), ["RT-LINEAGE-008", "RT-LINEAGE-008"])

    def reconfirm(self, item, decision_refs=()):
        treatments = [
            {"object_kind": "project", "source_ref": "PRJ-1", "treatment": "PRESERVE"},
            {"treatment": "RECONFIRM", **item},
        ]
        action = TransitionAction(
            PLAN, self.plan(treatments=treatments), decision_refs=tuple(decision_refs)
        )
        return self.check(action)

    def test_reconfirm_requires_derived_object_and_decision(self):
        cases = (
            {"source_ref": "FND-1", "human_decision_ref": "DEC-1"},
            {"source_ref": "FND-1", "derived_object": {"id": "FND-1"}},
            {"source_ref": "FND-1", "derived_object": "x", "human_decision_ref": "DEC-1"},
        )
        for item in cases:
            with self.subTest(item=item):
                issues = self.reconfirm(item, ("DEC-1",))
                self.assertEqual(codes(issues), ["RT-LINEAGE-013"])
                self.assertEqual(issues[0].affected_refs, ("FND-1",))

    def test_reconfirm_with_same_identity_and_bound_decision_passes(self):
        item = {
            "source_ref": "FND-1",
            "derived_object": {"id": "FND-1", "decision_ids": ["DEC-1"]},
            "human_decision_ref": "DEC-1",
        }
        self.assertEqual(self.reconfirm(item, ("DEC-1",)), [])

    def test_reconfirm_identity_change_needs_matching_derived_ref(self):
        base = {
            "source_ref": "FND-1",
            "derived_object": {"id": "FND-2", "decision_ids": ["DEC-1"]},
            "human_decision_ref": "DEC-1",
        }
        issues = self.reconfirm(base, ("DEC-1",))
        self.assertEqual(codes(issues), ["RT-LINEAGE-015"])
        self.assertEqual(issues[0].affected_refs, ("FND-1", "FND-2"))
        self.assertIn("identity changes", issues[0].message)
        self.assertEqual(self.reconfirm({**base, "derived_ref": "FND-2"}, ("DEC-1",)), [])

    def test_reconfirm_derived_ref_must_match_even_without_identity_change(self):
        item = {
            "source_ref": "FND-1",
            "derived_ref": "FND-9",
            "derived_object": {"id": "FND-1", "decision_ids": ["DEC-1"]},
            "human_decision_ref": "DEC-1",
        }
        issues = self.reconfirm(item, ("DEC-1",))
        self.assertEqual(codes(issues), ["RT-LINEAGE-015"])
        self.assertEqual(issues[0].affected_refs, ("FND-9", "FND-1"))
        self.assertIn("derived_ref must match", issues[0].message)

    def test_reconfirm_decision_must_be_bound_to_action_and_derived_object(self):
        item = {
            "source_ref": "FND-1",
            "derived_object": {"id": "FND-1", "decision_ids": ["DEC-1"]},
            "human_decision_ref": "DEC-1",
        }
        issues = self.reconfirm(item, ())
        self.assertEqual(codes(issues), ["RT-LINEAGE-014"])
        self.assertEqual(issues[0].affected_refs, ("DEC-1", "FND-1"))
        unbound = {**item, "derived_object": {"id": "FND-1", "decision_ids": None}}
        self.assertEqual(codes(self.reconfirm(unbound, ("DEC-1",))), ["RT-LINEAGE-014"])

    def test_corrective_recovery_requires_replay_plan(self):
        action = TransitionAction(PLAN, self.plan(lineage_kind="corrective_recovery"))
        self.assertEqual(codes(self.check(action)), ["RT-LINEAGE-009"])
        action = TransitionAction(
            PLAN, self.plan(lineage_kind="corrective_recovery", replay_plan_ref="RPL-1")
        )
        self.assertEqual(self.check(action), [])

    def test_switch_target_must_resolve(self):
        self.assertEqual(self.check(TransitionAction(SWITCH, {"target_lineage_ref": "LIN-1"})), [])
        issues = self.check(TransitionAction(SWITCH, {"target_lineage_ref": "LIN-9"}))
        self.assertEqual(codes(issues), ["RT-LINEAGE-010"])
        self.assertEqual(issues[0].affected_refs, ("LIN-9",))

    def test_other_actions_are_ignored(self):
        self.assertEqual(self.check(obj_action(rq())), [])


class EpistemicPreconditionTests(unittest.TestCase):
    def check(self, state, *actions, source_refs=(), lineage_ref=None):
        request = make_request(state, actions, source_refs=source_refs)
        if lineage_ref is not None:
            request = replace(request, lineage_ref=lineage_ref)
        return av._validate_epistemic_preconditions(state, request)

    def test_synthetic_evidence_cannot_become_empirical(self):
        state = seed_state(objects=[project(), source(), evidence(mode="synthetic")])
        issues = self.check(state, obj_action(evidence(revision=1, mode="empirical")))
        self.assertEqual(codes(issues), ["RT-EPI-001"])
        self.assertEqual(issues[0].stage, ValidationStage.EPISTEMIC_FIREWALL)
        self.assertEqual(issues[0].affected_refs, ("EVD-1",))

    def test_synthetic_to_synthetic_and_new_evidence_pass(self):
        state = seed_state(objects=[project(), source(), evidence(mode="synthetic")])
        self.assertEqual(self.check(state, obj_action(evidence(revision=1, mode="synthetic"))), [])
        self.assertEqual(self.check(seed_state(), obj_action(evidence(mode="empirical"))), [])

    def test_virtual_source_research_content_in_real_lineage(self):
        state = seed_state(source_modes={"SRC-V": "virtual", "SRC-S": "synthetic_test"})
        issues = self.check(
            state, obj_action(finding(), source_refs=("SRC-S",)), source_refs=("SRC-V",)
        )
        self.assertEqual(codes(issues), ["RT-EPI-002"])
        self.assertEqual(issues[0].affected_refs, ("SRC-V", "SRC-S"))

    def test_virtual_source_non_research_object_passes(self):
        state = seed_state(source_modes={"SRC-V": "virtual"})
        self.assertEqual(self.check(state, obj_action(project()), source_refs=("SRC-V",)), [])

    def test_content_class_triggers_002_and_003(self):
        state = seed_state(source_modes={"SRC-V": "virtual"})
        action = TransitionAction(
            TransitionKind.RECORD_RUN_RESULT_ADOPTION,
            {"content_class": "finding"},
            source_refs=("SRC-V",),
        )
        self.assertEqual(codes(self.check(state, action)), ["RT-EPI-002", "RT-EPI-003"])

    def test_content_class_raw_data_triggers_only_003(self):
        state = seed_state(source_modes={"SRC-V": "virtual"})
        action = TransitionAction(
            TransitionKind.RECORD_RUN_RESULT_ADOPTION,
            {"content_class": "raw_data"},
            source_refs=("SRC-V",),
        )
        self.assertEqual(codes(self.check(state, action)), ["RT-EPI-003"])

    def test_real_source_modes_pass(self):
        state = seed_state(source_modes={"SRC-R": "real"})
        self.assertEqual(self.check(state, obj_action(finding()), source_refs=("SRC-R",)), [])

    def test_virtual_lineage_skips_firewall(self):
        state = seed_state(mode="virtual", source_modes={"SRC-V": "virtual"})
        self.assertEqual(self.check(state, obj_action(finding()), source_refs=("SRC-V",)), [])

    def test_unknown_lineage_falls_back_to_snapshot_mode(self):
        virtual = seed_state(mode="virtual", source_modes={"SRC-V": "virtual"})
        self.assertEqual(
            self.check(virtual, obj_action(finding()), source_refs=("SRC-V",), lineage_ref="X"),
            [],
        )
        real = seed_state(source_modes={"SRC-V": "virtual"})
        self.assertEqual(
            codes(self.check(real, obj_action(finding()), source_refs=("SRC-V",), lineage_ref="X")),
            ["RT-EPI-002"],
        )

    def test_non_reusable_ref_cannot_be_adopted_again(self):
        state = seed_state(non_reusable=("RUN-OLD",))
        adopt = TransitionAction(
            TransitionKind.RECORD_RUN_RESULT_ADOPTION, {}, source_refs=("RUN-OLD",)
        )
        issues = self.check(state, adopt, source_refs=("RUN-OLD",))
        # Request and action both name the ref; the duplicate issue is removed.
        self.assertEqual(codes(issues), ["RT-EPI-004"])
        self.assertEqual(issues[0].affected_refs, ("RUN-OLD",))
        other = TransitionAction(CREATE, {}, source_refs=("RUN-OLD",))
        self.assertEqual(self.check(state, other), [])


class HelperTests(unittest.TestCase):
    def test_decision_pool_merges_state_and_recorded_decisions(self):
        stored = decision("DEC-1", "k", "c", "project", "PRJ-1")
        state = seed_state(decisions=[stored, {"kind": "decision"}])
        recorded = decision("DEC-2", "k", "c", "project", "PRJ-1")
        actions = [
            TransitionAction(TransitionKind.RECORD_DECISION, {"object": recorded}),
            TransitionAction(TransitionKind.RECORD_DECISION, {"object": {"kind": "decision"}}),
            TransitionAction(TransitionKind.RECORD_DECISION, {}),
            obj_action(decision("DEC-3", "k", "c", "project", "PRJ-1")),
        ]
        pool = av._decision_pool(state, make_request(state, actions))
        self.assertEqual(sorted(pool), ["DEC-1", "DEC-2"])

    def test_decision_refs_for_object_collects_target_refs(self):
        state = seed_state()
        actions = [
            obj_action(evidence(), decision_refs=("D1", "D2")),
            TransitionAction(
                REVISE, {"target": {"kind": "evidence", "id": "EVD-1"}}, decision_refs=("D2", "D3")
            ),
            obj_action(finding(), decision_refs=("D4",)),
            TransitionAction(REVISE, {}, decision_refs=("D5",)),
        ]
        request = make_request(state, actions)
        self.assertEqual(
            av._decision_refs_for_object(request, "evidence", "EVD-1"), ("D1", "D2", "D3")
        )

    def test_decision_subject_matches(self):
        dec = {"subjects": ["junk", {"kind": "finding", "id": "F1"}]}
        self.assertTrue(av._decision_subject_matches(dec, "finding", "F1"))
        self.assertFalse(av._decision_subject_matches(dec, "finding", "F2"))
        self.assertFalse(av._decision_subject_matches({"subjects": None}, "finding", "F1"))
        self.assertFalse(av._decision_subject_matches({}, "finding", "F1"))

    def test_material_change_ignores_bookkeeping_fields(self):
        prior = rq()
        same = {**rq(revision=3, state="approved"), "decision_ids": ["D1"]}
        self.assertFalse(av._material_research_change(prior, same))
        self.assertTrue(av._material_research_change(prior, {**prior, "text": "other"}))


if __name__ == "__main__":
    unittest.main()
