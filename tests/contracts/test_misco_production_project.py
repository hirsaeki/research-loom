from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

import rfc8785

from plugins.local_application.profile_resolution import resolve_effective_profile_set

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG = ROOT / "projects/misco-ai-2026/project-config.json"
PROJECT_EPS = ROOT / "projects/misco-ai-2026/effective-profile-set.json"
WRITER = ROOT / "profiles/narrative/misco/profile.json"
PUBLICATION = ROOT / "profiles/publication/misco/profile.json"
CONTINUITY = ROOT / "profiles/research/misco-workspace-continuity/profile.json"
PROBE2_RESOLVE = ROOT / "projects/misco-ai-2026/probe2-profile-resolve.json"


class MiscoProductionProjectContractTests(unittest.TestCase):
    def test_project_config_digest_and_production_resolution_are_exact(self):
        config = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
        payload = dict(config)
        declared = payload.pop("configuration_digest")
        self.assertEqual(declared, "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest())

        expected = json.loads(PROJECT_EPS.read_text(encoding="utf-8"))
        actual = resolve_effective_profile_set(config, [WRITER, PUBLICATION])
        self.assertEqual(actual, expected)
        self.assertEqual(
            [(x["profile_type"], x["profile_id"], x["profile_version"]) for x in actual["effective_profiles"]],
            [("narrative", "misco.writer", "1.1.0"), ("publication", "misco.publication", "1.2.0")],
        )
        self.assertFalse(any(str(x["profile_id"]).startswith("fixture.") for x in actual["effective_profiles"]))

    def test_continuity_profile_is_migration_only_and_does_not_import_research_policy(self):
        profile = json.loads(CONTINUITY.read_text(encoding="utf-8"))
        self.assertEqual(profile["profile_id"], "misco.workspace-continuity.exact-locator")
        self.assertEqual(
            [(x["path"], x["value"]) for x in profile["constraints"]],
            [("evidence.capture.locator_precision", "exact")],
        )
        self.assertFalse(any(str(x["path"]).startswith("research_quality.") for x in profile["constraints"]))
        self.assertEqual(profile.get("extends", []), [])
        self.assertEqual(profile.get("requires", []), [])
        self.assertEqual(profile.get("resources", []), [])

    def test_probe2_operator_request_is_bounded_and_uses_only_production_targets(self):
        request = json.loads(PROBE2_RESOLVE.read_text(encoding="utf-8"))
        self.assertEqual(
            request["profile_manifest_files"],
            [
                "profiles/research/misco-workspace-continuity/profile.json",
                "profiles/narrative/misco/profile.json",
                "profiles/publication/misco/profile.json",
            ],
        )
        targets = [item["to"] for item in request["request_replacements"]]
        self.assertEqual([x["profile_id"] for x in targets], ["misco.writer", "misco.publication"])
        self.assertEqual(
            request["request_additions"],
            [{"profile_id": "misco.workspace-continuity.exact-locator", "profile_type": "research", "version": "1.0.0"}],
        )

    def test_fresh_config_contains_no_legacy_research_state_or_virtual_feedback(self):
        config = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["project_id"], "misco-m3-2026")
        self.assertEqual(config["project"]["title"], "AIの進化とそれがもたらすMISCO企業への影響")
        self.assertEqual(config["research_questions"]["references"], [])
        self.assertEqual(len(config["research_questions"]["seeds"]), 1)
        self.assertEqual(config["research_questions"]["seeds"][0]["seed_id"], "RQ-SEED-MISCO-FRESH-START")
        self.assertIn("not copied from legacy/probe", config["research_questions"]["seeds"][0]["rationale"])
        self.assertEqual(config["research_attention"], [])
        refs = {x["reference_id"]: x for x in config["resource_references"]}
        self.assertEqual(set(refs), {"REF-MISCO-ATTENTION-MAP"})
        self.assertNotIn("project_feedback/virtual_run_feedback", PROJECT_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["profile_requests"]["research"], [])
        self.assertEqual(config["profile_requests"]["organization"], [])
        self.assertEqual(config["profile_requests"]["narrative"], [])
        self.assertEqual(config["profile_requests"]["publication"][0]["profile_id"], "misco.publication")
        for legacy_rq_id in [
            "RQ-2dcc76ea645e41de88ec20a6f0dab2e5",
            "RQ-9d960b47be384c36a430662a21d560eb",
            "RQ-24ed165b540f415db26bea1623950e4d",
            "RQ-6a5f775e739946518eaf6d72dc11aeeb",
            "RQ-0eca3487d70644d0af64935f395e0f86",
        ]:
            self.assertNotIn(legacy_rq_id, PROJECT_CONFIG.read_text(encoding="utf-8"))
        for ref in config["resource_references"]:
            source = ROOT / ref["locator"]
            self.assertTrue(source.is_file())
            self.assertEqual(ref["digest"], "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
