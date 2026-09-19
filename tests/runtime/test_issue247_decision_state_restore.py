from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core.decision import HumanDecisionError, make_response
from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade, LocalWorkspace
from test_research_question_review import _workspace, _adopt_question


class DecisionStateRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = _workspace(self.root)
        self.parent = self.workspace / ".research-loom"
        self.backup = self.root / "quiesced-backup"
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            candidate = facade.submit_action({"action_type": "research_question.propose", "payload": {"text": "Restore-bound question"}, "actor_id": "H"})
            self.question_id = candidate["data"]["research_question_candidate"]["id"]
            confirmation = facade.submit_action({"action_type": "state.apply_candidate", "payload": {"state_delta_proposal_id": candidate["data"]["state_delta_proposal_id"]}, "actor_id": "H"})
            self.request = facade.submit_confirmation({"confirmation_request_id": confirmation["confirmation_request"]["confirmation_request_id"], "actor_id": "H"})["decision_request"]
            self.response = make_response(request=self.request, disposition="approve_exact", actor_id="H", responded_at="2026-09-20T01:00:00Z")
            self.before = facade.status()["snapshot"]
        # The backup is made only after all application/SQLite handles close.
        shutil.copytree(self.parent, self.backup)

    def _resolve(self):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            return facade.resolve_human_decision(self.response)

    def test_state_only_rollback_is_not_ok_or_resolved_and_does_not_reapply(self):
        self._resolve()
        shutil.copy2(self.backup / "research-state.sqlite3", self.parent / "research-state.sqlite3")
        diagnosis = LocalWorkspace.doctor(self.workspace)
        self.assertEqual(diagnosis["status"], "ERROR", diagnosis)
        self.assertIn("WORKSPACE-DECISION-STATE-MISMATCH-001", {item["code"] for item in diagnosis["issues"]})
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            with patch.object(facade._application.state_transition_service, "apply", side_effect=AssertionError("a missing historical commit must not be replayed silently")):
                with self.assertRaises(HumanDecisionError) as raised:
                    facade.resolve_human_decision(self.response)
            self.assertEqual(raised.exception.code, "DECISION-STATE-MISMATCH-001")
            self.assertEqual(facade.status()["snapshot"], self.before)

    def test_whole_quiesced_backup_restores_same_effect_identity(self):
        original = self._resolve()
        quarantined = self.root / "post-commit-parent"
        self.parent.rename(quarantined)
        shutil.copytree(self.backup, self.parent)
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")
        recovered = self._resolve()
        self.assertEqual(recovered["status"], "RESOLVED")
        self.assertEqual(recovered["response"], original["response"])
        self.assertEqual(recovered["commit_receipt"], original["commit_receipt"])
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")

    def test_historical_success_survives_later_state_commits(self):
        original = self._resolve()
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            _adopt_question(facade, "A later independent question")
            advanced = facade.status()["snapshot"]
            self.assertNotEqual(advanced["snapshot_id"], original["commit_receipt"]["new_snapshot_ref"])
            with patch.object(facade._application.state_transition_service, "apply", side_effect=AssertionError("historical replay is read-only")):
                reused = facade.resolve_human_decision(self.response)
            self.assertEqual(reused["commit_receipt"], original["commit_receipt"])
            self.assertEqual(facade.status()["snapshot"], advanced)
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")

    def test_commit_before_finalize_interruption_remains_recoverable(self):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            with patch.object(facade._application.decision_store, "finalize", side_effect=OSError("injected finalize failure")):
                with self.assertRaises(OSError):
                    facade.resolve_human_decision(self.response)
            committed = facade.status()["snapshot"]
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")
        recovered = self._resolve()
        self.assertEqual(recovered["status"], "RESOLVED")
        self.assertEqual(recovered["commit_receipt"]["new_snapshot_ref"], committed["snapshot_id"])

    def test_mismatched_operational_receipt_is_not_historical_success(self):
        original = self._resolve()
        changed = deepcopy(original["commit_receipt"])
        changed["timestamp"] = "2099-01-01T00:00:00Z"
        with closing(sqlite3.connect(self.parent / "decision.db")) as db, db:
            db.execute("UPDATE decision_requests SET commit_receipt_json=? WHERE request_id=?", (json.dumps(changed), self.request["request_id"]))
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "ERROR")
        with self.assertRaises(HumanDecisionError) as raised:
            self._resolve()
        self.assertEqual(raised.exception.code, "DECISION-STATE-MISMATCH-001")

    def test_missing_canonical_decision_is_not_a_valid_receipt(self):
        original = self._resolve()
        decision_id = original["commit_receipt"]["resolving_decision_refs"][0]
        with closing(sqlite3.connect(self.parent / "research-state.sqlite3")) as db, db:
            db.execute("DELETE FROM object_revisions WHERE kind='decision' AND object_id=?", (decision_id,))
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "ERROR")
        with self.assertRaises(HumanDecisionError) as raised:
            self._resolve()
        self.assertEqual(raised.exception.code, "DECISION-STATE-MISMATCH-001")

    def _assert_doctor_history_mismatch(self):
        state_path = self.parent / "research-state.sqlite3"
        before = state_path.read_bytes()
        diagnosis = LocalWorkspace.doctor(self.workspace)
        self.assertEqual(diagnosis["status"], "ERROR", diagnosis)
        self.assertIn("WORKSPACE-DECISION-STATE-MISMATCH-001", {item["code"] for item in diagnosis["issues"]})
        self.assertEqual(state_path.read_bytes(), before)

    def test_doctor_rejects_object_revision_from_another_project(self):
        receipt = self._resolve()["commit_receipt"]
        project_id = self.request["project_ref"]
        for kind, ref in (("snapshot", receipt["new_snapshot_ref"]), ("decision", receipt["resolving_decision_refs"][0])):
            with self.subTest(kind=kind):
                with closing(sqlite3.connect(self.parent / "research-state.sqlite3")) as db, db:
                    db.execute("UPDATE object_revisions SET project_ref=? WHERE kind=? AND object_id=?", ("PRJ-OTHER", kind, ref))
                try:
                    self._assert_doctor_history_mismatch()
                finally:
                    with closing(sqlite3.connect(self.parent / "research-state.sqlite3")) as db, db:
                        db.execute("UPDATE object_revisions SET project_ref=? WHERE kind=? AND object_id=?", (project_id, kind, ref))
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")

    def test_doctor_rejects_self_consistent_cross_project_decision_payload(self):
        decision_id = self._resolve()["commit_receipt"]["resolving_decision_refs"][0]
        with closing(sqlite3.connect(self.parent / "research-state.sqlite3")) as db, db:
            row = db.execute("SELECT payload_json FROM object_revisions WHERE kind='decision' AND object_id=?", (decision_id,)).fetchone()
            payload = json.loads(row[0])
            payload["project_id"] = "PRJ-OTHER"
            digest = canonical_digest(payload)
            db.execute("UPDATE object_revisions SET payload_json=?,payload_digest=?,content_digest=? WHERE kind='decision' AND object_id=?", (json.dumps(payload), digest, digest, decision_id))
            db.execute("UPDATE decisions SET payload_digest=? WHERE decision_ref=?", (digest, decision_id))
        self._assert_doctor_history_mismatch()

    def test_doctor_rejects_snapshot_and_decision_index_digest_mismatch(self):
        receipt = self._resolve()["commit_receipt"]
        for table, key, ref in (("snapshots", "snapshot_ref", receipt["new_snapshot_ref"]), ("decisions", "decision_ref", receipt["resolving_decision_refs"][0])):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.parent / "research-state.sqlite3")) as db, db:
                    original = db.execute(f"SELECT payload_digest FROM {table} WHERE {key}=?", (ref,)).fetchone()[0]
                    db.execute(f"UPDATE {table} SET payload_digest=? WHERE {key}=?", ("sha256:" + "0" * 64, ref))
                try:
                    self._assert_doctor_history_mismatch()
                finally:
                    with closing(sqlite3.connect(self.parent / "research-state.sqlite3")) as db, db:
                        db.execute(f"UPDATE {table} SET payload_digest=? WHERE {key}=?", (original, ref))
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")

    def test_omitted_state_wal_is_a_mixed_generation_not_a_safe_backup(self):
        restored = self.root / "unsupported-db-only-copy"
        restored.mkdir()
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            # Fault injection only: freeze an idle live connection's WAL/main-file
            # split, then omit its WAL from a copy. This is not a backup recipe.
            state_db = facade._application.state_repository._connection
            state_db.execute("PRAGMA journal_mode=WAL")
            state_db.execute("PRAGMA wal_autocheckpoint=0")
            state_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            facade.resolve_human_decision(self.response)
            self.assertGreater((self.parent / "research-state.sqlite3-wal").stat().st_size, 0)
            shutil.copytree(self.parent, restored / ".research-loom")
        for suffix in ("-wal", "-shm"):
            (restored / ".research-loom" / ("research-state.sqlite3" + suffix)).unlink(missing_ok=True)
        diagnosis = LocalWorkspace.doctor(restored)
        self.assertEqual(diagnosis["status"], "ERROR", diagnosis)
        self.assertIn("WORKSPACE-DECISION-STATE-MISMATCH-001", {item["code"] for item in diagnosis["issues"]})

    def test_lineage_switch_without_new_snapshot_keeps_historical_receipt(self):
        import test_human_decision_gate as gate_support
        from core.runtime import TransitionAction, TransitionKind
        from runtime_fixtures import project, rq, seed_state

        state = seed_state(objects=[project(), rq(state="approved")])
        second = replace(state.lineages[0], lineage_id="LIN-2", lineage_kind="exploratory_fork")
        state = replace(state, lineages=(*state.lineages, second))
        helper = gate_support.HumanDecisionGateTests()
        self.addCleanup(helper.doCleanups)
        _store, repo, transitions, service = helper.make_service(state)
        gate = service.gate_candidate(
            gate_support.candidate(state, [TransitionAction(TransitionKind.SWITCH_ACTIVE_LINEAGE, {"target_lineage_ref": "LIN-2"})]),
            state=state, actor=gate_support.ACTOR,
        )
        response = make_response(request=gate.decision_request, disposition="approve_exact", actor_id="HUMAN-1", responded_at=gate_support.CLOCK.now())
        original = service.resolve(response)
        self.assertIsNone(original.commit_receipt.new_snapshot_ref)
        with patch.object(transitions, "apply", side_effect=AssertionError("must not switch Lineage again")):
            reused = service.resolve(response)
        self.assertEqual(reused.commit_receipt, original.commit_receipt)
        self.assertEqual(repo.load_state_view("PRJ-1", "LIN-1").active_lineage_ref, "LIN-2")

    def test_partial_restore_is_not_repaired_by_doctor(self):
        self._resolve()
        # Simulates a interrupted copy into an isolated restore destination,
        # not a supported in-place restore into a live workspace.
        restored = self.root / "incomplete-restore"
        restored.mkdir()
        shutil.copytree(self.parent, restored / ".research-loom")
        missing = restored / ".research-loom" / "decision.db"
        missing.unlink()
        self.assertEqual(LocalWorkspace.doctor(restored)["status"], "ERROR")
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
