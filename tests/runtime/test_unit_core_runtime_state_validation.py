"""Characterization tests for ``core.runtime.state_validation`` (#507).

They pin the post-reduction checks (reference integrity, Core invariants,
Profile strengthening, Project guards, adoption boundaries, lineage and
epistemic postconditions, next-state snapshot checks), their RT-* error codes,
and the reference-extraction helpers.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from core.runtime import state_validation as sv
from core.runtime.transition_models import (
    LineageView,
    ReductionResult,
    TransitionAction,
    TransitionKind,
    ValidationStage,
    canonical_digest,
    with_content_digest,
)
from tests.runtime.runtime_fixtures import (
    decision,
    evidence,
    finding,
    make_request,
    project,
    rq,
    seed_state,
    snapshot,
    source,
)


def codes(issues) -> list[str]:
    return [issue.error_code for issue in issues]


def reduction(
    *, objects=(), new_snapshot=None, lineage_updates=(), new_lineages=()
) -> ReductionResult:
    return ReductionResult(
        object_revisions=tuple(objects),
        decision_records=(),
        new_snapshot=new_snapshot,
        lineage_updates=tuple(lineage_updates),
        new_lineages=tuple(new_lineages),
        active_lineage_update=None,
        adoption_refs=(),
        used_decision_refs=(),
        audit_events=(),
        applied_actions=(),
    )


class ReferenceIntegrityTests(unittest.TestCase):
    def check(self, state, *objects):
        return sv._validate_reference_integrity(state, reduction(objects=objects))

    def test_resolving_references_pass(self):
        state = seed_state(objects=[project(), source()])
        self.assertEqual(self.check(state, evidence(), rq(), finding()), [])

    def test_unresolved_typed_reference(self):
        issues = self.check(seed_state(), evidence())
        self.assertEqual(codes(issues), ["RT-REF-001"])
        self.assertEqual(issues[0].stage, ValidationStage.REFERENCE_INTEGRITY)
        self.assertEqual(
            issues[0].message, "Referenced source:SRC-1 does not resolve in the proposed state."
        )
        self.assertEqual(issues[0].affected_refs, ("SRC-1",))

    def test_project_reference_to_current_project_always_resolves(self):
        state = seed_state(objects=[])
        self.assertEqual(self.check(state, rq()), [])

    def test_other_project_reference_must_resolve(self):
        issues = self.check(seed_state(), rq(project_id="PRJ-2"))
        self.assertEqual(codes(issues), ["RT-REF-001"])
        self.assertEqual(issues[0].affected_refs, ("PRJ-2",))

    def test_wildcard_reference_matches_any_kind(self):
        action = {
            "kind": "next_action",
            "id": "NA-1",
            "revision": 0,
            "blocked_by": ["RQ-1", "MISSING-1"],
        }
        issues = self.check(seed_state(), rq(), action)
        self.assertEqual(codes(issues), ["RT-REF-001"])
        self.assertEqual(issues[0].message, "Referenced object ID does not resolve.")
        self.assertEqual(issues[0].affected_refs, ("MISSING-1",))

    def test_duplicate_issues_are_deduplicated(self):
        obj = {
            "kind": "finding",
            "id": "FND-9",
            "revision": 0,
            "question_ids": ["RQ-X", "RQ-X"],
        }
        self.assertEqual(codes(self.check(seed_state(), obj)), ["RT-REF-001"])


class ReferencesFromObjectTests(unittest.TestCase):
    def refs(self, obj):
        return list(sv._references_from_object(obj))

    def test_project_id_is_yielded_first(self):
        self.assertEqual(self.refs({"kind": "source", "project_id": "P"}), [("project", "P")])
        self.assertEqual(self.refs({"kind": "source"}), [])

    def test_research_question_references(self):
        obj = {
            "kind": "research_question",
            "parent_question_id": "RQ-0",
            "question_lineage_id": "QL-1",
            "downstream_review_required_refs": [
                {"kind": "finding", "id": "F1"},
                {"kind": "finding"},
                "junk",
            ],
        }
        self.assertEqual(self.refs(obj), [("research_question", "RQ-0"), ("finding", "F1")])
        self.assertEqual(
            self.refs({"kind": "research_question", "downstream_review_required_refs": None}), []
        )

    def test_claim_method_evidence_analysis(self):
        self.assertEqual(
            self.refs(
                {
                    "kind": "claim",
                    "question_id": "RQ-1",
                    "supporting_evidence_ids": ["E1"],
                    "challenging_evidence_ids": ["E2"],
                }
            ),
            [("research_question", "RQ-1"), ("evidence", "E1"), ("evidence", "E2")],
        )
        self.assertEqual(self.refs({"kind": "claim"}), [])
        self.assertEqual(
            self.refs({"kind": "method", "question_ids": ["RQ-1"]}),
            [("research_question", "RQ-1")],
        )
        self.assertEqual(self.refs({"kind": "evidence", "source_id": "S"}), [("source", "S")])
        self.assertEqual(self.refs({"kind": "evidence"}), [])
        self.assertEqual(
            self.refs(
                {"kind": "analysis", "question_ids": ["Q"], "method_id": "M", "evidence_ids": ["E"]}
            ),
            [("research_question", "Q"), ("method", "M"), ("evidence", "E")],
        )
        self.assertEqual(self.refs({"kind": "analysis"}), [])

    def test_finding_counter_review_argument(self):
        self.assertEqual(
            self.refs(
                {
                    "kind": "finding",
                    "question_ids": ["Q"],
                    "evidence_ids": ["E"],
                    "analysis_ids": ["A"],
                    "counter_evidence_ids": ["CE"],
                }
            ),
            [("research_question", "Q"), ("evidence", "E"), ("analysis", "A"), ("evidence", "CE")],
        )
        self.assertEqual(
            self.refs(
                {
                    "kind": "counter_review",
                    "target": {"kind": "finding", "id": "F"},
                    "evidence_ids": ["E"],
                }
            ),
            [("finding", "F"), ("evidence", "E")],
        )
        self.assertEqual(self.refs({"kind": "counter_review", "target": {"kind": "finding"}}), [])
        self.assertEqual(
            self.refs(
                {
                    "kind": "argument",
                    "question_ids": ["Q"],
                    "conclusion_claim_id": "C0",
                    "premise_claim_ids": ["C1"],
                    "finding_ids": ["F"],
                    "evidence_ids": ["E"],
                    "counter_review_ids": ["CR"],
                }
            ),
            [
                ("research_question", "Q"),
                ("claim", "C0"),
                ("claim", "C1"),
                ("finding", "F"),
                ("evidence", "E"),
                ("counter_review", "CR"),
            ],
        )
        self.assertEqual(self.refs({"kind": "argument"}), [])

    def test_contribution_recommendation_next_action(self):
        self.assertEqual(
            self.refs({"kind": "contribution", "finding_ids": ["F"]}), [("finding", "F")]
        )
        self.assertEqual(
            self.refs({"kind": "recommendation", "finding_ids": ["F"]}), [("finding", "F")]
        )
        self.assertEqual(
            self.refs(
                {
                    "kind": "next_action",
                    "target": {"kind": "finding", "id": "F"},
                    "blocked_by": ["X"],
                }
            ),
            [("finding", "F"), ("*", "X")],
        )
        self.assertEqual(self.refs({"kind": "next_action", "target": "F"}), [])

    def test_decision_subjects_are_limited_to_core_kinds(self):
        obj = {
            "kind": "decision",
            "subjects": [
                {"kind": "finding", "id": "F"},
                {"kind": "research_lineage", "id": "LIN-1"},
                {"kind": "lineage_plan", "id": "PLAN"},
                {"id": "no-kind"},
                "junk",
            ],
        }
        self.assertEqual(self.refs(obj), [("finding", "F")])
        self.assertEqual(self.refs({"kind": "decision", "subjects": None}), [])

    def test_artifact_snapshot_reference(self):
        self.assertEqual(
            self.refs({"kind": "artifact", "source_snapshot_id": "SNP-1"}), [("snapshot", "SNP-1")]
        )
        self.assertEqual(self.refs({"kind": "artifact"}), [])

    def test_unknown_kind_yields_only_project(self):
        self.assertEqual(self.refs({"kind": "mystery", "finding_ids": ["F"]}), [])

    def test_ids_ignores_strings_and_non_sequences(self):
        self.assertEqual(list(sv._ids("evidence", "E1")), [])
        self.assertEqual(list(sv._ids("evidence", b"E1")), [])
        self.assertEqual(list(sv._ids("evidence", None)), [])
        self.assertEqual(
            list(sv._ids("evidence", (1, "E2"))), [("evidence", "1"), ("evidence", "E2")]
        )


class CoreInvariantTests(unittest.TestCase):
    def check(self, *objects, state=None):
        state = state or seed_state()
        return sv._validate_core_invariants(
            state, make_request(state, ()), reduction(objects=objects)
        )

    def test_valid_fixture_objects_pass(self):
        self.assertEqual(self.check(rq(), evidence(), finding()), [])

    def test_question_derivation_must_resolve_exact_revision(self):
        good = {
            **rq(),
            "id": "RQ-2",
            "derived_from_question_revisions": [{"id": "RQ-1", "revision": 0}],
        }
        self.assertEqual(self.check(rq(), good), [])
        bad = {
            **rq(),
            "id": "RQ-2",
            "derived_from_question_revisions": [{"id": "RQ-1", "revision": 5}, "junk"],
        }
        issues = self.check(rq(), bad)
        self.assertEqual(codes(issues), ["RT-CORE-PROV-005"])
        self.assertEqual(issues[0].affected_refs, ("RQ-2", "RQ-1"))
        self.assertEqual(issues[0].stage, ValidationStage.CORE_INVARIANTS)
        self.assertEqual(self.check({**rq(), "derived_from_question_revisions": None}), [])

    def test_evidence_traceability(self):
        for field in ("source_id", "locator"):
            with self.subTest(field=field):
                obj = evidence()
                obj[field] = ""
                issues = self.check(obj)
                self.assertEqual(codes(issues), ["RT-CORE-TRACE-001"])
                self.assertEqual(issues[0].affected_refs, ("EVD-1",))

    def test_finding_requires_question(self):
        obj = finding()
        obj["question_ids"] = []
        self.assertEqual(codes(self.check(obj)), ["RT-CORE-TRACE-002"])

    def test_argument_requires_finding_or_evidence(self):
        arg = {"kind": "argument", "id": "ARG-1", "revision": 0}
        self.assertEqual(codes(self.check(arg)), ["RT-CORE-TRACE-003"])
        self.assertEqual(self.check({**arg, "finding_ids": ["F"]}), [])
        self.assertEqual(self.check({**arg, "evidence_ids": ["E"]}), [])

    def test_recommendation_requires_finding(self):
        rec = {"kind": "recommendation", "id": "REC-1", "revision": 0}
        self.assertEqual(codes(self.check(rec)), ["RT-CORE-TRACE-004"])
        self.assertEqual(self.check({**rec, "finding_ids": ["F"]}), [])

    def test_generated_artifact_requires_snapshot(self):
        for artifact_class in ("generated", "published"):
            with self.subTest(artifact_class=artifact_class):
                art = {
                    "kind": "artifact",
                    "id": "ART-1",
                    "revision": 0,
                    "artifact_class": artifact_class,
                }
                issues = self.check(art)
                self.assertEqual(codes(issues), ["RT-CORE-PROV-001"])
                self.assertEqual(issues[0].affected_refs, ())
                self.assertEqual(self.check({**art, "source_snapshot_id": "SNP-0"}), [])
        self.assertEqual(
            self.check({"kind": "artifact", "id": "A", "revision": 0, "artifact_class": "input"}),
            [],
        )

    def test_publication_artifact_must_be_explicitly_not_evidence(self):
        art = {"kind": "artifact", "id": "ART-1", "revision": 0, "lane": "publication"}
        self.assertEqual(codes(self.check(art)), ["RT-CORE-FW-001"])
        self.assertEqual(codes(self.check({**art, "evidence_eligible": True})), ["RT-CORE-FW-001"])
        self.assertEqual(self.check({**art, "evidence_eligible": False}), [])

    def test_existing_revision_cannot_be_replaced(self):
        state = seed_state(objects=[project(), rq()])
        self.assertEqual(self.check(rq(), state=state), [])
        changed = {**rq(), "text": "Changed"}
        issues = self.check(changed, state=state)
        self.assertEqual(codes(issues), ["RT-CORE-PROV-002"])
        self.assertEqual(issues[0].affected_refs, ("RQ-1",))

    def test_snapshot_members_are_part_of_effective_objects(self):
        bad = finding()
        bad["question_ids"] = []
        state = seed_state(objects=[project(), bad])
        self.assertEqual(codes(self.check(state=state)), ["RT-CORE-TRACE-002"])


class ProfileStrengtheningTests(unittest.TestCase):
    def check(self, constraints, *objects):
        state = seed_state(constraints=constraints)
        return sv._validate_profile_strengthening(state, reduction(objects=objects))

    def test_no_constraints_pass(self):
        self.assertEqual(self.check({}, rq()), [])

    def test_weakening_core_is_rejected(self):
        for constraints in ({"weakens_core": True}, {"core_override_requests": ["x"]}):
            with self.subTest(constraints=constraints):
                issues = self.check(constraints)
                self.assertEqual(codes(issues), ["RT-PROFILE-001"])
                self.assertEqual(issues[0].stage, ValidationStage.PROFILE_CONSTRAINTS)

    def test_required_fields_by_kind(self):
        constraints = {"required_fields_by_kind": {"research_question": ["text", "scope", "owner"]}}
        issues = self.check(constraints, rq(), finding())
        self.assertEqual(codes(issues), ["RT-PROFILE-002"])
        self.assertEqual(
            issues[0].message, "Resolved Profile strengthening requires fields: scope, owner."
        )
        self.assertEqual(issues[0].affected_refs, ("RQ-1",))

    def test_malformed_required_fields_are_ignored(self):
        for value in ("not-a-map", {"research_question": "scope"}, {"research_question": None}):
            with self.subTest(value=value):
                self.assertEqual(self.check({"required_fields_by_kind": value}, rq()), [])


class ProjectGuardTests(unittest.TestCase):
    def check(self, project_config, *objects):
        state = seed_state(project_config=project_config)
        return sv._validate_project_guards(state, reduction(objects=objects))

    def test_literal_guard_statement_is_rejected(self):
        config = {
            "project_constraints": {
                "must_not_claim": [
                    {"guard_id": "G-1", "statement": "supported"},
                    {"statement": "Candidate"},
                    {"guard_id": "G-EMPTY", "statement": ""},
                    "junk",
                ]
            }
        }
        issues = self.check(config, rq(), finding())
        self.assertEqual(
            [(issue.error_code, issue.affected_refs) for issue in issues],
            [("RT-PROJECT-001", ("G-1", "RQ-1")), ("RT-PROJECT-001", ("guard", "FND-1"))],
        )
        self.assertEqual(issues[0].stage, ValidationStage.PROJECT_GUARDS)

    def test_only_text_fields_are_searched(self):
        config = {"project_constraints": {"must_not_claim": [{"statement": "RQ-1"}]}}
        self.assertEqual(self.check(config, rq()), [])

    def test_malformed_configs_are_ignored(self):
        for config in (
            {},
            {"project_constraints": "x"},
            {"project_constraints": {"must_not_claim": "supported"}},
        ):
            with self.subTest(config=config):
                self.assertEqual(self.check(config, rq()), [])

    def test_non_mapping_project_config(self):
        state = replace(seed_state(), project_config=["not", "a", "mapping"])
        self.assertEqual(sv._validate_project_guards(state, reduction(objects=[rq()])), [])


class AdoptionBoundaryTests(unittest.TestCase):
    def test_direct_mutation_flags(self):
        state = seed_state()
        actions = [
            TransitionAction(TransitionKind.CREATE_OBJECT, {"direct_handoff_mutation": True}),
            TransitionAction(
                TransitionKind.CREATE_OBJECT, {"direct_writer_feedback_mutation": True}
            ),
            TransitionAction(TransitionKind.CREATE_OBJECT, {"direct_handoff_mutation": "yes"}),
        ]
        issues = sv._validate_adoption_boundaries(state, make_request(state, actions), reduction())
        self.assertEqual(codes(issues), ["RT-BOUNDARY-001", "RT-BOUNDARY-002"])
        self.assertTrue(all(i.stage == ValidationStage.ADOPTION_BOUNDARIES for i in issues))


class LineagePostconditionTests(unittest.TestCase):
    def setUp(self):
        self.state = seed_state()
        self.parent = self.state.lineages[0]
        self.child = replace(self.parent, lineage_id="LIN-2", lineage_kind="exploratory_fork")
        self.action = TransitionAction(
            TransitionKind.APPLY_LINEAGE_PLAN, {"target_lineage_id": "LIN-2"}
        )

    def check(self, red, request=None):
        request = request or make_request(self.state, [self.action])
        return sv._validate_lineage_postconditions(self.state, request, red)

    def test_child_created_and_parent_unmoved_passes(self):
        self.assertEqual(self.check(reduction(new_lineages=[self.child])), [])
        self.assertEqual(
            self.check(reduction(new_lineages=[self.child], lineage_updates=[self.parent])), []
        )

    def test_missing_child(self):
        issues = self.check(reduction())
        self.assertEqual(codes(issues), ["RT-LINEAGE-012"])
        self.assertEqual(issues[0].affected_refs, ("LIN-2",))

    def test_parent_head_moved(self):
        for change in ({"head_snapshot_ref": "SNP-X"}, {"head_snapshot_digest": "sha256:x"}):
            with self.subTest(change=change):
                moved = replace(self.parent, **change)
                issues = self.check(reduction(new_lineages=[self.child], lineage_updates=[moved]))
                self.assertEqual(codes(issues), ["RT-LINEAGE-011"])
                self.assertEqual(issues[0].affected_refs, ("LIN-1",))

    def test_unknown_parent_skips_head_check(self):
        request = replace(make_request(self.state, [self.action]), lineage_ref="LIN-X")
        moved = LineageView("LIN-X", "primary", "S", "d", 0, "real")
        self.assertEqual(
            self.check(reduction(new_lineages=[self.child], lineage_updates=[moved]), request), []
        )

    def test_other_actions_are_ignored(self):
        request = make_request(self.state, [TransitionAction(TransitionKind.CREATE_OBJECT, {})])
        self.assertEqual(self.check(reduction(), request), [])


class EpistemicPostconditionTests(unittest.TestCase):
    def check(self, prior, revised, *, actions=(), decisions=()):
        state = seed_state(objects=[project(), source(), prior], decisions=decisions)
        return sv._validate_epistemic_postconditions(
            state, make_request(state, actions), reduction(objects=[revised])
        )

    def test_non_evidence_and_new_evidence_are_ignored(self):
        state = seed_state()
        self.assertEqual(
            sv._validate_epistemic_postconditions(
                state, make_request(state, ()), reduction(objects=[rq(), evidence()])
            ),
            [],
        )

    def test_synthetic_mode_is_immutable(self):
        issues = self.check(evidence(mode="synthetic"), evidence(revision=1, mode="empirical"))
        self.assertEqual(codes(issues), ["RT-EPI-005"])
        self.assertEqual(issues[0].affected_refs, ("EVD-1",))
        self.assertEqual(
            self.check(evidence(mode="synthetic"), evidence(revision=1, mode="synthetic")), []
        )

    def test_limitations_cannot_be_silently_erased(self):
        prior = evidence(limitations=["small n", "self-report"])
        revised = evidence(revision=1, limitations=["small n"])
        issues = self.check(prior, revised)
        self.assertEqual(codes(issues), ["RT-EPI-006"])
        self.assertEqual(issues[0].stage, ValidationStage.EPISTEMIC_FIREWALL)
        self.assertEqual(
            self.check(prior, evidence(revision=1, limitations=["small n", "self-report", "new"])),
            [],
        )

    def test_limitation_removal_allowed_with_human_revision_decision(self):
        prior = evidence(limitations=["small n"])
        revised = evidence(revision=1)
        dec = decision("DEC-R", "research_revision", "revise", "evidence", "EVD-1")
        action = TransitionAction(
            TransitionKind.REVISE_OBJECT, {"object": revised}, decision_refs=("DEC-R",)
        )
        self.assertEqual(self.check(prior, revised, actions=[action], decisions=[dec]), [])

    def test_limitation_removal_with_unsuitable_decisions(self):
        prior = evidence(limitations=["small n"])
        revised = evidence(revision=1)
        variants = {
            "agent": {
                **decision("D", "research_revision", "revise", "evidence", "EVD-1"),
                "actor_type": "agent",
            },
            "kind": decision("D", "research_adoption", "revise", "evidence", "EVD-1"),
            "choice": decision("D", "research_revision", "approve", "evidence", "EVD-1"),
            "subject": decision("D", "research_revision", "revise", "evidence", "EVD-2"),
        }
        for name, dec in variants.items():
            with self.subTest(name=name):
                action = TransitionAction(
                    TransitionKind.REVISE_OBJECT, {"object": revised}, decision_refs=("D",)
                )
                issues = self.check(prior, revised, actions=[action], decisions=[dec])
                self.assertEqual(codes(issues), ["RT-EPI-006"])
        unresolved = TransitionAction(
            TransitionKind.REVISE_OBJECT, {"object": revised}, decision_refs=("NOPE",)
        )
        self.assertEqual(codes(self.check(prior, revised, actions=[unresolved])), ["RT-EPI-006"])


class NextStateTests(unittest.TestCase):
    def setUp(self):
        self.state = seed_state(objects=[project(), rq()])

    def check(self, new_snapshot, objects=()):
        return sv._validate_next_state(
            self.state, reduction(objects=objects, new_snapshot=new_snapshot)
        )

    def test_no_snapshot_passes(self):
        self.assertEqual(self.check(None), [])

    def test_canonical_new_snapshot_passes(self):
        revised = rq(revision=1)
        snap = snapshot("SNP-1", [project(), revised], prior="SNP-0")
        self.assertEqual(self.check(snap, [revised]), [])

    def test_snapshot_identity_reuse(self):
        snap = snapshot("SNP-0", [project(), rq()])
        issues = self.check(snap)
        self.assertEqual(codes(issues), ["RT-STATE-001"])
        self.assertEqual(issues[0].affected_refs, ("SNP-0",))
        self.assertEqual(issues[0].stage, ValidationStage.NEXT_STATE)

    def test_snapshot_identity_reuse_of_stored_snapshot_object(self):
        old = snapshot("SNP-OLD", [project()])
        state = replace(self.state, objects=(*self.state.objects, old))
        issues = sv._validate_next_state(
            state, reduction(new_snapshot=snapshot("SNP-OLD", [project(), rq()]))
        )
        self.assertEqual(codes(issues), ["RT-STATE-001"])

    def resealed(self, members):
        snap = snapshot("SNP-1", [project(), rq()])
        snap["members"] = members
        return with_content_digest(snap)

    def test_duplicate_unresolved_and_wrong_digest_members(self):
        good = {
            "kind": "project",
            "id": "PRJ-1",
            "revision": 0,
            "digest": canonical_digest(project()),
        }
        members = [
            good,
            dict(good),
            {"kind": "finding", "id": "FND-X", "revision": 0, "digest": "sha256:x"},
            {"kind": "research_question", "id": "RQ-1", "revision": 0, "digest": "sha256:bad"},
        ]
        issues = self.check(self.resealed(members))
        self.assertEqual(
            [(issue.error_code, issue.affected_refs) for issue in issues],
            [
                ("RT-STATE-002", ("PRJ-1",)),
                ("RT-STATE-003", ("FND-X",)),
                ("RT-STATE-004", ("RQ-1",)),
            ],
        )

    def test_members_may_resolve_to_new_revisions(self):
        revised = rq(revision=1)
        member = {
            "kind": "research_question",
            "id": "RQ-1",
            "revision": 1,
            "digest": canonical_digest(revised),
        }
        self.assertEqual(self.check(self.resealed([member]), [revised]), [])
        self.assertEqual(codes(self.check(self.resealed([member]))), ["RT-STATE-003"])

    def test_non_canonical_content_digest(self):
        snap = snapshot("SNP-1", [project(), rq()])
        snap["content_digest"] = "sha256:" + "0" * 64
        issues = self.check(snap)
        self.assertEqual(codes(issues), ["RT-STATE-005"])
        self.assertEqual(issues[0].affected_refs, ("SNP-1",))

    def test_snapshot_without_members(self):
        snap = with_content_digest({"id": "SNP-1", "kind": "snapshot"})
        self.assertEqual(self.check(snap), [])


class MapHelperTests(unittest.TestCase):
    def test_effective_object_map_overlays_new_revisions(self):
        state = seed_state(objects=[project(), rq()])
        revised = rq(revision=1)
        result = sv._effective_object_map(state, [revised])
        self.assertEqual(set(result), {("project", "PRJ-1"), ("research_question", "RQ-1")})
        self.assertIs(result[("research_question", "RQ-1")], revised)

    def test_object_revision_map_keys_by_exact_revision(self):
        result = sv._object_revision_map([rq()], [rq(revision=1), {"kind": "x"}])
        self.assertEqual(
            set(result),
            {("research_question", "RQ-1", 0), ("research_question", "RQ-1", 1), ("x", "", -1)},
        )


if __name__ == "__main__":
    unittest.main()
