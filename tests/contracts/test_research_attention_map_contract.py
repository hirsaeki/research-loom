from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from core.conversation import canonical_digest


ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG_SCHEMA = ROOT / "projects/contracts/project-config.schema.json"
ATTENTION_MAP_SCHEMA = ROOT / "projects/contracts/research-attention-map.schema.json"
CORE_SCHEMA = ROOT / "core/models/research-object.schema.json"


class ResearchAttentionMapContractTests(unittest.TestCase):
    def setUp(self):
        self.project_schema = json.loads(PROJECT_CONFIG_SCHEMA.read_text(encoding="utf-8"))
        self.map_schema = json.loads(ATTENTION_MAP_SCHEMA.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.map_schema, format_checker=FormatChecker())

    def map(self):
        value = {
            "schema_version": "0.1.0",
            "map_id": "ATTMAP-FIXTURE-001",
            "project_id": "PRJ-1",
            "project_config": {"ref": "project-config.json", "digest": "sha256:" + "1" * 64},
            "base": {"source": "project_config_baseline"},
            "items": [{
                "attention_id": "ATT-FIXTURE-001",
                "statement": "Keep a synthetic cross-cutting issue visible.",
                "source_reference_ids": ["REF-1"],
                "related_question_ids": ["RQ-1"],
                "related_question_seed_ids": ["RQ-SEED-1"],
                "disposition": "active",
                "projection_hints": [{
                    "hint_type": "publication_location",
                    "value": "synthetic location",
                    "normative": False,
                }],
            }],
            "provenance": {
                "source_action_proposal_id": "PROP-1",
                "source_action_proposal_digest": "sha256:" + "2" * 64,
                "source_input_id": "IN-1",
            },
            "created_at": "2026-08-29T00:00:00Z",
        }
        value["map_digest"] = canonical_digest(value)
        return value

    def test_attention_item_semantics_are_identical_to_project_config(self):
        self.assertEqual(self.map_schema["$defs"]["attention_item"], self.project_schema["$defs"]["attention_item"])
        self.assertEqual(self.map_schema["$defs"]["projection_hint"], self.project_schema["$defs"]["projection_hint"])

    def test_valid_complete_snapshot_and_active_base_validate(self):
        value = self.map()
        self.assertEqual(list(self.validator.iter_errors(value)), [])
        active = deepcopy(value)
        active["map_id"] = "ATTMAP-FIXTURE-002"
        active["base"] = {"source": "active_map", "map_id": value["map_id"], "map_digest": value["map_digest"]}
        active["map_digest"] = canonical_digest({k: v for k, v in active.items() if k != "map_digest"})
        self.assertEqual(list(self.validator.iter_errors(active)), [])

    def test_dropped_attention_requires_reason_and_unknown_item_fields_fail(self):
        value = self.map()
        value["items"][0]["disposition"] = "dropped"
        self.assertTrue(list(self.validator.iter_errors(value)))
        value["items"][0]["disposition_reason"] = "Synthetic reason."
        value["items"][0]["semantic_override"] = "forbidden"
        self.assertTrue(list(self.validator.iter_errors(value)))

    def test_attention_map_is_not_added_to_core_research_object_vocabulary(self):
        core = json.loads(CORE_SCHEMA.read_text(encoding="utf-8"))
        serialized = json.dumps(core, sort_keys=True)
        self.assertNotIn('"attention_map"', serialized)
        self.assertNotIn('"attention"', serialized)


if __name__ == "__main__":
    unittest.main()
