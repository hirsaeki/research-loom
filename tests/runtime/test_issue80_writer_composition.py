from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
import issue80_writer_composition_suite as _suite


class Issue80WriterCompositionTests(_suite.Issue80WriterCompositionTests):

    def test_issue177_lifetime_history_does_not_block_valid_revisions_or_series(self):
        facade, case = self._build()
        try:
            current = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-LONG-HISTORY"))["composition"]
            first_digest = current["composition_digest"]
            for revision in range(2, 66):
                proposal = self._proposal(case, composition_id=current["composition_id"], base=current)
                proposal["sections"][0]["purpose"] = f"Sequential revision {revision}."
                current = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            self.assertEqual(current["version"], 65)
            self.assertEqual(facade.show_writer_composition(current["composition_id"], 1)["composition"]["composition_digest"], first_digest)

            for index in range(65):
                facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id=f"COMP-SERIES-{index:03d}"))
            listed = facade.list_writer_compositions()
            self.assertEqual(len(listed["compositions"]), 64)
            self.assertTrue(listed["truncated"])
            self.assertEqual(facade.show_writer_composition("COMP-SERIES-064", 1)["composition"]["version"], 1)
        finally:
            facade.close()

    def test_issue177_exact_selection_retry_is_idempotent_but_real_changes_are_historical(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-SELECTION-HISTORY"))["composition"]
            proposal2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            proposal2["sections"][0]["purpose"] = "Second selectable version."
            v2 = facade.capture_writer_composition(case["package_id"], proposal2)["composition"]

            first = facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            retry = facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            self.assertTrue(first["selection_changed"])
            self.assertFalse(retry["selection_changed"])
            self.assertEqual(retry["selection"], first["selection"])

            facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            duplicate_v2 = facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            self.assertFalse(duplicate_v2["selection_changed"])
            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            shown = facade.show_writer_composition(v1["composition_id"], 1)["selection"]
            self.assertEqual([(event["version"], event["digest"]) for event in shown["history"]], [
                (1, v1["composition_digest"]), (2, v2["composition_digest"]), (1, v1["composition_digest"]),
            ])
            self.assertEqual(shown["history_count"], 3)
            self.assertFalse(shown["history_truncated"])
        finally:
            facade.close()

    def test_issue177_selection_history_read_is_bounded_without_blocking_changes(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-BOUNDED-SELECTION-READ"))["composition"]
            proposal2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            proposal2["sections"][0]["purpose"] = "Alternate selection target."
            v2 = facade.capture_writer_composition(case["package_id"], proposal2)["composition"]
            for index in range(257):
                selected = v1 if index % 2 == 0 else v2
                facade.select_writer_composition(v1["composition_id"], selected["version"], selected["composition_digest"])
            selection = facade.show_writer_composition(v1["composition_id"], 1)["selection"]
            self.assertEqual(selection["history_count"], 257)
            self.assertEqual(len(selection["history"]), 256)
            self.assertTrue(selection["history_truncated"])
        finally:
            facade.close()

    def test_issue177_ablation_legacy_revision_ceiling_would_reject_a_valid_65th_revision(self):
        facade, case = self._build()
        try:
            current = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-LEGACY-BOUND-ABLATION"))["composition"]
            for revision in range(2, 65):
                proposal = self._proposal(case, composition_id=current["composition_id"], base=current)
                proposal["sections"][0]["purpose"] = f"Revision {revision}."
                current = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            service = facade._writer_composition_service()
            original_base_guard = service._validated_update_base
            def legacy_bounded_base(composition_id, latest, base_version, base_digest):
                if latest >= 64:
                    raise LocalApplicationError("APPLICATION-WRITER-COMPOSITION-BOUND-001", "composition version bound exceeded")
                return original_base_guard(composition_id, latest, base_version, base_digest)
            proposal65 = self._proposal(case, composition_id=current["composition_id"], base=current)
            proposal65["sections"][0]["purpose"] = "Otherwise valid revision 65."
            with patch.object(service, "_validated_update_base", side_effect=legacy_bounded_base):
                with self.assertRaises(LocalApplicationError) as blocked:
                    facade.capture_writer_composition(case["package_id"], proposal65)
            self.assertEqual(blocked.exception.code, "APPLICATION-WRITER-COMPOSITION-BOUND-001")
            accepted = facade.capture_writer_composition(case["package_id"], proposal65)["composition"]
            self.assertEqual(accepted["version"], 65)
        finally:
            facade.close()

    def test_issue177_ablation_base_guard_is_required_for_stale_write_rejection(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-BASE-GUARD-ABLATION"))["composition"]
            p2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            p2["sections"][0]["purpose"] = "Current second revision."
            v2 = facade.capture_writer_composition(case["package_id"], p2)["composition"]
            stale = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            stale["sections"][0]["purpose"] = "Stale competing revision."
            with self.assertRaises(LocalApplicationError) as rejected:
                facade.capture_writer_composition(case["package_id"], stale)
            self.assertEqual(rejected.exception.code, "APPLICATION-WRITER-COMPOSITION-STALE-001")

            service = facade._writer_composition_service()
            with patch.object(service, "_validated_update_base", return_value=v2):
                invalid = facade.capture_writer_composition(case["package_id"], stale)["composition"]
            self.assertEqual(invalid["version"], 3)
            self.assertEqual(invalid["base_version"], 1)
            self.assertEqual(invalid["base_digest"], v1["composition_digest"])
        finally:
            facade.close()

    def test_issue177_legacy_selection_history_migrates_without_rewriting_events(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-LEGACY-SELECTION"))["composition"]
            proposal2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            proposal2["sections"][0]["purpose"] = "Legacy selectable revision."
            v2 = facade.capture_writer_composition(case["package_id"], proposal2)["composition"]
            service = facade._writer_composition_service()
            legacy_events = [
                {"version": 1, "digest": v1["composition_digest"], "selected_at": "2026-09-16T00:00:00Z"},
                {"version": 2, "digest": v2["composition_digest"], "selected_at": "2026-09-16T00:01:00Z"},
            ]
            service._selection_state_path(v1["composition_id"]).write_text(
                json.dumps({"selected": legacy_events[-1], "history": legacy_events}), encoding="utf-8"
            )

            retry = facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            self.assertFalse(retry["selection_changed"])
            shown = facade.show_writer_composition(v1["composition_id"], 2)["selection"]
            self.assertEqual(shown["history"], legacy_events)
            self.assertEqual(shown["history_count"], 2)
            compact = json.loads(service._selection_state_path(v1["composition_id"]).read_text(encoding="utf-8"))
            self.assertNotIn("history", compact)
            self.assertEqual(compact["history_count"], 2)
            self.assertTrue(service._selection_event_path(v1["composition_id"], 1).is_file())
            self.assertTrue(service._selection_event_path(v1["composition_id"], 2).is_file())
        finally:
            facade.close()

    def test_issue177_selection_pointer_write_failure_recovers_without_duplicate_event(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-SELECTION-RECOVERY"))["composition"]
            proposal2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            proposal2["sections"][0]["purpose"] = "Recovery target revision."
            v2 = facade.capture_writer_composition(case["package_id"], proposal2)["composition"]
            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            service = facade._writer_composition_service()
            original_write_state = service._write_selection_state
            with patch.object(service, "_write_selection_state", side_effect=LocalApplicationError("APPLICATION-WRITER-COMPOSITION-WRITE-001", "fixture")):
                with self.assertRaises(LocalApplicationError):
                    facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            self.assertTrue(service._selection_event_path(v1["composition_id"], 2).is_file())
            self.assertFalse(service._selection_event_path(v1["composition_id"], 3).exists())

            with patch.object(service, "_write_selection_state", wraps=original_write_state):
                retry = facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            self.assertFalse(retry["selection_changed"])
            selection = facade.show_writer_composition(v1["composition_id"], 2)["selection"]
            self.assertEqual(selection["history_count"], 2)
            self.assertEqual([event["version"] for event in selection["history"]], [1, 2])
            self.assertFalse(service._selection_event_path(v1["composition_id"], 3).exists())
        finally:
            facade.close()

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

            with (
                patch.object(service, "_series_exists", side_effect=[False, True, True]),
                patch.object(service, "_series_lock", wraps=service._series_lock) as series_lock,
            ):
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
            existing = self.root / "existing"; existing.mkdir(); (existing/"keep").write_text("keep")
            with self.assertRaises(LocalApplicationError): facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", existing)
            self.assertEqual((existing/"keep").read_text(), "keep")
            failed = self.root / "failed"
            with patch("plugins.local_application.writer_composition_service.os.replace", side_effect=OSError("fixture")):
                with self.assertRaises(LocalApplicationError): facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", failed)
            self.assertFalse(failed.exists())
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
