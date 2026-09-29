from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import rfc8785

from plugins.local_application import LocalApplicationError
from plugins.local_application.profile_resolution import resolve_effective_profile_set
from plugins.local_application.publication_docx import W
from test_misco_writer_profile_application import MiscoWriterProfileApplicationTests, WRITER_MANIFEST
import test_external_desktop_research_intake as intake

ROOT = Path(__file__).resolve().parents[2]
PUBLICATION_MANIFEST = ROOT / "profiles/publication/misco/profile.json"


def _sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class MiscoPublicationProfileApplicationTests(MiscoWriterProfileApplicationTests):
    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.1.0"}
            ],
            "publication": [
                {"profile_id": "misco.publication", "profile_type": "publication", "version": "1.1.0"}
            ],
        }
        config.pop("configuration_digest", None)
        config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        effective = resolve_effective_profile_set(config, [WRITER_MANIFEST, PUBLICATION_MANIFEST])
        cfg = self.root / "project-config-input.json"
        eps = self.root / "profiles-input.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(json.dumps(effective, ensure_ascii=False), encoding="utf-8")
        return cfg, eps

    def _prepared_publication(self):
        facade, case, composition, input_doc, _output = self._build_round_trip()
        response = self._response(input_doc, response_id="WR-PUB-335")
        scope = input_doc["sections"][0]["citation_scope"][0]
        response["sections"][0]["citations"] = [{
            "source_ref": scope["source_ref"],
            "locator_ref": scope["locators"][0],
        }]
        imported = facade.import_writer_response(response)
        return facade, case, composition, imported

    @staticmethod
    def _approval(request):
        return {
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_release",
            "actor_id": request["human_actor_id"],
        }

    @staticmethod
    def _application_inputs():
        formal_source = "synthetic formal specification for Issue 335 acceptance only"
        url_source = "synthetic URL display approval for Issue 335 acceptance only"
        return {
            "schema_version": "0.1.0",
            "formal_spec_profile": {
                "profile_id": "synthetic.misco.formal-spec",
                "profile_version": "0.0.1",
                "source": {
                    "source_ref": "synthetic-test://formal-spec",
                    "source_digest": _sha_text(formal_source),
                    "approval_ref": "SYNTHETIC_TEST_ONLY/ISSUE-335",
                },
                "docx_layout": {
                    "page_width_twips": 11906,
                    "page_height_twips": 16838,
                    "margin_top_twips": 1200,
                    "margin_right_twips": 1300,
                    "margin_bottom_twips": 1400,
                    "margin_left_twips": 1500,
                    "body_font": "SyntheticBodyFont",
                    "body_size_half_points": 21,
                    "heading_font": "SyntheticHeadingFont",
                    "heading1_size_half_points": 29,
                    "heading2_size_half_points": 23,
                    "title_font": "SyntheticTitleFont",
                    "title_size_half_points": 35,
                    "table_font": "SyntheticTableFont",
                    "table_body_size_half_points": 19,
                    "table_header_size_half_points": 20,
                    "first_line_indent_twips": 420,
                },
                "reference_list_placement": "end_of_document",
                "research_group_type_required": False,
            },
            "url_display_profile": {
                "profile_id": "synthetic.misco.url-display",
                "profile_version": "0.0.1",
                "source": {
                    "source_ref": "synthetic-test://url-display",
                    "source_digest": _sha_text(url_source),
                    "approval_ref": "SYNTHETIC_TEST_ONLY/ISSUE-335",
                },
                "template": "{title} <{url}>",
            },
            "editorial_review": {
                "reviewer_id": "synthetic-human-335",
                "reviewed_at": "2026-09-29T00:00:00Z",
                "checks": [
                    {
                        "check_id": "misco-editorial-qa",
                        "status": "passed",
                        "rationale": "Synthetic acceptance input exercises the review binding only; it is not production approval.",
                    }
                ],
            },
        }

    def test_e1_e2_missing_formal_inputs_are_visible_preview_and_block_release(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            built = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
            build = built["build"]
            self.assertEqual(build["publication_profile"]["profile_id"], "misco.publication")
            self.assertEqual(build["publication_profile"]["profile_version"], "1.1.0")
            self.assertEqual(build["verification"]["formal_specification"], "failed")
            self.assertEqual(build["verification"]["editorial_qa"], "warning")
            self.assertIn("INPUT-FORMAL-SPEC", build["publication_policy"]["missing_inputs"])
            self.assertIn("INPUT-URL-DISPLAY", build["publication_policy"]["missing_inputs"])
            self.assertTrue(build["publication_policy"]["release_blocked"])
            self.assertTrue(any(x["code"] == "PUBLICATION_FORMAL_INPUT_MISSING" for x in build["issues"]))
            shown = facade.show_publication_preview(build["build_id"])
            self.assertIn("Publication diagnostics — release blocked", shown["preview_markdown"])
            with self.assertRaises(LocalApplicationError) as raised:
                facade.request_publication_release(build["build_id"], "human-335")
            self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001")
        finally:
            facade.close()

    def test_e1_e3_explicit_synthetic_formal_input_changes_actual_docx_and_url_display(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            inputs = self._application_inputs()
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"], inputs
            )
            build = built["build"]
            self.assertEqual(build["verification"]["formal_specification"], "passed")
            self.assertEqual(build["verification"]["editorial_qa"], "passed")
            self.assertFalse(build["publication_policy"]["release_blocked"])
            self.assertEqual(len(build["publication_policy"]["rules"]["rule_ids"]), 23)
            self.assertEqual(build["publication_policy"]["rules"]["role"], "PUBLICATION_RULES")
            self.assertEqual(build["publication_policy"]["source_documents"]["role"], "PUBLICATION_SOURCE_DOCUMENTS")

            shown = facade.show_publication_preview(build["build_id"])
            root = Path(shown["output_root"])
            self.assertIn("<https://example.test/source-a#section-1>", shown["preview_markdown"])
            with zipfile.ZipFile(root / "formal.docx") as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
                body = document.find(f"{{{W}}}body")
                sect = body.find(f"{{{W}}}sectPr")
                pg = sect.find(f"{{{W}}}pgSz")
                mar = sect.find(f"{{{W}}}pgMar")
                self.assertEqual(pg.get(f"{{{W}}}w"), "11906")
                self.assertEqual(pg.get(f"{{{W}}}h"), "16838")
                self.assertEqual(mar.get(f"{{{W}}}left"), "1500")
                styles = archive.read("word/styles.xml").decode("utf-8")
                self.assertIn("SyntheticBodyFont", styles)
                self.assertIn("SyntheticHeadingFont", styles)

            request = facade.request_publication_release(build["build_id"], "human-335")["decision_request"]
            self.assertEqual(
                request["publication_policy_digest"],
                "sha256:" + hashlib.sha256(
                    json.dumps(build["publication_policy"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            )
            self.assertIn("delivered Publication editorial/formal rules", request["required_human_review"])
            released = facade.release_publication(build["build_id"], self._approval(request))
            self.assertEqual(released["status"], "RELEASED")
            self.assertEqual(released["release"]["publication_policy_digest"], request["publication_policy_digest"])
        finally:
            facade.close()

    def test_e2_unsupported_formal_value_is_diagnostic_not_silent_last_write_wins(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            inputs = self._application_inputs()
            inputs["formal_spec_profile"]["reference_list_placement"] = "before_appendices"
            built = facade.build_publication_preview(composition["composition_id"], imported["revision_id"], inputs)
            self.assertEqual(built["build"]["verification"]["formal_specification"], "failed")
            self.assertTrue(any(x["code"] == "PUBLICATION_FORMAL_VALUE_UNSUPPORTED" for x in built["build"]["issues"]))
            with self.assertRaises(LocalApplicationError):
                facade.request_publication_release(built["build"]["build_id"], "human-335")
        finally:
            facade.close()

    def test_e5_editorial_qa_unevaluated_never_becomes_release_approval(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            inputs = self._application_inputs()
            inputs["editorial_review"]["checks"][0]["status"] = "unevaluated"
            built = facade.build_publication_preview(composition["composition_id"], imported["revision_id"], inputs)
            self.assertEqual(built["build"]["verification"]["editorial_qa"], "warning")
            with self.assertRaises(LocalApplicationError) as raised:
                facade.request_publication_release(built["build"]["build_id"], "human-335")
            self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001")
        finally:
            facade.close()

    def test_ablation_same_manuscript_without_formal_input_changes_diagnostic_and_build_identity(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            blocked = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
            supplied = facade.build_publication_preview(composition["composition_id"], imported["revision_id"], self._application_inputs())
            self.assertNotEqual(blocked["build"]["build_id"], supplied["build"]["build_id"])
            self.assertEqual(blocked["build"]["verification"]["formal_specification"], "failed")
            self.assertEqual(supplied["build"]["verification"]["formal_specification"], "passed")
            self.assertEqual(
                blocked["build"]["source_manuscript"]["revision_digest"],
                supplied["build"]["source_manuscript"]["revision_digest"],
            )
        finally:
            facade.close()

    def test_e3_table_caption_above_and_figure_caption_below_in_native_docx(self):
        import io
        from plugins.local_application.publication_docx import docx_bytes
        from test_issue256_native_publication import fixture_png, A

        table = {
            "ref": "EX-T",
            "caption": "Table 1. Values",
            "kind": "table",
            "rows": [["x"], ["1"]],
            "provenance": {},
        }
        png = fixture_png()
        image = {
            "ref": "EX-I",
            "caption": "Figure 1. Bars",
            "kind": "image",
            "data": png,
            "width": 320,
            "height": 120,
            "asset_digest": "sha256:" + hashlib.sha256(png).hexdigest(),
            "provenance": {},
        }
        data = docx_bytes([("exhibit", table), ("exhibit", image)])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            body = document.find(f"{{{W}}}body")
            children = [node for node in body if node.tag != f"{{{W}}}sectPr"]
            table_caption = next(i for i, node in enumerate(children) if "Table 1. Values" in "".join(t.text or "" for t in node.findall(f".//{{{W}}}t")))
            table_block = next(i for i, node in enumerate(children) if node.tag == f"{{{W}}}tbl")
            figure_block = next(i for i, node in enumerate(children) if node.find(f".//{{{A}}}blip") is not None)
            figure_caption = next(i for i, node in enumerate(children) if "Figure 1. Bars" in "".join(t.text or "" for t in node.findall(f".//{{{W}}}t")))
            self.assertLess(table_caption, table_block)
            self.assertLess(figure_block, figure_caption)
