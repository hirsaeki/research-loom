from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from virtual_runner_oracle import (
    ERROR_IDS,
    canonical_digest,
    context_error,
    cutover_error,
    descriptor_error,
    real_start_error,
    result_error,
)

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
VR = PKG / "virtual-runner"
FIX = ROOT / "core/fixtures/capabilities/valid"
CONV = ROOT / "core/fixtures/conversation/valid"


def digest_fill(char):
    return "sha256:" + char * 64


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def refresh(document, field="extension_digest"):
    document[field] = canonical_digest(document, field)


def context(method_family="survey", scenario="STANDARD"):
    doc = {
        "schema_version": "0.1.0",
        "object_type": "virtual_runner_context",
        "context_pack_binding": {
            "context_pack_id": "CTX-VR-1",
            "context_pack_digest": digest_fill("1"),
            "project_id": "PROJ-1",
        },
        "execution_mode": "virtual",
        "scenario_class": scenario,
        "method_execute_binding": {
            "method_family": method_family,
            "method_capability_id": f"fixture.{method_family}",
            "function_id": "execute",
            "research_method_context_extension_digest": digest_fill("2"),
        },
        "adopted_core_method": {
            "method_id": f"METHOD-{method_family.upper()}-1",
            "revision": 1,
            "adoption_state": "approved",
        },
        "approved_protocol": {
            "id": "PROT-1",
            "version": "1.0.0",
            "content_digest": digest_fill("3"),
            "approval_status": "approved",
        },
        "approved_instruments": [
            {
                "id": "INST-1",
                "version": "1.0.0",
                "content_digest": digest_fill("4"),
                "approval_status": "approved",
            }
        ],
        "run_spec": {
            "id": "RS-1",
            "version": "1.0.0",
            "content_digest": digest_fill("5"),
            "input_digest": digest_fill("6"),
        },
        "pins": {
            "project_config_digest": digest_fill("7"),
            "effective_profile_set_digest": digest_fill("8"),
            "research_snapshot": {
                "snapshot_id": "SNAP-1",
                "revision": 4,
                "content_digest": digest_fill("9"),
            },
        },
        "runtime_authorization": {
            "authorization_id": "AUTH-VR-1",
            "authorization_digest": digest_fill("a"),
        },
        "synthetic_population": {
            "identity_namespace": f"synthetic:{method_family}:vr1",
            "real_identity_namespaces": [f"real:{method_family}"],
            "population_size": 32,
            "composition_intent": "Exercise contract paths without claiming empirical representation.",
            "scenario_dimensions": ["role", "branch"],
            "role_attribute_constraints": ["bounded synthetic roles only"],
            "allowed_variation_dimensions": ["response-pattern", "missingness"],
            "forbidden_inference_dimensions": ["population-prevalence", "real-person-identity"],
            "real_identity_mapping_refs": [],
            "synthetic_personas_are_real_people": False,
            "empirical_distribution_claimed": False,
            "target_population_representation_claimed": False,
        },
        "generation_provenance": {
            "generator_identity": "fixture-generator",
            "provider_identity": "fixture-provider",
            "model_identity": "fixture-model",
            "model_version_ref": "model-v1",
            "prompt_template_version": "1.0.0",
            "prompt_template_digest": digest_fill("b"),
            "schema_version": "1.0.0",
            "schema_digest": digest_fill("c"),
            "runner_version": "1.0.0",
            "runner_digest": digest_fill("d"),
            "sampling_seed": "42",
            "generated_at": "2026-08-25T00:00:00Z",
            "generation_configuration_digest": digest_fill("e"),
            "reproducibility_semantics": "provenance_complete_replay_attempt_capable",
            "byte_identical_rerun_assumed": False,
            "seed_proves_determinism": False,
        },
        "runner_configuration_pin": {
            "runner_id": "fixture.virtual-runner",
            "version": "1.0.0",
            "content_digest": digest_fill("f"),
        },
        "extension_digest": "",
    }
    refresh(doc)
    return doc


def result(ctx, run_id="VR-RUN-1"):
    doc = {
        "schema_version": "0.1.0",
        "object_type": "virtual_runner_result",
        "handoff_binding": {
            "handoff_id": "HND-VR-1",
            "handoff_digest": digest_fill("a"),
            "invocation_id": "INV-VR-1",
            "run_id": run_id,
            "context_pack_id": "CTX-VR-1",
            "context_pack_digest": digest_fill("1"),
            "capability_id": "fixture.virtual-runner",
            "function_id": "execute",
        },
        "scenario_class": ctx["scenario_class"],
        "evidence_status": "SYNTHETIC_TEST_ONLY",
        "completion_status": "complete",
        "synthetic_outputs": [
            {
                "output_id": "SYN-RESP-1",
                "kind": "response",
                "identity_namespace": ctx["synthetic_population"]["identity_namespace"],
                "content_digest": digest_fill("1"),
                "evidence_status": "SYNTHETIC_TEST_ONLY",
                "empirical_adoption_performed": False,
            }
        ],
        "candidate_analyses": [
            {
                "analysis_id": "VAN-1",
                "evidence_status": "SYNTHETIC_TEST_ONLY",
                "core_analysis_adoption_performed": False,
            }
        ],
        "candidate_findings": [
            {
                "finding_id": "VFND-1",
                "evidence_status": "SYNTHETIC_TEST_ONLY",
                "authoritative_finding": False,
            }
        ],
        "defects": [],
        "warnings": [],
        "unresolved_ambiguities": [],
        "human_gate_requirements": [],
        "candidate_change_requests": [],
        "readiness_assessment": {
            "status": "CANDIDATE_READY",
            "candidate_only": True,
            "real_execution_started": False,
            "reasons": ["required path exercised"],
        },
        "execution_trace": ["synthetic generation", "method execute"],
        "extension_digest": "",
    }
    refresh(doc)
    return doc


def cutover():
    doc = {
        "schema_version": "0.1.0",
        "object_type": "virtual_real_cutover_manifest",
        "cutover_manifest_id": "CUT-1",
        "project_id": "PROJ-1",
        "source_virtual_run_ids": ["VR-RUN-1", "VR-RUN-2"],
        "freeze_package": {
            "method": {"id": "METHOD-SURVEY-1", "revision": 1},
            "protocol": {"id": "PROT-2", "version": "1.1.0", "content_digest": digest_fill("3")},
            "instruments": [{"id": "INST-1", "version": "1.1.0", "content_digest": digest_fill("4")}],
            "schemas": [{"id": "survey-schema", "version": "1.0.0", "content_digest": digest_fill("c")}],
            "prompt_templates": [{"id": "synthetic-template", "version": "1.0.0", "content_digest": digest_fill("b")}],
            "runner_code": [{"id": "fixture.virtual-runner", "version": "1.0.0", "content_digest": digest_fill("d")}],
            "validation_gate_contracts": [{"id": "virtual-runner-contract", "version": "0.1.0", "content_digest": digest_fill("e")}],
            "effective_profile_set_digest": digest_fill("8"),
            "project_config_digest": digest_fill("7"),
        },
        "readiness_criteria": {
            "required_standard_completed": True,
            "required_stress_completed": True,
            "critical_design_defects_closed": True,
            "critical_implementation_defects_closed": True,
            "material_revisions_approved": True,
            "schema_validation_green": True,
            "required_gates_exercised": True,
            "no_blocking_issue": True,
        },
        "threshold_policy_sources": [{"owner": "protocol", "reference_id": "PROT-2"}],
        "human_gate": {
            "required": True,
            "decision_ref": "DEC-CUT-1",
            "confirmation_is_human_decision": False,
        },
        "status": "CANDIDATE_READY",
        "candidate_only": True,
        "real_start_boundary": {
            "separate_authorized_invocation_required": True,
            "virtual_runner_may_start_real": False,
            "new_run_root_required": True,
            "new_run_id_required": True,
            "isolated_raw_data_namespace_required": True,
        },
        "allowed_transfer_kinds": [
            "approved_method_design",
            "approved_protocol",
            "approved_instrument",
            "schema",
            "prompt_template",
            "executable_code_pin",
            "gate_definition",
            "defect_history",
            "resolved_change_history",
            "validation_result",
            "cutover_manifest",
            "design_rationale",
        ],
        "forbidden_transfer_kinds": [
            "virtual_response",
            "virtual_observation",
            "synthetic_raw_data",
            "virtual_evidence_candidate",
            "virtual_analysis_candidate",
            "virtual_finding_candidate",
            "virtual_participant_identity",
        ],
        "manifest_digest": "",
    }
    refresh(doc, "manifest_digest")
    return doc


class VirtualRunnerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load(VR / "virtual-runner-contract.schema.json")
        cls.descriptor_schema = load(PKG / "capability-descriptor.schema.json")
        cls.conversation_schema = load(PKG / "work-conversation.schema.json")
        cls.descriptor = load(FIX / "generic-virtual-runner-capability-descriptor.json")
        cls.catalog = load(FIX / "generic-virtual-runner-fixture-catalog.json")
        cls.routing = load(CONV / "virtual-runner-routing.json")

    def _result_error(self, result_document, ctx):
        return result_error(
            result_document,
            ctx,
            expected_capability_id=self.descriptor["capability_id"],
        )

    def test_schema_descriptor_and_semantic_error_catalog(self):
        Draft202012Validator.check_schema(self.schema)
        self.assertEqual(list(Draft202012Validator(self.descriptor_schema).iter_errors(self.descriptor)), [])
        self.assertEqual(descriptor_error(self.descriptor), None)
        semantics = yaml.safe_load((VR / "virtual-runner-semantics.yaml").read_text(encoding="utf-8"))
        self.assertEqual({x["id"] for x in semantics["errors"]}, ERROR_IDS)
        declared_errors = {case["expected_error"] for case in self.catalog["cases"] if "expected_error" in case}
        self.assertTrue(declared_errors.issubset(ERROR_IDS))
        self.assertFalse(semantics["capability"]["research_method_family"])
        self.assertFalse(semantics["scenario_semantics"]["scenario_class_is_execution_mode"])

    def test_digest_and_binding_error_branches(self):
        bad_descriptor = deepcopy(self.descriptor)
        bad_descriptor["descriptor_digest"] = digest_fill("0")
        self.assertEqual(descriptor_error(bad_descriptor), "VR-DESCRIPTOR-001")

        ctx = context()
        ctx["extension_digest"] = digest_fill("0")
        self.assertEqual(context_error(ctx), "VR-CONTEXT-DIGEST-001")

        ctx = context()
        ctx["adopted_core_method"]["adoption_state"] = "candidate"
        refresh(ctx)
        self.assertEqual(context_error(ctx), "VR-METHOD-BINDING-001")

        ctx = context()
        res = result(ctx)
        res["extension_digest"] = digest_fill("0")
        self.assertEqual(self._result_error(res, ctx), "VR-RESULT-DIGEST-001")

    def test_result_binding_accepts_non_fixture_capability_identity(self):
        ctx = context()
        res = result(ctx)
        res["handoff_binding"]["capability_id"] = "plugin.virtual-runner"
        refresh(res)
        self.assertEqual(
            result_error(res, ctx, expected_capability_id="plugin.virtual-runner"),
            None,
        )

    def test_survey_and_delphi_standard_stress_contracts(self):
        validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        for family in ("survey", "delphi"):
            for scenario in ("STANDARD", "STRESS"):
                ctx = context(family, scenario)
                res = result(ctx)
                self.assertEqual(list(validator.iter_errors(ctx)), [])
                self.assertEqual(list(validator.iter_errors(res)), [])
                self.assertEqual(context_error(ctx), None)
                self.assertEqual(self._result_error(res, ctx), None)
        ids = {x["id"] for x in self.catalog["cases"]}
        self.assertIn("delphi-no-consensus-dropout-stress", ids)
        self.assertIn("survey-stress-valid", ids)

    def test_generation_provenance_and_identity_firewall(self):
        ctx = context()
        ctx["generation_provenance"]["byte_identical_rerun_assumed"] = True
        refresh(ctx)
        self.assertEqual(context_error(ctx), "VR-SYNTHETIC-PROVENANCE-001")

        ctx = context()
        ctx["synthetic_population"]["identity_namespace"] = "real:survey"
        refresh(ctx)
        self.assertEqual(context_error(ctx), "VR-IDENTITY-COLLISION-001")

        ctx = context()
        del ctx["runtime_authorization"]["authorization_digest"]
        refresh(ctx)
        self.assertEqual(context_error(ctx), "VR-RUNTIME-AUTH-001")

    def test_synthetic_content_cannot_be_promoted(self):
        ctx = context()
        res = result(ctx)
        res["synthetic_outputs"][0]["evidence_status"] = "EMPIRICAL"
        refresh(res)
        self.assertEqual(self._result_error(res, ctx), "VR-EPISTEMIC-FIREWALL-001")

        res = result(ctx)
        res["candidate_findings"][0]["authoritative_finding"] = True
        refresh(res)
        self.assertEqual(self._result_error(res, ctx), "VR-EPISTEMIC-FIREWALL-001")

    def test_critical_defect_blocks_readiness_and_changes_are_candidate_only(self):
        ctx = context()
        res = result(ctx)
        res["defects"] = [
            {
                "defect_id": "DEF-1",
                "taxonomy": "IMPLEMENTATION_DEFECT",
                "severity": "critical",
                "affected_ref": "runner://v1",
                "detecting_run_id": "VR-RUN-1",
                "reproduction_refs": ["trace://1"],
                "observed_behavior": "bad",
                "expected_contract_behavior": "fail closed",
                "proposed_correction": "fix runner",
                "disposition": "open",
                "resolution_refs": [],
            }
        ]
        refresh(res)
        self.assertEqual(self._result_error(res, ctx), "VR-READINESS-001")

        res = result(ctx)
        res["candidate_change_requests"] = [
            {
                "change_request_id": "CHG-1",
                "target_ref": "INST-1@1.0.0",
                "proposal": "revise and rerun",
                "authoritative_change_applied": True,
            }
        ]
        refresh(res)
        self.assertEqual(self._result_error(res, ctx), "VR-DEFECT-AUTHORITY-001")

    def test_cutover_ready_blocked_stale_and_human_decision(self):
        validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        manifest = cutover()
        self.assertEqual(list(validator.iter_errors(manifest)), [])
        self.assertEqual(cutover_error(manifest), None)

        case = deepcopy(manifest)
        case["readiness_criteria"]["required_stress_completed"] = False
        refresh(case, "manifest_digest")
        self.assertEqual(cutover_error(case), "VR-READINESS-001")

        case = deepcopy(manifest)
        case["freeze_package"]["project_config_digest"] = digest_fill("0")
        refresh(case, "manifest_digest")
        self.assertEqual(
            cutover_error(case, current_pins={"project_config_digest": digest_fill("7")}),
            "VR-FREEZE-STALE-001",
        )

        case = deepcopy(manifest)
        del case["freeze_package"]["prompt_templates"]
        refresh(case, "manifest_digest")
        self.assertTrue(list(validator.iter_errors(case)))
        self.assertEqual(cutover_error(case), "VR-FREEZE-STALE-001")

        case = deepcopy(manifest)
        del case["human_gate"]["decision_ref"]
        refresh(case, "manifest_digest")
        self.assertTrue(list(validator.iter_errors(case)))
        self.assertEqual(cutover_error(case), "VR-HUMAN-DECISION-001")

    def test_revised_instrument_requires_new_virtual_run_and_real_is_new_root(self):
        old = context()
        revised = context()
        revised["approved_instruments"][0]["version"] = "1.1.0"
        revised["approved_instruments"][0]["content_digest"] = digest_fill("0")
        refresh(revised)

        old_result = result(old, "VR-RUN-1")
        new_result = result(revised, "VR-RUN-2")
        self.assertNotEqual(old["extension_digest"], revised["extension_digest"])
        self.assertNotEqual(old_result["handoff_binding"]["run_id"], new_result["handoff_binding"]["run_id"])

        virtual_run_roots = {
            "VR-RUN-1": "VR-ROOT-1",
            "VR-RUN-2": "VR-ROOT-2",
        }
        real = {
            "run_root_id": "REAL-ROOT-1",
            "run_id": "REAL-RUN-1",
            "execution_mode": "real",
            "runtime_authorization_id": "AUTH-REAL-1",
            "access_zone": "REAL-ZONE",
            "owner": "research-owner",
            "permission_context": "real-approved",
            "raw_data_namespace": "real:survey:run1",
            "source_virtual_run_id": "VR-RUN-1",
            "copied_virtual_content_ids": [],
            "virtual_identity_mapping_refs": [],
        }
        self.assertEqual(list(Draft202012Validator(self.schema).iter_errors(real)), [])
        self.assertEqual(real_start_error(real, virtual_run_roots), None)

        unknown_source = deepcopy(real)
        unknown_source["source_virtual_run_id"] = "VR-RUN-MISSING"
        self.assertEqual(
            real_start_error(unknown_source, virtual_run_roots),
            "VR-REAL-ISOLATION-001",
        )

        reused_root = deepcopy(real)
        reused_root["run_root_id"] = "VR-ROOT-1"
        self.assertEqual(
            real_start_error(reused_root, virtual_run_roots),
            "VR-REAL-ISOLATION-001",
        )

        reused_run_id = deepcopy(real)
        reused_run_id["run_id"] = "VR-RUN-2"
        self.assertEqual(
            real_start_error(reused_run_id, virtual_run_roots),
            "VR-VIRTUAL-COPY-001",
        )

        copied_content = deepcopy(real)
        copied_content["copied_virtual_content_ids"] = ["SYN-RESP-1"]
        self.assertEqual(
            real_start_error(copied_content, virtual_run_roots),
            "VR-VIRTUAL-COPY-001",
        )

    def test_pr10_conversational_routing_is_proposal_only(self):
        proposal = self.routing["action_proposal"]
        self.assertEqual(
            list(Draft202012Validator(self.conversation_schema, format_checker=FormatChecker()).iter_errors(proposal)),
            [],
        )
        self.assertEqual(proposal["route"]["execution_mode"], "virtual")
        self.assertEqual(proposal["route"]["capability"]["capability_id"], "fixture.virtual-runner")
        self.assertEqual(proposal["route"]["capability"]["function_id"], "execute")
        self.assertEqual(proposal["commitment_mode"], "proposal_only")
        self.assertFalse(self.routing["auto_adopted"])
        self.assertEqual(
            set(self.routing["candidate_only_actions"]),
            {"add_standard_run", "add_stress_run", "revise_protocol", "cutover_real"},
        )


if __name__ == "__main__":
    unittest.main()
