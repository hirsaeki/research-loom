from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path

from core.runtime import canonical_digest
from plugins.local_application.workspace.profile_resolution import resolve_effective_profile_set
from plugins.local_application.workspace.workspace import LocalWorkspaceError

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "docs/acceptance/writer-answer-delivery"


class WriterAnswerDeliveryRecordsTests(unittest.TestCase):
    def test_diagnostic_exports_retain_exact_pins_priorities_and_authority(self):
        record = json.loads((RECORDS / "diagnosis.json").read_text(encoding="utf-8"))
        self.assertFalse(record["actual_research_workspace_verified"])
        self.assertFalse(record["work_host_verified"])
        for row in record["records"]:
            archive = RECORDS / f"diagnosis-{row['version']}.zip"
            self.assertEqual(
                hashlib.sha256(archive.read_bytes()).hexdigest(), record["archives"][archive.name]
            )
            with zipfile.ZipFile(archive) as bundle:
                doc = json.loads(bundle.read("input/writer-input.json"))
                composition = json.loads(bundle.read("composition.json"))
                package = json.loads(bundle.read("package.json"))
            self.assertEqual(doc["input_digest"], row["input_digest"])
            basis = deepcopy(doc)
            basis.pop("input_digest")
            self.assertEqual(canonical_digest(basis), doc["input_digest"])
            self.assertEqual(doc["source"], row["source"])
            self.assertEqual(doc["source"]["composition_digest"], composition["composition_digest"])
            self.assertEqual(doc["source"]["research_package_digest"], package["package_digest"])
            self.assertEqual(doc["source"]["source_epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertTrue(doc["source"]["preview_only"])
            self.assertFalse(doc["source"]["release_eligible"])
            self.assertFalse(any(doc["authority_boundary"].values()))
            for section in doc["sections"]:
                delivered = section["section_input"]
                self.assertEqual(delivered["communication"], row["communication"])
                self.assertEqual(
                    delivered["writer_profile"]["profile_pins"][0]["profile_version"],
                    row["version"],
                )
                self.assertEqual(delivered["writer_profile"]["rule_count"], 127)
                self.assertIn(section["section_input_digest"], row["section_digests"])

    def test_explicit_retained_writer_versions_and_incompatible_publication_request(self):
        config = json.loads(
            (ROOT / "projects/misco-ai-2026/project-config.json").read_text(encoding="utf-8")
        )
        for version in ("1.1.0", "1.4.0"):
            requested = deepcopy(config)
            requested["profile_requests"]["narrative"] = [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": version}
            ]
            requested["profile_requests"]["publication"][0]["version"] = "1.6.0"
            candidates = [
                ROOT / f"profiles/narrative/misco/{version}/profile.json",
                ROOT / "profiles/publication/misco/1.6.0/profile.json",
            ]
            resolved = resolve_effective_profile_set(requested, candidates)
            self.assertEqual(
                {(p["profile_id"], p["profile_version"]) for p in resolved["effective_profiles"]},
                {("misco.writer", version), ("misco.publication", "1.6.0")},
            )
            requested["profile_requests"]["publication"][0]["version"] = "2.0.0"
            with self.assertRaises(LocalWorkspaceError) as raised:
                resolve_effective_profile_set(requested, candidates)
            self.assertEqual(raised.exception.code, "PROFILE-VERSION-001")
