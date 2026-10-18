from __future__ import annotations

import io
import json
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfWriter

import tests.runtime.test_external_desktop_research_intake as intake
from plugins.local_application import LocalApplicationError
from plugins.local_application.publication.publication_docx import W, docx_bytes
from plugins.local_application.publication.publication_formal_report import (
    assemble,
    inspect_formal,
    outline,
)
from plugins.local_application.publication.publication_pdf import coverage_review, inspect_pdf
from plugins.local_application.publication.publication_release_support import (
    _validate_publication_inputs,
)
from plugins.local_application.workspace.profile_advancement import _validate_target_project_delta
from plugins.local_application.workspace.profile_resolution import target_project_config

ROOT = Path(__file__).resolve().parents[2]


def representative_report():
    return {
        "research_kind": "research_theme",
        "title": "情報システムの検証報告書",
        "subtitle": "数値と資料の対応を確かめる",
        "created_month": "2026-10",
        "abstract": "経営への提言\n\n段階的に検証を進める。",
        "introduction": "本研究会の活動の目的を説明する。",
        "activity_record": "2026年10月 検証会議",
        "roster": "主査 検証太郎\n担当事務局 検証花子",
        "appendices": [{"title": "調査資料", "content": "付録の検証資料。"}],
        "structure": [
            {"section_id": "s1", "level": 1},
            {"section_id": "s2", "level": 2},
            {"section_id": "s3", "level": 3},
            {"section_id": "s4", "level": 4},
            {"section_id": "s5", "level": 5},
            {"section_id": "s6", "level": 6},
            {"section_id": "s7", "level": 7},
            {"section_id": "s8", "level": 2},
            {"section_id": "s9", "level": 1},
            {"section_id": "s10", "level": 2},
        ],
        "footnotes": [{"section_id": "s2", "marker": "{{note-1}}", "text": "定義の補足説明。"}],
    }


class FormalDocumentTests(unittest.TestCase):
    def test_pdf_part_ranges_are_bound_to_exported_bookmarks(self):
        pdf = PdfWriter()
        for _ in range(3):
            pdf.add_blank_page(width=595.276, height=841.89)
        pdf.add_outline_item("RL_cover", 0)
        stream = io.BytesIO()
        pdf.write(stream)
        ranges = {"cover": [1, 1], "abstract": [1, 1], "body": [2, 2], "appendix": [3, 3]}
        result = inspect_pdf(stream.getvalue(), page_ranges=ranges, expected_parts=["cover"])
        self.assertNotIn("page-bookmark-binding:cover", result["problems"])
        ranges["cover"] = [2, 2]
        self.assertIn(
            "page-bookmark-binding:cover",
            inspect_pdf(stream.getvalue(), page_ranges=ranges, expected_parts=["cover"])[
                "problems"
            ],
        )

    def test_g_m_native_outer_parts_notes_and_single_clause_ablations(self):
        report = representative_report()
        layout = json.loads(
            (
                ROOT / "profiles/publication/misco-v1.4/resources/publication-formal-spec.json"
            ).read_text(encoding="utf-8")
        )["formal_spec_profile"]["docx_layout"]
        layout["formal_document"] = True
        structure = outline(report["structure"], [row["section_id"] for row in report["structure"]])
        self.assertEqual(
            [
                structure[s]["label"]
                for s in ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"]
            ],
            ["第１章", "１－１", "（１）", "①", "ａ．", "ⅰ．", "・", "１－２", "第２章", "２－１"],
        )
        lines = [("title", report["title"])]
        for row in report["structure"]:
            entry = structure[row["section_id"]]
            lines.append(("heading" + str(entry["level"]), entry["label"] + "　検証事項"))
            lines.append(
                (
                    "body",
                    "固定本文"
                    + ("{{note-1}}" if row["section_id"] == "s2" else "")
                    + "。数値123を保持する。",
                )
            )
        native = docx_bytes(lines, layout)
        for group in ["G", "M"]:
            with self.subTest(group=group):
                candidate = deepcopy(report)
                if group == "M":
                    candidate.pop("introduction")
                output = assemble(native, candidate, group, layout)
                self.assertEqual(inspect_formal(output, candidate, group, layout), [])
                with zipfile.ZipFile(io.BytesIO(output)) as archive:
                    parts = {name: archive.read(name) for name in archive.namelist()}
                document = ET.fromstring(parts["word/document.xml"])
                for grid in document.findall(".//w:sectPr/w:docGrid", {"w": W}):
                    self.assertEqual(grid.get(f"{{{W}}}linePitch"), "342")
                    self.assertEqual(grid.get(f"{{{W}}}charSpace"), "3430")
                labels = [
                    node.get("{urn:research-loom:publication}part")
                    for node in document.findall(".//w:sectPr", {"w": W})
                ]
                self.assertEqual("introduction" in labels, group == "G")
                self.assertIn("word/footnotes.xml", parts)
                self.assertEqual(len(document.findall(".//w:footnoteReference", {"w": W})), 1)
                for part, path, attribute in [
                    ("word/document.xml", ".//w:sectPr/w:pgNumType", "start"),
                    ("word/document.xml", ".//w:sectPr/w:footnotePr/w:numRestart", "val"),
                    ("word/document.xml", ".//w:sectPr/w:docGrid", "linePitch"),
                    ("word/document.xml", ".//w:sectPr/w:docGrid", "charSpace"),
                    (
                        "word/styles.xml",
                        './/w:style[@w:styleId="FormalFootnote"]/w:rPr/w:sz',
                        "val",
                    ),
                    ("word/styles.xml", './/w:style[@w:styleId="FormalBody6"]/w:pPr/w:ind', "left"),
                    ("word/styles.xml", './/w:style[@w:styleId="TOC2"]/w:pPr/w:ind', "left"),
                    (
                        "word/styles.xml",
                        './/w:style[@w:styleId="SourceCaption"]/w:rPr/w:rFonts',
                        "eastAsia",
                    ),
                ]:
                    mutated = dict(parts)
                    tree = ET.fromstring(mutated[part])
                    tree.find(path, {"w": W}).set(f"{{{W}}}{attribute}", "9")
                    mutated[part] = ET.tostring(tree)
                    out = io.BytesIO()
                    with zipfile.ZipFile(out, "w") as archive:
                        for name, payload in mutated.items():
                            archive.writestr(name, payload)
                    self.assertTrue(inspect_formal(out.getvalue(), candidate, group, layout))
        wrong_note = deepcopy(report)
        wrong_note["footnotes"][0]["section_id"] = "s3"
        with self.assertRaises(LocalApplicationError):
            assemble(native, wrong_note, "G", layout)
        commissioned = deepcopy(report)
        commissioned.update(
            {
                "research_kind": "commissioned",
                "department": "検証部会",
                "committee": "検証委員会",
                "chair": "検証太郎",
                "report_number": "TEST-456",
            }
        )
        self.assertEqual(
            inspect_formal(assemble(native, commissioned, "M", layout), commissioned, "M", layout),
            [],
        )
        historical_layout = {**layout, "doc_grid_line_pitch_twips": 335}
        historical_native = docx_bytes(lines, historical_layout)
        historical_document = assemble(historical_native, report, "G", historical_layout)
        self.assertEqual(inspect_formal(historical_document, report, "G", historical_layout), [])
        self.assertTrue(inspect_formal(historical_document, report, "G", layout))

    def test_parent_skips_and_unknown_groups_are_rejected(self):
        with self.assertRaises(LocalApplicationError):
            outline([{"section_id": "s", "level": 2}], ["s"])
        for value in [None, "", " ", "\t  "]:
            self.assertEqual(
                _validate_publication_inputs(
                    {"schema_version": "0.1.0", "research_group_type": value}
                )["research_group_type"],
                value,
            )
        self.assertEqual(
            _validate_publication_inputs(
                {"schema_version": "0.1.0", "research_group_type": "other-profile-group"}
            )["research_group_type"],
            "other-profile-group",
        )

    def test_metadata_update_is_small_versioned_and_preserves_research_guards(self):
        current = intake.bootstrap_config()
        target = target_project_config(
            current, [], publication_metadata={"research_group_type": "G"}
        )
        _validate_target_project_delta(current, target)
        self.assertNotEqual(current["configuration_digest"], target["configuration_digest"])
        self.assertEqual(target["publication_metadata"], {"research_group_type": "G"})
        for field in [
            "project",
            "scope",
            "research_questions",
            "research_attention",
            "project_constraints",
            "profile_requests",
        ]:
            self.assertEqual(target[field], current[field])
        self.assertEqual(
            target_project_config(target, [], publication_metadata={"research_group_type": "G"}),
            target,
        )
        corrupted = deepcopy(target)
        corrupted["project"]["title"] = "Unrelated change"
        with self.assertRaises(Exception):
            _validate_target_project_delta(current, corrupted)

    def test_coverage_requires_every_applicable_clause_and_exact_pdf_pages(self):
        coverage = json.loads(
            (
                ROOT / "profiles/publication/misco-v1.4/resources/publication-coverage.json"
            ).read_text(encoding="utf-8")
        )
        digest = "sha256:" + "a" * 64
        policy = {
            "formal_report": representative_report(),
            "review_conditions": {"interview": False, "company_information": False},
        }
        review = {
            "pdf_digest": digest,
            "reviewer_id": "synthetic-reviewer",
            "reviewed_at": "2026-10-13T00:00:00Z",
            "checks": [
                {
                    "check_id": item["id"],
                    "status": "passed",
                    "rationale": "Synthetic exact-output acceptance only.",
                }
                for item in coverage["items"]
            ],
            "pages": [{"page": 1, "status": "passed", "rationale": "Synthetic fixture page."}],
        }
        for id_ in [
            "misco-editorial-qa",
            "final-pdf-all-pages",
            "final-pdf-toc",
            "final-pdf-footnotes",
            "final-pdf-parity",
            "final-pdf-cover",
        ]:
            review["checks"].append(
                {"check_id": id_, "status": "passed", "rationale": "Synthetic fixture check."}
            )
        self.assertEqual(coverage_review(coverage, policy, review, digest, 1)["problems"], [])
        self.assertIn(
            "unrecorded-should-deviation:misco-body-length",
            coverage_review(coverage, policy, review, digest, 1, page_ranges={"body": [10, 13]})[
                "problems"
            ],
        )
        deviation = deepcopy(review)
        next(row for row in deviation["checks"] if row["check_id"] == "misco-body-length").update(
            status="warning", rationale="Short synthetic report for rendering acceptance."
        )
        self.assertEqual(
            coverage_review(coverage, policy, deviation, digest, 1, page_ranges={"body": [10, 13]})[
                "problems"
            ],
            [],
        )
        presenting = deepcopy(policy)
        presenting["formal_report"]["presentation_required"] = True
        self.assertIn(
            "presentation-review-binding",
            coverage_review(coverage, presenting, review, digest, 1)["problems"],
        )
        slides = deepcopy(review)
        slides["presentation_review"] = {
            "artifact_digest": digest,
            "artifact_reference": "synthetic-slides.pptx",
            "software_version": "PowerPoint 16.0",
            "slide_count": 2,
            "slides": [
                {
                    "slide": i,
                    "status": "passed",
                    "citations_required": True,
                    "citations": ["Synthetic source, publisher, 2026, https://example.test/source"],
                    "rationale": "Source visible on this specific slide.",
                }
                for i in [1, 2]
            ],
        }
        self.assertEqual(coverage_review(coverage, presenting, slides, digest, 1)["problems"], [])

        class NonIterableSlides(list):
            def __iter__(self):
                raise AssertionError("Invalid slide counts must be rejected before iteration")

        oversized = deepcopy(slides)
        oversized["presentation_review"]["slides"] = NonIterableSlides([None] * 257)
        self.assertIn(
            "presentation-per-slide-citations",
            coverage_review(coverage, presenting, oversized, digest, 1)["problems"],
        )
        mismatched = deepcopy(slides)
        mismatched["presentation_review"]["slides"] = NonIterableSlides([None])
        self.assertIn(
            "presentation-per-slide-citations",
            coverage_review(coverage, presenting, mismatched, digest, 1)["problems"],
        )
        slides["presentation_review"]["slides"][0]["citations"] = []
        self.assertIn(
            "presentation-per-slide-citations",
            coverage_review(coverage, presenting, slides, digest, 1)["problems"],
        )
        for id_ in ["misco-abstract", "manual-bibliography", "misco-editorial-qa"]:
            broken = deepcopy(review)
            next(row for row in broken["checks"] if row["check_id"] == id_)["status"] = (
                "not_applicable"
            )
            self.assertIn(
                "required-check:" + id_,
                coverage_review(coverage, policy, broken, digest, 1)["problems"],
            )
        broken = deepcopy(review)
        broken["pdf_digest"] = "sha256:" + "b" * 64
        broken["pages"] = []
        problems = coverage_review(coverage, policy, broken, digest, 1)["problems"]
        self.assertIn("review-output-binding", problems)
        self.assertIn("all-page-review-incomplete", problems)


if __name__ == "__main__":
    unittest.main()
