from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
import issue80_writer_composition_suite as _suite


class Issue80WriterCompositionTests(_suite.Issue80WriterCompositionTests):
    def test_review_fixes_series_lock_and_list_package_cache(self):
        facade, case = self._build()
        try:
            service = facade._writer_composition_service()
            facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-LOCK"))
            with service._series_lock("COMP-LOCK"):
                with self.assertRaises(LocalApplicationError) as error:
                    with service._series_lock("COMP-LOCK"):
                        pass
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-COMPOSITION-BUSY-001")

            with patch.object(service, "_series_lock", wraps=service._series_lock) as series_lock:
                with service._capture_lock("COMP-LOCK"):
                    pass
            self.assertEqual(series_lock.call_count, 1)

            lock_files_before = sorted(path.name for path in service.root.glob(".*.lock"))
            for index in range(8):
                with self.assertRaises(LocalApplicationError) as missing:
                    facade.select_writer_composition(f"COMP-MISSING-{index}", 1, "sha256:" + "0" * 64)
                self.assertEqual(missing.exception.code, "APPLICATION-WRITER-COMPOSITION-404")
            self.assertEqual(sorted(path.name for path in service.root.glob(".*.lock")), lock_files_before)

            facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-A"))
            facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-B"))
            with patch.object(service, "_package", wraps=service._package) as package_load:
                listed = service.list()
            self.assertEqual(len(listed["compositions"]), 3)
            self.assertEqual(package_load.call_count, 1)
        finally:
            facade.close()

    def test_co6_output_safety_and_write_failure_are_atomic(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            existing = self.root / "existing"
            existing.mkdir()
            (existing / "keep").write_text("keep")
            with self.assertRaises(LocalApplicationError):
                facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", existing)
            self.assertEqual((existing / "keep").read_text(), "keep")

            failed = self.root / "failed"
            with patch("plugins.local_application.writer_composition_service.os.replace", side_effect=OSError("fixture")):
                with self.assertRaises(LocalApplicationError):
                    facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", failed)
            self.assertFalse(failed.exists())

            retried = facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            self.assertTrue(retried["selection_reused"])
            self.assertEqual(facade.show_writer_composition(v1["composition_id"], 1)["selection"]["history_total"], 1)

            with patch("plugins.local_application.writer_composition_service.MAX_SECTION_INPUT_BYTES", 1):
                with self.assertRaises(LocalApplicationError) as output_bound:
                    facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", self.root / "too-large")
                self.assertEqual(output_bound.exception.code, "APPLICATION-WRITER-COMPOSITION-BOUND-001")
                self.assertFalse((self.root / "too-large").exists())
        finally:
            facade.close()

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
