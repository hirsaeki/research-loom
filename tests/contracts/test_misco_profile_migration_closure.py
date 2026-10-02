from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/migration/misco-profile-migration-ledger/index.json"
CLOSURE = ROOT / "docs/migration/misco-profile-migration-closure.json"


class MiscoProfileMigrationClosureTests(unittest.TestCase):
    def test_every_ledger_migration_class_has_final_target_consumer_and_evidence(self):
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
        self.assertEqual(set(closure["rule_classes"]), set(ledger["migration_classes"]))
        for class_id, row in closure["rule_classes"].items():
            self.assertTrue(row["disposition"], class_id)
            self.assertTrue(row["target"], class_id)
            self.assertTrue(row["consumer"], class_id)
            self.assertTrue(row["evidence"], class_id)
            for path in row["evidence"]:
                self.assertTrue((ROOT / path).is_file(), f"{class_id}: missing {path}")

    def test_all_245_ledger_rows_map_to_a_final_closure_class(self):
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
        ledger_root = LEDGER.parent
        rows = []
        for shard_name in ledger["shards"]:
            shard = json.loads((ledger_root / shard_name).read_text(encoding="utf-8"))
            if not isinstance(shard, dict) or "rules" not in shard:
                continue
            columns = shard["columns"]
            class_index = columns.index("class")
            id_index = columns.index("id")
            for row in shard["rules"]:
                rows.append((row[id_index], row[class_index], shard_name))

        expected = sum(
            ledger["counts"][key]
            for key in ("project_rules", "writer_items", "publication_items", "support_items")
        )
        self.assertEqual(expected, 245)
        self.assertEqual(len(rows), expected)
        for rule_id, class_id, shard_name in rows:
            self.assertIn(class_id, closure["rule_classes"], f"{shard_name}:{rule_id}")

    def test_legacy_project_knowledge_is_validation_only_not_fresh_runtime_input(self):
        closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
        project_knowledge = closure["rule_classes"]["project-knowledge"]
        self.assertEqual(project_knowledge["disposition"], "validation_only")
        self.assertEqual(project_knowledge["consumer"], "none in fresh production runtime")
        config = json.loads((ROOT / "projects/misco-ai-2026/project-config.json").read_text(encoding="utf-8"))
        locators = {row["locator"] for row in config["resource_references"]}
        self.assertNotIn("research-profile/project_feedback/virtual_run_feedback_v0.1.md", locators)

    def test_historical_missing_inputs_have_explicit_final_status_without_inventing_values(self):
        closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
        missing = closure["missing_inputs"]
        self.assertEqual(missing["INPUT-FORMAL-SPEC"]["status"], "resolved")
        self.assertEqual(missing["INPUT-URL-DISPLAY"]["status"], "resolved")
        self.assertEqual(missing["INPUT-RESEARCH-GROUP-TYPE"]["status"], "not_required_by_current_formal_profile")
        self.assertEqual(missing["INPUT-PERMISSION"]["status"], "conditional_runtime_input")

    def test_live_acceptance_records_g3_without_falsely_closing_host_uat(self):
        closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
        live = closure["live_gates"]
        self.assertEqual(live["existing_workspace_operator_reprobe"], "passed_durable_replacement")
        self.assertEqual(live["live_uat_revision"], "UAT-02R3")
        self.assertEqual(live["codex_live_acceptance"], "pending_uat_02r3")
        self.assertEqual(live["chatgpt_work_live_acceptance"], "pending_uat_02r3")
        self.assertEqual(live["publication_visual_inspection_335"], "passed_for_profile_acceptance")
        self.assertEqual(live["host_output_human_inspection"], "pending_uat_02r3")


if __name__ == "__main__":
    unittest.main()
