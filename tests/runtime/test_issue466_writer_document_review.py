from __future__ import annotations

import io
import json
from copy import deepcopy
from unittest.mock import patch

import tests.runtime.test_issue464_writer_rule_scope as scope_tests
from plugins.local_application import LocalApplicationError
from plugins.local_application.cli import main
from plugins.local_application.writer.writer_round_trip_service import WriterRoundTripService
from tests.runtime.research_package_acceptance_support import ResearchPackageAcceptanceSupport


class Issue466WriterDocumentReviewTests(ResearchPackageAcceptanceSupport):
    REUSE_INITIAL_WORKSPACE = True

    _build_round_trip = scope_tests.Issue464WriterRuleScopeTests._build_round_trip
    _write_structured_workspace_inputs = (
        scope_tests.Issue464WriterRuleScopeTests._write_structured_workspace_inputs
    )
    _review = staticmethod(scope_tests.Issue464WriterRuleScopeTests._review)
    _response = classmethod(scope_tests.Issue464WriterRuleScopeTests._response.__func__)

    @staticmethod
    def _document_review(prepared, *, outcome="unevaluated", coverage="full"):
        rows = []
        for group in prepared["review_plan"]:
            results = []
            for rule_id in group["rule_ids"]:
                kind = prepared["rule_metadata"][rule_id]["check_kind"]
                results.append(
                    {
                        "rule_id": rule_id,
                        "outcome": outcome,
                        "applicability": "undetermined"
                        if outcome == "unevaluated"
                        else "not_applicable"
                        if outcome == "not_applicable"
                        else "applicable",
                        "method": "unevaluated" if outcome == "unevaluated" else kind,
                        "rationale": "Synthetic test declaration; not independent evidence of text quality.",
                    }
                )
            rows.append(
                {
                    "review_id": group["review_id"],
                    "rule_ids": list(group["rule_ids"]),
                    "outcome": outcome,
                    "violated_rule_ids": list(group["rule_ids"]) if outcome == "violation" else [],
                    "rationale": "Synthetic document review for exact target.",
                    "rule_results": results,
                }
            )
        return {
            "target_digest": prepared["target_digest"],
            "coverage": coverage,
            "section_ids": list(prepared["scope_section_ids"]),
            "reviewer": {"reviewer_id": "synthetic-host", "method": "host_self_review"},
            "reviewed_at": "2026-10-16T08:00:00Z",
            "profile_review": rows,
        }

    def test_public_prepare_import_replay_and_partial_edit_drop_old_review(self):
        facade, _, composition, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            prepared = facade.prepare_writer_document_review(response)
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertFalse(prepared["research_state_mutation_performed"])
            self.assertEqual(len(prepared["material"]["sections"]), 2)
            self.assertTrue(prepared["review_plan"])
            response["document_review"] = self._document_review(prepared, outcome="conformant")
            first = facade.import_writer_response(response)
            self.assertEqual(
                facade.import_writer_response(deepcopy(response))["status"], "VERIFIED_REUSE"
            )
            shown = facade.inspect_writer_round_trip(composition["composition_id"])
            self.assertEqual(shown["document_review_status"]["status"], "reviewed")
            self.assertFalse(shown["document_review_status"]["semantic_quality_guaranteed"])
            old = deepcopy(shown["revision"])
            changed = deepcopy(response)
            changed["response_id"] = "WR-466-EDIT"
            changed["base_revision_ref"] = {
                key: first[key] for key in ("revision_id", "revision_digest")
            }
            changed["sections"] = changed["sections"][:1]
            changed["sections"][0]["content"] = (
                "A concrete editorial revision reconnects the opening question to the supplied recommendation."
            )
            second_target = facade.prepare_writer_document_review(changed)
            self.assertNotEqual(second_target["target_digest"], prepared["target_digest"])
            self.assertEqual(
                second_target["material"]["sections"][1]["content"], old["sections"][1]["content"]
            )
            with self.assertRaisesRegex(LocalApplicationError, "does not match"):
                facade.import_writer_response(changed)
            changed.pop("document_review")
            second = facade.import_writer_response(changed)
            self.assertEqual(second["reused_section_ids"], [old["sections"][1]["section_id"]])
            now = facade.inspect_writer_round_trip(composition["composition_id"])
            self.assertEqual(now["document_review_status"]["status"], "unevaluated")
            self.assertNotIn("document_review", now["revision"])
            self.assertEqual(now["revision"]["sections"][1], old["sections"][1])
            self.assertEqual(
                facade.inspect_writer_round_trip(
                    composition["composition_id"], first["revision_id"]
                )["revision"],
                old,
            )
        finally:
            facade.close()

    def test_citation_and_exhibit_changes_invalidate_review_even_with_same_prose(self):
        facade, _, composition, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            prepared = facade.prepare_writer_document_review(response)
            response["document_review"] = self._document_review(prepared)
            for field in ("citations", "exhibit_refs"):
                with self.subTest(field=field):
                    changed = deepcopy(response)
                    section = changed["sections"][0]
                    if field == "citations":
                        allowed = doc["sections"][0]["citation_scope"][0]
                        section[field].append(
                            {"source_ref": allowed["source_ref"], "locator_ref": None}
                        )
                    else:
                        self.assertTrue(section[field])
                        section[field] = []
                    new = facade.prepare_writer_document_review(changed)
                    self.assertNotEqual(new["target_digest"], prepared["target_digest"])
                    with self.assertRaisesRegex(LocalApplicationError, "does not match"):
                        facade.import_writer_response(changed)
            self.assertEqual(facade.import_writer_response(response)["status"], "IMPORTED")
        finally:
            facade.close()

    def test_partial_missing_rules_invalid_na_and_structural_substitution_do_not_pass(self):
        facade, _, _, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            prepared = facade.prepare_writer_document_review(response)
            for mutation in (
                "full-excerpt",
                "partial-pass",
                "partial-na",
                "missing-rule",
                "wrong-method",
                "invalid-na",
            ):
                with self.subTest(mutation=mutation):
                    changed = deepcopy(response)
                    review = self._document_review(prepared, outcome="conformant")
                    changed["document_review"] = review
                    if mutation == "full-excerpt":
                        review["section_ids"] = review["section_ids"][:1]
                    elif mutation in {"partial-pass", "partial-na"}:
                        review["coverage"] = "partial"
                        review["section_ids"] = review["section_ids"][:1]
                        if mutation == "partial-na":
                            review["profile_review"] = self._document_review(
                                prepared, outcome="not_applicable"
                            )["profile_review"]
                    elif mutation == "missing-rule":
                        review["profile_review"][0]["rule_results"].pop()
                    elif mutation == "wrong-method":
                        item = next(
                            item
                            for row in review["profile_review"]
                            for item in row["rule_results"]
                            if item["method"] != "structural"
                        )
                        item["method"] = "structural"
                    else:
                        review["profile_review"][0]["outcome"] = "not_applicable"
                    with self.assertRaises(LocalApplicationError):
                        facade.import_writer_response(changed)
            response["document_review"] = self._document_review(prepared, coverage="partial")
            response["document_review"]["section_ids"] = prepared["scope_section_ids"][:1]
            result = facade.import_writer_response(response)
            self.assertFalse(result["research_state_mutation_performed"])
        finally:
            facade.close()

    def test_document_violations_require_feedback_and_do_not_prevent_draft_edits(self):
        facade, _, composition, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            prepared = facade.prepare_writer_document_review(response)
            response["document_review"] = self._document_review(prepared, outcome="violation")
            with self.assertRaisesRegex(LocalApplicationError, "require Writing Feedback"):
                facade.import_writer_response(response)
            response["feedback"] = [
                {
                    "issue_id": "WFI-466-DOCUMENT",
                    "target_type": "package",
                    "target_id": doc["source"]["research_package_id"],
                    "issue_category": "NARRATIVE_CONSTRAINT_CONFLICT",
                    "description": "The opening asks for a decision, but the ending does not answer it; repeated limits also interrupt the middle.",
                    "severity": "major",
                    "supporting_package_refs": [],
                    "proposed_next_action": "Reconnect the recommendation to the opening and consolidate duplicate limits without changing the research conclusion.",
                    "profile_rule_ids": [
                        item
                        for row in response["document_review"]["profile_review"]
                        for item in row["rule_ids"]
                    ],
                }
            ]
            result = facade.import_writer_response(response)
            shown = facade.inspect_writer_round_trip(composition["composition_id"])
            self.assertEqual(shown["revision"]["writing_feedback"]["issues"], response["feedback"])
            self.assertEqual(
                set(shown["document_review_status"]["rule_outcomes"].values()), {"violation"}
            )
            self.assertFalse(result["research_state_mutation_performed"])
        finally:
            facade.close()

    def test_target_uses_input_pins_and_canonical_section_order_not_review_metadata(self):
        facade, _, _, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            first = facade.prepare_writer_document_review(response)
            response["sections"].reverse()
            second = facade.prepare_writer_document_review(response)
            self.assertEqual(second["target_digest"], first["target_digest"])
            changed = deepcopy(doc)
            changed["input_digest"] = "sha256:" + "1" * 64
            self.assertNotEqual(
                WriterRoundTripService._document_target(changed, first["material"]["sections"])[
                    "target_digest"
                ],
                first["target_digest"],
            )
            reversed_target = WriterRoundTripService._document_target(
                doc, list(reversed(first["material"]["sections"]))
            )
            self.assertNotEqual(reversed_target["target_digest"], first["target_digest"])
            response["document_review"] = self._document_review(first)
            self.assertEqual(
                facade.prepare_writer_document_review(response)["target_digest"],
                first["target_digest"],
            )
        finally:
            facade.close()

    def test_cli_prepare_reads_detached_response_without_saving_or_research_mutation(self):
        facade, _, _, doc, _ = self._build_round_trip()
        response = self._response(doc)
        expected = facade.prepare_writer_document_review(response)
        before = facade.status()["snapshot"]
        path = self.root / "response466.json"
        path.write_text(json.dumps(response), encoding="utf-8")
        facade.close()
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = main(
                [
                    "writer-round-trip",
                    "prepare-review",
                    "--workspace",
                    str(self.workspace),
                    "--json",
                    str(path),
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        prepared = json.loads(output.getvalue())
        self.assertEqual(prepared["target_digest"], expected["target_digest"])
        from plugins.local_application import LocalApplicationFacade

        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened.status()["snapshot"], before)
            with self.assertRaises(LocalApplicationError):
                reopened.inspect_writer_round_trip(doc["source"]["composition_id"])

    def test_new_composition_input_cannot_keep_previous_document_review(self):
        facade, case, composition, doc, _ = self._build_round_trip()
        try:
            response = self._response(doc)
            first_target = facade.prepare_writer_document_review(response)
            response["document_review"] = self._document_review(first_target)
            first = facade.import_writer_response(response)
            proposal = scope_tests.composition_tests.Issue80WriterCompositionTests._proposal(
                self, case, composition_id=composition["composition_id"], base=composition
            )
            proposal["sections"][0]["purpose"] = (
                "Changed framing role requiring a fresh complete target."
            )
            proposal["sections"][1]["narrative_stage_refs"] = ["framing"]
            proposal["sections"][1]["semantic_purpose_refs"] = ["frame_problem"]
            new_comp = facade.capture_writer_composition(case["package_id"], proposal)[
                "composition"
            ]
            facade.select_writer_composition(
                new_comp["composition_id"], 2, new_comp["composition_digest"]
            )
            output = self.root / "document-review-new-input"
            facade.export_writer_round_trip_input(
                new_comp["composition_id"], first_target["scope_section_ids"], output
            )
            new_doc = json.loads((output / "writer-input.json").read_text(encoding="utf-8"))
            changed = self._response(new_doc)
            changed["response_id"] = "WR-466-COMPOSITION"
            changed["base_revision_ref"] = {
                key: first[key] for key in ("revision_id", "revision_digest")
            }
            changed["document_review"] = deepcopy(response["document_review"])
            new_target = facade.prepare_writer_document_review(changed)
            self.assertNotEqual(new_target["target_digest"], first_target["target_digest"])
            with self.assertRaisesRegex(LocalApplicationError, "does not match"):
                facade.import_writer_response(changed)
            changed.pop("document_review")
            result = facade.import_writer_response(changed)
            self.assertEqual(result["reused_section_ids"], [])
        finally:
            facade.close()
