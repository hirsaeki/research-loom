from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import issue80_writer_composition_suite as composition_tests
import rfc8785
import test_external_desktop_research_intake as intake
import test_misco_writer_profile_application as legacy
from research_package_acceptance_support import ResearchPackageAcceptanceSupport

from plugins.local_application import LocalApplicationError
from plugins.local_application.profile_resolution import resolve_effective_profile_set
from plugins.local_application.writer_round_trip_service import WriterRoundTripService

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "profiles/narrative/misco/1.2.0/profile.json"


class Issue464WriterRuleScopeTests(ResearchPackageAcceptanceSupport):
    _build_round_trip = legacy.MiscoWriterProfileApplicationTests._build_round_trip

    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "publication": [],
            "narrative": [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.2.0"}
            ],
        }
        config.pop("configuration_digest", None)
        config["configuration_digest"] = (
            "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        )
        effective = resolve_effective_profile_set(
            config, [MANIFEST, MANIFEST.parents[1] / "profile.json"]
        )
        cfg, eps = self.root / "config.json", self.root / "profiles.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(json.dumps(effective), encoding="utf-8")
        return cfg, eps

    @staticmethod
    def _review(section_input, **kwargs):
        rows = legacy.MiscoWriterProfileApplicationTests._review(section_input, **kwargs)
        scope = {"section_input": section_input}
        metadata = WriterRoundTripService._writer_rule_metadata(scope)
        for row in rows:
            row["rule_results"] = [
                {
                    "rule_id": rule_id,
                    "outcome": "unevaluated",
                    "applicability": "undetermined",
                    "method": "unevaluated",
                    "rationale": "Synthetic draft: content has not been semantically reviewed.",
                }
                for rule_id in row["rule_ids"]
            ]
            assert all(rule_id in metadata for rule_id in row["rule_ids"])
        return rows

    @classmethod
    def _response(cls, input_doc):
        response = legacy.MiscoWriterProfileApplicationTests._response.__func__(
            cls, input_doc, response_id="WR-464"
        )
        for draft, scope in zip(response["sections"], input_doc["sections"], strict=False):
            draft["citations"] = deepcopy(
                scope["section_input"]["section_contract"]["citation_requirements"]
            )
        return response

    def test_opt_in_detached_rules_sources_and_old_version(self):
        facade, case, composition, input_doc, output = self._build_round_trip()
        try:
            delivery = input_doc["sections"][0]["section_input"]["writer_profile"]
            self.assertEqual(len(delivery["review_plan"]), 8)
            self.assertEqual(delivery["rule_count"], 127)
            self.assertEqual({p["profile_version"] for p in delivery["profile_pins"]}, {"1.2.0"})
            resources = {r["role"]: json.loads(r["content"]) for r in delivery["resources"]}
            rules = resources["WRITER_RULES"]["items"]
            source_docs = {
                r["path"]: r["content"]
                for r in resources["WRITER_SOURCE_DOCUMENTS"]["source_documents"]
            }
            for item in rules:
                self.assertIn(item["source"]["path"], source_docs)
                for source in item.get("additional_sources", []):
                    self.assertIn(source["locator"], source_docs[source["path"]])
                    self.assertIn(item["body"], source_docs[source["path"]])
            self.assertEqual(sum(bool(r.get("additional_sources")) for r in rules), 6)
            self.assertEqual(
                {r["review"]["check_kind"] for r in rules}, {"structural", "semantic", "editorial"}
            )
            self.assertEqual({r["review"]["scope"] for r in rules}, {"section", "document"})
            original = json.loads(
                (MANIFEST.parents[1] / "resources/writer-clean-rules.json").read_text()
            )
            self.assertNotIn("review_contract_version", original)
            self.assertEqual({r["id"] for r in rules}, {r["id"] for r in original["items"]})
            self.assertEqual(
                json.loads((MANIFEST.parents[1] / "profile.json").read_text())["profile_version"],
                "1.1.0",
            )
        finally:
            facade.close()
        shutil.rmtree(self.workspace)
        detached = json.loads((output / "writer-input.json").read_text())
        self.assertEqual(detached, input_doc)
        self.assertTrue(
            all(
                r["content"]
                for r in detached["sections"][0]["section_input"]["writer_profile"]["resources"]
            )
        )

    def test_structural_success_preserves_semantically_wrong_draft_as_unevaluated(self):
        facade, _, composition, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            response["sections"][0]["content"] = (
                "The proposed trial has already proved universal effectiveness."
            )
            result = facade.import_writer_response(response)
            revision = facade.inspect_writer_round_trip(
                composition["composition_id"], result["revision_id"]
            )["revision"]
            self.assertTrue(
                all(
                    r["outcome"] == "unevaluated"
                    for s in revision["sections"]
                    for r in s["profile_review"]
                )
            )
            self.assertFalse(result["research_state_mutation_performed"])
        finally:
            facade.close()

    def test_explicit_countermaterial_reference_required_but_allowlist_not_required(self):
        facade, _, _, doc, _ = self._build_round_trip()
        try:
            scope = deepcopy(doc["sections"][0])
            required = {"source_ref": scope["citation_scope"][0]["source_ref"], "locator_ref": None}
            scope["section_input"]["section_contract"]["citation_requirements"] = [required]
            receipt = {"sections": [scope]}
            package = facade.show_research_package(doc["source"]["research_package_id"])["package"]
            draft = self._response(doc)["sections"][0]
            draft["citations"] = []
            response = {"sections": [draft], "feedback": []}
            with self.assertRaisesRegex(LocalApplicationError, "explicitly required citation"):
                facade._writer_round_trip_service()._validate_response_semantics(
                    response, receipt, package
                )
            draft["citations"] = [deepcopy(required)]
            scope["citation_scope"].append({"source_ref": "S-ALLOWED-UNUSED", "locators": []})
            facade._writer_round_trip_service()._validate_response_semantics(
                response, receipt, package
            )
            required["locator_ref"] = scope["citation_scope"][0]["locators"][0]
            with self.assertRaisesRegex(LocalApplicationError, "explicitly required citation"):
                facade._writer_round_trip_service()._validate_response_semantics(
                    response, receipt, package
                )
        finally:
            facade.close()

    def test_rule_review_rejects_false_pass_and_invalid_na(self):
        facade, _, _, doc, _ = self._build_round_trip()
        try:
            scope = doc["sections"][0]
            draft = self._response(doc)["sections"][0]
            for mutation in (
                "missing",
                "structural-semantic",
                "partial-na",
                "unevaluated-pass",
                "document-pass",
                "blank-rationale",
            ):
                with self.subTest(mutation=mutation):
                    bad = deepcopy(draft)
                    row = next(r for r in bad["profile_review"] if "PUB-EV-04" in r["rule_ids"])
                    item = next(i for i in row["rule_results"] if i["rule_id"] == "PUB-EV-04")
                    if mutation == "missing":
                        row["rule_results"].pop()
                    elif mutation == "structural-semantic":
                        item.update(
                            outcome="conformant", applicability="applicable", method="structural"
                        )
                    elif mutation == "partial-na":
                        row["outcome"] = "not_applicable"
                    elif mutation == "unevaluated-pass":
                        row["outcome"] = "conformant"
                    elif mutation == "blank-rationale":
                        item["rationale"] = "  "
                    else:
                        row = next(r for r in bad["profile_review"] if "PUB-RC-04" in r["rule_ids"])
                        item = next(i for i in row["rule_results"] if i["rule_id"] == "PUB-RC-04")
                        item.update(
                            outcome="conformant", applicability="applicable", method="semantic"
                        )
                    with self.assertRaises(LocalApplicationError):
                        WriterRoundTripService._validate_profile_review(bad, scope)
            # N/A is a declared content review, not an automatic source-ID check.
            valid = deepcopy(draft)
            row = next(r for r in valid["profile_review"] if r["review_id"] == "writer-terminology")
            row["outcome"] = "not_applicable"
            for item in row["rule_results"]:
                item.update(
                    outcome="not_applicable",
                    applicability="not_applicable",
                    method="semantic",
                    rationale="Synthetic definition-only fragment contains no relevant terminology transformation.",
                )
            WriterRoundTripService._validate_profile_review(valid, scope)
            mixed = deepcopy(valid)
            row = next(r for r in mixed["profile_review"] if r["review_id"] == "writer-terminology")
            row["outcome"] = "mixed"
            row["violated_rule_ids"] = list(row["rule_ids"])
            for item in row["rule_results"]:
                item.update(
                    outcome="violation",
                    applicability="applicable",
                    method="semantic",
                    rationale="Synthetic terminology review found an internal term in every rule target.",
                )
            with self.assertRaisesRegex(LocalApplicationError, "Mixed group requires both"):
                WriterRoundTripService._validate_profile_review(mixed, scope)
            retained = row["rule_results"][0]
            retained.update(
                outcome="conformant", rationale="This terminology rule was evaluated and satisfied."
            )
            row["violated_rule_ids"].remove(retained["rule_id"])
            WriterRoundTripService._validate_profile_review(mixed, scope)
        finally:
            facade.close()

    def test_public_export_import_requires_selected_adverse_source(self):
        facade, case = (
            composition_tests.Issue80WriterCompositionTests._build_complete_support_package(
                self, include_adverse=True
            )
        )
        try:
            proposal = composition_tests.Issue80WriterCompositionTests._proposal(self, case)
            proposal["sections"] = proposal["sections"][:1]
            section = proposal["sections"][0]
            section.pop("next_section_id")
            section["evidence_refs"] = [case["counter_evidence_id"]]
            section["counter_review_refs"] = [case["counter_review_id"]]
            section["citation_requirements"] = [
                {"source_ref": case["counter_source_id"], "locator_ref": case["counter_locator"]}
            ]
            composition = facade.capture_writer_composition(case["package_id"], proposal)[
                "composition"
            ]
            facade.select_writer_composition(
                composition["composition_id"], 1, composition["composition_digest"]
            )
            output = self.root / "adverse-input"
            facade.export_writer_round_trip_input(
                composition["composition_id"], ["SEC-FRAME"], output
            )
            doc = json.loads((output / "writer-input.json").read_text())
            response = self._response(doc)
            response["sections"][0]["citations"] = []
            with self.assertRaisesRegex(LocalApplicationError, "explicitly required citation"):
                facade.import_writer_response(response)
            response["sections"][0]["citations"] = deepcopy(section["citation_requirements"])
            result = facade.import_writer_response(response)
            self.assertEqual(result["status"], "IMPORTED")
            self.assertEqual(facade.import_writer_response(response)["status"], "VERIFIED_REUSE")
        finally:
            facade.close()
