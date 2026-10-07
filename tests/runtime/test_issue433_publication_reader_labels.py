"""Synthetic renderer regressions; these do not constitute live visual QA."""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
from xml.etree import ElementTree as ET
import unittest
import zipfile

from plugins.local_application.publication_docx import W
from plugins.local_application.publication_release_service import PublicationReleaseService
from test_issue256_native_publication import fixture_png


class ReaderPresentationTests(unittest.TestCase):
    def inspection(self):
        png = fixture_png(2, 2)
        source = {"id": "SRC", "kind": "source", "title": "Study", "canonical_locator": "https://example.org/study", "publisher_or_author": "Publisher", "publication_or_update_date": "2025"}
        spec = {"chart_type": "bar", "x_column": "enterprise_size", "y_column": "ai_use", "units": {"enterprise_size": None, "ai_use": "%"}, "caption": "企業規模別の利用率", "denominator": "対象企業", "period": "2025"}
        exhibit = {"exhibit_id": "EX", "kind": "figure", "title": spec["caption"], "generated_visual": {}, "visual_semantics": {}, "content": {"value": {"chart_spec": spec}}}
        return {"publication_profile": {"profile_id": "misco.publication"}, "publication_policy": {"url_display_profile": {"template": "{title} — {url}"}}, "source_package_document": {"project": {"title": "Research"}, "resolved_content": {"research_objects": [source], "working_material": {"research_exhibits": [exhibit]}}}, "revision": {"sections": [{"section_id": "SEC", "content": "比較する[[exhibit:EX]]。資料[[citation:SRC]]。", "citations": [{"source_ref": "SRC", "locator_ref": "https://example.org/study#sizes"}], "exhibit_refs": ["EX"]}]}, "composition": {"sections": [{"section_id": "SEC", "heading": "比較"}]}, "exhibit_blocks": {"EX": {"kind": "image", "data": png, "width": 2, "height": 2, "asset_digest": "sha256:" + hashlib.sha256(png).hexdigest(), "legend_rows": [["ordinal", "enterprise_size", "ai_use"], ["1", "小規模", "17.0"], ["2", "大規模", "55.03"]], "provenance": {"citation_sources": [source], "generation_input": {"chart_spec": spec}}}}}

    def render(self, inspection):
        service = object.__new__(PublicationReleaseService)
        service.workspace = Path("unused")
        return service._render(inspection)

    def test_reader_labels_preserve_exact_cells_image_and_research_input(self):
        inspection = self.inspection()
        original = deepcopy(inspection)
        markdown, docx, issues, checks = self.render(inspection)
        self.assertEqual(inspection, original)
        self.assertEqual(issues, [])
        self.assertEqual(checks["render_verification"], "passed")
        text = markdown.decode()
        self.assertIn("図 1", text)
        self.assertNotIn("Citations:", text)
        self.assertNotIn("enterprise_size", text)
        self.assertNotIn("ai_use", text)
        self.assertNotIn("not applicable", text)
        self.assertIn("番号 | 区分 | 値（%）", text)
        self.assertIn("1 | 小規模 | 17.0", text)
        self.assertIn("2 | 大規模 | 55.03", text)
        self.assertNotIn("https://example.org/study — https://example.org/study#sizes", text)
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            self.assertEqual(archive.read("word/media/image-1.png"), original["exhibit_blocks"]["EX"]["data"])
            document = ET.fromstring(archive.read("word/document.xml"))
            image = document.find(f".//{{{W}}}drawing/../..")
            self.assertIsNotNone(image.find(f"{{{W}}}pPr/{{{W}}}keepNext"))
            table = document.find(f".//{{{W}}}tbl")
            self.assertTrue(all(p.find(f"{{{W}}}pPr/{{{W}}}keepNext") is not None for p in table.findall(f".//{{{W}}}p")))
            source_notes = [p for p in document.findall(f".//{{{W}}}p") if p.find(f"{{{W}}}pPr/{{{W}}}pStyle") is not None and p.find(f"{{{W}}}pPr/{{{W}}}pStyle").get(f"{{{W}}}val") == 'SourceCaption']
            self.assertEqual(len(source_notes), 1)
            self.assertIsNotNone(source_notes[0].find(f"{{{W}}}pPr/{{{W}}}keepLines"))

    def test_generic_labels_and_non_url_locators_remain_available(self):
        inspection = self.inspection()
        inspection["publication_profile"]["profile_id"] = "generic"
        inspection["revision"]["sections"][0]["content"] = "Compare [[exhibit:EX]]."
        text = self.render(inspection)[0].decode()
        self.assertIn("Figure 1", text)
        self.assertIn("Citations: [1]", text)
        self.assertIn("enterprise_size", text)
        source = inspection["source_package_document"]["resolved_content"]["research_objects"][0]
        label = PublicationReleaseService._citation_label(source, "page 5", inspection["publication_policy"])
        self.assertIn("https://example.org/study — page 5", label)

    def test_japanese_explanation_notes_keep_meaning_and_exact_png(self):
        inspection = self.inspection()
        exhibit = inspection["source_package_document"]["resolved_content"]["working_material"]["research_exhibits"][0]
        exhibit["title"] = "比較結果・対象・限界"
        exhibit["content"]["value"] = {"request": {"allowed_labels": ["比較結果", "調査対象", "解釈の限界"]}}
        inspection["exhibit_blocks"]["EX"].pop("legend_rows")
        original = deepcopy(inspection)
        markdown, docx, issues, checks = self.render(inspection)
        self.assertEqual(issues, [])
        self.assertEqual(checks["render_verification"], "passed")
        self.assertIn("図に示す内容：比較結果、調査対象、解釈の限界。", markdown.decode())
        self.assertNotIn("Represented research:", markdown.decode())
        self.assertNotIn("Representation reviewed", markdown.decode())
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            self.assertEqual(archive.read("word/media/image-1.png"), original["exhibit_blocks"]["EX"]["data"])
            text = archive.read("word/document.xml").decode()
            self.assertIn("既存の研究内容を整理した図", text)
        self.assertEqual(inspection, original)


if __name__ == "__main__":
    unittest.main()
