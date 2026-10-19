"""Characterization tests for ``virtual_runner_method_context`` and ``virtual_runner_binding`` (#507).

Both modules live in ``plugins.local_application.virtual_runner``. The tests pin
how ``build_method_context`` assembles the context pack, its binding, the
Protocol reference, the Run Spec and the Research Method Context, and how
``build_survey_virtual_extension`` derives the Survey context, the synthetic
population defaults for the structural and LLM backends, and the LLM respondent
plan. Both builders' validation failures are pinned with their error codes.
Inputs come from the resolver stand-ins in the ``virtual_runner_resolve`` tests.
"""

from __future__ import annotations

import unittest
from copy import deepcopy

from core.conversation.validation import canonical_digest
from plugins.application_errors import LocalApplicationError
from plugins.local_application.virtual_runner.virtual_runner_binding import (
    build_survey_virtual_extension,
)
from plugins.local_application.virtual_runner.virtual_runner_input import _payload
from plugins.local_application.virtual_runner.virtual_runner_method_context import (
    build_method_context,
)
from plugins.local_application.virtual_runner.virtual_runner_resolve import (
    resolve_virtual_inputs,
)
from plugins.survey_virtual_runner.contracts import document_digest
from plugins.survey_virtual_runner.llm_backend import prompt_template_pin
from tests.runtime.survey_virtual_runner_test_support import METHOD_ID, PROTOCOL_ID
from tests.unit.plugins.local_application.virtual_runner.test_virtual_runner_resolve import (
    CONFIG_DIGEST,
    EPS_DIGEST,
    SNAPSHOT,
    FakeFacade,
    FakeState,
    design_record,
    instrument_record,
    payload,
)

RESOLVED_NAMES = (
    "questionnaire",
    "rq_ids",
    "rq_objects",
    "method",
    "method_decisions",
    "protocol",
    "material_decisions",
    "snapshot",
    "effective",
    "attention",
    "project_constraints",
    "effective_constraints",
)

LLM_PROFILES = [
    {"profile_id": "SYN-PROFILE-A", "attributes": {"role_level": "manager", "area": "sales"}},
    {"profile_id": "SYN-PROFILE-B", "attributes": {"role_level": "contributor"}},
]


class BuilderCase(unittest.TestCase):
    def setUp(self) -> None:
        self.state = FakeState()
        self.state.project_ref = "PRJ-1"
        self.state.project_config = {
            "guards": {"requirements": ["R1", "R2"], "prohibitions": ["P"]}
        }
        self.state.effective_constraints = [{"id": "C-1"}]
        self.facade = FakeFacade(attention=[{"attention_id": "ATT-1"}])
        self.record = instrument_record()
        self.design = design_record()
        self.design["design"]["title"] = "Design fixture"

    def resolved(self, raw_payload) -> dict:
        values = resolve_virtual_inputs(
            self.facade, self.state, self.record, self.design, raw_payload
        )
        return dict(zip(RESOLVED_NAMES, values, strict=True))

    def method_context(self, raw_payload=None, *, normalized=None, resolved=None):
        normalized = normalized if normalized is not None else _payload(raw_payload or payload())
        resolved = resolved if resolved is not None else self.resolved(normalized)
        return (
            normalized,
            resolved,
            build_method_context(
                self.state, self.record, normalized, context_pack_id="CTX-VR-UNIT", **resolved
            ),
        )

    def extension(self, raw_payload=None):
        normalized, resolved, built = self.method_context(raw_payload)
        _context, binding, protocol_ref, run_spec, research_method = built
        return build_survey_virtual_extension(
            self.record,
            self.design,
            normalized,
            context_pack_id="CTX-VR-UNIT",
            binding=binding,
            questionnaire=resolved["questionnaire"],
            method=resolved["method"],
            protocol_ref=protocol_ref,
            run_spec=run_spec,
            research_method=research_method,
        )


def llm_raw_payload(**overrides) -> dict:
    raw = payload()
    raw.pop("population_size")
    raw.update(
        generator_backend="llm",
        respondent_profiles=deepcopy(LLM_PROFILES),
        llm_backend={"backend_id": "openai_responses", "model_id": "gpt-test"},
    )
    raw.update(overrides)
    return raw


class MethodContextTests(BuilderCase):
    def test_context_pack_pins_bounds_and_digest(self):
        _normalized, _resolved, built = self.method_context()
        context, binding, _protocol_ref, _run_spec, _research_method = built
        self.assertEqual(context["context_pack_id"], "CTX-VR-UNIT")
        self.assertEqual(context["project_id"], "PRJ-1")
        self.assertEqual(context["purpose"], "Pre-REAL Survey structural validation for QNR-1.")
        self.assertEqual(context["pins"]["project_config"], {"configuration_digest": CONFIG_DIGEST})
        self.assertEqual(context["pins"]["effective_profile_set"]["content_digest"], EPS_DIGEST)
        self.assertEqual(
            context["pins"]["research_snapshot"],
            {"snapshot_id": "SNP-1", "revision": 3, "content_digest": SNAPSHOT["content_digest"]},
        )
        self.assertEqual(context["question_ids"], ["RQ-1"])
        self.assertEqual(
            context["research_object_references"],
            [
                {"kind": "research_question", "id": "RQ-1", "revision": 0},
                {"kind": "method", "id": METHOD_ID, "revision": 0},
            ],
        )
        self.assertEqual(context["resources"], [])
        self.assertEqual(
            context["bounds"],
            {
                "max_questions": 1,
                "max_research_object_references": 2,
                "max_resources": 0,
                "max_attention_items": 1,
                "max_project_guards": 3,
                "max_effective_constraints": 1,
            },
        )
        without_digest = {k: v for k, v in context.items() if k != "context_pack_digest"}
        self.assertEqual(context["context_pack_digest"], canonical_digest(without_digest))
        self.assertEqual(
            binding,
            {
                "context_pack_id": "CTX-VR-UNIT",
                "context_pack_digest": context["context_pack_digest"],
                "project_id": "PRJ-1",
            },
        )

    def test_explicit_purpose_is_used(self):
        raw = payload()
        raw["purpose"] = "Exercise branching"
        context = self.method_context(raw)[2][0]
        self.assertEqual(context["purpose"], "Exercise branching")

    def test_protocol_ref_run_spec_and_research_method(self):
        raw = payload()
        raw["protocol"].update(
            material_revision=True, material_revision_decision_id="DEC-PROTOCOL-MAT-1"
        )
        normalized, _resolved, built = self.method_context(raw)
        _context, binding, protocol_ref, run_spec, research_method = built
        self.assertEqual(
            protocol_ref,
            {
                "protocol_id": PROTOCOL_ID,
                "version": "1.0.0",
                "content_digest": raw["protocol"]["content_digest"],
                "approval_status": "approved",
                "material_revision": True,
            },
        )
        self.assertEqual(run_spec["run_spec_id"], "RUNSPEC-STANDARD")
        self.assertEqual(run_spec["version"], "1.0.0")
        self.assertEqual(
            run_spec["data_roles"],
            ["synthetic_response", "validation_report", "defect_report", "readiness_assessment"],
        )
        self.assertEqual(
            run_spec["coverage_dimensions"],
            ["survey_schema", "branching", "missingness", "execution_flow"],
        )
        without_digest = {k: v for k, v in run_spec.items() if k != "content_digest"}
        self.assertEqual(run_spec["content_digest"], canonical_digest(without_digest))
        self.assertEqual(research_method["context_binding"], binding)
        self.assertEqual(research_method["targets"]["question_ids"], ["RQ-1"])
        self.assertEqual(
            research_method["targets"]["evidence_gap_refs"], normalized["evidence_gap_refs"]
        )
        self.assertEqual(
            research_method["human_decision_bindings"],
            {
                "method_adoption_decision_ids": ["DEC-METHOD-1"],
                "material_protocol_revision_decision_ids": ["DEC-PROTOCOL-MAT-1"],
            },
        )
        self.assertEqual(research_method["prior_run_result_refs"], [])
        self.assertEqual(
            research_method["extension_digest"],
            document_digest(research_method, "extension_digest"),
        )

    def test_run_spec_input_digest_tracks_run_inputs(self):
        first = self.method_context()[2][3]
        raw = payload()
        raw["sampling_seed"] = 99
        second = self.method_context(raw)[2][3]
        self.assertNotEqual(first["input_digest"], second["input_digest"])

    def test_invalid_research_method_context_is_rejected(self):
        normalized = _payload(payload())
        resolved = self.resolved(normalized)
        resolved["method_decisions"] = ["not a valid id"]
        with self.assertRaises(LocalApplicationError) as caught:
            self.method_context(normalized=normalized, resolved=resolved)
        self.assertEqual(caught.exception.code, "VR-METHOD-BINDING-001")
        self.assertEqual(
            caught.exception.message,
            "Research Method execute context is invalid: "
            "human_decision_bindings.method_adoption_decision_ids.0: 'not a valid id' "
            "does not match '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'",
        )


class SurveyExtensionTests(BuilderCase):
    def test_structural_extension_defaults(self):
        extension = self.extension()
        self.assertEqual(extension["binding_type"], "survey_virtual_runner")
        self.assertEqual(extension["scenario_class"], "STANDARD")
        self.assertEqual(extension["generator_backend"], "structural")
        self.assertEqual(extension["core_method_ref"], {"method_id": METHOD_ID, "revision": 0})
        self.assertEqual(extension["design"], self.design["design"])
        self.assertEqual(extension["design_ref"], self.record["design_ref"])
        survey = extension["survey_context"]
        self.assertEqual(survey["object_type"], "survey_context_extension")
        self.assertEqual(
            survey["research_method_context_digest"],
            extension["research_method_context"]["extension_digest"],
        )
        self.assertEqual(survey["questionnaire_decision_ids"], ["DEC-QNR-1"])
        self.assertEqual(survey["duplicate_response_policy"], "exclude_all")
        self.assertEqual(survey["missing_data_policy"], "preserve")
        population = extension["synthetic_population"]
        self.assertEqual(population["identity_namespace"], "synthetic:survey:CTX-VR-UNIT")
        self.assertEqual(population["population_size"], 6)
        self.assertEqual(
            population["composition_intent"],
            "Exercise Survey contract paths without claiming empirical representation.",
        )
        self.assertEqual(
            population["scenario_dimensions"], ["branching", "missingness", "validation"]
        )
        self.assertEqual(
            population["role_attribute_constraints"],
            ["structural synthetic labels only; no real employee personas"],
        )
        self.assertEqual(
            population["allowed_variation_dimensions"],
            ["stable_response_value", "missing_value_state", "branch_path"],
        )
        self.assertEqual(
            population["forbidden_inference_dimensions"],
            ["real-person-identity", "population-prevalence", "organizational-distribution"],
        )
        self.assertFalse(population["synthetic_personas_are_real_people"])
        self.assertEqual(
            extension["runner_configuration"],
            {
                "generator_backend": "structural",
                "sampling_seed": 41,
                "stress_faults": [],
                "readiness_policy": {
                    "require_standard": True,
                    "require_stress": True,
                    "blocking_severities": ["critical"],
                },
                "prior_virtual_run_ids": [],
                "minimum_valid_response_count": 1,
            },
        )
        for key in ("respondent_profiles", "respondent_plan", "prompt_template"):
            self.assertNotIn(key, extension)
        self.assertEqual(
            extension["extension_digest"], document_digest(extension, "extension_digest")
        )

    def test_material_instrument_decision_and_configured_population(self):
        self.record["questionnaire"].update(
            material_revision=True, material_revision_decision_id="DEC-QNR-MAT"
        )
        raw = payload()
        raw["synthetic_population"] = {
            "composition_intent": "Edge cases",
            "scenario_dimensions": ["dropout"],
            "role_attribute_constraints": ["labels"],
            "allowed_variation_dimensions": ["value"],
            "forbidden_inference_dimensions": ["identity"],
        }
        extension = self.extension(raw)
        self.assertEqual(
            extension["survey_context"]["questionnaire_decision_ids"],
            ["DEC-QNR-1", "DEC-QNR-MAT"],
        )
        population = extension["synthetic_population"]
        self.assertEqual(population["composition_intent"], "Edge cases")
        self.assertEqual(population["scenario_dimensions"], ["dropout"])
        self.assertEqual(population["role_attribute_constraints"], ["labels"])
        self.assertEqual(population["allowed_variation_dimensions"], ["value"])
        self.assertEqual(population["forbidden_inference_dimensions"], ["identity"])

    def test_llm_extension_derives_dimensions_and_respondent_plan(self):
        extension = self.extension(llm_raw_payload(minimum_valid_response_count=2))
        population = extension["synthetic_population"]
        self.assertEqual(population["population_size"], 2)
        self.assertEqual(population["scenario_dimensions"], ["area", "role_level"])
        self.assertEqual(
            population["role_attribute_constraints"],
            ["explicit synthetic respondent profiles only; no real-person identity"],
        )
        self.assertEqual(
            population["allowed_variation_dimensions"],
            ["area", "role_level", "sampling_parameters"],
        )
        self.assertEqual(extension["generator_backend"], "llm")
        self.assertEqual(extension["runner_configuration"]["minimum_valid_response_count"], 2)
        profiles = extension["respondent_profiles"]
        self.assertEqual(
            [item["profile_id"] for item in profiles], ["SYN-PROFILE-A", "SYN-PROFILE-B"]
        )
        plan = extension["respondent_plan"]
        self.assertEqual(plan["profile_ids"], ["SYN-PROFILE-A", "SYN-PROFILE-B"])
        self.assertEqual(
            plan["profile_digests"],
            [
                {"profile_id": item["profile_id"], "content_digest": canonical_digest(item)}
                for item in profiles
            ],
        )
        self.assertEqual(plan["profiles_digest"], canonical_digest(profiles))
        self.assertEqual(plan["composition_intent"], population["composition_intent"])
        self.assertEqual(plan["interaction_model"], "full_instrument_single_call")
        self.assertEqual(
            extension["llm_backend_config_digest"],
            canonical_digest(extension["llm_backend_configuration"]),
        )
        self.assertEqual(extension["prompt_template"], prompt_template_pin())

    def test_llm_profiles_without_attributes_fall_back_to_structural_dimensions(self):
        raw = llm_raw_payload(
            respondent_profiles=[{"profile_id": "SYN-PROFILE-A"}, {"profile_id": "SYN-PROFILE-B"}]
        )
        population = self.extension(raw)["synthetic_population"]
        self.assertEqual(
            population["scenario_dimensions"], ["branching", "missingness", "validation"]
        )
        self.assertEqual(population["allowed_variation_dimensions"], ["sampling_parameters"])

    def test_invalid_survey_context_is_rejected(self):
        self.record["questionnaire"]["approval_decision_id"] = "not a valid id"
        with self.assertRaises(LocalApplicationError) as caught:
            self.extension()
        self.assertEqual(caught.exception.code, "APPLICATION-VIRTUAL-PIN-001")
        # The Survey schema is a oneOf, so the first error is reported at the root.
        message = caught.exception.message
        self.assertTrue(message.startswith("Survey execute context is invalid: $: "), message)
        self.assertTrue(message.endswith("is not valid under any of the given schemas"), message)


if __name__ == "__main__":
    unittest.main()
