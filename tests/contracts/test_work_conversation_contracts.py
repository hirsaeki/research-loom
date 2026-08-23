from __future__ import annotations

import ast
from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from conversation_oracle import (
    apply_semantic_case,
    conversation_semantic_error,
    document_digest,
    payload_digest,
    refresh_document_digest,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = ROOT / "tests/contracts/conversation_oracle.py"
CONTRACT_PATH = ROOT / "core/packages/work-conversation.schema.json"
SEMANTICS_SCHEMA_PATH = ROOT / "core/packages/work-conversation-semantics.schema.json"
SEMANTICS_PATH = ROOT / "core/packages/work-conversation-semantics.yaml"
FLOW_PATH = ROOT / "core/fixtures/conversation/valid/generic-conversation-flow.json"
CASES_PATH = ROOT / "core/fixtures/conversation/semantic/cases.json"
INVOCATION_PATH = ROOT / "core/fixtures/capabilities/valid/generic-capability-invocation.json"
HANDOFF_PATH = ROOT / "core/fixtures/capabilities/valid/generic-capability-handoff.json"


class WorkConversationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text())
        cls.semantics_schema = json.loads(SEMANTICS_SCHEMA_PATH.read_text())
        cls.validator = Draft202012Validator(cls.contract)
        cls.semantics_validator = Draft202012Validator(cls.semantics_schema)
        cls.semantics = yaml.safe_load(SEMANTICS_PATH.read_text())
        cls.flow = json.loads(FLOW_PATH.read_text())
        cls.cases = json.loads(CASES_PATH.read_text())["cases"]
        cls.invocation = json.loads(INVOCATION_PATH.read_text())
        cls.handoff = json.loads(HANDOFF_PATH.read_text())

    def assert_valid_document(self, document):
        errors = list(self.validator.iter_errors(document))
        self.assertFalse(errors, "\n".join(f"{list(error.path)}: {error.message}" for error in errors))

    def assert_invalid_document(self, document):
        self.assertTrue(list(self.validator.iter_errors(document)))

    def by_id(self, message_type, identifier):
        id_field = {
            "conversation_input": "input_id",
            "action_proposal": "proposal_id",
            "confirmation_request": "confirmation_request_id",
            "confirmation_receipt": "confirmation_receipt_id",
            "action_receipt": "action_receipt_id",
            "candidate_presentation": "presentation_id",
        }[message_type]
        return next(document for document in self.flow["documents"] if document["message_type"] == message_type and document[id_field] == identifier)

    def test_schemas_semantics_and_generic_flow_are_valid(self):
        Draft202012Validator.check_schema(self.contract)
        Draft202012Validator.check_schema(self.semantics_schema)
        self.assertFalse(list(self.semantics_validator.iter_errors(self.semantics)))
        for document in self.flow["documents"]:
            self.assert_valid_document(document)
            digest_field = {
                "conversation_input": "input_digest",
                "action_proposal": "proposal_digest",
                "confirmation_request": "request_digest",
                "confirmation_receipt": "receipt_digest",
                "action_receipt": "receipt_digest",
                "candidate_presentation": "presentation_digest",
            }[document["message_type"]]
            self.assertEqual(document[digest_field], document_digest(document))
            if document["message_type"] == "action_proposal":
                self.assertEqual(document["action"]["payload_digest"], payload_digest(document))
        self.assertIsNone(conversation_semantic_error(self.flow, self.invocation, self.handoff))

    def test_closed_input_classification_and_explicit_targets(self):
        enum = self.contract["$defs"]["conversation_input"]["properties"]["classification"]["enum"]
        self.assertEqual(enum, ["QUERY", "PROPOSAL", "COMMITTABLE_ACTION", "CONFIRMATION", "CANCEL"])
        confirmation = deepcopy(self.by_id("conversation_input", "IN-CONFIRM"))
        confirmation.pop("target")
        refresh_document_digest(confirmation)
        self.assert_invalid_document(confirmation)
        cancel = deepcopy(self.by_id("conversation_input", "IN-CANCEL"))
        cancel.pop("target")
        refresh_document_digest(cancel)
        self.assert_invalid_document(cancel)
        query = deepcopy(self.by_id("conversation_input", "IN-Q"))
        query["target"] = {"target_type": "proposal", "target_id": "P-Q"}
        refresh_document_digest(query)
        self.assert_invalid_document(query)

    def test_action_vocabulary_is_open_but_typed_and_legacy_enum_is_not_canonicalized(self):
        action_schema = self.contract["$defs"]["action_proposal"]["properties"]["action"]["properties"]
        self.assertNotIn("enum", action_schema["action_type"])
        self.assertIn("payload_contract", action_schema)
        self.assertIn("payload_digest", action_schema)
        proposal = deepcopy(self.by_id("action_proposal", "P-Q"))
        proposal["action"]["action_type"] = "adapter.future.status"
        proposal["route"]["service_id"] = "adapter.future.status"
        refresh_document_digest(proposal)
        self.assert_valid_document(proposal)

    def test_natural_language_has_no_direct_state_or_evidence_authority(self):
        query = self.by_id("conversation_input", "IN-Q")
        self.assertNotIn("research_state_patch", query)
        self.assertNotIn("evidence", query)
        bad = deepcopy(query)
        bad["research_state_patch"] = {"anything": "forbidden"}
        refresh_document_digest(bad)
        self.assert_invalid_document(bad)
        self.assertIn("proposal_binding", self.contract["$defs"]["action_receipt"]["required"])

    def test_read_only_query_has_no_confirmation_and_does_not_change_state(self):
        proposal = self.by_id("action_proposal", "P-Q")
        receipt = self.by_id("action_receipt", "AR-Q")
        self.assertEqual(proposal["action"]["effect"], "read_only")
        self.assertFalse(proposal["confirmation_policy"]["required_on_commit"])
        self.assertNotIn("confirmation_receipt_binding", receipt)
        self.assertEqual(receipt["state_before"], receipt["state_after"])
        self.assertFalse(receipt["research_state_mutation_performed"])

    def test_proposal_cancel_is_pending_only_and_does_not_abort_or_rewind(self):
        proposal = self.by_id("action_proposal", "P-PENDING")
        cancel = self.by_id("conversation_input", "IN-CANCEL")
        receipt = self.by_id("action_receipt", "AR-CANCEL")
        self.assertEqual(proposal["commitment_mode"], "proposal_only")
        self.assertEqual(cancel["target"], {"target_type": "proposal", "target_id": "P-PENDING"})
        self.assertEqual(receipt["status"], "cancelled")
        self.assertEqual(receipt["execution"]["execution_type"], "none")
        self.assertEqual(receipt["state_before"], receipt["state_after"])
        self.assertNotIn("run_id", cancel)

    def test_state_changing_capability_action_uses_bound_single_use_confirmation(self):
        proposal = self.by_id("action_proposal", "P-CAP")
        request = self.by_id("confirmation_request", "CR-CAP")
        confirmation = self.by_id("confirmation_receipt", "CF-CAP")
        receipt = self.by_id("action_receipt", "AR-CAP")
        self.assertEqual(proposal["commitment_mode"], "commit_requested")
        self.assertEqual(proposal["action"]["effect"], "state_changing")
        self.assertTrue(request["single_use"])
        self.assertEqual(request["actor_binding"], confirmation["actor"])
        self.assertEqual(request["action_binding"], confirmation["action_binding"])
        self.assertEqual(request["state_binding"], confirmation["observed_state"])
        self.assertEqual(request["research_context_binding"], confirmation["research_context_binding"])
        self.assertFalse(proposal["human_decision_boundary"]["confirmation_is_human_decision"])
        self.assertEqual(receipt["confirmation_receipt_binding"]["confirmation_receipt_id"], "CF-CAP")

    def test_capability_route_is_pr9_invocation_and_authorization_is_not_in_conversation(self):
        proposal = self.by_id("action_proposal", "P-CAP")
        receipt = self.by_id("action_receipt", "AR-CAP")
        route = proposal["route"]
        self.assertEqual(route["route_type"], "capability_invocation")
        self.assertEqual(route["invocation_contract"], "capability-invocation@0.1.0")
        self.assertEqual(route["capability"], self.invocation["capability"])
        self.assertEqual(route["execution_mode"], self.invocation["execution_mode"])
        self.assertEqual(route["context_pack"], self.invocation["context_pack"])
        self.assertNotIn("runtime_authorization_evidence", route)
        self.assertIn("runtime_authorization_evidence", self.invocation)
        self.assertEqual(receipt["execution"]["invocation_id"], self.invocation["invocation_id"])
        self.assertEqual(receipt["execution"]["invocation_digest"], self.invocation["invocation_digest"])
        self.assertFalse(receipt["research_state_mutation_performed"])
        bad = deepcopy(proposal)
        bad["route"]["runtime_authorization_evidence"] = {"authorization_id": "FAKE"}
        refresh_document_digest(bad)
        self.assert_invalid_document(bad)

    def test_handoff_candidates_are_structured_proposals_not_auto_adopted(self):
        next_action = self.by_id("candidate_presentation", "PRES-NA")
        next_method = self.by_id("candidate_presentation", "PRES-NM")
        action_proposal = self.by_id("action_proposal", "P-NA")
        method_proposal = self.by_id("action_proposal", "P-NM")
        self.assertEqual(next_action["handoff_binding"]["handoff_digest"], self.handoff["handoff_digest"])
        self.assertEqual(next_method["handoff_binding"]["handoff_digest"], self.handoff["handoff_digest"])
        self.assertFalse(next_action["auto_adopted"])
        self.assertFalse(next_method["auto_adopted"])
        self.assertTrue(next_action["structured_source_only"])
        self.assertTrue(next_method["structured_source_only"])
        self.assertEqual(action_proposal["commitment_mode"], "proposal_only")
        self.assertEqual(method_proposal["commitment_mode"], "proposal_only")
        self.assertEqual(method_proposal["route"]["route_type"], "unresolved")
        self.assertTrue(method_proposal["human_decision_boundary"]["required"])
        self.assertFalse(method_proposal["human_decision_boundary"]["confirmation_is_human_decision"])
        handoff_method_ids = {item["proposal_id"] for item in self.handoff["outputs"]["candidate_next_methods"]}
        self.assertIn(next_method["candidate"]["candidate_proposal_id"], handoff_method_ids)

    def test_semantic_mutations_fail_with_stable_error_codes(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                mutated = apply_semantic_case(self.flow, case)
                for document in mutated["documents"]:
                    self.assert_valid_document(document)
                self.assertEqual(case["expected_error"], conversation_semantic_error(mutated, self.invocation, self.handoff))

    def test_oracle_error_codes_match_semantics_catalog(self):
        tree = ast.parse(ORACLE_PATH.read_text())
        oracle_codes = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("CONV-")}
        catalog_codes = {item["id"] for item in self.semantics["errors"]}
        self.assertEqual(catalog_codes, oracle_codes)


if __name__ == "__main__":
    unittest.main()
