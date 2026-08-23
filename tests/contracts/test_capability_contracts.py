from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import unittest
from pathlib import Path

import rfc8785
import yaml
from jsonschema import Draft202012Validator

from capability_oracle import (
    apply_fixture_mutation,
    context_semantic_error,
    descriptor_semantic_error,
    expected_context_pack_digest,
    expected_descriptor_digest,
    expected_handoff_digest,
    expected_invocation_digest,
    handoff_semantic_error,
    invocation_semantic_error,
    refresh_digest,
    semantic_case_error,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = ROOT / "tests/contracts/capability_oracle.py"
PATHS = {
    "descriptor": ROOT / "core/packages/capability-descriptor.schema.json",
    "context": ROOT / "core/packages/capability-context-pack.schema.json",
    "invocation": ROOT / "core/packages/capability-invocation.schema.json",
    "handoff": ROOT / "core/packages/capability-handoff.schema.json",
    "semantics": ROOT / "core/packages/capability-semantics.schema.json",
}
FIX = {
    "descriptor": ROOT
    / "core/fixtures/capabilities/valid/generic-capability-descriptor.json",
    "context": ROOT
    / "core/fixtures/capabilities/valid/generic-capability-context-pack.json",
    "invocation": ROOT
    / "core/fixtures/capabilities/valid/generic-capability-invocation.json",
    "handoff": ROOT
    / "core/fixtures/capabilities/valid/generic-capability-handoff.json",
}


class CapabilityContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {
            key: json.loads(path.read_text()) for key, path in PATHS.items()
        }
        cls.validators = {
            key: Draft202012Validator(schema)
            for key, schema in cls.schemas.items()
        }
        cls.fixtures = {
            key: json.loads(path.read_text()) for key, path in FIX.items()
        }
        cls.project = json.loads(
            (ROOT / "projects/fixtures/valid/generic-project-config.json").read_text()
        )
        cls.effective_profiles = json.loads(
            (ROOT / "profiles/fixtures/valid/effective-profile-set.json").read_text()
        )
        cls.objects = json.loads(
            (ROOT / "core/fixtures/research-objects/valid.json").read_text()
        )["objects"]
        cls.semantics = yaml.safe_load(
            (ROOT / "core/packages/capability-semantics.yaml").read_text()
        )

    def assert_valid(self, key, document):
        errors = list(self.validators[key].iter_errors(document))
        self.assertFalse(
            errors,
            "\n".join(
                f"{list(error.path)}: {error.message}" for error in errors
            ),
        )

    def assert_invalid(self, key, document):
        errors = list(self.validators[key].iter_errors(document))
        self.assertTrue(
            errors,
            f"expected {key} schema validation to fail, but document was valid",
        )

    def test_valid_chain_and_digests(self):
        for schema in self.schemas.values():
            Draft202012Validator.check_schema(schema)

        for key, document in self.fixtures.items():
            self.assert_valid(key, document)

        self.assert_valid("semantics", self.semantics)
        descriptor = self.fixtures["descriptor"]
        context = self.fixtures["context"]
        invocation = self.fixtures["invocation"]
        handoff = self.fixtures["handoff"]

        self.assertIsNone(descriptor_semantic_error(descriptor))
        self.assertIsNone(
            context_semantic_error(
                context,
                self.project,
                self.effective_profiles,
                self.objects,
            )
        )
        self.assertIsNone(invocation_semantic_error(invocation, descriptor, context))
        self.assertIsNone(handoff_semantic_error(handoff, invocation, context))

        self.assertEqual(
            descriptor["descriptor_digest"],
            expected_descriptor_digest(descriptor),
        )
        self.assertEqual(
            context["context_pack_digest"],
            expected_context_pack_digest(context),
        )
        self.assertEqual(
            invocation["invocation_digest"],
            expected_invocation_digest(invocation),
        )
        self.assertEqual(
            handoff["handoff_digest"],
            expected_handoff_digest(handoff),
        )
        expected_effective_digest = "sha256:" + hashlib.sha256(
            rfc8785.dumps(self.effective_profiles)
        ).hexdigest()
        self.assertEqual(
            context["pins"]["effective_profile_set"]["content_digest"],
            expected_effective_digest,
        )

    def test_oracle_error_codes_match_semantics_catalog(self):
        tree = ast.parse(ORACLE_PATH.read_text())
        oracle_codes = {
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.value.value.startswith("CAP-")
        }
        catalog_codes = {item["id"] for item in self.semantics["errors"]}
        self.assertEqual(catalog_codes, oracle_codes)

    def test_context_pins_and_preserves_governance(self):
        context = self.fixtures["context"]
        self.assertEqual(
            context["research_attention"],
            self.project["research_attention"],
        )
        self.assertEqual(
            context["project_constraints"],
            self.project["project_constraints"],
        )
        self.assertEqual(
            context["effective_constraints"],
            self.effective_profiles["effective_constraints"],
        )

        profile_pins = [
            {
                key: profile[key]
                for key in (
                    "profile_id",
                    "profile_type",
                    "profile_version",
                    "manifest_sha256",
                )
            }
            for profile in self.effective_profiles["effective_profiles"]
        ]
        self.assertEqual(
            context["pins"]["effective_profile_set"]["profile_pins"],
            profile_pins,
        )

        bad = deepcopy(context)
        bad["bounds"]["max_resources"] = 2
        refresh_digest("context", bad)
        self.assertEqual(
            "CAP-CONTEXT-BOUND-001",
            context_semantic_error(
                bad,
                self.project,
                self.effective_profiles,
                self.objects,
            ),
        )

        bad = deepcopy(context)
        bad["project_constraints"]["must_not_claim"] = []
        refresh_digest("context", bad)
        self.assertEqual(
            "CAP-CONTEXT-BINDING-001",
            context_semantic_error(
                bad,
                self.project,
                self.effective_profiles,
                self.objects,
            ),
        )

    def test_reference_keys_are_unique_before_resolution(self):
        descriptor = self.fixtures["descriptor"]
        context = self.fixtures["context"]

        bad_descriptor = deepcopy(descriptor)
        duplicate_function = deepcopy(bad_descriptor["declared_functions"][0])
        duplicate_function["description"] = "duplicate key fixture"
        bad_descriptor["declared_functions"].append(duplicate_function)
        refresh_digest("descriptor", bad_descriptor)
        self.assert_valid("descriptor", bad_descriptor)
        self.assertEqual(
            "CAP-DESCRIPTOR-IDENTITY-001",
            descriptor_semantic_error(bad_descriptor),
        )

        duplicate_context_cases = (
            ("resources", 1, "max_resources", "evidentiary_use", "context_only"),
            ("research_attention", 0, "max_attention_items", None, None),
            ("effective_constraints", 0, "max_effective_constraints", None, None),
        )
        for collection, index, bound, changed_key, changed_value in (
            duplicate_context_cases
        ):
            with self.subTest(collection=collection):
                bad = deepcopy(context)
                duplicate = deepcopy(bad[collection][index])
                if changed_key is not None:
                    duplicate[changed_key] = changed_value
                bad[collection].append(duplicate)
                bad["bounds"][bound] += 1
                refresh_digest("context", bad)
                self.assert_valid("context", bad)
                self.assertEqual(
                    "CAP-CONTEXT-IDENTITY-001",
                    context_semantic_error(
                        bad,
                        self.project,
                        self.effective_profiles,
                        self.objects,
                    ),
                )

        bad = deepcopy(context)
        duplicate_guard = deepcopy(bad["project_constraints"]["requirements"][0])
        duplicate_guard["statement"] = "Duplicate guard key fixture."
        bad["project_constraints"]["prohibitions"].append(duplicate_guard)
        bad["bounds"]["max_project_guards"] += 1
        refresh_digest("context", bad)
        self.assert_valid("context", bad)
        self.assertEqual(
            "CAP-CONTEXT-IDENTITY-001",
            context_semantic_error(
                bad,
                self.project,
                self.effective_profiles,
                self.objects,
            ),
        )

    def test_availability_and_project_hints_are_not_authorization(self):
        descriptor = self.fixtures["descriptor"]
        invocation = self.fixtures["invocation"]

        self.assertEqual("available", descriptor["availability"]["declaration"])
        self.assertEqual(
            "no_project_objection",
            self.project["capability_hints"][0]["permission_hint"],
        )

        bad = deepcopy(descriptor)
        bad["runtime_authorization_evidence"] = invocation[
            "runtime_authorization_evidence"
        ]
        self.assert_invalid("descriptor", bad)

        bad = deepcopy(invocation)
        bad["runtime_authorization_evidence"] = self.project["capability_hints"][0]
        self.assert_invalid("invocation", bad)

    def test_invocation_requires_declared_function_mode_and_resource_authorization(
        self,
    ):
        descriptor = self.fixtures["descriptor"]
        context = self.fixtures["context"]
        invocation = self.fixtures["invocation"]

        bad = deepcopy(invocation)
        bad["capability"]["function_id"] = "choose-next-method"
        refresh_digest("invocation", bad)
        self.assertEqual(
            "CAP-DESCRIPTOR-BINDING-001",
            invocation_semantic_error(bad, descriptor, context),
        )

        bad = deepcopy(invocation)
        bad["runtime_authorization_evidence"]["resource_reference_ids"].remove(
            "REF-ARTIFACT-001"
        )
        refresh_digest("invocation", bad)
        self.assertEqual(
            "CAP-AUTH-001",
            invocation_semantic_error(bad, descriptor, context),
        )

    def test_execution_mode_catalog_rejects_empirical_virtual_modes(self):
        for mode in ("virtual", "synthetic_test"):
            with self.subTest(mode=mode):
                bad = deepcopy(self.semantics)
                bad["execution_modes"][mode]["empirical_candidate_possible"] = True
                self.assert_invalid("semantics", bad)

        real = deepcopy(self.semantics)
        real["execution_modes"]["real"]["empirical_candidate_possible"] = False
        self.assert_invalid("semantics", real)

    def test_virtual_output_never_becomes_empirical(self):
        handoff = self.fixtures["handoff"]
        invocation = self.fixtures["invocation"]
        context = self.fixtures["context"]

        bad = deepcopy(handoff)
        bad["outputs"]["evidence_candidates"][0]["epistemic_mode"] = "empirical"
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-MODE-001",
            handoff_semantic_error(bad, invocation, context),
        )
        self.assertFalse(
            self.semantics["execution_modes"]["virtual"][
                "empirical_candidate_possible"
            ]
        )
        self.assertFalse(
            self.semantics["execution_modes"]["synthetic_test"][
                "empirical_candidate_possible"
            ]
        )

    def test_sources_may_be_pre_registered_or_newly_acquired_but_artifacts_are_not_evidence(
        self,
    ):
        handoff = self.fixtures["handoff"]
        invocation = self.fixtures["invocation"]
        context = self.fixtures["context"]

        acquired = deepcopy(handoff)
        acquired["outputs"]["source_captures"][0]["origin"] = {
            "origin_type": "acquired_source",
            "acquisition_locator": "https://example.invalid/fixture",
        }
        refresh_digest("handoff", acquired)
        self.assert_valid("handoff", acquired)
        self.assertIsNone(handoff_semantic_error(acquired, invocation, context))

        artifact = next(
            resource
            for resource in context["resources"]
            if resource["reference_type"] == "artifact"
        )
        bad = deepcopy(handoff)
        bad["outputs"]["counterevidence"][0]["source_basis"] = {
            "basis_type": "resource_reference",
            "resource_reference_id": artifact["reference_id"],
        }
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-RESOURCE-001",
            handoff_semantic_error(bad, invocation, context),
        )

    def test_handoff_is_candidate_only_structured_source_of_truth(self):
        handoff = self.fixtures["handoff"]
        boundary = handoff["adoption_boundary"]
        self.assertEqual(
            (False, True, True),
            (
                boundary["research_state_mutation_performed"],
                boundary["outputs_are_candidates"],
                boundary["human_decision_required_for_authoritative_transition"],
            ),
        )

        for key, value in (
            ("research_state_patch", {"findings": ["FND-X"]}),
            ("conversational_handoff", "authoritative prose"),
        ):
            with self.subTest(key=key):
                bad = deepcopy(handoff)
                bad[key] = value
                self.assert_invalid("handoff", bad)

        bad = deepcopy(handoff)
        bad["outputs"]["candidate_findings"][0]["adoption_state"] = "approved"
        self.assert_invalid("handoff", bad)

        bad = deepcopy(handoff)
        bad["outputs"]["candidate_next_methods"][0]["selected"] = True
        self.assert_invalid("handoff", bad)

    def test_handoff_provenance_is_bound_to_invocation(self):
        handoff = self.fixtures["handoff"]
        invocation = self.fixtures["invocation"]
        context = self.fixtures["context"]

        bad = deepcopy(handoff)
        bad["provenance"]["trace_id"] = "TRACE-OTHER"
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-PROVENANCE-001",
            handoff_semantic_error(bad, invocation, context),
        )

        bad = deepcopy(handoff)
        bad["provenance"]["input_content_digests"] = ["sha256:" + "f" * 64]
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-PROVENANCE-001",
            handoff_semantic_error(bad, invocation, context),
        )

        bad = deepcopy(handoff)
        bad["provenance"]["input_content_digests"].append("sha256:" + "e" * 64)
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-PROVENANCE-001",
            handoff_semantic_error(bad, invocation, context),
        )

        reordered = deepcopy(handoff)
        reordered["provenance"]["input_content_digests"] = list(
            reversed(reordered["provenance"]["input_content_digests"])
        )
        refresh_digest("handoff", reordered)
        self.assertIsNone(handoff_semantic_error(reordered, invocation, context))

    def test_handoff_preserves_governance_and_closed_references(self):
        handoff = self.fixtures["handoff"]
        invocation = self.fixtures["invocation"]
        context = self.fixtures["context"]

        bad = deepcopy(handoff)
        bad["preserved_context"]["research_attention_ids"] = ["ATT-FIXTURE-001"]
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-PRESERVE-001",
            handoff_semantic_error(bad, invocation, context),
        )

        bad = deepcopy(handoff)
        bad["outputs"]["candidate_findings"][0]["question_ids"] = [
            "RQ-NOT-IN-CONTEXT"
        ]
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-REF-001",
            handoff_semantic_error(bad, invocation, context),
        )

        bad = deepcopy(handoff)
        bad["outputs"]["unknowns"][0]["unknown_id"] = "OBS-001"
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-IDENTITY-001",
            handoff_semantic_error(bad, invocation, context),
        )

    def test_validation_status_is_not_adoption(self):
        handoff = self.fixtures["handoff"]
        invocation = self.fixtures["invocation"]
        context = self.fixtures["context"]

        for status in ("partial", "rejected"):
            with self.subTest(status=status):
                candidate = deepcopy(handoff)
                candidate["validation"] = {
                    "status": status,
                    "issues": [
                        {
                            "code": "FIXTURE_ISSUE",
                            "severity": "warning" if status == "partial" else "error",
                            "message": "fixture",
                        }
                    ],
                }
                refresh_digest("handoff", candidate)
                self.assertIsNone(
                    handoff_semantic_error(candidate, invocation, context)
                )
                self.assertTrue(
                    candidate["adoption_boundary"]["outputs_are_candidates"]
                )

        bad = deepcopy(handoff)
        bad["validation"]["status"] = "partial"
        refresh_digest("handoff", bad)
        self.assertEqual(
            "CAP-HANDOFF-VALIDATION-001",
            handoff_semantic_error(bad, invocation, context),
        )

    def test_semantic_mutation_fixtures(self):
        bases = self.fixtures
        cases = json.loads(
            (ROOT / "core/fixtures/capabilities/semantic/cases.json").read_text()
        )["cases"]

        for case in cases:
            with self.subTest(case=case["id"]):
                candidate = apply_fixture_mutation(
                    bases[case["target"]],
                    case["mutation"],
                )
                if case.get("rehash"):
                    refresh_digest(case["target"], candidate)
                self.assert_valid(case["target"], candidate)
                error = semantic_case_error(
                    case["target"],
                    candidate,
                    descriptor=bases["descriptor"],
                    context=bases["context"],
                    invocation=bases["invocation"],
                    project_config=self.project,
                    effective_profile_set=self.effective_profiles,
                    core_objects=self.objects,
                )
                self.assertEqual(case["expected_error"], error, case["id"])

    def test_semantics_closes_ownership_and_authority_boundaries(self):
        self.assertTrue(
            all(value is False for value in self.semantics["principles"].values())
        )
        self.assertEqual(
            {
                "common_contracts": "core/packages",
                "imperative_implementations": "plugins",
                "project_config": "configures_not_owns",
                "profiles": "constrain_not_implement",
            },
            self.semantics["ownership"],
        )
        self.assertEqual(
            "Core Human Decision semantics",
            self.semantics["adoption_boundary"]["authoritative_transition_owner"],
        )


if __name__ == "__main__":
    unittest.main()
