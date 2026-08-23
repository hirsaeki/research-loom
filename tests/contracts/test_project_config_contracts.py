from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from project_config_oracle import (
    apply_fixture_mutation,
    expected_configuration_digest,
    flatten_profile_requests,
    project_config_semantic_error,
    project_core_binding_error,
    project_profile_binding_error,
    refresh_configuration_digest,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SCHEMA = ROOT / "projects/contracts/project-config.schema.json"
CORE_SCHEMA = ROOT / "core/models/research-object.schema.json"
PROFILE_MANIFEST_SCHEMA = ROOT / "profiles/contracts/profile-manifest.schema.json"
SEMANTICS_SCHEMA = ROOT / "projects/contracts/project-config-semantics.schema.json"
SEMANTICS_CATALOG = ROOT / "projects/contracts/project-config-semantics.yaml"
EFFECTIVE_PROFILE_SCHEMA = ROOT / "profiles/contracts/effective-profile-set.schema.json"
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
SEMANTIC_CASES = ROOT / "projects/fixtures/semantic/cases.json"
EFFECTIVE_PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"
CORE_VALID_FIXTURE = ROOT / "core/fixtures/research-objects/valid.json"


class ProjectConfigContractTests(unittest.TestCase):
    """Executable specification for canonical Project Config contracts."""

    @classmethod
    def setUpClass(cls):
        cls.project_schema = json.loads(PROJECT_SCHEMA.read_text(encoding="utf-8"))
        cls.core_schema = json.loads(CORE_SCHEMA.read_text(encoding="utf-8"))
        cls.profile_manifest_schema = json.loads(PROFILE_MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        cls.semantics_schema = json.loads(SEMANTICS_SCHEMA.read_text(encoding="utf-8"))
        cls.semantics = yaml.safe_load(SEMANTICS_CATALOG.read_text(encoding="utf-8"))
        cls.effective_profile_schema = json.loads(EFFECTIVE_PROFILE_SCHEMA.read_text(encoding="utf-8"))
        cls.project_validator = Draft202012Validator(cls.project_schema)
        cls.core_validator = Draft202012Validator(cls.core_schema)
        cls.semantics_validator = Draft202012Validator(cls.semantics_schema)
        cls.effective_profile_validator = Draft202012Validator(cls.effective_profile_schema)
        cls.fixture = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
        cls.effective_profiles = json.loads(EFFECTIVE_PROFILE_FIXTURE.read_text(encoding="utf-8"))
        cls.core_objects = json.loads(CORE_VALID_FIXTURE.read_text(encoding="utf-8"))["objects"]

    def assert_schema_invalid(self, config: dict):
        self.assertTrue(list(self.project_validator.iter_errors(config)))

    def test_project_config_schema_and_generic_fixture_are_valid(self):
        Draft202012Validator.check_schema(self.project_schema)
        errors = list(self.project_validator.iter_errors(self.fixture))
        self.assertFalse(errors, errors)
        self.assertIsNone(project_config_semantic_error(self.fixture))
        self.assertEqual(self.fixture["configuration_digest"], expected_configuration_digest(self.fixture))

    def test_project_identity_and_profile_request_grammars_reuse_existing_contracts(self):
        self.assertEqual(
            self.core_schema["$defs"]["identifier"]["pattern"],
            self.project_schema["$defs"]["identifier"]["pattern"],
        )
        self.assertEqual(
            self.profile_manifest_schema["$defs"]["version_range"]["pattern"],
            self.project_schema["$defs"]["version_range"]["pattern"],
        )

        project = self.fixture["project"]
        scope = self.fixture["scope"]
        core_project = {
            "schema_version": "0.1.0",
            "id": project["project_id"],
            "kind": "project",
            "revision": 0,
            "title": project["title"],
            "objective": project["objective"],
            "scope": scope["in_scope"],
            "out_of_scope": scope["out_of_scope"],
        }
        self.assertFalse(list(self.core_validator.iter_errors(core_project)))

    def test_project_config_references_bind_to_existing_core_fixture_objects(self):
        self.assertIsNone(project_core_binding_error(self.fixture, self.core_objects))

        wrong_question = deepcopy(self.fixture)
        wrong_question["research_questions"]["references"][0]["question_id"] = "FND-1"
        refresh_configuration_digest(wrong_question)
        self.assertEqual("PROJECT-CORE-BINDING-001", project_core_binding_error(wrong_question, self.core_objects))

        wrong_source = deepcopy(self.fixture)
        source_ref = next(ref for ref in wrong_source["resource_references"] if ref["reference_type"] == "source")
        source_ref["object_id"] = "ART-1"
        refresh_configuration_digest(wrong_source)
        self.assertEqual("PROJECT-CORE-BINDING-001", project_core_binding_error(wrong_source, self.core_objects))

    def test_project_config_semantics_catalog_is_valid_and_keeps_boundaries_closed(self):
        Draft202012Validator.check_schema(self.semantics_schema)
        errors = list(self.semantics_validator.iter_errors(self.semantics))
        self.assertFalse(errors, errors)
        principles = self.semantics["principles"]
        self.assertTrue(principles["core_floor_unchanged"])
        self.assertTrue(principles["project_config_is_not_research_state"])
        self.assertTrue(principles["profile_requests_are_direct_only"])
        self.assertTrue(principles["project_constraints_cannot_weaken_core_or_profiles"])
        self.assertFalse(principles["attention_may_determine_answer"])
        self.assertFalse(principles["attention_may_select_method"])
        self.assertFalse(principles["capability_permission_hint_is_authorization"])
        self.assertFalse(principles["resource_reference_is_evidence"])
        self.assertFalse(principles["project_facts_flow_to_reusable_profiles"])
        self.assertFalse(principles["cli_override_precedence_defined"])

    def test_configuration_digest_is_rfc8785_content_binding(self):
        mutated = deepcopy(self.fixture)
        mutated["project"]["objective"] += " Changed without rehash."
        self.assertEqual("PROJECT-CONFIG-DIGEST-001", project_config_semantic_error(mutated))

        reordered = {key: self.fixture[key] for key in reversed(list(self.fixture))}
        self.assertEqual(self.fixture["configuration_digest"], expected_configuration_digest(reordered))

    def test_semantic_fixture_cases_have_exact_expected_outcomes(self):
        cases = json.loads(SEMANTIC_CASES.read_text(encoding="utf-8"))
        for case in cases["cases"]:
            config = apply_fixture_mutation(self.fixture, case["mutation"])
            if case.get("rehash"):
                refresh_configuration_digest(config)
            errors = list(self.project_validator.iter_errors(config))
            self.assertFalse(errors, f"{case['id']}: {errors}")
            self.assertEqual(case["expected_error"], project_config_semantic_error(config), case["id"])

    def test_attention_is_guidance_not_answer_method_or_normative_chapter_map(self):
        without_reason = deepcopy(self.fixture)
        without_reason["research_attention"][1].pop("disposition_reason")
        self.assert_schema_invalid(without_reason)

        normative_hint = deepcopy(self.fixture)
        normative_hint["research_attention"][0]["projection_hints"][0]["normative"] = True
        self.assert_schema_invalid(normative_hint)

        for field, value in [("answer", "synthetic answer"), ("selected_method", "survey")]:
            illegal = deepcopy(self.fixture)
            illegal["research_attention"][0][field] = value
            self.assert_schema_invalid(illegal)

        serialized = json.dumps(self.fixture, ensure_ascii=False).lower()
        self.assertNotIn("misco", serialized)
        hints = [
            hint["hint_type"]
            for attention in self.fixture["research_attention"]
            for hint in attention.get("projection_hints", [])
        ]
        self.assertNotIn("chapter_number", hints)
        self.assertNotIn("literal_heading", hints)

    def test_rq_seeds_are_not_authoritative_research_state(self):
        for field, value in [
            ("adoption_state", "approved"),
            ("answer", "fixture answer"),
            ("method_id", "METHOD-FIXTURE-001"),
            ("revision", 1),
        ]:
            illegal = deepcopy(self.fixture)
            illegal["research_questions"]["seeds"][0][field] = value
            self.assert_schema_invalid(illegal)

        no_questions = deepcopy(self.fixture)
        no_questions["research_questions"] = {"references": [], "seeds": []}
        self.assert_schema_invalid(no_questions)

    def test_project_guards_do_not_become_profile_constraints_or_precedence(self):
        for field, value in [
            ("path", "research_quality.evidence_sufficiency.required_checks"),
            ("merge_strategy", "replace"),
            ("effect", "weaken"),
        ]:
            illegal = deepcopy(self.fixture)
            illegal["project_constraints"]["requirements"][0][field] = value
            self.assert_schema_invalid(illegal)

        top_level = deepcopy(self.fixture)
        top_level["effective_constraints"] = []
        self.assert_schema_invalid(top_level)

        self.assertFalse(self.semantics["profile_request_bridge"]["project_constraints_join_effective_constraints"])
        self.assertFalse(self.semantics["principles"]["cli_override_precedence_defined"])

    def test_communication_and_capability_hints_do_not_absorb_other_contracts(self):
        formatting = deepcopy(self.fixture)
        formatting["communication_brief"]["docx_template"] = "template.docx"
        self.assert_schema_invalid(formatting)

        capability = deepcopy(self.fixture)
        capability["capability_hints"][0]["selected_method"] = "survey"
        self.assert_schema_invalid(capability)

        runtime_grant = deepcopy(self.fixture)
        runtime_grant["capability_hints"][0]["permission_hint"] = "runtime_authorized"
        self.assert_schema_invalid(runtime_grant)

    def test_resource_references_neither_assert_evidence_nor_runtime_access(self):
        reference = deepcopy(self.fixture)
        reference["resource_references"][0]["evidence_status"] = "verified"
        self.assert_schema_invalid(reference)

        access = deepcopy(self.fixture)
        access["resource_references"][0]["runtime_access"] = "read"
        self.assert_schema_invalid(access)

        no_locator_or_object = deepcopy(self.fixture)
        no_locator_or_object["resource_references"][1].pop("object_id")
        self.assert_schema_invalid(no_locator_or_object)

    def test_profile_requests_bind_losslessly_to_pr4_effective_profile_set(self):
        eps_errors = list(self.effective_profile_validator.iter_errors(self.effective_profiles))
        self.assertFalse(eps_errors, eps_errors)
        self.assertIsNone(project_profile_binding_error(self.fixture, self.effective_profiles))
        self.assertEqual(self.effective_profiles["requested_profiles"], flatten_profile_requests(self.fixture))

        self.assertEqual([], self.fixture["profile_requests"]["research"])
        self.assertEqual([], self.fixture["profile_requests"]["organization"])
        effective_types = {profile["profile_type"] for profile in self.effective_profiles["effective_profiles"]}
        self.assertEqual({"research", "organization", "narrative", "publication"}, effective_types)

        missing = deepcopy(self.effective_profiles)
        missing["requested_profiles"] = missing["requested_profiles"][:-1]
        self.assertEqual("PROJECT-PROFILE-BINDING-001", project_profile_binding_error(self.fixture, missing))

    def test_profile_request_bridge_contract_targets_pr4_direct_request_field_only(self):
        bridge = self.semantics["profile_request_bridge"]
        self.assertEqual("profile_requests", bridge["source_path"])
        self.assertEqual("urn:research-loom:profiles:effective-profile-set:0.1.0", bridge["target_contract"])
        self.assertEqual("requested_profiles", bridge["target_field"])
        self.assertTrue(bridge["direct_requests_only"])
        self.assertFalse(bridge["transitive_profiles_written_back"])
        self.assertFalse(bridge["effective_profiles_owned_by_project_config"])


if __name__ == "__main__":
    unittest.main()
