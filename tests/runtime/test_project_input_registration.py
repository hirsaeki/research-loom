from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade
from tests.runtime.test_research_question_review import _workspace as make_workspace, _adopt_question


class ProjectInputRegistrationTests(unittest.TestCase):
    def test_register_duplicate_read_and_question_review_linkage(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                question_id = _adopt_question(facade)
                root = workspace
                source = root / "theme.md"
                source.write_text("Theme input\n", encoding="utf-8")
                resume = facade.resume_context()
                snap = resume["research_state"]["snapshot"]
                payload = {"file": str(source), "role": "theme", "expected_snapshot_id": snap["snapshot_id"], "expected_snapshot_digest": snap["content_digest"], "provenance": {"supplied_by": "test"}}
                first = facade.register_project_input(payload)["project_input"]
                second = facade.register_project_input(payload)["project_input"]
                self.assertEqual(first["input_id"], second["input_id"])
                self.assertEqual(first["content_digest"], second["content_digest"])
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)
                self.assertEqual(facade.show_project_input(first["input_id"])["project_input"]["role"], "theme")
                review = facade.submit_action({"action_type":"research_question.review","payload":{"operation":"KEEP","question_ids":[question_id],"rationale":"review supplied theme","review_inputs":{"project_input_ids":[first["input_id"]]}}})
                self.assertFalse(review["data"]["question_review"]["material_change"])
                self.assertEqual(review["data"]["question_review"]["review_inputs"]["project_input_ids"], [first["input_id"]])
                refine = facade.submit_action({"action_type":"research_question.review","payload":{"operation":"REFINE","question_ids":[question_id],"rationale":"narrow from supplied theme","text":"Refined question","review_inputs":{"project_input_ids":[first["input_id"]]}}})
                self.assertEqual(refine["data"]["question_delta"]["operation"], "REFINE")
                self.assertEqual(refine["data"]["state_delta_proposal"]["provenance"]["review_inputs"]["project_input_ids"], [first["input_id"]])
                with self.assertRaises(Exception):
                    facade.submit_action({"action_type":"research_question.review","payload":{"operation":"KEEP","question_ids":[question_id],"rationale":"bad provenance","review_inputs":{"project_input_ids":["PIN-missing"]}}})
            finally:
                facade.close()

    def test_stale_and_outside_workspace_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                root = workspace
                source = root / "expectations.md"; source.write_text("x", encoding="utf-8")
                resume = facade.resume_context(); snap = resume["research_state"]["snapshot"]
                with self.assertRaises(Exception):
                    facade.register_project_input({"file":str(source),"role":"expectations","expected_snapshot_id":"SNP-stale","expected_snapshot_digest":snap["content_digest"]})
                outside = Path(tmp).parent / "outside-project-input.txt"; outside.write_text("x", encoding="utf-8")
                try:
                    with self.assertRaises(Exception):
                        facade.register_project_input({"file":str(outside),"role":"other","expected_snapshot_id":snap["snapshot_id"],"expected_snapshot_digest":snap["content_digest"]})
                finally:
                    outside.unlink(missing_ok=True)
            finally:
                facade.close()
