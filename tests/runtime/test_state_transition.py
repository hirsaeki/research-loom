from __future__ import annotations

from dataclasses import replace
import unittest

from core.runtime import StateTransitionRejected, TransitionAction, TransitionKind, reduce_state
from core.runtime.transition_models import CommitReceipt
from runtime_fixtures import *

class StateTransitionRuntimeTests(unittest.TestCase):
    def test_create_first_project_and_rq_draft_state(self):
        base = seed_state(objects=[])
        p = project()
        q = rq()
        req = make_request(base, [
            TransitionAction(TransitionKind.CREATE_OBJECT,{"object":p}),
            TransitionAction(TransitionKind.CREATE_OBJECT,{"object":q}),
        ])
        repo, svc = service(base)
        receipt = svc.apply(req)
        self.assertIsInstance(receipt, CommitReceipt)
        current = repo.load_state_view("PRJ-1","LIN-1")
        self.assertIsNotNone(current.latest_object("project","PRJ-1"))
        self.assertEqual(current.latest_object("research_question","RQ-1")["adoption_state"],"candidate")

    def test_adopt_rq_requires_exact_human_decision(self):
        base = seed_state(objects=[project(),rq()])
        no_decision = make_request(base,[TransitionAction(TransitionKind.ADOPT_OBJECT,{"object":rq(revision=1,state="approved")})])
        _, svc = service(base)
        rejected = svc.apply(no_decision)
        self.assertIsInstance(rejected, StateTransitionRejected)
        self.assertIn("RT-DECISION-001", codes(rejected))

        dec = decision("DEC-RQ","research_adoption","approve","research_question","RQ-1")
        adopted = rq(revision=1,state="approved",decision_ids=("DEC-RQ",))
        req = make_request(base,[
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":dec}),
            TransitionAction(TransitionKind.ADOPT_OBJECT,{"object":adopted},decision_refs=("DEC-RQ",)),
        ],suffix="2")
        repo, svc = service(base)
        receipt = svc.apply(req)
        self.assertIsInstance(receipt, CommitReceipt)
        self.assertEqual(repo.load_state_view("PRJ-1","LIN-1").latest_object("research_question","RQ-1")["revision"],1)

    def test_human_decision_cannot_be_replayed_for_later_transition(self):
        base = seed_state(objects=[project(),rq()])
        dec = decision("DEC-RQ","research_adoption","approve","research_question","RQ-1")
        adopted = rq(revision=1,state="approved",decision_ids=("DEC-RQ",))
        first = make_request(base,[
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":dec}),
            TransitionAction(TransitionKind.ADOPT_OBJECT,{"object":adopted},decision_refs=("DEC-RQ",)),
        ])
        repo, svc = service(base)
        self.assertIsInstance(svc.apply(first), CommitReceipt)
        current = repo.load_state_view("PRJ-1","LIN-1")
        revised = dict(adopted); revised.update(revision=2,text="Materially changed RQ",decision_ids=["DEC-RQ"])
        second = make_request(current,[TransitionAction(TransitionKind.REVISE_OBJECT,{"object":revised},decision_refs=("DEC-RQ",))],suffix="2")
        rejected = svc.apply(second)
        self.assertIn("RT-DECISION-005", codes(rejected))

    def test_active_lineage_switch_is_authorized_and_does_not_create_snapshot(self):
        base = seed_state(objects=[project(),rq()])
        second_line = replace(base.lineages[0], lineage_id="LIN-2")
        dec = decision("DEC-SWITCH","active_lineage_selection","switch","research_lineage","LIN-2")
        base = replace(base, lineages=(*base.lineages, second_line), decisions=(dec,), objects=(*base.objects, dec))
        action = TransitionAction(TransitionKind.SWITCH_ACTIVE_LINEAGE,{"target_lineage_ref":"LIN-2"},decision_refs=("DEC-SWITCH",))
        repo, svc = service(base)
        receipt = svc.apply(make_request(base,[action]))
        self.assertIsInstance(receipt, CommitReceipt)
        self.assertIsNone(receipt.new_snapshot_ref)
        self.assertEqual(repo.debug_state()["active"],"LIN-2")
        self.assertEqual(repo.load_state_view("PRJ-1","LIN-1").current_snapshot["id"],base.current_snapshot["id"])

    def test_material_finding_revision_requires_revision_decision(self):
        base = seed_state(objects=[project(),rq(),finding()])
        revised = finding(revision=1,statement="Materially revised finding")
        _, svc = service(base)
        rejected = svc.apply(make_request(base,[TransitionAction(TransitionKind.REVISE_OBJECT,{"object":revised})]))
        self.assertIn("RT-DECISION-001", codes(rejected))

        dec = decision("DEC-REV","research_revision","revise","finding","FND-1")
        revised["decision_ids"]=["DEC-REV"]
        req = make_request(base,[
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":dec}),
            TransitionAction(TransitionKind.REVISE_OBJECT,{"object":revised},decision_refs=("DEC-REV",)),
        ],suffix="2")
        repo, svc = service(base)
        self.assertIsInstance(svc.apply(req), CommitReceipt)
        self.assertIsNotNone(repo.load_object_revision("finding","FND-1",0))
        self.assertIsNotNone(repo.load_object_revision("finding","FND-1",1))

    def test_evidence_verify_and_reclassify_requires_combined_authority(self):
        base = seed_state(objects=[project(),source(),evidence()])
        verify = decision("DEC-VERIFY","evidence_qualification","verify","evidence","EVD-1")
        changed = evidence(revision=1,evidence_kind="supporting",verification="verified",decision_ids=("DEC-VERIFY",))
        req = make_request(base,[
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":verify}),
            TransitionAction(TransitionKind.VERIFY_EVIDENCE,{"object":changed},decision_refs=("DEC-VERIFY",)),
        ])
        _, svc = service(base)
        rejected = svc.apply(req)
        self.assertIn("RT-DECISION-001", codes(rejected))

        reclass = decision("DEC-RECLASS","evidence_reclassification","reclassify","evidence","EVD-1")
        changed["decision_ids"]=["DEC-VERIFY","DEC-RECLASS"]
        req = make_request(base,[
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":verify}),
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":reclass}),
            TransitionAction(TransitionKind.VERIFY_EVIDENCE,{"object":changed},decision_refs=("DEC-VERIFY","DEC-RECLASS")),
        ],suffix="2")
        repo, svc = service(base)
        self.assertIsInstance(svc.apply(req), CommitReceipt)
        self.assertEqual(repo.load_object_revision("evidence","EVD-1",1)["evidence_kind"],"supporting")

    def test_dangling_reference_is_rejected(self):
        base = seed_state(objects=[project()])
        bad = finding(question_id="RQ-MISSING")
        _, svc = service(base)
        rejected = svc.apply(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":bad})]))
        self.assertIn("RT-REF-001", codes(rejected))

    def test_snapshot_digest_membership_and_lineage_head_are_atomic(self):
        base = seed_state(objects=[project(),rq()])
        claim = {"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"Candidate claim","assessment":"proposed"}
        req = make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim})])
        repo, svc = service(base)
        receipt = svc.apply(req)
        self.assertIsInstance(receipt, CommitReceipt)
        state = repo.load_state_view("PRJ-1","LIN-1")
        self.assertEqual(state.current_snapshot["id"],receipt.new_snapshot_ref)
        self.assertEqual(state.current_snapshot["content_digest"],receipt.new_snapshot_digest)
        member = next(item for item in state.current_snapshot["members"] if item["id"]=="CLM-1")
        self.assertEqual(member["digest"],canonical_digest(claim))

    def test_snapshot_id_reuse_rejected(self):
        base = seed_state(objects=[project(),rq()],snapshot_id="SNP-OLD")
        claim = {"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"Candidate","assessment":"proposed"}
        _, svc = service(base)
        rejected = svc.apply(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim})],new_snapshot_id="SNP-OLD"))
        self.assertIn("RT-STATE-001", codes(rejected))

    def test_stale_head_rejected_without_automatic_rebase(self):
        base = seed_state(objects=[project(),rq()])
        repo, svc = service(base)
        stale_req = make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":{"schema_version":"0.1.0","id":"CLM-B","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"B","assessment":"proposed"}})],suffix="2")
        first = make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":{"schema_version":"0.1.0","id":"CLM-A","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"A","assessment":"proposed"}})],suffix="1")
        self.assertIsInstance(svc.apply(first),CommitReceipt)
        rejected = svc.apply(stale_req)
        self.assertIn("RT-HEAD-001",codes(rejected))
        self.assertTrue(any(issue.retryable for issue in rejected.issues))

    def test_idempotent_retry_and_payload_collision(self):
        base = seed_state(objects=[project(),rq()])
        repo, svc = service(base)
        action = TransitionAction(TransitionKind.CREATE_OBJECT,{"object":{"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"A","assessment":"proposed"}})
        req = make_request(base,[action],key="IDEMP-X")
        first = svc.apply(req)
        second = svc.apply(req)
        self.assertEqual(first,second)
        collision = replace(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":{"schema_version":"0.1.0","id":"CLM-2","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"B","assessment":"proposed"}})],suffix="2",key="IDEMP-X"), expected_head_snapshot_ref=req.expected_head_snapshot_ref, expected_head_snapshot_digest=req.expected_head_snapshot_digest)
        collision = collision.with_calculated_digest()
        rejected = svc.apply(collision)
        self.assertIn("RT-IDEMPOTENCY-001",codes(rejected))

    def test_failed_commit_leaves_repository_unchanged(self):
        base = seed_state(objects=[project(),rq()])
        repo, svc = service(base)
        before = repo.debug_state()
        repo.fail_next_commit=True
        claim = {"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"A","assessment":"proposed"}
        rejected = svc.apply(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim})]))
        self.assertIn("RT-PERSIST-001",codes(rejected))
        self.assertEqual(before,repo.debug_state())

    def test_capability_handoff_and_writer_feedback_cannot_mutate_directly(self):
        base = seed_state(objects=[project(),rq(),finding()])
        _, svc = service(base)
        handoff = finding(revision=1,statement="Direct handoff mutation")
        dec = decision("DEC-REV","research_revision","revise","finding","FND-1")
        handoff["decision_ids"]=["DEC-REV"]
        req = make_request(base,[
            TransitionAction(TransitionKind.RECORD_DECISION,{"object":dec}),
            TransitionAction(TransitionKind.REVISE_OBJECT,{"object":handoff,"direct_handoff_mutation":True},decision_refs=("DEC-REV",)),
        ])
        rejected = svc.apply(req)
        self.assertIn("RT-BOUNDARY-001",codes(rejected))

        next_action={"schema_version":"0.1.0","id":"ACT-1","kind":"next_action","revision":0,"project_id":"PRJ-1","action_type":"verify","target":{"kind":"finding","id":"FND-1"},"instruction":"Verify scope","reason":"Writer feedback gap","priority":"high","status":"open"}
        rejected = svc.apply(make_request(base,[TransitionAction(TransitionKind.REGISTER_WRITING_FEEDBACK_ACTION,{"object":next_action,"direct_writer_feedback_mutation":True})],suffix="2"))
        self.assertIn("RT-BOUNDARY-002",codes(rejected))

    def test_fork_creates_child_without_moving_parent(self):
        objs=[project(),rq()]
        dec=decision("DEC-FORK","lineage_plan","apply","lineage_plan","PLAN-1")
        base=seed_state(objects=objs,decisions=(dec,))
        action=TransitionAction(TransitionKind.APPLY_LINEAGE_PLAN,{
            "plan_ref":"PLAN-1","target_lineage_id":"LIN-CHILD","lineage_kind":"exploratory_fork",
            "baseline_snapshot_ref":base.current_snapshot["id"],"baseline_snapshot_digest":base.current_snapshot["content_digest"],
            "treatments":[{"object_kind":item["kind"],"source_ref":item["id"],"treatment":"PRESERVE"} for item in objs]
        },decision_refs=("DEC-FORK",))
        repo,svc=service(base)
        receipt=svc.apply(make_request(base,[action]))
        self.assertIsInstance(receipt,CommitReceipt)
        parent=repo.load_state_view("PRJ-1","LIN-1")
        child=repo.load_state_view("PRJ-1","LIN-CHILD")
        self.assertEqual(parent.current_snapshot["id"],base.current_snapshot["id"])
        self.assertNotEqual(child.current_snapshot["id"],parent.current_snapshot["id"])
        self.assertEqual(repo.debug_state()["active"],"LIN-1")

    def test_recovery_applies_explicit_treatments_and_registers_replay_plan(self):
        objs=[project(),rq(),finding()]
        plan=decision("DEC-REC","lineage_plan","apply","lineage_plan","PLAN-REC")
        reconfirm=decision("DEC-RECONF","lineage_reconfirmation","reconfirm","finding","FND-1")
        base=seed_state(objects=objs,decisions=(plan,reconfirm))
        derived=finding(revision=1,statement="Reconfirmed finding",decision_ids=("DEC-RECONF",))
        action=TransitionAction(TransitionKind.APPLY_LINEAGE_PLAN,{
            "plan_ref":"PLAN-REC","target_lineage_id":"LIN-REC","lineage_kind":"corrective_recovery",
            "baseline_snapshot_ref":base.current_snapshot["id"],"baseline_snapshot_digest":base.current_snapshot["content_digest"],"replay_plan_ref":"REPLAY-1",
            "treatments":[
                {"object_kind":"project","source_ref":"PRJ-1","treatment":"PRESERVE"},
                {"object_kind":"research_question","source_ref":"RQ-1","treatment":"PRESERVE"},
                {"object_kind":"finding","source_ref":"FND-1","treatment":"RECONFIRM","derived_object":derived,"human_decision_ref":"DEC-RECONF"},
            ]
        },decision_refs=("DEC-REC","DEC-RECONF"))
        repo,svc=service(base)
        receipt=svc.apply(make_request(base,[action]))
        self.assertIsInstance(receipt,CommitReceipt)
        recovered=repo.load_state_view("PRJ-1","LIN-REC")
        self.assertEqual(recovered.latest_object("finding","FND-1")["revision"],1)
        self.assertIn("REPLAY-1",recovered.adoption_refs)

    def test_old_run_or_handoff_marked_non_reusable_is_rejected(self):
        base=seed_state(objects=[project()],non_reusable=("HND-OLD",))
        action=TransitionAction(TransitionKind.RECORD_RUN_RESULT_ADOPTION,{"adoption_refs":["HND-OLD"]},source_refs=("HND-OLD",))
        _,svc=service(base)
        rejected=svc.apply(make_request(base,[action],source_refs=("HND-OLD",)))
        self.assertIn("RT-EPI-004",codes(rejected))

    def test_virtual_to_real_content_and_synthetic_evidence_promotion_rejected(self):
        base=seed_state(objects=[project(),source(),evidence(mode="synthetic")])
        promoted=evidence(revision=1,evidence_kind="counterevidence",verification="unverified",mode="empirical")
        dec=decision("DEC-RECLASS","evidence_reclassification","reclassify","evidence","EVD-1")
        promoted["decision_ids"]=["DEC-RECLASS"]
        _,svc=service(base)
        rejected=svc.apply(make_request(base,[TransitionAction(TransitionKind.RECLASSIFY_EVIDENCE,{"object":promoted},decision_refs=("DEC-RECLASS",))]))
        self.assertIn("RT-EPI-001",codes(rejected))

        base=seed_state(objects=[project(),rq()],source_modes={"HND-VIRTUAL":"virtual"})
        claim={"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"Virtual-derived claim","assessment":"proposed"}
        _,svc=service(base)
        rejected=svc.apply(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim},source_refs=("HND-VIRTUAL",))],source_refs=("HND-VIRTUAL",)))
        self.assertIn("RT-EPI-002",codes(rejected))

    def test_profile_weakening_and_project_must_not_claim_rejected(self):
        base=seed_state(objects=[project(),rq()],constraints={"weakens_core":True})
        claim={"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"A","assessment":"proposed"}
        _,svc=service(base)
        rejected=svc.apply(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim})]))
        self.assertIn("RT-PROFILE-001",codes(rejected))

        config={"project_constraints":{"must_not_claim":[{"guard_id":"G-1","statement":"AGI date is certain"}]}}
        base=seed_state(objects=[project(),rq()],project_config=config)
        bad=finding(statement="AGI date is certain")
        _,svc=service(base)
        rejected=svc.apply(make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":bad})]))
        self.assertIn("RT-PROJECT-001",codes(rejected))

    def test_deterministic_reduction_under_object_order_variation(self):
        base=seed_state(objects=[project(),rq(),source()])
        shuffled=replace(base,objects=tuple(reversed(base.objects)))
        claim={"schema_version":"0.1.0","id":"CLM-1","kind":"claim","revision":0,"project_id":"PRJ-1","question_id":"RQ-1","statement":"A","assessment":"proposed"}
        req=make_request(base,[TransitionAction(TransitionKind.CREATE_OBJECT,{"object":claim})])
        left=reduce_state(base,req)
        right=reduce_state(shuffled,req)
        self.assertEqual(left.new_snapshot,right.new_snapshot)
        self.assertEqual(left.object_revisions,right.object_revisions)
