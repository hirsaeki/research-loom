from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from plugins.survey_analysis import (
    AGGREGATE_RESULT_SCHEMA_PATH,
    ANALYSIS_SPEC_SCHEMA_PATH,
    analysis_spec_content_digest,
    registry_digest,
    stable_identity,
    validate_analysis_spec,
)


class SurveyAnalysisContractTests(unittest.TestCase):
    def test_schemas_are_valid_draft_2020_12(self):
        for path in (ANALYSIS_SPEC_SCHEMA_PATH, AGGREGATE_RESULT_SCHEMA_PATH):
            schema = json.loads(Path(path).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)

    def test_analysis_spec_semantic_digest_ignores_identity_and_timestamp(self):
        base = {
            "schema_version": "0.1.0",
            "object_type": "survey_analysis_spec",
            "project_id": "PRJ-1",
            "dataset_ref": {"id": "SRD-1", "content_digest": "sha256:" + "1" * 64},
            "instrument_ref": {
                "id": "QNR-1",
                "version": "1.0.0",
                "content_digest": "sha256:" + "2" * 64,
            },
            "analysis_items": [{
                "item_id": "AN-001",
                "analysis_type": "missingness",
                "question_id": "Q1",
            }],
            "created_at": "2026-09-02T00:00:00Z",
        }
        digest = analysis_spec_content_digest(base)
        first = deepcopy(base)
        first["content_digest"] = digest
        first["analysis_spec_id"] = stable_identity("SAS-", digest)
        first["registry_digest"] = registry_digest(first)
        validate_analysis_spec(first)

        second = deepcopy(first)
        second["created_at"] = "2026-09-03T00:00:00Z"
        second["analysis_spec_id"] = "SAS-placeholder"
        second.pop("registry_digest")
        self.assertEqual(analysis_spec_content_digest(second), digest)

    def test_analysis_spec_rejects_duplicate_item_identity(self):
        value = {
            "schema_version": "0.1.0",
            "object_type": "survey_analysis_spec",
            "project_id": "PRJ-1",
            "dataset_ref": {"id": "SRD-1", "content_digest": "sha256:" + "1" * 64},
            "instrument_ref": {
                "id": "QNR-1",
                "version": "1.0.0",
                "content_digest": "sha256:" + "2" * 64,
            },
            "analysis_items": [
                {"item_id": "AN-001", "analysis_type": "missingness", "question_id": "Q1"},
                {"item_id": "AN-001", "analysis_type": "missingness", "question_id": "Q2"},
            ],
            "created_at": "2026-09-02T00:00:00Z",
        }
        value["content_digest"] = analysis_spec_content_digest(value)
        value["analysis_spec_id"] = stable_identity("SAS-", value["content_digest"])
        value["registry_digest"] = registry_digest(value)
        with self.assertRaisesRegex(ValueError, "item IDs must be unique"):
            validate_analysis_spec(value)


if __name__ == "__main__":
    unittest.main()
