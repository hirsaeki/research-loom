"""Synthetic backend controls, never live Host/Human visual QA."""
from copy import deepcopy
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import rfc8785
from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError
from plugins.local_application.generated_explanation import matching_review
from plugins.local_application.publication_exhibits import prepare_exhibits
from plugins.local_application.publication_docx import docx_bytes, verify_native_docx
from plugins.local_application.research_chart import validate_chart_exhibit
from plugins.research_visual_semantics import validate_visual_package_bindings
import test_issue405_research_charts as charts
from test_issue256_native_publication import fixture_png
from test_research_exhibits import state_signature
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import issue80_writer_composition_suite as compositions
import test_issue219_writer_round_trip as writer


class HostChartTests(unittest.TestCase):
    setUp = charts.ChartCaptureTests.setUp

    def request(self):
        return {"package_id": self.package["package_id"], "chart_spec": charts.chart_spec(self.evidence),
                "renderer": {"identity": "unit host renderer", "version": "not exposed", "instruction": "Plot exact selected categories and values, no new semantics."},
                "output_base64": base64.b64encode(fixture_png(2, 2)).decode()}

    def capture(self, request=None):
        with patch.object(self.facade, "show_research_package", return_value={"package": self.package}):
            result = self.facade.capture_chart_exhibit(request or self.request())
        self.assertEqual(result["visual_conformance"], "review_required")
        return self.facade.show_exhibit(result["exhibit"]["exhibit_id"])["exhibit"]

    def review_request(self, candidate, disposition="existing_meaning_only"):
        return {"candidate_id": candidate["exhibit_id"], "disposition": disposition, "semantic_changes": [],
                "reviewer": {"actor_type": "host", "actor_id": "UNIT-SEPARATE-REVIEW"},
                "rationale": "Synthetic attestation, not actual image inspection.",
                "chart_checks": dict.fromkeys(("axes", "series", "ordering", "major_values"), "pass")}

    def review(self, candidate, disposition="existing_meaning_only"):
        result = self.facade.capture_visual_review(self.review_request(candidate, disposition))
        return self.facade.show_exhibit(result["exhibit"]["exhibit_id"])["exhibit"]

    def test_reference_and_host_share_spec_not_pixels_or_authority(self):
        before = state_signature(self.app)
        reference = charts.ChartCaptureTests.capture(self)
        host = self.capture()
        self.assertEqual(reference["content"]["value"]["chart_spec"], host["content"]["value"]["chart_spec"])
        self.assertNotEqual(reference["content"]["value"]["output"], host["content"]["value"]["output"])
        self.assertEqual(host["content"]["value"]["chart_spec_digest"], canonical_digest(charts.chart_spec(self.evidence)))
        self.assertEqual(validate_chart_exhibit(host, [self.evidence]), fixture_png(2, 2))
        self.assertIsNone(matching_review(host, []))
        review = self.review(host)
        validate_visual_package_bindings([host, review], self.package["resolved_content"]["research_objects"])
        self.assertEqual(matching_review(host, [review]), "existing_meaning_only")
        self.assertEqual(before, state_signature(self.app))
        self.assertEqual(self.facade.show_exhibit(reference["exhibit_id"])["exhibit"], reference)

    def test_data_provenance_output_and_legend_tampering_fail_closed(self):
        for mutate in (
            lambda r: r["chart_spec"].update(values=[31, 20, 50]),
            lambda r: r["chart_spec"].update(input_digest="sha256:" + "0" * 64),
            lambda r: r["chart_spec"].update(units={"category": None, "cases": "%"}),
            lambda r: r["chart_spec"].update(row_order=[0, 1, 1]),
            lambda r: r["renderer"].update(identity="research-chart-png/1"),
            lambda r: r["renderer"].update(instruction=""),
            lambda r: r.update(output_base64=base64.b64encode(b"not PNG").decode()),
            lambda r: r.update(output_base64="A" * 1048577),
            lambda r: r.update(generator_identity="self approve"),
            lambda r: r.update(disposition="existing_meaning_only"),
        ):
            request = self.request(); mutate(request)
            with self.assertRaises(LocalApplicationError): self.capture(request)
        host = self.capture()
        for mutate in (
            lambda v: v.update(chart_spec_digest="sha256:" + "0" * 64),
            lambda v: v["legend"]["rows"][0].__setitem__(1, "invented category"),
            lambda v: v["renderer"].update(version="changed"),
            lambda v: v["output"].update(digest="sha256:" + "0" * 64),
        ):
            changed = deepcopy(host); mutate(changed["content"]["value"])
            with self.assertRaises(ValueError): validate_chart_exhibit(changed, [self.evidence])

    def test_review_requires_all_checks_exact_candidate_and_no_capture_self_approval(self):
        host = self.capture()
        for mutate in (
            lambda r: r.pop("chart_checks"),
            lambda r: r["chart_checks"].pop("axes"),
            lambda r: r["chart_checks"].update(major_values="fail"),
            lambda r: r["chart_checks"].update(axes=True),
            lambda r: r["reviewer"].update(actor_type="renderer"),
        ):
            request = self.review_request(host); mutate(request)
            with self.assertRaises(LocalApplicationError): self.facade.capture_visual_review(request)
        review = self.review(host)
        changed = deepcopy(review)
        changed["content"]["value"]["candidate_content_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError): matching_review(host, [changed])
        with self.assertRaises(ValueError): validate_visual_package_bindings([review], [self.evidence])
        with self.assertRaises(LocalApplicationError):
            self.facade.capture_exhibit({"kind": "note", "title": "self approval", "purpose": "approval", "rq_ids": ["RQ-1"], "content": review["content"]})

    def consumer(self, candidate, reviews):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        workspace = Path(temp.name)
        root = workspace / ".research-loom/research-packages/RP-CONSUMER"
        root.mkdir(parents=True)
        candidate = deepcopy(candidate)
        png = base64.b64decode(candidate["content"]["value"]["output"]["bytes_base64"])
        def pin(path, data, media):
            (root / path).write_bytes(data)
            return {"path": path, "media_type": media, "byte_length": len(data), "content_digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        image = pin("chart.png", png, "image/png")
        origin = pin("origin.json", rfc8785.dumps(self.package), "application/json")
        candidate["generated_visual"] = {"visual_class": "data_visualization", "attachment_path": image["path"], "media_type": "image/png", "byte_length": len(png), "digest": image["content_digest"], "generation_context": {"attachment_path": origin["path"], "byte_length": origin["byte_length"], "content_digest": origin["content_digest"]}}
        package = {"package_id": "RP-CONSUMER", "attachments": [image, origin], "resolved_content": {"research_objects": self.package["resolved_content"]["research_objects"], "working_material": {"research_exhibits": [candidate, *reviews]}}}
        inspection = {"source_package_document": package, "revision": {"sections": [{"exhibit_refs": [candidate["exhibit_id"]]}]}}
        return prepare_exhibits(inspection, workspace)[candidate["exhibit_id"]]

    def test_four_way_publication_ablation_and_fail_dominates_later_pass(self):
        before = state_signature(self.app)
        reference = charts.ChartCaptureTests.capture(self)
        self.assertEqual(self.consumer(reference, [])["kind"], "image")
        host = self.capture()
        self.assertEqual(self.consumer(host, [])["code"], "VISUAL_REVIEW_REQUIRED")
        passed = self.review(host)
        block = self.consumer(host, [passed])
        self.assertEqual(block["kind"], "image")
        self.assertEqual(block["legend_rows"][1], ["1", "東京", "30"])
        block.update(ref=host["exhibit_id"], caption="Figure 1. 比較", note="Units: 件; period: 2026")
        lines = [("exhibit", block)]
        docx = docx_bytes(lines)
        self.assertTrue(verify_native_docx(docx, lines))
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            images = [n for n in archive.namelist() if n.startswith("word/media/")]
            self.assertEqual(archive.read(images[0]), fixture_png(2, 2))
        failed = self.review(host, "nonconforming")
        self.assertEqual(self.consumer(host, [failed])["code"], "VISUAL_CONFORMANCE_FAILED")
        self.assertEqual(self.consumer(host, [failed, passed])["code"], "VISUAL_CONFORMANCE_FAILED")
        replacement_request = self.request(); replacement_request["output_base64"] = base64.b64encode(fixture_png(3, 2)).decode()
        replacement = self.capture(replacement_request)
        self.assertIsNone(matching_review(replacement, [passed]))
        self.assertNotEqual(host["content_digest"], replacement["content_digest"])
        self.assertEqual(self.facade.show_exhibit(host["exhibit_id"])["exhibit"], host)
        self.assertEqual(before, state_signature(self.app))


class HostChartRoundTripTests(ResearchPackageAcceptanceSupport):
    def test_actual_package_writer_preview_blocks_pending_and_fail_preserves_history(self):
        facade, case = self._prepare_case()
        self.addCleanup(facade.close)
        app = facade._application
        def apply_fixture(proposal_id):
            pending = facade.submit_action({"action_type": "state.apply_candidate", "payload": {"state_delta_proposal_id": proposal_id}, "actor_id": "UNIT-HUMAN"})
            confirmed = facade.submit_confirmation({"confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"], "actor_id": "UNIT-HUMAN"})
            if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
                request = confirmed["decision_request"]
                facade.resolve_human_decision({"request_id": request["request_id"], "request_digest": request["request_digest"], "disposition": "approve_exact", "actor_id": "UNIT-HUMAN"})
        apply_fixture(case["proposal"]["proposal_id"])
        obj = next(o for o in facade._current_state().effective_objects() if o["kind"] == "evidence")
        qualified = facade.submit_action({"action_type": "research.evidence.qualify", "actor_id": "UNIT-HUMAN", "payload": {
            "evidence_id": obj["id"], "expected_revision": obj["revision"], "expected_digest": canonical_digest(obj),
            "rationale": "Synthetic qualification fixture; not empirical UAT evidence.", "excerpt": charts.chart_evidence()["excerpt"]}})
        apply_fixture(qualified["data"]["state_delta_proposal_id"])
        obj = next(o for o in facade._current_state().effective_objects() if o["id"] == obj["id"])
        before = state_signature(app)
        build_input = {**case["build_input"], "snapshot_id": facade._current_state().current_snapshot["id"],
                       "object_ids": [obj["id"], obj["source_id"]]}
        original = facade.build_research_package(build_input)["package"]
        original = facade.show_research_package(original["package_id"])["package"]
        eid = facade.capture_chart_exhibit({"package_id": original["package_id"], "chart_spec": charts.chart_spec(obj),
              "renderer": {"identity": "unit host", "version": "1", "instruction": "Synthetic exact-output control, not live chart QA."},
              "output_base64": base64.b64encode(fixture_png(2, 2)).decode()})["exhibit"]["exhibit_id"]
        previews = []
        for disposition in (None, "existing_meaning_only", "nonconforming"):
            selected = [eid]
            if disposition:
                review = facade.capture_visual_review({"candidate_id": eid, "disposition": disposition, "semantic_changes": [],
                         "reviewer": {"actor_type": "host", "actor_id": "UNIT-SEPARATE-REVIEW"}, "rationale": "Synthetic backend control, not live QA.",
                         "chart_checks": dict.fromkeys(("axes", "series", "ordering", "major_values"), "pass" if disposition == "existing_meaning_only" else "fail")})
                selected.append(review["exhibit"]["exhibit_id"])
            package = facade.build_research_package({**build_input, "exhibit_ids": selected})["package"]
            from plugins.local_application.research_package_format import verify_export_root
            export = self.root / package["package_id"]
            facade.export_research_package(package["package_id"], export)
            self.assertEqual(verify_export_root(export)["status"], "VERIFIED")
            proposal = compositions.Issue80WriterCompositionTests._proposal(self, {"run_id": "unused", "exhibit_id": eid})
            for section in proposal["sections"]:
                section.pop("material_refs", None); section.pop("gap_refs", None)
                section["narrative_stage_refs"] = ["framing"]
                section["semantic_purpose_refs"] = ["frame_problem"]
            composition = facade.capture_writer_composition(package["package_id"], proposal)["composition"]
            facade.select_writer_composition(composition["composition_id"], 1, composition["composition_digest"])
            output = self.root / composition["composition_id"]
            facade.export_writer_round_trip_input(composition["composition_id"], ["SEC-FRAME", "SEC-VALIDATE"], output)
            response = writer.Issue219WriterRoundTripTests._response(json.loads((output / "writer-input.json").read_text()))
            response["sections"][0]["content"] = "See [[exhibit:" + eid + "]]."
            facade.import_writer_response(response)
            built = facade.build_publication_preview(composition["composition_id"])["build"]
            shown = facade.show_publication_preview(built["build_id"])
            if disposition == "existing_meaning_only":
                self.assertEqual(built["verification"]["render_verification"], "passed")
                with zipfile.ZipFile(Path(shown["output_root"]) / "formal.docx") as archive:
                    images = [n for n in archive.namelist() if n.startswith("word/media/")]
                    self.assertEqual(archive.read(images[0]), fixture_png(2, 2))
            else:
                self.assertEqual(built["verification"]["render_verification"], "failed")
                self.assertIn("VISUAL_REVIEW_REQUIRED" if disposition is None else "VISUAL_CONFORMANCE_FAILED", shown["preview_markdown"])
                with self.assertRaises(LocalApplicationError): facade.request_publication_release(built["build_id"], "unit human")
            previews.append(built)
        for built in previews:
            self.assertEqual(facade.show_publication_preview(built["build_id"])["build"], built)
        self.assertEqual(facade.show_research_package(original["package_id"])["package"], original)
        self.assertEqual(before, state_signature(app))


if __name__ == "__main__":
    unittest.main()
