from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

ROOT = Path(__file__).resolve().parents[2]
RESPONSE_SCHEMA = ROOT / "core/packages/survey/survey-response.schema.json"
DESCRIPTOR_SCHEMA = ROOT / "core/packages/capability-descriptor.schema.json"
VIRTUAL_DESCRIPTOR = ROOT / "core/packages/virtual-runner/virtual-runner-capability-descriptor.json"


def digest_without(document: dict, field: str) -> str:
    value = deepcopy(document)
    value.pop(field, None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


class SurveyResponseProductionContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(RESPONSE_SCHEMA.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def _virtual_response(self) -> dict:
        return {
            "schema_version": "0.1.0", "object_type": "survey_response_record",
            "response_id": "SYN-RESP-001", "raw_data_ref_id": "ART-VR-RESP-RUN-1",
            "participant_id": "SYN-PARTICIPANT-001", "identity_namespace": "synthetic:survey:CTX-1",
            "epistemic_mode": "virtual", "synthetic": True, "response_status": "complete",
            "eligibility_status": "eligible", "duplicate_disposition": "not_duplicate",
            "verified_evidence_claimed": False, "dropout": False,
            "answers": [
                {"response_key": "role", "state": "answered", "value": "manager"},
                {"response_key": "notes", "state": "unknown"},
            ],
        }

    def test_response_schema_and_virtual_firewall(self):
        Draft202012Validator.check_schema(self.schema)
        response = self._virtual_response()
        self.assertEqual(list(self.validator.iter_errors(response)), [])
        empirical = deepcopy(response); empirical["epistemic_mode"] = "empirical"
        self.assertTrue(list(self.validator.iter_errors(empirical)))
        real_namespace = deepcopy(response); real_namespace["identity_namespace"] = "real:survey"
        self.assertTrue(list(self.validator.iter_errors(real_namespace)))
        evidence_claim = deepcopy(response); evidence_claim["verified_evidence_claimed"] = True
        self.assertTrue(list(self.validator.iter_errors(evidence_claim)))

    def test_same_response_contract_can_represent_future_real_intake(self):
        response = self._virtual_response()
        response.update(response_id="REAL-RESP-001", raw_data_ref_id="REAL-RAW-001", participant_id="REAL-PARTICIPANT-001", identity_namespace="real:survey", epistemic_mode="empirical", synthetic=False)
        self.assertEqual(list(self.validator.iter_errors(response)), [])

    def test_production_virtual_runner_descriptor_is_canonical(self):
        descriptor_schema = json.loads(DESCRIPTOR_SCHEMA.read_text(encoding="utf-8"))
        descriptor = json.loads(VIRTUAL_DESCRIPTOR.read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(descriptor_schema).iter_errors(descriptor)), [])
        self.assertEqual(descriptor["descriptor_digest"], digest_without(descriptor, "descriptor_digest"))
        self.assertEqual(descriptor["capability_kind"], "execution_backend.virtual_runner")
        self.assertEqual(descriptor["declared_functions"][0]["supported_execution_modes"], ["virtual"])


if __name__ == "__main__":
    unittest.main()
