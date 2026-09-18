from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
from plugins.local_application.writer_round_trip_service import WriterRoundTripService
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import issue80_writer_composition_suite as writer_comp_support


class Issue219WriterRoundTripTests(ResearchPackageAcceptanceSupport):
    def _build_round_trip(self):
        facade, case = writer_comp_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        proposal = writer_comp_support.Issue80WriterCompositionTests._proposal(self, case)
        proposal["sections"][1]["narrative_stage_refs"] = ["framing"]
        proposal["sections"][1]["semantic_purpose_refs"] = ["frame_problem"]
        composition = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
        facade.select_writer_composition(
            composition["composition_id"], 1, composition["composition_digest"]
        )
        output = self.root / "writer-round-trip-input"
        exported = facade.export_writer_round_trip_input(
            composition["composition_id"], ["SEC-FRAME", "SEC-VALIDATE"], output
        )
        input_doc = json.loads((output / "writer-input.json").read_text(encoding="utf-8"))
        return facade, case, composition, exported, input_doc

    @staticmethod
    def _response(input_doc, *, response_id="WR-1", base=None, sections=None, feedback=None):
        if sections is None:
            sections = [
                {
                    "section_id": "SEC-FRAME",
                    "content": "Framing draft grounded in the supplied package.",
                    "citations": [],
                    "exhibit_refs": list(input_doc["sections"][0]["exhibit_refs"]),
                },
                {
                    "section_id": "SEC-VALIDATE",
                    "content": "Validation remains bounded by the supplied unresolved material.",
                    "citations": [],
                    "exhibit_refs": [],
                },
            ]
        if feedback is None:
            feedback = [
                {
                    "issue_id": "WFI-MISSING",
                    "target_type": "section",
                    "target_id": "SEC-VALIDATE",
                    "issue_category": "MISSING_EVIDENCE",
                    "description": "Additional evidence is needed before a stronger validation claim.",
                    "severity": "major",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Collect additional evidence for the validation section.",
                },
                {
                    "issue_id": "WFI-SCOPE",
                    "target_type": "section",
                    "target_id": "SEC-FRAME",
                    "issue_category": "AMBIGUOUS_SCOPE",
                    "description": "The intended scope qualifier should be made explicit.",
                    "severity": "minor",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Clarify the scope qualifier before the next Writer pass.",
                },
                {
                    "issue_id": "WFI-LIMIT",
                    "target_type": "section",
                    "target_id": "SEC-VALIDATE",
                    "issue_category": "LIMITATION_CONFLICT",
                    "description": "The limitation and the draft conclusion remain unresolved.",
                    "severity": "major",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Review the limitation and decide whether research follow-up is required.",
                },
            ]
        return {
            "schema_version": "0.1.0",
            "object_type": "writer_response",
            "response_id": response_id,
            "input_ref": {
                "input_id": input_doc["input_id"],
                "input_digest": input_doc["input_digest"],
            },
            "base_revision_ref": base,
            "writer": {"writer_id": "external-writer", "writer_version": "1"},
            "sections": sections,
            "feedback": feedback,
            "provenance": {"generated_at": "2026-09-18T08:30:00Z", "channel": "external"},
        }

    def test_round_trip_import_reuse_revision_and_joined_inspection(self):
        facade, case, composition, exported, input_doc = self._build_round_trip()
        try:
            before = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot["content_digest"]
            response = self._response(input_doc)
            with patch.object(
                facade._application.state_transition_service,
                "apply",
                side_effect=AssertionError("Writer import must not mutate Research State"),
            ):
                first = facade.import_writer_response(response)
                retry = facade.import_writer_response(deepcopy(response))
            self.assertEqual(first["status"], "IMPORTED")
            self.assertEqual(retry["status"], "VERIFIED_REUSE")
            self.assertEqual(first["revision_id"], retry["revision_id"])
            self.assertFalse(first["research_state_mutation_performed"])

            service = facade._writer_round_trip_service()
            service._head_path(composition["composition_id"]).unlink()
            recovered = facade.import_writer_response(deepcopy(response))
            self.assertEqual(recovered["status"], "VERIFIED_REUSE")
            recovered_head = service._head(composition["composition_id"])
            self.assertEqual(recovered_head["revision_id"], first["revision_id"])
            self.assertEqual(recovered_head["revision_digest"], first["revision_digest"])

            shown = facade.inspect_writer_round_trip(composition["composition_id"])
            self.assertEqual(shown["source_package"]["package_id"], case["package_id"])
            self.assertEqual(
                shown["writer_input"]["source"]["effective_profile_set_digest"],
                input_doc["source"]["effective_profile_set_digest"],
            )
            self.assertEqual(
                shown["writer_input"]["sections"][0]["section_input"]["section_input_digest"],
                input_doc["sections"][0]["section_input"]["section_input_digest"],
            )
            self.assertTrue(
                shown["writer_input"]["sections"][0]["section_input"]["resolved_profile_constraints"]
            )
            self.assertTrue(shown["effective_constraints"])
            self.assertEqual(len(shown["revision"]["sections"]), 2)
            self.assertEqual(len(shown["revision"]["writing_feedback"]["issues"]), 3)
            self.assertFalse(shown["revision"]["writing_feedback"]["is_research_evidence"])
            self.assertEqual(len(shown["revision"]["candidate_follow_ups"]), 3)

            after = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot["content_digest"]
            self.assertEqual(after, before)

            revision_path = facade._writer_round_trip_service()._revision_path(
                composition["composition_id"], first["revision_id"]
            )
            original_bytes = revision_path.read_bytes()
            base = {"revision_id": first["revision_id"], "revision_digest": first["revision_digest"]}
            changed = self._response(
                input_doc,
                response_id="WR-2",
                base=base,
                sections=[{
                    "section_id": "SEC-FRAME",
                    "content": "Revised framing only; validation is intentionally reused.",
                    "citations": [],
                    "exhibit_refs": list(input_doc["sections"][0]["exhibit_refs"]),
                }],
                feedback=[],
            )
            second = facade.import_writer_response(changed)
            self.assertEqual(second["status"], "IMPORTED")
            self.assertEqual(second["revision_number"], 2)
            self.assertEqual(second["reused_section_ids"], ["SEC-VALIDATE"])
            self.assertEqual(revision_path.read_bytes(), original_bytes)

            service._head_path(composition["composition_id"]).unlink()
            old_replay = facade.import_writer_response(deepcopy(response))
            self.assertEqual(old_replay["status"], "VERIFIED_REUSE")
            latest_head = service._head(composition["composition_id"])
            self.assertEqual(latest_head["revision_id"], second["revision_id"])
            self.assertEqual(latest_head["revision_digest"], second["revision_digest"])

            joined = facade.inspect_writer_round_trip(
                composition["composition_id"], second["revision_id"]
            )
            sections = {row["section_id"]: row for row in joined["revision"]["sections"]}
            first_shown = facade.inspect_writer_round_trip(
                composition["composition_id"], first["revision_id"]
            )
            first_sections = {row["section_id"]: row for row in first_shown["revision"]["sections"]}
            self.assertEqual(
                sections["SEC-VALIDATE"]["content_digest"],
                first_sections["SEC-VALIDATE"]["content_digest"],
            )
            self.assertEqual(
                sections["SEC-VALIDATE"]["origin_revision_id"], first["revision_id"]
            )
            self.assertEqual(sections["SEC-FRAME"]["origin_revision_id"], second["revision_id"])
            self.assertEqual(
                [row["revision_id"] for row in joined["revision_lineage"]],
                [second["revision_id"], first["revision_id"]],
            )
        finally:
            facade.close()

    def test_exact_context_pins_are_required(self):
        facade, _case, composition, _exported, input_doc = self._build_round_trip()
        try:
            service = facade._writer_round_trip_service()
            receipt_path = service._input_path(input_doc["input_id"])
            tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
            tampered["source"]["research_package_digest"] = "sha256:" + "0" * 64
            from plugins.local_application.writer_composition_service import _digest_document
            tampered["input_digest"] = _digest_document(tampered, "input_digest")
            receipt_path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            response = self._response(tampered)
            with self.assertRaises(LocalApplicationError) as error:
                facade.import_writer_response(response)
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-ROUND-TRIP-PIN-001")

            # Ablation: without the exact context guard, the same response attaches to a tampered receipt.
            with patch.object(WriterRoundTripService, "_validate_input_context", return_value=(
                facade._writer_composition_service()._load_version(composition["composition_id"], 1),
                facade.show_research_package(input_doc["source"]["research_package_id"])["package"],
            )):
                imported = facade.import_writer_response(response)
            self.assertEqual(imported["status"], "IMPORTED")
        finally:
            facade.close()

    def test_managed_receipt_summary_must_match_embedded_section_input(self):
        facade, _case, _composition, _exported, input_doc = self._build_round_trip()
        try:
            service = facade._writer_round_trip_service()
            receipt_path = service._input_path(input_doc["input_id"])
            tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
            tampered["sections"][0]["citation_scope"] = []
            from plugins.local_application.writer_composition_service import _digest_document
            tampered["input_digest"] = _digest_document(tampered, "input_digest")
            receipt_path.write_text(
                json.dumps(tampered, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(LocalApplicationError) as error:
                facade.import_writer_response(self._response(tampered))
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-ROUND-TRIP-PIN-001")
        finally:
            facade.close()

    def test_managed_receipt_cannot_drop_canonical_objects_or_materials(self):
        facade, _case, _composition, _exported, input_doc = self._build_round_trip()
        try:
            service = facade._writer_round_trip_service()
            receipt_path = service._input_path(input_doc["input_id"])
            tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
            embedded = tampered["sections"][0]["section_input"]
            embedded["resolved_object_ids"] = []
            embedded["resolved_research_objects"] = []
            embedded["resolved_material_refs"] = []
            embedded["resolved_materials"] = []
            from plugins.local_application.writer_composition_service import _digest_document
            embedded["section_input_digest"] = _digest_document(
                embedded, "section_input_digest"
            )
            tampered["sections"][0]["section_input_digest"] = embedded[
                "section_input_digest"
            ]
            tampered["input_digest"] = _digest_document(tampered, "input_digest")
            receipt_path.write_text(
                json.dumps(tampered, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(LocalApplicationError) as error:
                facade.import_writer_response(self._response(tampered))
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-ROUND-TRIP-PIN-001")
        finally:
            facade.close()

    def test_export_destination_lock_prevents_parallel_overwrite_and_recovers(self):
        facade, _case, composition, _exported, _input_doc = self._build_round_trip()
        try:
            output = self.root / "writer-round-trip-contended"
            service = facade._writer_round_trip_service()
            composer = facade._writer_composition_service()
            lock_path = service._export_lock_path(output)
            with composer._file_lock(lock_path, "fixture lock"):
                with self.assertRaises(LocalApplicationError) as error:
                    facade.export_writer_round_trip_input(
                        composition["composition_id"], ["SEC-FRAME"], output
                    )
                self.assertEqual(
                    error.exception.code, "APPLICATION-WRITER-ROUND-TRIP-EXPORT-001"
                )
                self.assertFalse(output.exists())

            # The lock file remains as a harmless marker; only the OS lock owns exclusion.
            self.assertTrue(lock_path.exists())
            exported = facade.export_writer_round_trip_input(
                composition["composition_id"], ["SEC-FRAME"], output
            )
            self.assertEqual(exported["status"], "EXPORTED")
            self.assertTrue(output.is_dir())
        finally:
            facade.close()

    def test_round_trip_input_has_aggregate_size_bound_and_releases_lock(self):
        facade, _case, composition, _exported, _input_doc = self._build_round_trip()
        try:
            output = self.root / "writer-round-trip-too-large"
            with patch(
                "plugins.local_application.writer_round_trip_service.MAX_ROUND_TRIP_INPUT_BYTES",
                1,
            ):
                with self.assertRaises(LocalApplicationError) as error:
                    facade.export_writer_round_trip_input(
                        composition["composition_id"], ["SEC-FRAME"], output
                    )
            self.assertEqual(
                error.exception.code, "APPLICATION-WRITER-ROUND-TRIP-BOUND-001"
            )
            self.assertFalse(output.exists())

            # A failed bounded export must not poison the destination.
            exported = facade.export_writer_round_trip_input(
                composition["composition_id"], ["SEC-FRAME"], output
            )
            self.assertEqual(exported["status"], "EXPORTED")
        finally:
            facade.close()

    def test_changed_input_does_not_reuse_sections_from_older_outline(self):
        facade, case, composition, first_export, input_doc = self._build_round_trip()
        try:
            first = facade.import_writer_response(self._response(input_doc))
            proposal = writer_comp_support.Issue80WriterCompositionTests._proposal(
                self, case, composition_id=composition["composition_id"], base=composition
            )
            proposal["sections"][0]["purpose"] = "Changed outline purpose requiring a fresh draft set."
            proposal["sections"][1]["narrative_stage_refs"] = ["framing"]
            proposal["sections"][1]["semantic_purpose_refs"] = ["frame_problem"]
            v2 = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            facade.select_writer_composition(v2["composition_id"], 2, v2["composition_digest"])
            out = self.root / "writer-round-trip-v2"
            facade.export_writer_round_trip_input(v2["composition_id"], ["SEC-FRAME", "SEC-VALIDATE"], out)
            input_v2 = json.loads((out / "writer-input.json").read_text(encoding="utf-8"))
            base = {"revision_id": first["revision_id"], "revision_digest": first["revision_digest"]}
            partial = self._response(
                input_v2,
                response_id="WR-V2-PARTIAL",
                base=base,
                sections=[{
                    "section_id": "SEC-FRAME",
                    "content": "Only one section for a changed outline.",
                    "citations": [],
                    "exhibit_refs": list(input_v2["sections"][0]["exhibit_refs"]),
                }],
                feedback=[],
            )
            with self.assertRaises(LocalApplicationError) as error:
                facade.import_writer_response(partial)
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-ROUND-TRIP-INPUT-001")

            complete = deepcopy(partial)
            complete["response_id"] = "WR-V2-COMPLETE"
            complete["sections"].append({
                "section_id": "SEC-VALIDATE",
                "content": "Fresh validation draft under the changed outline.",
                "citations": [],
                "exhibit_refs": [],
            })
            imported = facade.import_writer_response(complete)
            self.assertEqual(imported["status"], "IMPORTED")
            self.assertEqual(imported["reused_section_ids"], [])
        finally:
            facade.close()
