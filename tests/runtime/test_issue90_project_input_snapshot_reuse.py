from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from tests.runtime.test_research_question_review import _adopt_question, _workspace


class Issue90ProjectInputSnapshotReuseTests(unittest.TestCase):
    def _register(self, facade: LocalApplicationFacade, workspace: Path):
        source = workspace / "theme.md"
        content = b"Theme input\n"
        source.write_bytes(content)
        snap = facade.resume_context()["research_state"]["snapshot"]
        item = facade.register_project_input({
            "file": str(source),
            "role": "theme",
            "expected_snapshot_id": snap["snapshot_id"],
            "expected_snapshot_digest": snap["content_digest"],
            "provenance": {"supplied_by": "issue-90-test"},
        })["project_input"]
        return item, content, snap

    @staticmethod
    def _review(facade, qid: str, input_id: str, *, operation="KEEP", text=None):
        payload = {
            "operation": operation,
            "question_ids": [qid],
            "rationale": "Issue 90 acceptance",
            "review_inputs": {"project_input_ids": [input_id]},
        }
        if text is not None:
            payload["text"] = text
        return facade.submit_action({"action_type": "research_question.review", "payload": payload, "actor_id": "H"})

    def test_b1_b2_b3_reuse_keeps_registration_provenance_and_refine_requires_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _workspace(Path(temp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                q1 = _adopt_question(facade, "Q1")
                item, content, s0 = self._register(facade, workspace)
                self.assertEqual(item["content_digest"], "sha256:" + hashlib.sha256(content).hexdigest())
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)
                keep0 = self._review(facade, q1, item["input_id"])
                self.assertEqual(keep0["status"], "SUCCEEDED")
                self.assertFalse(keep0["data"]["question_review"]["material_change"])
                self.assertEqual(keep0["data"]["question_review"]["bound_snapshot"]["snapshot_id"], s0["snapshot_id"])
                self.assertEqual(facade.resume_context()["research_state"]["snapshot"], s0)
                _adopt_question(facade, "Q2")
                s1 = facade.resume_context()["research_state"]["snapshot"]
                self.assertNotEqual(s1["snapshot_id"], s0["snapshot_id"])
            finally:
                facade.close()

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                with patch(
                    "plugins.local_project_input_store.LocalProjectInputStore._read_verified_blob",
                    side_effect=AssertionError("Review must not materialize verified blob content"),
                ):
                    keep1 = self._review(facade, q1, item["input_id"])
                self.assertEqual(keep1["status"], "SUCCEEDED")
                self.assertFalse(keep1["data"]["question_review"]["material_change"])
                self.assertEqual(keep1["data"]["question_review"]["bound_snapshot"]["snapshot_id"], s1["snapshot_id"])
                stored = facade.show_project_input(item["input_id"])["project_input"]
                self.assertEqual(stored["input_id"], item["input_id"])
                self.assertEqual(stored["snapshot_id"], s0["snapshot_id"])
                self.assertEqual(stored["snapshot_digest"], s0["content_digest"])
                self.assertEqual(stored["content_digest"], item["content_digest"])
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)
                self.assertEqual(facade.resume_context()["research_state"]["snapshot"], s1)

                refine = self._review(facade, q1, item["input_id"], operation="REFINE", text="Q1 refined")
                proposal = refine["data"]["state_delta_proposal"]
                self.assertEqual(proposal["current_snapshot_ref"], s1["snapshot_id"])
                self.assertEqual(proposal["current_snapshot_digest"], s1["content_digest"])
                self.assertEqual(proposal["provenance"]["review_inputs"]["project_input_ids"], [item["input_id"]])
                self.assertEqual(facade.resume_context()["research_state"]["snapshot"], s1)

                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": refine["data"]["state_delta_proposal_id"]},
                    "actor_id": "H",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "H",
                })
                self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
                self.assertIn("research_revision", {u["required_decision_kind"] for u in confirmed["decision_request"]["decision_units"]})
                resolved = facade.resolve_human_decision({
                    "request_id": confirmed["decision_request"]["request_id"],
                    "request_digest": confirmed["decision_request"]["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "H",
                })
                self.assertEqual(resolved["status"], "RESOLVED")
                s2 = facade.resume_context()["research_state"]["snapshot"]
                self.assertNotEqual(s2["snapshot_id"], s1["snapshot_id"])
                self.assertEqual(facade.show_project_input(item["input_id"])["project_input"], stored)
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)

    def test_b4_reused_input_does_not_rebase_stale_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                q1 = _adopt_question(facade, "Q1")
                item, _, _ = self._register(facade, workspace)
                refine = self._review(facade, q1, item["input_id"], operation="REFINE", text="Q1 refined")
                _adopt_question(facade, "Advance head")
                head = facade.resume_context()["research_state"]["snapshot"]
                apply = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": refine["data"]["state_delta_proposal_id"]},
                    "actor_id": "H",
                })
                confirmed = facade.submit_confirmation({
                    "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "H",
                })
                self.assertEqual(confirmed["status"], "FAILED")
                self.assertEqual(facade.resume_context()["research_state"]["snapshot"], head)
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)

    def test_b5_review_path_rejects_unknown_foreign_and_tampered_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                q1 = _adopt_question(facade, "Q1")
                item, _, snap = self._register(facade, workspace)
                input_id = item["input_id"]
                with self.assertRaises(LocalApplicationError) as unknown:
                    self._review(facade, q1, "PIN-missing")
                self.assertEqual(unknown.exception.code, "APPLICATION-PROJECT-INPUT-404")

                registry = facade._registry()
                registry.db.execute("UPDATE project_inputs SET project_id=? WHERE input_id=?", ("PRJ-foreign", input_id))
                registry.db.commit()
                with self.assertRaises(LocalApplicationError) as project:
                    self._review(facade, q1, input_id)
                self.assertEqual(project.exception.code, "APPLICATION-PROJECT-INPUT-404")
                registry.db.execute("UPDATE project_inputs SET project_id=? WHERE input_id=?", (facade.project_id, input_id))
                registry.db.execute("UPDATE project_inputs SET lineage_ref=? WHERE input_id=?", ("LIN-foreign", input_id))
                registry.db.commit()
                with self.assertRaises(LocalApplicationError) as lineage:
                    self._review(facade, q1, input_id)
                self.assertEqual(lineage.exception.code, "APPLICATION-PROJECT-INPUT-STALE-001")
                registry.db.execute("UPDATE project_inputs SET lineage_ref=? WHERE input_id=?", (facade._current_binding()[0], input_id))
                registry.db.execute("UPDATE project_inputs SET content_digest=? WHERE input_id=?", ("bad", input_id))
                registry.db.commit()
                with self.assertRaises(LocalApplicationError) as malformed_digest:
                    self._review(facade, q1, input_id)
                self.assertEqual(malformed_digest.exception.code, "APPLICATION-PROJECT-INPUT-INTEGRITY-001")
                registry.db.execute("UPDATE project_inputs SET content_digest=? WHERE input_id=?", (item["content_digest"], input_id))
                registry.db.commit()

                digest_hex = item["content_digest"].split(":", 1)[1]
                blob = workspace / ".research-loom" / "project-inputs" / "blobs" / digest_hex[:2] / digest_hex
                original = blob.read_bytes()
                blob.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                with self.assertRaises(LocalApplicationError) as corrupt:
                    self._review(facade, q1, input_id)
                self.assertEqual(corrupt.exception.code, "APPLICATION-PROJECT-INPUT-INTEGRITY-001")
                blob.write_bytes(original)
                blob.unlink()
                with self.assertRaises(LocalApplicationError) as missing:
                    self._review(facade, q1, input_id)
                self.assertEqual(missing.exception.code, "APPLICATION-PROJECT-INPUT-INTEGRITY-001")
                self.assertEqual(facade.resume_context()["research_state"]["snapshot"], snap)
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)


if __name__ == "__main__":
    unittest.main()
