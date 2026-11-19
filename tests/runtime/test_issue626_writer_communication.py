from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, verify_writer_section_input
from plugins.local_application.writer.writer_composition_support import _digest_document
from plugins.local_application.writer.writer_input_bundle import compact_input, expand_input
from plugins.local_application.writer.writer_section_input import WriterSectionInputMixin
from tests.runtime import test_issue219_writer_round_trip as round_trip
from tests.runtime.research_package_acceptance_support import ResearchPackageAcceptanceSupport


class WriterCommunicationTests(ResearchPackageAcceptanceSupport):
    REUSE_INITIAL_WORKSPACE = True

    def _write_structured_workspace_inputs(self):
        cfg, eps = super()._write_structured_workspace_inputs()
        config = json.loads(cfg.read_text(encoding="utf-8"))
        config["communication_brief"]["must_include"] = [
            "Retain the adopted recommendation and its reason.",
            "State that the operational effect remains unmeasured.",
        ]
        config["project_constraints"]["must_not_claim"].append(
            {"guard_id": "NO-INVENTED-SUCCESS", "statement": "Do not invent measured success."}
        )
        config.pop("configuration_digest")
        config["configuration_digest"] = canonical_digest(config)
        cfg.write_text(json.dumps(config), encoding="utf-8")
        return cfg, eps

    def _build(self):
        result = round_trip.Issue219WriterRoundTripTests._build_round_trip(self)
        self.addCleanup(result[0].close)
        return result

    def test_public_export_round_trip_preserves_positive_and_negative_brief(self):
        facade, case, composition, exported, compact = self._build()
        expanded = expand_input(compact)
        package = facade._writer_composition_service()._package(case["package_id"])
        for row in expanded["sections"]:
            section = row["section_input"]
            self.assertEqual(
                section["communication"]["must_include"],
                package["communication_brief"]["must_include"],
            )
            self.assertIn(
                "Do not invent measured success.", section["communication"]["must_not_claim"]
            )
            self.assertFalse(any(section["authority_boundary"].values()))
            # Document priorities are not copied into each section's messages.
            self.assertNotIn(
                package["communication_brief"]["must_include"][0],
                section["section_contract"]["messages"],
            )
        self.assertEqual(compact_input(expanded["source"], expanded["sections"]), compact)
        response = round_trip.Issue219WriterRoundTripTests._response(expanded)
        imported = facade.import_writer_response(response)
        self.assertEqual(imported["status"], "IMPORTED")
        inspected = facade.inspect_writer_round_trip(composition["composition_id"])
        self.assertEqual(inspected["writer_input"]["sections"], expanded["sections"])
        self.assertFalse(imported["research_state_mutation_performed"])
        section_path = self.root / "writer-round-trip-input/sections/SEC-FRAME"
        self.assertEqual(verify_writer_section_input(section_path)["status"], "VERIFIED")

    def test_brief_changes_affect_digest_without_changing_research_or_contract(self):
        facade, case, composition, _, compact = self._build()
        composer = facade._writer_composition_service()
        original = expand_input(compact)["sections"][0]["section_input"]
        package = composer._package(case["package_id"])
        for key in ("must_include", "must_not_claim"):
            changed = deepcopy(package)
            changed["communication_brief"][key].append("A changed communication priority.")
            with patch.object(composer, "_package", return_value=changed):
                updated = composer._build_section_input_document(
                    composition["composition_id"],
                    "SEC-FRAME",
                    version=1,
                    digest=composition["composition_digest"],
                )
            self.assertNotEqual(updated["section_input_digest"], original["section_input_digest"])
            for preserved in (
                "source",
                "section_contract",
                "resolved_research_objects",
                "resolved_materials",
            ):
                self.assertEqual(updated[preserved], original[preserved])

    def test_empty_or_unspecified_priority_keeps_the_historical_projection(self):
        facade, case, composition, _, _ = self._build()
        composer = facade._writer_composition_service()
        package = composer._package(case["package_id"])
        inputs = []
        for missing in (False, True):
            changed = deepcopy(package)
            changed["communication_brief"]["must_include"] = []
            if missing:
                changed["communication_brief"].pop("must_include")
            with patch.object(composer, "_package", return_value=changed):
                value = composer._build_section_input_document(
                    composition["composition_id"],
                    "SEC-FRAME",
                    version=1,
                    digest=composition["composition_digest"],
                )
            self.assertNotIn("must_include", value["communication"])
            inputs.append(value)
        self.assertEqual(inputs[0], inputs[1])

    def test_old_receipt_import_and_inspection_keep_original_identity(self):
        build = WriterSectionInputMixin._build_section_input_document

        def historical(instance, *args, **kwargs):
            value = build(instance, *args, **kwargs)
            value["communication"].pop("must_include", None)
            value["section_input_digest"] = _digest_document(value, "section_input_digest")
            return value

        with patch.object(WriterSectionInputMixin, "_build_section_input_document", historical):
            facade, _, composition, _, compact = self._build()
        expanded = expand_input(compact)
        response = round_trip.Issue219WriterRoundTripTests._response(expanded)
        imported = facade.import_writer_response(response)
        inspected = facade.inspect_writer_round_trip(composition["composition_id"])
        self.assertEqual(inspected["writer_input"]["input_id"], compact["input_id"])
        self.assertEqual(inspected["writer_input"]["input_digest"], compact["input_digest"])
        self.assertEqual(inspected["writer_input"]["sections"], expanded["sections"])
        self.assertEqual(imported["status"], "IMPORTED")

    def test_legacy_compatibility_does_not_accept_other_changes(self):
        facade, _, _, _, compact = self._build()
        service = facade._writer_round_trip_service()
        expanded = expand_input(compact)
        for mode in ("wrong_positive", "legacy_with_wrong_negative", "legacy_with_wrong_contract"):
            changed = deepcopy(expanded)
            section = changed["sections"][0]["section_input"]
            if mode == "wrong_positive":
                section["communication"]["must_include"] = ["Invent a new priority."]
            else:
                section["communication"].pop("must_include")
                if mode == "legacy_with_wrong_negative":
                    section["communication"]["must_not_claim"] = []
                else:
                    section["section_contract"]["messages"] = ["A different message."]
            section["section_input_digest"] = _digest_document(section, "section_input_digest")
            changed["sections"][0]["section_input_digest"] = section["section_input_digest"]
            with self.assertRaises(LocalApplicationError) as raised:
                service._validate_input_context(changed)
            self.assertEqual(raised.exception.code, "APPLICATION-WRITER-ROUND-TRIP-PIN-001")
