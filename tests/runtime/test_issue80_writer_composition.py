from __future__ import annotations

from copy import deepcopy
import json

from plugins.local_application import LocalApplicationError
import issue80_writer_composition_suite as _suite


class Issue80WriterCompositionTests(_suite.Issue80WriterCompositionTests):
    def test_review_round4_support_chain_rq_locator_and_candidate_readiness(self):
        facade, case = self._build_complete_support_package()
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            by_kind = {
                obj["kind"]: obj
                for obj in package["resolved_content"]["research_objects"]
                if obj.get("kind") in {"research_question", "source", "evidence", "finding"}
            }
            proposal = self._proposal(case)
            proposal["sections"] = [deepcopy(proposal["sections"][0])]
            proposal["sections"][0].pop("next_section_id", None)
            proposal["sections"][0]["finding_refs"] = [by_kind["finding"]["id"]]
            proposal["sections"][0]["material_refs"] = []
            proposal["sections"][0]["exhibit_refs"] = []
            proposal["sections"][0]["gap_refs"] = []
            proposal["sections"][0]["citation_requirements"] = [{
                "source_ref": by_kind["source"]["id"],
                "locator_ref": by_kind["evidence"]["locator"],
            }]
            comp = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            facade.select_writer_composition(comp["composition_id"], 1, comp["composition_digest"])
            out = self.root / "support-chain-section"
            facade.export_writer_section_input(comp["composition_id"], "SEC-FRAME", out)
            detached = json.loads((out / "section-writer-input.json").read_text(encoding="utf-8"))
            resolved = {obj["id"]: obj for obj in detached["resolved_research_objects"]}
            self.assertEqual(resolved[case["rq_id"]]["text"], by_kind["research_question"]["text"])
            self.assertTrue({by_kind[k]["id"] for k in ("finding", "evidence", "source")} <= set(resolved))
            self.assertEqual(detached["resolved_materials"][0]["text_rendition"]["content"], case["source_text"])
            self.assertTrue(detached["resolved_materials"][0]["candidate_only"] in {True, False})

            bad = deepcopy(proposal)
            bad["composition_id"] = "COMP-BAD-LOC"
            bad["sections"][0]["citation_requirements"][0]["locator_ref"] = "https://example.test/not-real"
            with self.assertRaises(LocalApplicationError) as error:
                facade.capture_writer_composition(case["package_id"], bad)
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-COMPOSITION-REFERENCE-001")

            citation_only = self._proposal(case)
            citation_only["sections"] = [deepcopy(citation_only["sections"][0])]
            citation_only["sections"][0].pop("next_section_id", None)
            citation_only["sections"][0]["material_refs"] = []
            citation_only["sections"][0]["exhibit_refs"] = []
            citation_only["sections"][0]["gap_refs"] = []
            citation_only["sections"][0]["citation_requirements"] = [{
                "source_ref": by_kind["source"]["id"],
                "locator_ref": by_kind["evidence"]["locator"],
            }]
            citation_comp = facade.capture_writer_composition(case["package_id"], citation_only)["composition"]
            facade.select_writer_composition(
                citation_comp["composition_id"], 1, citation_comp["composition_digest"]
            )
            citation_out = self.root / "citation-only-section"
            facade.export_writer_section_input(
                citation_comp["composition_id"], "SEC-FRAME", citation_out
            )
            citation_detached = json.loads(
                (citation_out / "section-writer-input.json").read_text(encoding="utf-8")
            )
            self.assertIn(by_kind["source"]["id"], citation_detached["resolved_object_ids"])
            self.assertIn(by_kind["evidence"]["id"], citation_detached["resolved_object_ids"])
            self.assertEqual(
                citation_detached["resolved_materials"][0]["text_rendition"]["content"],
                case["source_text"],
            )

            candidate = deepcopy(proposal)
            candidate["composition_id"] = "COMP-CANDIDATE"
            candidate["sections"][0]["narrative_stage_refs"] = ["validation"]
            candidate["sections"][0]["semantic_purpose_refs"] = ["test_and_qualify"]
            candidate["sections"][0]["citation_requirements"] = []
            candidate_comp = facade.capture_writer_composition(
                case["package_id"], candidate
            )["composition"]
            diag = next(
                d
                for d in candidate_comp["validation"]["diagnostics"]
                if d["section_id"] == "SEC-FRAME"
            )
            self.assertIn("argument", diag["unmet_requires"])
        finally:
            facade.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
