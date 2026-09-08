from __future__ import annotations

import json

from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_format import (
    digest_bytes,
    digest_json,
    verify_export_root,
    without_digest,
)
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class ResearchPackageBodyMetadataReviewTests(ResearchPackageAcceptanceSupport):
    def _verify_mutation_rejected(self, label, mutate):
        facade, case = self._build()
        try:
            output = self.root / f"body-metadata-{label}"
            facade.export_research_package(case["package_id"], output)
        finally:
            facade.close()
        package_path = output / "research-package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        mutate(package)
        package["package_digest"] = digest_json(without_digest(package))
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(LocalApplicationError) as error:
            verify_export_root(output)
        self.assertIn(
            error.exception.code,
            {
                "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
                "APPLICATION-RESEARCH-PACKAGE-SCHEMA-001",
            },
        )

    def test_020_body_metadata_missing_or_null_fails_closed(self):
        cases = (
            ("material-digest-null", "material", "content_digest", "null"),
            ("material-digest-missing", "material", "content_digest", "missing"),
            ("material-size-null", "material", "byte_length", "null"),
            ("material-size-missing", "material", "byte_length", "missing"),
            ("input-digest-null", "input", "content_digest", "null"),
            ("input-digest-missing", "input", "content_digest", "missing"),
            ("input-size-null", "input", "byte_length", "null"),
            ("input-size-missing", "input", "byte_length", "missing"),
        )
        for label, row_kind, field, mode in cases:
            with self.subTest(label=label):
                def mutate(package, row_kind=row_kind, field=field, mode=mode):
                    if row_kind == "material":
                        row = package["resolved_content"]["materials"][0]["text_rendition"]
                    else:
                        row = package["resolved_content"]["working_material"]["project_inputs"][0]["content"]
                    if mode == "null":
                        row[field] = None
                    else:
                        row.pop(field, None)

                self._verify_mutation_rejected(label, mutate)

    def test_020_misbinding_cannot_skip_metadata_comparison(self):
        def mutate(package):
            row = package["resolved_content"]["materials"][0]["text_rendition"]
            row["attachment_path"] = "attachments/profile/narrative-semantics.yaml"
            row["content_digest"] = None
            row["byte_length"] = None

        self._verify_mutation_rejected("material-misbinding-null-metadata", mutate)

    def test_020_zero_byte_body_metadata_is_valid(self):
        facade, case = self._build()
        try:
            output = self.root / "zero-byte-project-input"
            facade.export_research_package(case["package_id"], output)
        finally:
            facade.close()
        package_path = output / "research-package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        content = package["resolved_content"]["working_material"]["project_inputs"][0]["content"]
        attachment_path = content["attachment_path"]
        attachment = next(item for item in package["attachments"] if item["path"] == attachment_path)
        (output / attachment_path).write_bytes(b"")
        empty_digest = digest_bytes(b"")
        content["content_digest"] = empty_digest
        content["byte_length"] = 0
        attachment["content_digest"] = empty_digest
        attachment["byte_length"] = 0
        package["package_digest"] = digest_json(without_digest(package))
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(verify_export_root(output)["status"], "VERIFIED")


if __name__ == "__main__":
    import unittest
    unittest.main()
