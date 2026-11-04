"""Cover contract regression: authored settings are not a final PDF verdict."""

import hashlib
import io
import json
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from plugins.local_application.misco import cover_profile
from plugins.local_application.misco.formal_report import assemble, inspect_formal
from plugins.local_application.publication.publication_docx import W, docx_bytes
from tests.runtime.test_issue456_formal_document import representative_report

ROOT = Path(__file__).resolve().parents[4]


class MiscoCoverProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = ROOT / "profiles/publication/misco/1.5.0"
        self.formal = json.loads(
            (self.profile / "resources/publication-formal-spec.json").read_text(encoding="utf-8")
        )
        self.layout = self.formal["formal_spec_profile"]["docx_layout"]
        self.spec = self.layout["misco_cover"]

    def test_profile_resources_are_pinned_and_preserve_the_historical_source(self):
        manifest = json.loads((self.profile / "profile.json").read_text(encoding="utf-8"))
        for resource in manifest["resources"]:
            self.assertEqual(
                hashlib.sha256(
                    (self.profile / resource["path"]).read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
                resource["sha256"],
            )
        self.assertEqual(manifest["profile_version"], "1.5.0")
        self.assertEqual(
            self.formal["source_archive"]["sha256"],
            "c5cc608e7a90499a46ed929b120c4a4e09111de00ebdecc57d8e3d20dd7d1439",
        )
        self.assertTrue(self.spec["final_pdf_review_required"])

    def test_actual_assembly_uses_profile_hierarchy_and_detects_lost_insets(self):
        report = representative_report()
        report.pop("introduction")
        report["footnotes"] = []
        self.layout["formal_document"] = True
        native = docx_bytes([("title", report["title"]), ("body", "本文を保持。")], self.layout)
        output = assemble(native, report, "M", self.layout)
        self.assertEqual(inspect_formal(output, report, "M", self.layout), [])
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        shapes = document.findall(f".//{{{cover_profile.V}}}shape")
        by_id = {s.get("id"): s for s in shapes}
        identification = by_id["MiscoCover_identification"]
        theme = by_id["MiscoCover_theme"]
        self.assertEqual("".join(identification.itertext()), "三井情報システム協議会(MISCO)報告書")
        self.assertEqual("".join(theme.itertext()), report["title"] + report["subtitle"])
        self.assertEqual(theme.find(".//w:sz", {"w": W}).get(f"{{{W}}}val"), "36")
        self.assertNotIn("番号要確認", "".join(document.itertext()))
        membership = by_id["MiscoCover_membership"]
        textbox = membership.find(f"{{{cover_profile.V}}}textbox")
        self.assertEqual(textbox.get("inset"), "2.5mm,1.3mm,2.5mm,1.3mm")
        textbox.set("inset", "0,0,0,0")
        self.assertIn(
            "cover-profile:MiscoCover_membership",
            cover_profile.inspect_boxes(document, report, self.spec),
        )

    def test_font_regression_and_profile_geometry_are_checked_separately_from_pdf(self):
        report = representative_report()
        document = ET.Element("document")
        document.extend(cover_profile.build_boxes(report, self.spec))
        self.assertEqual(cover_profile.inspect_boxes(document, report, self.spec), [])
        organization = document.find(
            f".//{{{cover_profile.V}}}shape[@id='MiscoCover_organization']"
        )
        organization.find(".//w:rFonts", {"w": W}).set(f"{{{W}}}eastAsia", "ＭＳ Ｐゴシック")
        self.assertIn(
            "cover-profile:MiscoCover_organization",
            cover_profile.inspect_boxes(document, report, self.spec),
        )
        self.assertNotEqual(
            self.spec["boxes"]["issue_date"]["box_top_mm"],
            self.spec["rendered_position_targets_mm"]["issue_date"]["top"],
        )
