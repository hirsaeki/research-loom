from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "docs/migration/misco-profile-migration-ledger"
LEDGER_PATH = LEDGER_DIR / "index.json"
PACK = ROOT / "research-profile/publication/authority/MISCO_Publication_Clean_Source_Pack_v1.0.2_HUMAN_APPROVED"
LAYER_A = PACK / "Layer_A_CLEAN_RUNTIME_SOURCE_PACK"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _h2_ids(path: Path, prefix_pattern: str) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(rf"^##\s+({prefix_pattern}[^\s—]*)", text, flags=re.MULTILINE))


def _coverage_errors(ledger: dict) -> list[str]:
    errors: list[str] = []
    rule_ids = [item["rule_id"] for item in ledger["rules"]]
    if len(rule_ids) != len(set(rule_ids)):
        errors.append("duplicate rule_id")

    indexed_sources = {item["source_id"] for item in ledger["sources"]}
    for rule in ledger["rules"]:
        if rule["source_id"] not in indexed_sources:
            errors.append(f"dangling source: {rule['rule_id']}")
        cls = ledger["migration_classes"].get(rule["migration_class"])
        if cls is None:
            errors.append(f"unknown migration class: {rule['rule_id']}")
        elif cls["state"] != "already_preserved" and not cls.get("target_issue"):
            errors.append(f"missing target issue: {rule['rule_id']}")
        if cls is not None and not cls.get("application_boundary"):
            errors.append(f"missing application boundary: {rule['rule_id']}")

    required = {item["runtime_rule_id"] for item in json.loads((LAYER_A / "01_PUBLICATION_STYLE_CONTRACT.json").read_text(encoding="utf-8"))}
    missing = required - set(rule_ids)
    if missing:
        errors.append("missing runtime rules: " + ",".join(sorted(missing)))
    return errors


class MiscoProfileMigrationLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        source_columns = cls.ledger["source_columns"]
        cls.ledger["sources"] = [dict(zip(source_columns, row)) for row in cls.ledger["sources"]]
        rule_columns = cls.ledger["rule_columns"]
        rules = []
        for spec in cls.ledger["rule_files"].values():
            payload = json.loads((LEDGER_DIR / spec["path"]).read_text(encoding="utf-8"))
            rules.extend(dict(zip(rule_columns, row)) for row in payload["rules"])
        cls.ledger["rules"] = rules
        cls.rules = {item["rule_id"]: item for item in rules}
        cls.sources = {item["source_id"]: item for item in cls.ledger["sources"]}

    def test_ledger_has_no_internal_coverage_errors(self):
        self.assertEqual([], _coverage_errors(self.ledger))

    def test_all_pinned_source_bytes_match(self):
        for item in self.ledger["sources"]:
            path = ROOT / self.ledger.get("source_roots", {}).get(item.get("root", "current"), "") / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual("sha256:" + item["sha256"], _sha256(path), item["path"])

    def test_source_pack_manifest_is_fully_inventoried(self):
        manifest = json.loads((PACK / "MANIFEST.json").read_text(encoding="utf-8"))
        inventoried = {item["path"] for item in self.ledger["sources"]}
        for entry in manifest:
            rel = "research-profile/publication/authority/MISCO_Publication_Clean_Source_Pack_v1.0.2_HUMAN_APPROVED/" + entry["path"]
            self.assertTrue(any((self.ledger.get("source_roots", {}).get(x.get("root", "current"), "") + x["path"]) == rel for x in self.ledger["sources"]))
            source = next(item for item in self.ledger["sources"] if self.ledger.get("source_roots", {}).get(item.get("root", "current"), "") + item["path"] == rel)
            self.assertEqual(entry["sha256"], source["sha256"])

    def test_legacy_manifest_entries_have_no_unknown_destination(self):
        manifest = json.loads((ROOT / "research-profile/profile.manifest.json").read_text(encoding="utf-8"))
        expected = {f"LEGACY-MANIFEST-{entry['role']}" for entry in manifest["entries"]}
        self.assertTrue(expected <= self.rules.keys())
        for rid in expected:
            cls = self.ledger["migration_classes"][self.rules[rid]["migration_class"]]
            self.assertTrue(cls.get("target_issue"), rid)
            self.assertTrue(cls["responsibility"], rid)

    def test_all_approved_runtime_rule_ids_are_tracked_once(self):
        expected = [item["runtime_rule_id"] for item in json.loads((LAYER_A / "01_PUBLICATION_STYLE_CONTRACT.json").read_text(encoding="utf-8"))]
        self.assertEqual(51, len(expected))
        for rid in expected:
            self.assertIn(rid, self.rules)
            self.assertEqual("PACK-A-01-JSON", self.rules[rid]["source_id"])
            self.assertIn("01_PUBLICATION_STYLE_CONTRACT.md", self.rules[rid].get("aliases", [""])[0])

    def test_layer_a_named_patterns_guards_and_synthetic_specs_are_covered(self):
        expected = set()
        expected |= _h2_ids(LAYER_A / "03_RHETORICAL_PATTERN_LIBRARY.md", r"PAT-")
        expected |= _h2_ids(LAYER_A / "06_CONTENT_AND_NARRATIVE_GUARDS.md", r"NG-")
        expected |= _h2_ids(LAYER_A / "09_SYNTHETIC_FEWSHOT_SPECIFICATION.md", r"SF-")
        self.assertTrue(expected <= self.rules.keys())
        for rid in _h2_ids(LAYER_A / "09_SYNTHETIC_FEWSHOT_SPECIFICATION.md", r"SF-"):
            cls = self.ledger["migration_classes"][self.rules[rid]["migration_class"]]
            self.assertFalse(cls["runtime"], rid)

    def test_map_rows_and_noncanonical_project_feedback_are_explicit(self):
        map_text = (ROOT / "research-profile/maps/research_attention_and_initial_publication_map.md").read_text(encoding="utf-8")
        chapter_rows = re.findall(r"^\| 第([1-8])章 ", map_text, flags=re.MULTILINE)
        section_rows = re.findall(r"^\| ([1-8])－([1-9]) ", map_text, flags=re.MULTILINE)
        self.assertEqual(len(chapter_rows), len([r for r in self.rules if r.startswith("MAP-CH-")]))
        self.assertEqual(len(section_rows), len([r for r in self.rules if r.startswith("MAP-SEC-")]))
        for rid, rule in self.rules.items():
            if rid.startswith("MAP-"):
                self.assertEqual("project-attention", rule["migration_class"])
            if rid.startswith("PROJECT-FEEDBACK-"):
                self.assertEqual("project-knowledge", rule["migration_class"])

    def test_audit_review_and_synthetic_material_are_not_runtime_authority(self):
        forbidden = {"audit-provenance", "human-review", "synthetic-example-spec", "project-knowledge"}
        for name in forbidden:
            self.assertFalse(self.ledger["migration_classes"][name]["runtime"], name)
        for source in self.ledger["sources"]:
            if source["role"] in {"audit_only_provenance", "human_review_support"}:
                self.assertNotEqual("clean_runtime_source", source["role"])

    def test_human_decision_gaps_are_not_filled_with_invented_values(self):
        decisions = {item["rule_id"] for item in self.ledger["rules"] if item["rule_id"].startswith("HD-") and not item["rule_id"].endswith("LAYER-A")}
        self.assertEqual({"HD-01", "HD-02", "HD-03", "HD-04"}, decisions)
        gaps = {item["id"]: item for item in self.ledger["missing_inputs"]}
        self.assertIn("MI-01", gaps)
        self.assertIn("MI-02", gaps)
        self.assertIn("do not infer", gaps["MI-01"]["when_missing"])
        self.assertIn("do not invent", gaps["MI-02"]["when_missing"])

    def test_bounded_ablation_detects_removed_rule_but_alias_does_not_duplicate_policy(self):
        ablated = json.loads(json.dumps(self.ledger))
        ablated["rules"] = [item for item in ablated["rules"] if item["rule_id"] != "PUB-FR-01"]
        self.assertTrue(any("PUB-FR-01" in error for error in _coverage_errors(ablated)))

        represented_twice = json.loads(json.dumps(self.ledger))
        target = next(item for item in represented_twice["rules"] if item["rule_id"] == "PUB-FR-01")
        target.setdefault("aliases", []).append("another-rendering-of-the-same-rule")
        self.assertEqual([], _coverage_errors(represented_twice))


if __name__ == "__main__":
    unittest.main()
