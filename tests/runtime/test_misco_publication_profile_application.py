from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import rfc8785

from plugins.local_application import LocalApplicationError
from plugins.local_application.profile_resolution import resolve_effective_profile_set
from plugins.local_application.publication_input import inspect_inputs
from plugins.local_application.publication_release_service import _publication_policy
from plugins.local_application.publication_docx import W, WP, docx_bytes
from test_misco_writer_profile_application import MiscoWriterProfileApplicationTests, WRITER_MANIFEST
import test_external_desktop_research_intake as intake

ROOT = Path(__file__).resolve().parents[2]
PUBLICATION_MANIFEST = ROOT / "profiles/publication/misco/profile.json"


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
                {"profile_id": "misco.publication", "profile_type": "publication", "version": "1.2.0"}
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
        response["sections"][0]["content"] += f" [[citation:{scope['source_ref']}]]"
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
        return {
            "schema_version": "0.1.0",
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

    def test_e1_e2_pinned_formal_inputs_apply_but_preview_without_editorial_review_is_not_release_approval(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            built = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
            build = built["build"]
            self.assertEqual(build["publication_profile"]["profile_id"], "misco.publication")
            self.assertEqual(build["publication_profile"]["profile_version"], "1.2.0")
            self.assertEqual(build["verification"]["formal_specification"], "passed")
            self.assertEqual(build["verification"]["editorial_qa"], "warning")
            self.assertEqual(build["publication_policy"]["missing_inputs"], [])
            self.assertFalse(build["publication_policy"]["release_blocked"])
            self.assertEqual(build["publication_policy"]["formal_spec_profile"]["profile_id"], "misco.formal-spec.2024-11-12")
            self.assertEqual(build["publication_policy"]["url_display_profile"]["profile_id"], "misco.url-display.full-url")
            shown = facade.show_publication_preview(build["build_id"])
            self.assertNotIn("Publication diagnostics — release blocked", shown["preview_markdown"])
            with self.assertRaises(LocalApplicationError) as raised:
                facade.request_publication_release(build["build_id"], "human-335")
            self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001")
        finally:
            facade.close()

    def test_e1_e3_pinned_production_formal_spec_changes_actual_docx_and_uses_full_urls_per_section(self):
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
            self.assertEqual(build["publication_policy"]["formal_spec_resource"]["role"], "PUBLICATION_FORMAL_SPEC")
            self.assertEqual(build["publication_policy"]["url_display_resource"]["role"], "PUBLICATION_URL_DISPLAY")

            shown = facade.show_publication_preview(build["build_id"])
            root = Path(shown["output_root"])
            self.assertIn("https://example.test/source-a", shown["preview_markdown"])
            self.assertEqual(shown["preview_markdown"].count("### ＜参考文献＞"), 1)
            second_heading = composition["sections"][1].get("heading") or composition["sections"][1].get("generated_heading") or "SEC-VALIDATE"
            if isinstance(second_heading, dict):
                second_heading = second_heading.get("text")
            self.assertLess(
                shown["preview_markdown"].index("### ＜参考文献＞"),
                shown["preview_markdown"].index(f"## {second_heading}"),
            )
            with zipfile.ZipFile(root / "formal.docx") as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
                body = document.find(f"{{{W}}}body")
                sect = body.find(f"{{{W}}}sectPr")
                pg = sect.find(f"{{{W}}}pgSz")
                mar = sect.find(f"{{{W}}}pgMar")
                grid = sect.find(f"{{{W}}}docGrid")
                self.assertEqual(pg.get(f"{{{W}}}w"), "11906")
                self.assertEqual(pg.get(f"{{{W}}}h"), "16838")
                self.assertEqual(mar.get(f"{{{W}}}top"), "1701")
                self.assertEqual(mar.get(f"{{{W}}}left"), "1418")
                self.assertEqual(mar.get(f"{{{W}}}header"), "851")
                self.assertEqual(mar.get(f"{{{W}}}footer"), "992")
                self.assertEqual(grid.get(f"{{{W}}}linePitch"), "335")
                self.assertEqual(grid.get(f"{{{W}}}charSpace"), "3430")
                styles = archive.read("word/styles.xml").decode("utf-8")
                self.assertIn("ＭＳ 明朝", styles)
                self.assertIn("ＭＳ ゴシック", styles)
                self.assertIn("Century", styles)
                doc_text = "".join(t.text or "" for t in body.findall(f".//{{{W}}}t"))
                self.assertEqual(doc_text.count("＜参考文献＞"), 1)

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

    def test_e2_conflicting_explicit_formal_value_is_rejected_not_silent_last_write_wins(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            inputs = self._application_inputs()
            pinned = json.loads((ROOT / "profiles/publication/misco/resources/publication-formal-spec.json").read_text(encoding="utf-8"))["formal_spec_profile"]
            inputs["formal_spec_profile"] = deepcopy(pinned)
            inputs["formal_spec_profile"]["docx_layout"]["margin_left_twips"] += 1
            with self.assertRaises(LocalApplicationError) as raised:
                facade.build_publication_preview(composition["composition_id"], imported["revision_id"], inputs)
            self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-PROFILE-001")
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

    def test_ablation_formal_layout_changes_output_not_manuscript_text(self):
        layout = json.loads((ROOT / "profiles/publication/misco/resources/publication-formal-spec.json").read_text(encoding="utf-8"))["formal_spec_profile"]["docx_layout"]
        lines = [("title", "同一原稿"), ("body", "本文の意味・数値・出典bindingは不変。")]
        control = docx_bytes(lines)
        applied = docx_bytes(lines, layout)
        self.assertNotEqual(hashlib.sha256(control).digest(), hashlib.sha256(applied).digest())
        with zipfile.ZipFile(io.BytesIO(control)) as left, zipfile.ZipFile(io.BytesIO(applied)) as right:
            left_doc = ET.fromstring(left.read("word/document.xml"))
            right_doc = ET.fromstring(right.read("word/document.xml"))
            left_text = "".join(t.text or "" for t in left_doc.findall(f".//{{{W}}}t"))
            right_text = "".join(t.text or "" for t in right_doc.findall(f".//{{{W}}}t"))
            self.assertEqual(left_text, right_text)
            left_pg = left_doc.find(f".//{{{W}}}pgMar")
            right_pg = right_doc.find(f".//{{{W}}}pgMar")
            self.assertNotEqual(left_pg.get(f"{{{W}}}top"), right_pg.get(f"{{{W}}}top"))


    def test_review_formal_contract_requires_research_group_type_flag(self):
        schema = json.loads((ROOT / "core/packages/writer-publication/publication-application.schema.json").read_text(encoding="utf-8"))
        self.assertIn(
            "research_group_type_required",
            schema["properties"]["formal_spec_profile"]["required"],
        )

    def test_review_section_reference_does_not_reuse_locator_from_another_section(self):
        facade, _case, composition, imported = self._prepared_publication()
        try:
            inspection = inspect_inputs(facade, composition["composition_id"], imported["revision_id"])
            first = inspection["revision"]["sections"][0]["citations"][0]
            source_ref = first["source_ref"]
            first_locator = first["locator_ref"]
            inspection["revision"]["sections"][1]["citations"] = [
                {"source_ref": source_ref, "locator_ref": None}
            ]
            package = inspection["source_package_document"]
            for row in package.get("resolved_content", {}).get("research_objects", []):
                if isinstance(row, dict) and row.get("id") == source_ref:
                    row["canonical_locator"] = "https://example.test/source-a"
            service = facade._publication_release_service()
            profile = service._profile_pin(package)
            inspection["publication_policy"] = _publication_policy(
                package, profile, self._application_inputs()
            )
            markdown, _docx, _issues, _checks = service._render(inspection)
            text = markdown.decode("utf-8")
            second_heading = composition["sections"][1].get("heading") or composition["sections"][1].get("generated_heading") or "SEC-VALIDATE"
            if isinstance(second_heading, dict):
                second_heading = second_heading.get("text")
            second = text[text.index(f"## {second_heading}"):]
            self.assertIn("https://example.test/source-a", second)
            self.assertNotIn(str(first_locator), second)
        finally:
            facade.close()

    def test_review_formal_content_width_bounds_table_and_image(self):
        from test_issue256_native_publication import fixture_png

        formal = json.loads(
            (ROOT / "profiles/publication/misco/resources/publication-formal-spec.json").read_text(encoding="utf-8")
        )["formal_spec_profile"]
        layout = formal["docx_layout"]
        content_width = layout["page_width_twips"] - layout["margin_left_twips"] - layout["margin_right_twips"]
        png = fixture_png()
        table = {
            "ref": "EX-WIDTH-T", "caption": "Table width", "kind": "table",
            "rows": [["a", "b"], ["1", "2"]], "provenance": {},
        }
        image = {
            "ref": "EX-WIDTH-I", "caption": "Figure width", "kind": "image",
            "data": png, "width": 2000, "height": 200,
            "asset_digest": "sha256:" + hashlib.sha256(png).hexdigest(), "provenance": {},
        }
        data = docx_bytes([("exhibit", table), ("exhibit", image)], layout)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            table_width = document.find(f".//{{{W}}}tblW")
            extent = document.find(f".//{{{WP}}}extent")
            self.assertEqual(int(table_width.get(f"{{{W}}}w")), content_width)
            self.assertLessEqual(int(extent.get("cx")), content_width * 635)

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
