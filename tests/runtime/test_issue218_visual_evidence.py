from __future__ import annotations

import json

from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_format import (
    digest_json,
    without_digest,
)
from plugins.local_application.research_package_service import verify_export_root
import test_research_exhibits as exhibits
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class Issue218VisualEvidenceTests(ResearchPackageAcceptanceSupport):
    def _visual_case(self):
        original = b"\x89PNG\r\n\x1a\nfixture-visual-source"
        facade, case = self._prepare_case(
            original_media_type="image/png",
            original_bytes=original,
        )
        original_ref = f"{case['run_id']}.CAP-1.original"
        payload = exhibits.exhibit_payload(
            rq_id=case["rq_id"],
            title="Selected source figure",
            kind="graph",
            representation="text",
            value="Working note about the selected source figure.",
            source_run_ids=[case["run_id"]],
            source_artifact_refs=[original_ref],
            source_object_ids=[],
        )
        payload["visual_target"] = {
            "source_run_id": case["run_id"],
            "capture_id": "CAP-1",
            "source_artifact_ref": original_ref,
            "locator": {
                "kind": "figure",
                "page": 1,
                "label": "Figure 1",
                "region": {
                    "x": 0.1,
                    "y": 0.2,
                    "width": 0.5,
                    "height": 0.4,
                    "unit": "normalized",
                },
            },
        }
        captured = facade.capture_exhibit(payload)["exhibit"]
        case["build_input"]["exhibit_ids"] = [captured["exhibit_id"]]
        built = facade.build_research_package(case["build_input"])
        case["package_id"] = built["package"]["package_id"]
        case["visual_original"] = original
        return facade, case

    def test_visual_target_round_trips_into_detached_package(self):
        facade, case = self._visual_case()
        out = self.root / "visual-detached"
        try:
            shown = facade.show_research_package(case["package_id"])["package"]
            exhibit = shown["resolved_content"]["working_material"]["research_exhibits"][0]
            visual = exhibit["visual_target"]
            self.assertEqual(visual["target_type"], "source_visual")
            self.assertEqual(visual["locator"]["kind"], "figure")
            self.assertEqual(visual["source_media_type"], "image/png")
            self.assertNotIn("excerpt", visual)
            source_path = visual["source_attachment_path"]
            self.assertTrue(source_path.startswith("attachments/visual/"))
            facade.export_research_package(case["package_id"], out)
        finally:
            facade.close()

        self.assertEqual(verify_export_root(out)["status"], "VERIFIED")
        package = json.loads((out / "research-package.json").read_text(encoding="utf-8"))
        visual = package["resolved_content"]["working_material"]["research_exhibits"][0]["visual_target"]
        self.assertEqual((out / visual["source_attachment_path"]).read_bytes(), case["visual_original"])
        self.assertIn("Source visual:", (out / "research-package.md").read_text(encoding="utf-8"))

    def test_derived_crop_keeps_source_derivation_and_is_detached(self):
        facade, case = self._prepare_case(
            original_media_type="image/png",
            original_bytes=b"\\x89PNG\\r\\n\\x1a\\nsource-for-crop",
        )
        out = self.root / "visual-derived"
        try:
            run = facade._application.execution_store.load_run(case["run_id"])
            source_ref = f"{case['run_id']}.CAP-1.original"
            derived = facade._application.execution_store.put_bytes(
                run,
                role="research_visual.crop",
                media_type="image/png",
                content=b"\\x89PNG\\r\\n\\x1a\\ncropped-region",
                artifact_id="ART-VISUAL-CROP-1",
                provenance={"derivation_type": "crop"},
                parent_artifact_refs=(source_ref,),
            )
            payload = exhibits.exhibit_payload(
                rq_id=case["rq_id"],
                title="Derived source crop",
                kind="graph",
                representation="text",
                value="Working note for the crop.",
                source_run_ids=[case["run_id"]],
                source_artifact_refs=[source_ref, derived.artifact_id],
                source_object_ids=[],
            )
            payload["visual_target"] = {
                "source_run_id": case["run_id"],
                "capture_id": "CAP-1",
                "source_artifact_ref": source_ref,
                "locator": {"kind": "figure", "page": 1, "label": "Figure 1"},
                "derived_artifact_ref": derived.artifact_id,
                "derivation_type": "crop",
            }
            exhibit = facade.capture_exhibit(payload)["exhibit"]
            case["build_input"]["exhibit_ids"] = [exhibit["exhibit_id"]]
            built = facade.build_research_package(case["build_input"])
            package_id = built["package"]["package_id"]
            shown = facade.show_research_package(package_id)["package"]
            visual = shown["resolved_content"]["working_material"]["research_exhibits"][0]["visual_target"]
            self.assertEqual(
                visual["derived_artifact"]["derived_from_artifact_ref"],
                source_ref,
            )
            self.assertEqual(visual["derived_artifact"]["derivation_type"], "crop")
            facade.export_research_package(package_id, out)
        finally:
            facade.close()

        package = json.loads((out / "research-package.json").read_text(encoding="utf-8"))
        visual = package["resolved_content"]["working_material"]["research_exhibits"][0]["visual_target"]
        derived_path = visual["derived_artifact"]["attachment_path"]
        self.assertEqual(
            (out / derived_path).read_bytes(),
            b"\\x89PNG\\r\\n\\x1a\\ncropped-region",
        )
        self.assertEqual(verify_export_root(out)["status"], "VERIFIED")

    def test_derived_visual_type_must_match_persisted_provenance(self):
        facade, case = self._prepare_case(
            original_media_type="image/png",
            original_bytes=b"source-image",
        )
        try:
            run = facade._application.execution_store.load_run(case["run_id"])
            source_ref = f"{case['run_id']}.CAP-1.original"
            derived = facade._application.execution_store.put_bytes(
                run,
                role="research_visual.crop",
                media_type="image/png",
                content=b"derived-image",
                artifact_id="ART-VISUAL-TYPE-MISMATCH",
                provenance={"derivation_type": "crop"},
                parent_artifact_refs=(source_ref,),
            )
            payload = exhibits.exhibit_payload(
                rq_id=case["rq_id"],
                source_run_ids=[case["run_id"]],
                source_artifact_refs=[source_ref, derived.artifact_id],
                source_object_ids=[],
            )
            payload["visual_target"] = {
                "source_run_id": case["run_id"],
                "capture_id": "CAP-1",
                "source_artifact_ref": source_ref,
                "locator": {"kind": "table", "page": 1},
                "derived_artifact_ref": derived.artifact_id,
                "derivation_type": "table_extraction",
            }
            with self.assertRaises(LocalApplicationError) as caught:
                facade.capture_exhibit(payload)
            self.assertEqual(caught.exception.code, "APPLICATION-EXHIBIT-VISUAL-001")
        finally:
            facade.close()

    def test_visual_region_rejects_non_finite_coordinates(self):
        facade, case = self._prepare_case(
            original_media_type="image/png",
            original_bytes=b"source-image",
        )
        try:
            source_ref = f"{case['run_id']}.CAP-1.original"
            payload = exhibits.exhibit_payload(
                rq_id=case["rq_id"],
                source_run_ids=[case["run_id"]],
                source_artifact_refs=[source_ref],
                source_object_ids=[],
            )
            payload["visual_target"] = {
                "source_run_id": case["run_id"],
                "capture_id": "CAP-1",
                "source_artifact_ref": source_ref,
                "locator": {
                    "kind": "region",
                    "page": 1,
                    "region": {
                        "x": float("nan"), "y": 0.1,
                        "width": 0.5, "height": 0.5, "unit": "normalized",
                    },
                },
            }
            with self.assertRaises(LocalApplicationError) as caught:
                facade.capture_exhibit(payload)
            self.assertEqual(caught.exception.code, "APPLICATION-EXHIBIT-VISUAL-001")
        finally:
            facade.close()

    def test_text_capture_cannot_be_promoted_to_visual_target(self):
        facade, case = self._prepare_case()
        try:
            original_ref = f"{case['run_id']}.CAP-1.original"
            payload = exhibits.exhibit_payload(
                rq_id=case["rq_id"],
                source_run_ids=[case["run_id"]],
                source_artifact_refs=[original_ref],
                source_object_ids=[],
            )
            payload["visual_target"] = {
                "source_run_id": case["run_id"],
                "capture_id": "CAP-1",
                "source_artifact_ref": original_ref,
                "locator": {"kind": "figure", "page": 1},
            }
            with self.assertRaises(LocalApplicationError) as caught:
                facade.capture_exhibit(payload)
            self.assertEqual(caught.exception.code, "APPLICATION-EXHIBIT-VISUAL-001")
        finally:
            facade.close()

    def test_package_verification_rejects_visual_digest_binding_tamper(self):
        facade, case = self._visual_case()
        out = self.root / "visual-tamper"
        try:
            facade.export_research_package(case["package_id"], out)
        finally:
            facade.close()

        package_path = out / "research-package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        visual = package["resolved_content"]["working_material"]["research_exhibits"][0]["visual_target"]
        visual["source_digest"] = "sha256:" + "0" * 64
        package["package_digest"] = digest_json(without_digest(package))
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(LocalApplicationError) as caught:
            verify_export_root(out)
        self.assertEqual(caught.exception.code, "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001")

    def test_package_verification_rejects_visual_locator_tamper(self):
        facade, case = self._visual_case()
        out = self.root / "visual-locator-tamper"
        try:
            facade.export_research_package(case["package_id"], out)
        finally:
            facade.close()

        package_path = out / "research-package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        visual = package["resolved_content"]["working_material"]["research_exhibits"][0]["visual_target"]
        visual["locator"]["page"] = 0
        package["package_digest"] = digest_json(without_digest(package))
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(LocalApplicationError) as caught:
            verify_export_root(out)
        self.assertEqual(caught.exception.code, "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001")

    def test_same_visual_source_is_bundled_once_for_multiple_exhibits(self):
        facade, case = self._prepare_case(
            original_media_type="image/png",
            original_bytes=b"shared-source-image",
        )
        try:
            source_ref = f"{case['run_id']}.CAP-1.original"
            exhibit_ids = []
            for title, label in (("Figure use A", "Figure 1"), ("Figure use B", "Figure 1 detail")):
                payload = exhibits.exhibit_payload(
                    rq_id=case["rq_id"],
                    title=title,
                    source_run_ids=[case["run_id"]],
                    source_artifact_refs=[source_ref],
                    source_object_ids=[],
                )
                payload["visual_target"] = {
                    "source_run_id": case["run_id"],
                    "capture_id": "CAP-1",
                    "source_artifact_ref": source_ref,
                    "locator": {"kind": "figure", "page": 1, "label": label},
                }
                exhibit_ids.append(facade.capture_exhibit(payload)["exhibit"]["exhibit_id"])
            case["build_input"]["exhibit_ids"] = exhibit_ids
            built = facade.build_research_package(case["build_input"])
            package = facade.show_research_package(built["package"]["package_id"])["package"]
        finally:
            facade.close()

        visual_attachments = [
            item for item in package["attachments"]
            if item["source"].startswith("visual_source:")
        ]
        self.assertEqual(len(visual_attachments), 1)
        paths = {
            exhibit["visual_target"]["source_attachment_path"]
            for exhibit in package["resolved_content"]["working_material"]["research_exhibits"]
        }
        self.assertEqual(paths, {visual_attachments[0]["path"]})

    def test_ablation_without_visual_target_has_no_citable_visual_attachment(self):
        facade, case = self._prepare_case(
            original_media_type="image/png",
            original_bytes=b"\x89PNG\r\n\x1a\nplain-source",
        )
        try:
            result = facade.build_research_package(case["build_input"])
            package = facade.show_research_package(result["package"]["package_id"])["package"]
            exhibit = package["resolved_content"]["working_material"]["research_exhibits"][0]
            self.assertNotIn("visual_target", exhibit)
            self.assertFalse(
                any(item["path"].startswith("attachments/visual/") for item in package["attachments"])
            )
        finally:
            facade.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
