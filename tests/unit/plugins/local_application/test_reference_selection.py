"""Local bibliography sufficiency and review invalidation (#619)."""

import io
import unittest
import zipfile
from copy import deepcopy
from xml.etree import ElementTree as ET

import tests.runtime.test_issue456_formal_rendering as fixtures
from plugins.application_errors import LocalApplicationError
from plugins.local_application.misco.publication_dialect import (
    MISCO_PUBLICATION_DIALECT,
    PUBLICATION_DIALECTS,
)
from plugins.local_application.publication.publication_dialect import PublicationDialect
from plugins.local_application.publication.publication_release_service import (
    PublicationReleaseService,
)
from plugins.local_application.publication.publication_release_support import (
    _publication_policy,
    _validate_publication_inputs,
)
from plugins.local_application.publication.reference_selection import (
    filter_references,
    select_references,
)


class ReferenceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.inspection = fixtures.representative_inspection()
        self.policy = self.inspection["publication_policy"]
        self.policy["bibliography"] = {"mode": "omit_complete_local", "displays": []}
        self.section = self.inspection["revision"]["sections"][1]
        self.source = self.inspection["source_package_document"]["resolved_content"][
            "research_objects"
        ][0]
        self.service = PublicationReleaseService.__new__(PublicationReleaseService)
        self.service.dialects = PUBLICATION_DIALECTS

    def plan(self):
        return select_references(
            self.inspection, MISCO_PUBLICATION_DIALECT, self.service._citation_label
        )

    def local_result(self):
        return next(r for r in self.plan() if r["section_id"] == "s2")

    def display(self, placement="footnote", method="reviewed"):
        self.section["content"] = "本文{{note-1}}。"
        display = {
            "display_id": "local-1",
            "section_id": "s2",
            "source_ref": self.source["id"],
            "locator_ref": "51頁",
            "marker": "{{note-1}}",
            "placement": placement,
            "method": method,
        }
        label = self.service._citation_label(self.source, "51頁", self.policy)
        self.policy["formal_report"]["footnotes"][0]["text"] = label
        if placement == "inline":
            self.section["content"] = "本文（" + label + "）。"
            display["marker"] = label
            self.policy["formal_report"]["footnotes"].pop(0)
        self.policy["bibliography"]["displays"].append(display)
        return display

    def confirm(self, display):
        digest = self.local_result()["displays"][0]["review_digest"]
        display["review"] = {
            "status": "sufficient",
            "content_digest": digest,
            "reviewer_id": "test-reviewer",
            "reviewed_at": "2026-11-19T00:00:00Z",
            "rationale": "Synthetic complete local source review.",
        }

    def test_default_and_repeat_preserve_legacy_output_and_inputs(self):
        self.policy.pop("bibliography")
        before = deepcopy(self.inspection)
        old = self.service._render(self.inspection)
        self.assertEqual(self.inspection, before)
        self.policy["bibliography"] = {"mode": "repeat"}
        repeated = self.service._render(self.inspection)
        self.assertEqual(old[0], repeated[0])
        with (
            zipfile.ZipFile(io.BytesIO(old[1])) as a,
            zipfile.ZipFile(io.BytesIO(repeated[1])) as b,
        ):
            self.assertEqual(
                {n: a.read(n) for n in a.namelist()}, {n: b.read(n) for n in b.namelist()}
            )

    def test_inline_omission_preserves_citations_sources_captions_and_no_empty_heading(self):
        before = deepcopy(self.inspection)
        self.assertTrue(all(r["omitted"] for r in self.plan()))
        markdown, docx, issues, _ = self.service._render(self.inspection)
        self.assertEqual(issues, [])
        self.assertNotIn("＜参考文献＞", markdown.decode())
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            text = "".join(ET.fromstring(archive.read("word/document.xml")).itertext())
            self.assertIn(self.source["title"], text)
            self.assertIn("（出典）", text)
        self.assertEqual(self.inspection, before)

    def test_one_incomplete_subsection_keeps_whole_formal_section(self):
        self.inspection["revision"]["sections"][2]["content"] = "略記のみ。"
        rows = self.plan()
        self.assertFalse(next(r for r in rows if r["section_id"] == "s3")["omitted"])
        self.assertEqual(
            filter_references([self.source["id"]], ["s2", "s3"], rows), [self.source["id"]]
        )
        self.assertEqual(self.service._render(self.inspection)[0].decode().count("＜参考文献＞"), 1)

    def test_explicit_keep_and_missing_locator(self):
        self.policy["bibliography"]["keep_sources"] = [self.source["id"]]
        self.assertFalse(self.local_result()["omitted"])
        self.policy["bibliography"].pop("keep_sources")
        self.section["citations"][0].pop("locator_ref")
        self.assertFalse(self.local_result()["sufficient"])

    def test_repeated_registered_use_needs_multiple_occurrences_and_distinct_locators_are_preserved(
        self,
    ):
        self.section["citations"].append(deepcopy(self.section["citations"][0]))
        self.assertFalse(self.local_result()["sufficient"])
        self.section["content"] += " 再引用[[citation:SRC-SYNTHETIC]]"
        self.assertTrue(self.local_result()["sufficient"])
        self.section["citations"][1]["locator_ref"] = "53頁"
        text = self.service._render(self.inspection)[0].decode()
        self.assertIn("51頁；53頁", text)
        self.assertEqual(self.section["citations"][1]["locator_ref"], "53頁")

    def test_generated_and_reviewed_native_footnotes_and_inline_displays(self):
        for placement in ["inline", "footnote"]:
            for method in ["generated", "reviewed"]:
                with self.subTest(placement=placement, method=method):
                    self.setUp()
                    display = self.display(placement, method)
                    if method == "reviewed":
                        self.assertFalse(self.local_result()["omitted"])
                        self.confirm(display)
                    self.assertTrue(self.local_result()["omitted"])
                    markdown, docx, issues, _ = self.service._render(self.inspection)
                    self.assertEqual(issues, [])
                    self.assertNotIn("出典：", markdown.decode())
                    if placement == "footnote":
                        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
                            self.assertIn(
                                self.source["title"],
                                "".join(
                                    ET.fromstring(archive.read("word/footnotes.xml")).itertext()
                                ),
                            )
                            self.assertIn("eachPage", archive.read("word/document.xml").decode())

    def test_review_invalidates_on_text_citation_source_footnote_and_scope_change(self):
        for change in ["body", "citation", "source", "note", "scope", "display"]:
            with self.subTest(change=change):
                self.setUp()
                display = self.display()
                self.confirm(display)
                self.assertTrue(self.local_result()["omitted"])
                if change == "body":
                    self.section["content"] += "改稿。"
                elif change == "citation":
                    self.section["citations"].append(deepcopy(self.section["citations"][0]))
                elif change == "source":
                    self.source["title"] += "改訂"
                elif change == "note":
                    self.policy["formal_report"]["footnotes"][0]["text"] += "改稿"
                elif change == "scope":
                    self.policy["formal_report"]["structure"][7]["level"] = 1
                else:
                    display["locator_exception"] = "Changed explanation."
                result = self.local_result()
                self.assertFalse(result["omitted"])
                self.assertEqual(result["displays"][0]["reason"], "stale_review")

    def test_duplicate_or_missing_anchor_shortened_url_and_unreviewed_text_keep_source(self):
        for change in ["duplicate", "missing", "short_url", "unconfirmed"]:
            with self.subTest(change=change):
                self.setUp()
                display = self.display("inline")
                if change == "duplicate":
                    self.section["content"] *= 2
                elif change == "missing":
                    self.section["content"] = "別の本文"
                elif change == "short_url":
                    display["marker"] = "著者、題名、https://example.test/…"
                    self.section["content"] = display["marker"]
                if change != "unconfirmed":
                    self.confirm(display)
                self.assertFalse(self.local_result()["omitted"])

    def test_missing_locator_can_only_use_reviewed_nonapplicability(self):
        display = self.display()
        self.section["citations"][0].pop("locator_ref")
        display.pop("locator_ref")
        display["locator_exception"] = "Whole unpaginated web document is cited."
        self.assertFalse(self.local_result()["omitted"])
        self.confirm(display)
        self.assertTrue(self.local_result()["omitted"])

    def test_exceptions_require_manual_review_and_no_metadata_is_invented(self):
        display = self.display()
        self.source.pop("author")
        self.source["bibliography_exceptions"] = {"author": "No author credited; checked original."}
        self.assertFalse(self.local_result()["omitted"])
        self.confirm(display)
        self.assertTrue(self.local_result()["sufficient"])
        self.assertFalse(self.local_result()["omitted"])  # Unreviewed peer in same formal section.
        self.assertNotIn("author", self.source)

    def test_schema_and_binding_reject_invalid_input(self):
        _validate_publication_inputs(
            {"schema_version": "0.1.0", "bibliography": {"mode": "repeat"}}
        )
        for config in [{"mode": "bad"}, {"mode": "repeat", "unknown": True}]:
            with self.assertRaises(LocalApplicationError):
                _validate_publication_inputs({"schema_version": "0.1.0", "bibliography": config})
        display = self.display()
        display["section_id"] = "unknown"
        with self.assertRaises(LocalApplicationError):
            self.plan()
        with self.assertRaises(LocalApplicationError):
            select_references(self.inspection, PublicationDialect(), self.service._citation_label)

    def test_negative_review_is_not_overridden_by_generated_label_and_rereview_restores_eligibility(
        self,
    ):
        display = self.display(method="generated")
        self.assertTrue(self.local_result()["sufficient"])
        self.confirm(display)
        display["review"]["status"] = "insufficient"
        self.assertFalse(self.local_result()["sufficient"])
        display["review"]["status"] = "unevaluated"
        self.assertFalse(self.local_result()["sufficient"])
        self.confirm(display)
        self.assertTrue(self.local_result()["sufficient"])
        self.section["content"] += "改稿"
        self.assertFalse(self.local_result()["sufficient"])
        self.confirm(display)
        self.assertTrue(self.local_result()["sufficient"])

    def test_unrelated_section_change_does_not_invalidate_local_review(self):
        display = self.display()
        self.confirm(display)
        self.inspection["revision"]["sections"][-1]["content"] += "別節改稿"
        self.assertTrue(self.local_result()["sufficient"])

    def test_same_inline_source_text_in_another_section_does_not_make_anchor_ambiguous(self):
        display = self.display("inline", "generated")
        self.inspection["revision"]["sections"][-1]["content"] += display["marker"]
        self.assertTrue(self.local_result()["sufficient"])

    def test_policy_retains_opt_in_only(self):
        package = {"effective_profile_set": {"effective_resources": []}}
        old = _publication_policy(package, {}, {})
        self.assertNotIn("bibliography", old)
        config = {"mode": "omit_complete_local"}
        current = _publication_policy(package, {}, {"bibliography": config})
        self.assertEqual(current["bibliography"], config)
        config["mode"] = "repeat"
        self.assertEqual(current["bibliography"]["mode"], "omit_complete_local")
