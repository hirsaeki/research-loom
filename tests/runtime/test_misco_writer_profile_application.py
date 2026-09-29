from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import rfc8785

from plugins.local_application import LocalApplicationError
from plugins.local_application.profile_resolution import resolve_effective_profile_set
from plugins.local_application.writer_composition_service import _writer_profile_delivery
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import issue80_writer_composition_suite as writer_comp
import test_external_desktop_research_intake as intake

ROOT = Path(__file__).resolve().parents[2]
WRITER_MANIFEST = ROOT / "profiles/narrative/misco/profile.json"
WRITER_RULES = ROOT / "profiles/narrative/misco/resources/writer-clean-rules.json"
WRITER_SOURCES = ROOT / "profiles/narrative/misco/resources/writer-clean-source-documents.json"


class MiscoWriterProfileApplicationTests(ResearchPackageAcceptanceSupport):
    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.1.0"}
            ],
            "publication": [],
        }
        config.pop("configuration_digest", None)
        config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        effective = resolve_effective_profile_set(config, [WRITER_MANIFEST])
        cfg = self.root / "project-config-input.json"
        eps = self.root / "profiles-input.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(json.dumps(effective, ensure_ascii=False), encoding="utf-8")
        return cfg, eps

    def _build_round_trip(self):
        facade, case = writer_comp.Issue80WriterCompositionTests._build_complete_support_package(self)
        proposal = writer_comp.Issue80WriterCompositionTests._proposal(self, case)
        # The support package deliberately lacks an adopted Argument; keep both
        # exported sections in the framing stage so the normal round trip can run
        # without pretending that an unmet validation prerequisite is satisfied.
        proposal["sections"][1]["narrative_stage_refs"] = ["framing"]
        proposal["sections"][1]["semantic_purpose_refs"] = ["frame_problem"]
        composition = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
        facade.select_writer_composition(composition["composition_id"], 1, composition["composition_digest"])
        output = self.root / "misco-writer-input"
        facade.export_writer_round_trip_input(
            composition["composition_id"], ["SEC-FRAME", "SEC-VALIDATE"], output
        )
        input_doc = json.loads((output / "writer-input.json").read_text(encoding="utf-8"))
        return facade, case, composition, input_doc, output

    @staticmethod
    def _review(section_input, *, violations: dict[str, set[str]] | None = None, outcome="unevaluated"):
        violations = violations or {}
        rows = []
        for plan in section_input["writer_profile"]["review_plan"]:
            violated = sorted(violations.get(plan["review_id"], set()))
            rows.append(
                {
                    "review_id": plan["review_id"],
                    "rule_ids": list(plan["rule_ids"]),
                    "outcome": "violation" if violated else outcome,
                    "violated_rule_ids": violated,
                    "rationale": (
                        "Host review found the named delivered rule violation."
                        if violated
                        else "Deterministic acceptance does not infer semantic/editorial compliance."
                    ),
                }
            )
        return rows

    @classmethod
    def _response(cls, input_doc, *, response_id, base=None, first_violations=None, feedback=None, partial=False):
        sections = []
        source_sections = input_doc["sections"][:1] if partial else input_doc["sections"]
        for index, row in enumerate(source_sections):
            section_id = row["section_id"]
            sections.append(
                {
                    "section_id": section_id,
                    "content": (
                        "The supplied observation proves a new causal relationship and can be generalized without the recorded limitations."
                        if index == 0 and first_violations
                        else f"Draft for {section_id} remains bounded by the supplied research material."
                    ),
                    "citations": [],
                    "exhibit_refs": list(row["exhibit_refs"]),
                    "profile_review": cls._review(
                        row["section_input"],
                        violations=first_violations if index == 0 else None,
                    ),
                }
            )
        return {
            "schema_version": "0.1.0",
            "object_type": "writer_response",
            "response_id": response_id,
            "input_ref": {"input_id": input_doc["input_id"], "input_digest": input_doc["input_digest"]},
            "base_revision_ref": base,
            "writer": {"writer_id": "acceptance-host", "writer_version": "1"},
            "sections": sections,
            "feedback": [] if feedback is None else feedback,
            "provenance": {"generated_at": "2026-09-29T00:00:00Z", "channel": "acceptance"},
        }

    def test_d1_production_narrative_profile_controls_real_composition(self):
        facade, case = writer_comp.Issue80WriterCompositionTests._build_complete_support_package(self)
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            pins = package["effective_profile_set"]["profile_pins"]
            self.assertIn(
                ("narrative", "misco.writer", "1.1.0"),
                {(row["profile_type"], row["profile_id"], row["profile_version"]) for row in pins},
            )
            paths = {row["path"] for row in package["resolved_profiles"]["effective_constraints"]}
            self.assertTrue(
                {
                    "narrative.stages.definitions",
                    "narrative.dependencies.required",
                    "narrative.section_purposes.definitions",
                    "narrative.preservation.required_content",
                    "narrative.connections.preserve",
                }
                <= paths
            )

            bad = writer_comp.Issue80WriterCompositionTests._proposal(self, case)
            bad["sections"][0]["order"] = 2
            bad["sections"][1]["order"] = 1
            bad["sections"][1]["narrative_stage_refs"] = ["formation"]
            bad["sections"][1]["semantic_purpose_refs"] = ["expose_argument"]
            with self.assertRaises(LocalApplicationError) as raised:
                facade.capture_writer_composition(case["package_id"], bad)
            self.assertEqual(raised.exception.code, "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001")

            legal = writer_comp.Issue80WriterCompositionTests._proposal(self, case)
            legal["sections"] = [deepcopy(legal["sections"][0])]
            legal["sections"][0].pop("next_section_id", None)
            legal["sections"][0]["narrative_stage_refs"] = ["framing", "formation"]
            legal["sections"][0]["semantic_purpose_refs"] = ["frame_problem", "expose_argument"]
            captured = facade.capture_writer_composition(case["package_id"], legal)["composition"]
            self.assertEqual(captured["validation"]["status"], "VALID_WITH_GAPS")
        finally:
            facade.close()

    def test_d2_d5_detached_input_carries_exact_rules_source_text_pins_and_review_mapping(self):
        facade, case, _composition, input_doc, output = self._build_round_trip()
        package = facade.show_research_package(case["package_id"])["package"]
        try:
            section_input = input_doc["sections"][0]["section_input"]
            delivery = section_input["writer_profile"]
            self.assertEqual(delivery["rule_count"], 127)
            self.assertEqual(
                {(row["profile_id"], row["profile_version"]) for row in delivery["profile_pins"]},
                {("misco.writer", "1.1.0")},
            )
            resources = {row["role"]: row for row in delivery["resources"]}
            self.assertEqual(set(resources), {"WRITER_RULES", "WRITER_SOURCE_DOCUMENTS"})
            rules = json.loads(resources["WRITER_RULES"]["content"])
            sources = json.loads(resources["WRITER_SOURCE_DOCUMENTS"]["content"])
            rule_ids = {item["id"] for item in rules["items"]}
            mapped = {rule_id for row in delivery["review_plan"] for rule_id in row["rule_ids"]}
            self.assertEqual(mapped, rule_ids)
            self.assertEqual(len(mapped), 127)
            self.assertEqual(
                {row["path"] for row in sources["source_documents"]},
                {item["source"]["path"] for item in rules["items"]},
            )
            expected_writer_ids_by_source = {}
            for item in rules["items"]:
                expected_writer_ids_by_source.setdefault(item["source"]["path"], set()).add(item["id"])
            self.assertEqual(
                {rule_id for row in sources["source_documents"] for rule_id in row["writer_rule_ids"]},
                rule_ids,
            )
            for row in sources["source_documents"]:
                self.assertEqual(set(row["writer_rule_ids"]), expected_writer_ids_by_source[row["path"]])
            self.assertNotIn("synthetic-example-spec", {item["class"] for item in rules["items"]})
            self.assertTrue(all("09_SYNTHETIC_FEWSHOT_SPECIFICATION" not in row["path"] for row in sources["source_documents"]))
            self.assertTrue(all("Layer_B" not in row["path"] and "Layer_C" not in row["path"] for row in sources["source_documents"]))

            ablated = deepcopy(package)
            ablated["effective_profile_set"]["effective_resources"] = [
                row for row in ablated["effective_profile_set"]["effective_resources"]
                if row["role"] != "WRITER_RULES"
            ]
            self.assertIsNone(_writer_profile_delivery(ablated))
            self.assertEqual(
                package["resolved_profiles"]["effective_constraints"],
                ablated["resolved_profiles"]["effective_constraints"],
            )
        finally:
            facade.close()
        shutil.rmtree(self.workspace)
        code = (
            "import json,sys; x=json.load(open(sys.argv[1],encoding='utf-8')); "
            "p=x['sections'][0]['section_input']['writer_profile']; "
            "r={i['role']:i for i in p['resources']}; "
            "assert set(r)=={'WRITER_RULES','WRITER_SOURCE_DOCUMENTS'}; "
            "s=json.loads(r['WRITER_SOURCE_DOCUMENTS']['content']); "
            "assert len(s['source_documents'])==8; assert all(i['content'] for i in s['source_documents'])"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(output / "writer-input.json")],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_d3_two_section_round_trip_and_partial_revision_preserve_history(self):
        facade, _case, composition, input_doc, _output = self._build_round_trip()
        try:
            before = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot["content_digest"]
            first_response = self._response(input_doc, response_id="WR-MISCO-1")
            first = facade.import_writer_response(first_response)
            self.assertEqual(first["status"], "IMPORTED")
            first_path = facade._writer_round_trip_service()._revision_path(
                composition["composition_id"], first["revision_id"]
            )
            first_bytes = first_path.read_bytes()
            shown = facade.inspect_writer_round_trip(composition["composition_id"], first["revision_id"])
            self.assertTrue(all(row["profile_review"] for row in shown["revision"]["sections"]))
            self.assertTrue(
                all(
                    review["outcome"] == "unevaluated"
                    for row in shown["revision"]["sections"]
                    for review in row["profile_review"]
                )
            )

            second_response = self._response(
                input_doc,
                response_id="WR-MISCO-2",
                base={"revision_id": first["revision_id"], "revision_digest": first["revision_digest"]},
                partial=True,
            )
            second_response["sections"][0]["content"] = "Only the framing section is revised; the other section must remain byte-identical."
            second = facade.import_writer_response(second_response)
            self.assertEqual(second["revision_number"], 2)
            self.assertEqual(second["reused_section_ids"], ["SEC-VALIDATE"])
            self.assertEqual(first_path.read_bytes(), first_bytes)
            joined = facade.inspect_writer_round_trip(composition["composition_id"], second["revision_id"])
            sections = {row["section_id"]: row for row in joined["revision"]["sections"]}
            old_sections = {row["section_id"]: row for row in shown["revision"]["sections"]}
            self.assertEqual(sections["SEC-VALIDATE"]["content_digest"], old_sections["SEC-VALIDATE"]["content_digest"])
            after = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot["content_digest"]
            self.assertEqual(before, after)
        finally:
            facade.close()

    def test_d4_explicit_host_profile_violation_requires_writing_feedback(self):
        facade, _case, composition, input_doc, _output = self._build_round_trip()
        try:
            violations = {"narrative-guard": {"NG-15", "NG-16"}}
            bad = self._response(
                input_doc,
                response_id="WR-MISCO-BAD",
                first_violations=violations,
            )
            with self.assertRaises(LocalApplicationError) as raised:
                facade.import_writer_response(bad)
            self.assertEqual(raised.exception.code, "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001")

            bad["feedback"] = [
                {
                    "issue_id": "WFI-MISCO-GUARD",
                    "target_type": "section",
                    "target_id": "SEC-FRAME",
                    "issue_category": "NARRATIVE_CONSTRAINT_CONFLICT",
                    "description": "Host review found new causal/generalized claims not supplied by Research.",
                    "severity": "major",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Return the unsupported interpretation to Research or weaken the prose to the approved scope.",
                    "profile_rule_ids": ["NG-15", "NG-16"],
                }
            ]
            imported = facade.import_writer_response(bad)
            shown = facade.inspect_writer_round_trip(composition["composition_id"], imported["revision_id"])
            self.assertEqual(shown["revision"]["writing_feedback"]["issues"][0]["profile_rule_ids"], ["NG-15", "NG-16"])
            frame = next(row for row in shown["revision"]["sections"] if row["section_id"] == "SEC-FRAME")
            guard = next(row for row in frame["profile_review"] if row["review_id"] == "narrative-guard")
            self.assertEqual(guard["outcome"], "violation")
            self.assertEqual(set(guard["violated_rule_ids"]), {"NG-15", "NG-16"})
            self.assertFalse(shown["revision"]["writing_feedback"]["is_research_evidence"])
            self.assertFalse(shown["revision"]["authority_boundary"]["research_state_mutation_performed"])
        finally:
            facade.close()

    def test_d4_host_review_routes_omitted_counterevidence_boundaries_and_limitations_to_feedback(self):
        facade, case = writer_comp.Issue80WriterCompositionTests._build_complete_support_package(
            self, include_adverse=True
        )
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            objects = {row["id"]: row for row in package["resolved_content"]["research_objects"]}
            finding = next(row for row in objects.values() if row.get("kind") == "finding")
            self.assertTrue(finding.get("limitations"))
            self.assertTrue(finding.get("boundary_conditions"))
            self.assertEqual(
                objects[case["counter_review_id"]]["target"],
                {"kind": "finding", "id": finding["id"]},
            )

            proposal = writer_comp.Issue80WriterCompositionTests._proposal(self, case)
            proposal["sections"] = [deepcopy(proposal["sections"][0])]
            proposal["sections"][0].pop("next_section_id", None)
            proposal["sections"][0]["finding_refs"] = [finding["id"]]
            proposal["sections"][0]["counter_review_refs"] = [case["counter_review_id"]]
            composition = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            facade.select_writer_composition(
                composition["composition_id"], 1, composition["composition_digest"]
            )
            output = self.root / "misco-adverse-writer-input"
            facade.export_writer_round_trip_input(composition["composition_id"], ["SEC-FRAME"], output)
            input_doc = json.loads((output / "writer-input.json").read_text(encoding="utf-8"))
            section_input = input_doc["sections"][0]["section_input"]
            delivered = {row["id"]: row for row in section_input["resolved_research_objects"]}
            self.assertEqual(delivered[finding["id"]]["limitations"], finding["limitations"])
            self.assertEqual(delivered[finding["id"]]["boundary_conditions"], finding["boundary_conditions"])
            self.assertIn(case["counter_review_id"], delivered)

            violations = {
                "writer-input-contract": {"IO-APPROVED_LIMITATIONS"},
                "writer-qa-boundary": {"PUB-EV-06"},
            }
            response = self._response(
                input_doc,
                response_id="WR-MISCO-OMIT-ADVERSE",
                first_violations=violations,
            )
            response["sections"][0]["content"] = "The supplied material supports the conclusion."
            with self.assertRaises(LocalApplicationError) as raised:
                facade.import_writer_response(response)
            self.assertEqual(
                raised.exception.code,
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
            )

            response["feedback"] = [
                {
                    "issue_id": "WFI-MISCO-COUNTER",
                    "target_type": "section",
                    "target_id": "SEC-FRAME",
                    "issue_category": "COUNTEREVIDENCE_NOT_INTEGRATED",
                    "description": "The draft omits the delivered counter-review scope narrowing.",
                    "severity": "major",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Revise the prose to retain the supplied adverse material and bounded scope.",
                    "profile_rule_ids": ["PUB-EV-06"],
                },
                {
                    "issue_id": "WFI-MISCO-LIMIT",
                    "target_type": "section",
                    "target_id": "SEC-FRAME",
                    "issue_category": "LIMITATION_CONFLICT",
                    "description": "The draft omits the approved limitation and boundary condition supplied with the Finding.",
                    "severity": "major",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Restore the supplied limitation/boundary without inventing a new one.",
                    "profile_rule_ids": ["IO-APPROVED_LIMITATIONS"],
                },
            ]
            imported = facade.import_writer_response(response)
            shown = facade.inspect_writer_round_trip(composition["composition_id"], imported["revision_id"])
            issues = shown["revision"]["writing_feedback"]["issues"]
            self.assertEqual(
                {rule for issue in issues for rule in issue.get("profile_rule_ids", [])},
                {"PUB-EV-06", "IO-APPROVED_LIMITATIONS"},
            )
            self.assertFalse(shown["revision"]["authority_boundary"]["research_state_mutation_performed"])
        finally:
            facade.close()

    def test_d6_runtime_input_excludes_synthetic_audit_and_preserves_reader_terms_verbatim(self):
        facade, _case, composition, input_doc, _output = self._build_round_trip()
        try:
            response = self._response(input_doc, response_id="WR-MISCO-TERMS")
            sentence = "MISCOとAPIという必要な専門用語、およびSource Aという資料名はそのまま読者向け本文に残す。"
            response["sections"][0]["content"] = sentence
            imported = facade.import_writer_response(response)
            shown = facade.inspect_writer_round_trip(composition["composition_id"], imported["revision_id"])
            frame = next(row for row in shown["revision"]["sections"] if row["section_id"] == "SEC-FRAME")
            self.assertEqual(frame["content"], sentence)
            resources = input_doc["sections"][0]["section_input"]["writer_profile"]["resources"]
            by_role = {resource["role"]: json.loads(resource["content"]) for resource in resources}
            self.assertNotIn(
                "synthetic-example-spec",
                {item["class"] for item in by_role["WRITER_RULES"]["items"]},
            )
            source_paths = {item["path"] for item in by_role["WRITER_SOURCE_DOCUMENTS"]["source_documents"]}
            self.assertFalse(any("09_SYNTHETIC_FEWSHOT_SPECIFICATION" in path for path in source_paths))
            self.assertFalse(any("Layer_B_AUDIT_PROVENANCE" in path for path in source_paths))
            self.assertFalse(any("Layer_C_HUMAN_REVIEW_SUPPORT" in path for path in source_paths))
        finally:
            facade.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
