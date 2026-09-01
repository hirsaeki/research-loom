from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from plugins.survey_response.contracts import (
    CANONICAL_RESPONSE_SCHEMA_PATH,
    DATASET_SCHEMA_PATH,
    RAW_SCHEMA_PATH,
    dataset_content_digest,
)


class SurveyResponseDatasetContractTests(unittest.TestCase):
    def test_new_contract_schemas_are_valid_draft_2020_12(self):
        for path in (RAW_SCHEMA_PATH, CANONICAL_RESPONSE_SCHEMA_PATH, DATASET_SCHEMA_PATH):
            schema = json.loads(Path(path).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_dataset_digest_is_response_order_independent(self):
        base = {
            "schema_version": "0.1.0",
            "object_type": "survey_response_dataset",
            "project_id": "PRJ-1",
            "dataset_id": "SRD-1",
            "instrument_ref": {"id": "QNR-1", "version": "1.0.0", "content_digest": "sha256:" + "1" * 64},
            "response_origin": "synthetic",
            "epistemic_status": "SYNTHETIC_TEST_ONLY",
            "accepted_response_refs": [
                {"response_id": "SYN-B", "identity_namespace": "synthetic:test", "content_digest": "sha256:" + "b" * 64},
                {"response_id": "SYN-A", "identity_namespace": "synthetic:test", "content_digest": "sha256:" + "a" * 64},
            ],
            "rejected_response_refs": [],
            "rejected_inputs": [],
            "response_count": 2,
            "accepted_count": 2,
            "rejected_count": 0,
            "created_at": "2026-09-02T00:00:00Z",
            "captured_against": {"lineage_ref": "LIN-1", "snapshot_ref": "SNP-1", "snapshot_digest": "sha256:" + "2" * 64},
            "project_config_digest": "sha256:" + "3" * 64,
            "effective_profile_set_digest": "sha256:" + "4" * 64,
            "capture_origin": "test",
            "source_run_ids": ["RUN-2", "RUN-1"],
            "source_provenance": {},
            "validation_summary": {"issue_count": 0, "issue_code_counts": {}},
            "research_state_mutation_performed": False,
        }
        reversed_value = deepcopy(base)
        reversed_value["accepted_response_refs"].reverse()
        reversed_value["source_run_ids"].reverse()
        self.assertEqual(dataset_content_digest(base), dataset_content_digest(reversed_value))
