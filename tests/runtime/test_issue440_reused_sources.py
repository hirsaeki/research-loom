from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from plugins.desktop_research.normalization import source_id_for_capture
from plugins.desktop_research.digest import canonical_extension_digest
from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_service import verify_export_root
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_external_desktop_research_intake as intake


class ReusedSourceTests(ResearchPackageAcceptanceSupport):
    def adopt(self, facade, proposal):
        pending = facade.submit_action({"action_type": "state.apply_candidate", "payload": {
            "state_delta_proposal_id": proposal["proposal_id"]}, "actor_id": "fixture"})
        confirmed = facade.submit_confirmation({
            "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
            "actor_id": "fixture"})
        if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
            request = confirmed["decision_request"]
            facade.resolve_human_decision({"request_id": request["request_id"],
                "request_digest": request["request_digest"], "disposition": "approve_exact",
                "actor_id": "fixture"})

    def test_two_questions_reusing_identical_material_keep_distinct_capture_sources(self):
        facade, case = self._prepare_case()
        self.addCleanup(facade.close)
        self.adopt(facade, case["proposal"])
        second_rq = intake.adopt_rq(facade)
        run_id = facade.submit_action({"action_type": "desktop_research.investigate",
            "payload": {"question_id": second_rq, "purpose": "Fixture second comparison."}})["run_id"]
        facade.start_external_retrieval_attempt(run_id, {"attempt_id": "ATT-1",
            "strategy": "support search", "coverage_dimension_ids": ["COV-SUPPORT"],
            "target_locator": "https://example.test/source-a"})
        capture = facade.capture_external_source(run_id, {"capture_id": "CAP-1",
            "source_category": "other", "exact_locator": "https://example.test/source-a#section-1",
            "acquired_at": "2026-09-07T00:00:00Z", "original_file": "captures/raw/source-a.html",
            "original_media_type": "text/html", "text_rendition_file": "captures/text/source-a.txt"})["capture"]
        facade.complete_external_retrieval_attempt(run_id, {"attempt_id": "ATT-1",
            "outcome": "source_captured", "resulting_capture_id": "CAP-1"})
        facade.start_external_retrieval_attempt(run_id, {"attempt_id": "ATT-2",
            "strategy": "counter search", "coverage_dimension_ids": ["COV-COUNTER"]})
        facade.complete_external_retrieval_attempt(run_id, {"attempt_id": "ATT-2",
            "outcome": "no_relevant_source"})
        handoff, extension = intake.golden_submission(facade._application, run_id, capture)
        # Gap identifiers are local to these otherwise identical fixture submissions.
        handoff = json.loads(json.dumps(handoff).replace("GAP-1", "GAP-2"))
        extension = json.loads(json.dumps(extension).replace("GAP-1", "GAP-2"))
        intake.refresh(handoff, "handoff_digest")
        extension["handoff_binding"]["handoff_digest"] = handoff["handoff_digest"]
        extension["extension_digest"] = canonical_extension_digest(extension)
        second = facade.collect_external(run_id, {"handoff": handoff, "extension": extension})
        proposal = second["execution_result"]["state_delta_proposal"]
        self.assertIsNotNone(proposal, second)
        self.adopt(facade, proposal)
        state = facade._current_state_view()
        before = deepcopy(state.current_snapshot)
        object_ids = [case["rq_id"], second_rq]
        for candidate in (case["proposal"], proposal):
            object_ids.extend(action["payload"]["object"]["id"] for action in candidate["proposed_actions"])
        value = {"snapshot_id": state.current_snapshot["id"], "rq_id": case["rq_id"],
            "object_ids": list(dict.fromkeys(object_ids)), "run_ids": [case["run_id"], run_id],
            "materials": [{"run_id": rid, "capture_id": "CAP-1"} for rid in (case["run_id"], run_id)]}
        built = facade.build_research_package(value)
        package = facade.show_research_package(built["package"]["package_id"])["package"]
        self.assertEqual(set(package["content"]["research_question_refs"]), {case["rq_id"], second_rq})
        for material in package["resolved_content"]["materials"]:
            self.assertEqual(material["source_id"], source_id_for_capture(material["run_id"], "CAP-1"))
        self.assertEqual(facade._current_state_view().current_snapshot, before)
        output = self.root / "combined-detached"
        facade.export_research_package(package["package_id"], output)
        self.assertEqual(verify_export_root(output)["status"], "VERIFIED")
        service = facade._research_package_service()
        objects = {obj["id"]: obj for obj in state.effective_objects()}
        original_id = source_id_for_capture(case["run_id"], "CAP-1")
        original = objects[original_id]
        single = {"snapshot_id": state.current_snapshot["id"], "rq_id": case["rq_id"],
            "run_ids": [case["run_id"]], "materials": [value["materials"][0]]}
        mismatched = {**deepcopy(original), "content_digest": "sha256:" + "0" * 64}
        with patch.object(service, "_objects", return_value={case["rq_id"]: objects[case["rq_id"]], original_id: mismatched}):
            with self.assertRaisesRegex(LocalApplicationError, "does not match verified material"):
                service.build({**single, "object_ids": [original_id]})
        unrelated = [{**deepcopy(original), "id": "SRC-UNRELATED-A"},
                     {**deepcopy(original), "id": "SRC-UNRELATED-B"}]
        with patch.object(service, "_objects", return_value={case["rq_id"]: objects[case["rq_id"]],
                **{obj["id"]: obj for obj in unrelated}}):
            with self.assertRaisesRegex(LocalApplicationError, "ambiguously resolves"):
                service.build({**single, "object_ids": [obj["id"] for obj in unrelated]})


if __name__ == "__main__":
    unittest.main()
