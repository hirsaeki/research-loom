from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
import zipfile
from xml.etree import ElementTree as ET

from plugins.local_application import LocalApplicationError
from plugins.local_application.publication_docx import W, docx_bytes, verify_native_docx
from plugins.local_application.publication_release_service import (
    _editorial_status,
    _publication_policy,
)
import test_external_desktop_research_intake as intake
import test_misco_publication_profile_application as publication_tests


class EditorialEvidenceTests(unittest.TestCase):
    def test_unknown_group_save_requirement_and_conditional_permissions(self):
        root = Path(__file__).resolve().parents[2] / "profiles/publication/misco-v1.4"
        manifest = json.loads((root / "profile.json").read_text(encoding="utf-8"))
        profile = {"profile_id": "misco.publication", "profile_version": "1.4.0"}
        package = {
            "effective_profile_set": {
                "effective_resources": [
                    {
                        **row,
                        "content": (root / row["path"]).read_text(encoding="utf-8"),
                        "provenance": [{**profile, "profile_type": "publication"}],
                    }
                    for row in manifest["resources"]
                ]
            },
            "resolved_content": {
                "research_objects": [
                    {
                        "id": "SRC-INTERVIEW",
                        "kind": "source",
                        "access_classification": "public",
                        "source_type": "interview",
                    }
                ]
            },
        }
        inputs = {
            "schema_version": "0.1.0",
            "document_mode": "formal_report",
            "formal_report": {"research_kind": "research_theme"},
        }
        for unknown in [None, "", "  ", "\t"]:
            config = intake.bootstrap_config()
            config["publication_metadata"] = {"research_group_type": unknown}
            policy = _publication_policy(package, profile, inputs, config)
            self.assertIn("INPUT-RESEARCH-GROUP-TYPE", policy["missing_inputs"])
            self.assertEqual(
                policy["host_questions"][0]["question"],
                "今回の報告書はG研究会とM研究会のどちらですか？",
            )
            self.assertIn("INPUT-PERMISSION", policy["missing_inputs"])
            self.assertTrue(policy["review_conditions"]["interview"])
        config = intake.bootstrap_config()
        with self.assertRaises(LocalApplicationError):
            _publication_policy(package, profile, {**inputs, "research_group_type": "G1"}, config)
        explicit = _publication_policy(
            package, profile, {**inputs, "research_group_type": "G"}, config
        )
        self.assertIn("INPUT-RESEARCH-GROUP-TYPE-SAVE", explicit["missing_inputs"])
        self.assertEqual(explicit["host_questions"], [])
        config["publication_metadata"] = {"research_group_type": "G"}
        saved = _publication_policy(package, profile, inputs, config)
        self.assertEqual(saved["research_group_type"], "G")
        self.assertNotIn("INPUT-RESEARCH-GROUP-TYPE", saved["missing_inputs"])
        self.assertEqual(saved["host_questions"], [])
        other = _publication_policy(
            {"resolved_content": {"research_objects": []}},
            {"profile_id": "other.publication"},
            {"research_group_type": "other-profile-group"},
            config,
        )
        self.assertEqual(other["research_group_type"], "other-profile-group")
        self.assertEqual(other["missing_inputs"], [])
        legacy = deepcopy(package)
        legacy["effective_profile_set"]["effective_resources"] = [
            row
            for row in legacy["effective_profile_set"]["effective_resources"]
            if row["role"] != "PUBLICATION_COVERAGE"
        ]
        self.assertIn(
            "INPUT-FORMAL-COVERAGE",
            _publication_policy(legacy, profile, inputs, config)["missing_inputs"],
        )
        with self.assertRaises(LocalApplicationError):
            _publication_policy(package, profile, {**inputs, "research_group_type": "M"}, config)

    def test_aggregate_review_preserves_non_pass_and_rejects_duplicates(self):
        for status, expected in [
            ("passed", "passed"),
            ("failed", "failed"),
            ("unevaluated", "warning"),
            ("warning", "warning"),
            ("not_applicable", "failed"),
        ]:
            with self.subTest(status=status):
                review = {"checks": [{"check_id": "misco-editorial-qa", "status": status}]}
                self.assertEqual(_editorial_status(review, misco=True), expected)
        review = {
            "checks": [
                {"check_id": "misco-editorial-qa", "status": "passed"},
                {"check_id": "misco-editorial-qa", "status": "failed"},
            ]
        }
        self.assertEqual(_editorial_status(review, misco=True), "failed")
        self.assertEqual(_editorial_status({"checks": []}, misco=True), "failed")


class NativeStyleAblationTests(unittest.TestCase):
    def test_single_rule_mutations_are_detected_without_changing_text(self):
        root = Path(__file__).resolve().parents[2]
        layout = json.loads(
            (root / "profiles/publication/misco/resources/publication-formal-spec.json").read_text(
                encoding="utf-8"
            )
        )["formal_spec_profile"]["docx_layout"]
        lines = [
            ("title", "日本語報告書"),
            ("heading", "第1章 検証"),
            ("body", "本文の意味と数値123を保持する。"),
            ("reference", "著者、資料、出版元、2026年。"),
        ]
        original = docx_bytes(lines, layout)
        self.assertTrue(verify_native_docx(original, lines, layout))
        mutations = [
            (
                "word/styles.xml",
                './/w:style[@w:styleId="Normal"]/w:rPr/w:rFonts',
                "eastAsia",
                "Arial",
            ),
            ("word/styles.xml", './/w:style[@w:styleId="Normal"]/w:rPr/w:sz', "val", "20"),
            ("word/styles.xml", './/w:style[@w:styleId="Heading1"]/w:rPr/w:sz', "val", "22"),
            ("word/document.xml", ".//w:docGrid", "type", None),
            ("word/document.xml", ".//w:pPr/w:ind", "firstLine", None),
            ("word/document.xml", ".//w:pPr/w:pStyle", "val", "Normal"),
        ]
        for part, path, attribute, replacement in mutations:
            with self.subTest(part=part, path=path, attribute=attribute):
                with zipfile.ZipFile(io.BytesIO(original)) as archive:
                    parts = {name: archive.read(name) for name in archive.namelist()}
                xml = ET.fromstring(parts[part])
                node = xml.find(path, {"w": W})
                self.assertIsNotNone(node)
                if replacement is None:
                    node.attrib.pop(f"{{{W}}}{attribute}")
                else:
                    node.set(f"{{{W}}}{attribute}", replacement)
                parts[part] = ET.tostring(xml)
                modified = io.BytesIO()
                with zipfile.ZipFile(modified, "w") as archive:
                    for name, payload in parts.items():
                        archive.writestr(name, payload)
                self.assertFalse(verify_native_docx(modified.getvalue(), lines, layout))


class PublicEditorialRegressionTests(publication_tests.MiscoPublicationProfileApplicationTests):
    def test_not_applicable_aggregate_keeps_preview_but_blocks_release_request(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            inputs = deepcopy(self._application_inputs())
            inputs["editorial_review"]["checks"][0]["status"] = "not_applicable"
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"], inputs
            )
            build = built["build"]
            self.assertEqual(build["verification"]["editorial_qa"], "failed")
            self.assertTrue(facade.show_publication_preview(build["build_id"])["preview_markdown"])
            with self.assertRaises(LocalApplicationError) as raised:
                facade.request_publication_release(build["build_id"], "human-456")
            self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001")
        finally:
            facade.close()


if __name__ == "__main__":
    unittest.main()
