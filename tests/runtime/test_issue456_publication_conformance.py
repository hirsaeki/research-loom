from __future__ import annotations

import io
import json
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import tests.runtime.test_external_desktop_research_intake as intake
import tests.runtime.test_misco_publication_profile_application as publication_tests
from plugins.local_application import LocalApplicationError
from plugins.local_application.misco.publication_dialect import (
    MISCO_EDITORIAL_QA,
    MISCO_PUBLICATION_DIALECT,
)
from plugins.local_application.publication import publication_release_support
from plugins.local_application.publication.publication_docx import W, docx_bytes, verify_native_docx
from plugins.local_application.publication.publication_release_support import (
    _editorial_status,
    _publication_policy,
    _validate_publication_inputs,
)


class EditorialEvidenceTests(unittest.TestCase):
    def test_unknown_group_save_requirement_and_conditional_permissions(self):
        root = Path(__file__).resolve().parents[2] / "profiles/publication/misco/1.4.0"
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
            policy = _publication_policy(
                package, profile, inputs, config, dialect=MISCO_PUBLICATION_DIALECT
            )
            self.assertIn("INPUT-RESEARCH-GROUP-TYPE", policy["missing_inputs"])
            self.assertEqual(
                policy["host_questions"][0]["question"],
                "今回の報告書はG研究会とM研究会のどちらですか？",
            )
            self.assertIn("INPUT-PERMISSION", policy["missing_inputs"])
            self.assertTrue(policy["review_conditions"]["interview"])
        config = intake.bootstrap_config()
        with self.assertRaises(LocalApplicationError):
            _publication_policy(
                package,
                profile,
                {**inputs, "research_group_type": "G1"},
                config,
                dialect=MISCO_PUBLICATION_DIALECT,
            )
        explicit = _publication_policy(
            package,
            profile,
            {**inputs, "research_group_type": "G"},
            config,
            dialect=MISCO_PUBLICATION_DIALECT,
        )
        self.assertIn("INPUT-RESEARCH-GROUP-TYPE-SAVE", explicit["missing_inputs"])
        self.assertEqual(explicit["host_questions"], [])
        config["publication_metadata"] = {"research_group_type": "G"}
        saved = _publication_policy(
            package, profile, inputs, config, dialect=MISCO_PUBLICATION_DIALECT
        )
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
            _publication_policy(legacy, profile, inputs, config, dialect=MISCO_PUBLICATION_DIALECT)[
                "missing_inputs"
            ],
        )
        with self.assertRaises(LocalApplicationError):
            _publication_policy(
                package,
                profile,
                {**inputs, "research_group_type": "M"},
                config,
                dialect=MISCO_PUBLICATION_DIALECT,
            )

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
                self.assertEqual(
                    _editorial_status(review, overall_check=MISCO_EDITORIAL_QA), expected
                )
        review = {
            "checks": [
                {"check_id": "misco-editorial-qa", "status": "passed"},
                {"check_id": "misco-editorial-qa", "status": "failed"},
            ]
        }
        self.assertEqual(_editorial_status(review, overall_check=MISCO_EDITORIAL_QA), "failed")
        self.assertEqual(
            _editorial_status({"checks": []}, overall_check=MISCO_EDITORIAL_QA), "failed"
        )


class NativeStyleAblationTests(unittest.TestCase):
    def test_single_rule_mutations_are_detected_without_changing_text(self):
        root = Path(__file__).resolve().parents[2]
        layout = json.loads(
            (
                root / "profiles/publication/misco/1.3.0/resources/publication-formal-spec.json"
            ).read_text(encoding="utf-8")
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


class PublicationApplicationCountTests(unittest.TestCase):
    def test_application_arrays_accept_more_items_than_previous_schema_bounds(self):
        payload = {
            "schema_version": "0.1.0",
            "formal_report": {
                "research_kind": "research_theme",
                "title": "Research report",
                "created_month": "2026-10",
                "abstract": "Abstract",
                "activity_record": "Activity",
                "roster": "Roster",
                "appendices": [
                    {"title": f"Appendix {index}", "content": "Content"} for index in range(129)
                ],
                "structure": [
                    {"section_id": f"SECTION-{index}", "level": 1} for index in range(129)
                ],
                "footnotes": [
                    {"section_id": "SECTION-0", "marker": f"N{index}", "text": "Note"}
                    for index in range(257)
                ],
            },
            "permissions": [
                {
                    "source_ref": f"SOURCE-{index}",
                    "publication_allowed": True,
                    "company_disclosure": "allowed",
                    "original_reviewed": True,
                    "approval_ref": "APPROVAL-1",
                }
                for index in range(257)
            ],
            "editorial_review": {
                "reviewer_id": "reviewer-1",
                "reviewed_at": "2026-10-20T12:00:00Z",
                "checks": [
                    {"check_id": f"CHECK-{index}", "status": "passed", "rationale": "Checked"}
                    for index in range(129)
                ],
            },
        }

        normalized = _validate_publication_inputs(payload)

        self.assertEqual(len(normalized["formal_report"]["appendices"]), 129)
        self.assertEqual(len(normalized["formal_report"]["structure"]), 129)
        self.assertEqual(len(normalized["formal_report"]["footnotes"]), 257)
        self.assertEqual(len(normalized["permissions"]), 257)
        self.assertEqual(len(normalized["editorial_review"]["checks"]), 129)

    def test_application_payload_capacity_error_precedes_schema_rejection(self):
        payload = {"schema_version": "0.1.0", "extra": "x" * 65}
        with patch.object(publication_release_support, "MAX_APPLICATION_INPUT_BYTES", 64):
            with self.assertRaises(LocalApplicationError) as error:
                _validate_publication_inputs(payload)

        self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-INPUT-001")
        self.assertIn("16 MiB operation budget", error.exception.message)


if __name__ == "__main__":
    unittest.main()
