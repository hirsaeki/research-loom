"""Exact footer expectations remain selected-layout specific (#621)."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from plugins.application_errors import LocalApplicationError
from plugins.local_application.misco.publication_dialect import MISCO_PUBLICATION_DIALECT
from plugins.local_application.publication.publication_dialect import PublicationDialect
from plugins.local_application.publication.publication_pdf import inspect_pdf

ROOT = Path(__file__).resolve().parents[4]


class Page:
    mediabox = SimpleNamespace(width=595.276, height=841.89)
    rotation = 0

    def __init__(self, footer):
        self.footer = footer

    def extract_text(self, *, visitor_text):
        visitor_text(
            self.footer, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 280, 40], {"/BaseFont": "/Century"}, 10
        )
        return self.footer


class PdfPageNumberPrefixTests(unittest.TestCase):
    def inspect(self, footers, **kwargs):
        reader = SimpleNamespace(is_encrypted=False, pages=[Page(f) for f in footers])
        with patch(
            "plugins.local_application.publication.publication_pdf.PdfReader", return_value=reader
        ):
            return inspect_pdf(
                b"%PDF-synthetic-visitor-fixture",
                page_ranges={"abstract": [1, 1], "body": [2, 3], "appendix": [4, 5]},
                **kwargs,
            )["problems"]

    def test_legacy_numeric_default_remains_exact(self):
        self.assertEqual(self.inspect(["", "1", "2", "1", "2"]), [])
        self.assertEqual(
            self.inspect(["", "1", "2", "付1", "付2"]),
            ["page-number:appendix:4", "page-number:appendix:5"],
        )

    def test_selected_prefix_accepts_each_appendix_ordinal(self):
        self.assertEqual(self.inspect(["", "1", "2", "付1", "付2"], appendix_page_prefix="付"), [])
        self.assertEqual(self.inspect(["", "1", "2", "A-1", "A-2"], appendix_page_prefix="A-"), [])

    def test_wrong_missing_duplicate_and_skipped_prefixes_or_numbers_are_rejected(self):
        for first, second in [
            ("1", "2"),
            ("別1", "別2"),
            ("付付1", "付2"),
            ("付1", "付1"),
            ("付1", "付3"),
            ("付0", "付2"),
            ("付1", "付02"),
            ("", "付2"),
        ]:
            with self.subTest(first=first, second=second):
                self.assertTrue(
                    self.inspect(["", "1", "2", first, second], appendix_page_prefix="付")
                )

    def test_prefix_cannot_relax_body_or_frontmatter_numbering(self):
        self.assertEqual(
            self.inspect(["", "付1", "付2", "付1", "付2"], appendix_page_prefix="付"),
            ["page-number:body:2", "page-number:body:3"],
        )
        self.assertEqual(
            self.inspect(["付1", "1", "2", "付1", "付2"], appendix_page_prefix="付"),
            ["unexpected-footer:1"],
        )

    def test_dialect_reads_pinned_layout_without_version_or_pdf_inference(self):
        self.assertEqual(PublicationDialect().appendix_page_prefix({}), "")
        for version, prefix in [("1.4.0", ""), ("1.5.0", ""), ("1.6.0", "付")]:
            formal = json.loads(
                (
                    ROOT
                    / f"profiles/publication/misco/{version}/resources/publication-formal-spec.json"
                ).read_text(encoding="utf-8")
            )["formal_spec_profile"]
            self.assertEqual(
                MISCO_PUBLICATION_DIALECT.appendix_page_prefix({"formal_spec_profile": formal}),
                prefix,
            )
        with self.assertRaises(LocalApplicationError):
            MISCO_PUBLICATION_DIALECT.appendix_page_prefix(
                {
                    "formal_spec_profile": {
                        "docx_layout": {
                            "misco_appendix_toc": {"helper_sha256": "present-but-prefix-missing"}
                        }
                    }
                }
            )
