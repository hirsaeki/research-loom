"""Regression for a full-manuscript research selection (143 evidence, 60 originals)."""

import unittest

from plugins.local_application import LocalApplicationError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from plugins.local_application.research_package_format import (
    MAX_MATERIALS,
    MAX_OBJECTS,
    MAX_OUTPUT_BYTES,
    MAX_TEXT_BYTES,
    str_list,
)


class ResearchPackageIntegrationBoundsTests(unittest.TestCase):
    def test_full_manuscript_object_selection(self):
        # All evidence, its 60 distinct Sources, and eight recommendations
        # can be selected in one bounded input without dropping references.
        ids = ([f"EVD-{n:04d}" for n in range(143)]
               + [f"SRC-{n:04d}" for n in range(60)]
               + [f"REC-{n:04d}" for n in range(8)])
        with self.assertRaises(LocalApplicationError):
            str_list(ids, "object_ids", 64)  # Prior cap: ablation.
        self.assertEqual(str_list(ids, "object_ids", MAX_OBJECTS), ids)
        self.assertEqual(len(ids), 211)
        self.assertEqual(MAX_OBJECTS, 512)

    def test_full_manuscript_original_budget(self):
        self.assertEqual(MAX_MATERIALS, 128)
        self.assertGreater(MAX_MATERIALS, 60)
        # A collection of 60 moderate-sized renditions can exceed the
        # former 4 MiB aggregate even though every item is below 1 MiB.
        sample_total = 60 * 128 * 1024
        self.assertGreater(sample_total, 4 * 1024 * 1024)
        self.assertLessEqual(sample_total, MAX_TEXT_BYTES)
        self.assertGreater(MAX_OUTPUT_BYTES, MAX_TEXT_BYTES)

    def test_selection_remains_bounded_and_duplicate_safe(self):
        with self.assertRaises(LocalApplicationError) as oversized:
            str_list([f"EVD-{n:04d}" for n in range(MAX_OBJECTS + 1)], "object_ids", MAX_OBJECTS)
        self.assertEqual(oversized.exception.code, "APPLICATION-RESEARCH-PACKAGE-BOUND-001")
        with self.assertRaises(LocalApplicationError) as duplicate:
            str_list(["EVD-0001", "EVD-0001"], "object_ids", MAX_OBJECTS)
        self.assertEqual(duplicate.exception.code, "APPLICATION-RESEARCH-PACKAGE-INPUT-001")

class ResearchPackageBulkAttachmentVerificationTests(ResearchPackageAcceptanceSupport):
    def test_sixty_material_renditions_verify_without_disabling_integrity(self):
        """Use the actual detached verifier with a >4 MiB, 60-body package."""
        from copy import deepcopy
        import json

        from plugins.local_application.research_package_format import (
            digest_bytes, digest_json, verify_export_root, without_digest,
        )
        from plugins.local_application.research_package_service import ResearchPackageService

        facade, case = self._build()
        try:
            root = self.workspace / ".research-loom" / "research-packages" / case["package_id"]
            filename = root / "research-package.json"
            package = json.loads(filename.read_text(encoding="utf-8"))
            prototype = package["resolved_content"]["materials"][0]
            run_id = prototype["run_id"]
            payload = b"Retained source rendition.\n" * 5100

            for index in range(1, 60):
                row = deepcopy(prototype)
                capture_id = f"CAP-SYNTHETIC-{index:03d}"
                row["capture"]["capture_id"] = capture_id
                attachment = f"attachments/materials/{run_id}/{capture_id}.txt"
                row["text_rendition"] = {
                    "encoding": "UTF-8",
                    "byte_length": len(payload),
                    "content_digest": digest_bytes(payload),
                    "attachment_path": attachment,
                }
                package["resolved_content"]["materials"].append(row)
                package["attachments"].append({
                    "path": attachment,
                    "media_type": "text/plain",
                    "byte_length": len(payload),
                    "content_digest": digest_bytes(payload),
                    "source": f"external_material:{run_id}:{capture_id}",
                })
                output = root / attachment
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)

            md = ResearchPackageService(facade)._markdown(package).encode("utf-8")
            (root / "research-package.md").write_bytes(md)
            package["projections"]["markdown"] = {
                "path": "research-package.md",
                "byte_length": len(md),
                "content_digest": digest_bytes(md),
            }
            package["package_digest"] = digest_json(without_digest(package))
            filename.write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

            self.assertEqual(len(package["resolved_content"]["materials"]), 60)
            self.assertGreater(sum(a["byte_length"] for a in package["attachments"]), 4 * 1024 * 1024)
            self.assertEqual(verify_export_root(root)["status"], "VERIFIED")
            # The higher budget must not weaken digest/size validation.
            (root / attachment).write_bytes(payload + b"tampered")
            with self.assertRaises(LocalApplicationError) as tamper:
                verify_export_root(root)
            self.assertEqual(tamper.exception.code, "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001")
        finally:
            facade.close()
