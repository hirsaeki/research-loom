from copy import deepcopy
import json
import unittest

from plugins.local_application.research_package_builder import _research_inventories


def _case_type(module_name, class_name):
    import importlib
    return getattr(importlib.import_module(f"tests.runtime.{module_name}"), class_name)
def _fixture(case_type):
    case = case_type(methodName="runTest")
    case.setUp()
    return case


class Issue438CitationVisualInventoryTests(unittest.TestCase):
    def test_citation_inventory_exposes_locator_bibliography_role_and_gaps(self):
        fixture = _fixture(_case_type("test_issue80_writer_composition", "Issue80WriterCompositionTests"))
        try:
            facade, case = fixture._build_complete_support_package()
            package = facade.show_research_package(case["package_id"])["package"]
            evidence = next(o for o in package["resolved_content"]["research_objects"] if o.get("kind") == "evidence")
            row = next(x for x in package["inventories"]["citation_inventory"] if x["evidence_id"] == evidence["id"])
            self.assertEqual(row["source_id"], evidence["source_id"])
            self.assertEqual(row["locator"], evidence["locator"])
            self.assertEqual(row["evidence_role"], evidence["evidence_kind"])
            self.assertEqual(row["citation_ready"], not row["unresolved_reasons"])

            objects = deepcopy(package["resolved_content"]["research_objects"])
            source = next(o for o in objects if o.get("kind") == "source")
            source.update({
                "title": "Retained official source",
                "publisher_or_author": "Example institution",
                "publication_or_update_date": "2026",
            })
            next(o for o in objects if o.get("kind") == "evidence")["verification_status"] = "verified"
            projected = _research_inventories(objects, [], package["resolved_content"]["materials"])
            ready = next(x for x in projected["citation_inventory"] if x["evidence_id"] == evidence["id"])
            self.assertTrue(ready["bibliography_ready"])
            self.assertTrue(ready["citation_ready"])
        finally:
            fixture.doCleanups()

    def test_composition_binding_derives_existing_writer_citation_scope(self):
        fixture = _fixture(_case_type("test_issue134_writer_composition", "Issue134WriterCompositionRecoveryTests"))
        facade, case = fixture._prepare_case()
        try:
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": case["proposal"]["proposal_id"]},
                "actor_id": "HUMAN-I438",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-I438",
            })
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-I438",
            })
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            finding = next(obj for obj in state.effective_objects() if obj.get("kind") == "finding")
            evidence = next(obj for obj in state.effective_objects() if obj.get("kind") == "evidence")
            source = next(obj for obj in state.effective_objects() if obj.get("kind") == "source")
            proposed = facade.submit_action({
                "action_type": "research.argument.propose",
                "payload": {
                    "conclusion": "The adopted Finding supports the bounded validation conclusion.",
                    "warrant": "The Finding and Evidence resolve in the exact current Research Snapshot.",
                    "question_ids": [case["rq_id"]],
                    "finding_ids": [finding["id"]],
                    "evidence_ids": [evidence["id"]],
                    "qualifier": "Within the captured source scope.",
                },
                "actor_id": "HUMAN-I438",
            })
            arg_pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                "actor_id": "HUMAN-I438",
            })
            facade.submit_confirmation({
                "confirmation_request_id": arg_pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-I438",
            })
            argument_id = proposed["data"]["argument_candidate"]["id"]
            current = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            built = facade.build_research_package({
                **case["build_input"],
                "snapshot_id": current.current_snapshot["id"],
                "snapshot_digest": current.current_snapshot["content_digest"],
                "lineage_ref": current.active_lineage_ref,
                "object_ids": [source["id"], evidence["id"], finding["id"], argument_id],
            })["package"]
            proposal = fixture._proposal(case, argument_id, finding["id"], evidence["id"])
            target = proposal["sections"][1]
            target["source_refs"] = [source["id"]]
            target["citation_requirements"] = []
            target["citation_bindings"] = [{
                "argument_id": argument_id, "evidence_id": evidence["id"],
                "citation_role": "primary_support", "status": "selected",
            }]
            composition = facade.capture_writer_composition(built["package_id"], proposal)["composition"]
            section = next(x for x in composition["sections"] if x["section_id"] == "SEC-G1-05")
            self.assertEqual(section["citation_requirements"], [{"source_ref": source["id"], "locator_ref": evidence["locator"]}])
            facade.select_writer_composition(composition["composition_id"], 1, composition["composition_digest"])
            output = fixture.root / "issue438-citation-section"
            facade.export_writer_section_input(composition["composition_id"], section["section_id"], output)
            detached = json.loads((output / "section-writer-input.json").read_text(encoding="utf-8"))
            self.assertEqual(detached["section_contract"]["citation_bindings"], section["citation_bindings"])

            round_root = fixture.root / "issue438-citation-round-trip"
            facade.export_writer_round_trip_input(composition["composition_id"], [section["section_id"]], round_root)
            writer_input = json.loads((round_root / "writer-input.json").read_text(encoding="utf-8"))
            writer_type = _case_type("test_issue219_writer_round_trip", "Issue219WriterRoundTripTests")
            response = writer_type._response(
                writer_input, response_id="WR-I438", feedback=[], sections=[{
                    "section_id": section["section_id"],
                    "content": "Bounded validation claim with the selected citation.",
                    "citations": [{"source_ref": source["id"], "locator_ref": evidence["locator"]}],
                    "exhibit_refs": [],
                }],
            )
            facade.import_writer_response(response)
            preview = facade.build_publication_preview(composition["composition_id"])["build"]
            self.assertEqual(preview["verification"]["citation_resolution"], "failed")
        finally:
            facade.close()
            fixture.doCleanups()

    def test_source_exhibit_inventory_and_use_mode_remain_separate_from_citations(self):
        fixture = _fixture(_case_type("test_issue218_visual_evidence", "Issue218VisualEvidenceTests"))
        try:
            facade, case = fixture._visual_case()
            package = facade.show_research_package(case["package_id"])["package"]
            self.assertEqual(package["inventories"]["citation_inventory"], [])
            row = package["inventories"]["source_exhibit_inventory"][0]
            exhibit = package["resolved_content"]["working_material"]["research_exhibits"][0]
            self.assertEqual(row["exhibit_id"], exhibit["exhibit_id"])
            self.assertEqual(row["retained_digest"], exhibit["visual_target"]["source_digest"])
            self.assertEqual(row["rights_status"], "unresolved")
            self.assertTrue(row["research_ready"])
            self.assertIn("rights_unresolved", row["unresolved_reasons"])

            proposal = {
                "purpose": "Select the retained source visual without changing Research authority.",
                "audience": ["reviewer"],
                "sections": [{
                    "section_id": "SEC-VIS", "order": 1, "heading": "Source visual",
                    "reader_question": "Which retained source visual is used?", "purpose": "Bind its use mode.",
                    "narrative_stage_refs": ["framing"], "semantic_purpose_refs": ["frame_problem"],
                    "exhibit_refs": [exhibit["exhibit_id"]],
                    "exhibit_bindings": [{"exhibit_id": exhibit["exhibit_id"], "use_mode": "adapt", "status": "selected"}],
                }],
                "created_by": {"type": "human_or_external_llm", "instruction": "Use supplied package only."},
            }
            composition = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            self.assertEqual(composition["sections"][0]["exhibit_bindings"][0]["use_mode"], "adapt")
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
