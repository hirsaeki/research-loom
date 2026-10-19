"""Characterization tests for ``plugins.local_application.virtual_runner.virtual_runner_input`` (#507).

They pin how the Virtual Runner execution payload is validated and normalized:
required and unknown fields, identifier/SemVer/digest shapes, protocol and
Evidence Gap references, structural defaults, and the bounded LLM respondent
backend (profiles, PII screening and backend configuration), together with the
``LocalApplicationError`` codes and messages each rejection raises.
"""

from __future__ import annotations

import unittest
from copy import deepcopy

from plugins.application_errors import LocalApplicationError
from plugins.local_application.virtual_runner.virtual_runner_input import (
    _DEFAULT_LIMITS,
    _PROFILE_PIN_FIELDS,
    _contains_profile_identifier,
    _nonempty,
    _payload,
    _string_list,
    canonical_protocol_ref,
)
from tests.runtime.survey_virtual_runner_test_support import (
    PROTOCOL_DIGEST,
    PROTOCOL_ID,
    PROTOCOL_REF,
    PROTOCOL_VERSION,
    execution_payload,
)

PAYLOAD_CODE = "APPLICATION-VIRTUAL-PAYLOAD-001"
INSTRUMENT_DIGEST = "sha256:" + "a" * 64


def base_payload(**overrides) -> dict:
    payload = execution_payload(
        scenario="STANDARD",
        instrument_version="1.0.0",
        instrument_digest=INSTRUMENT_DIGEST,
    )
    payload.update(overrides)
    return payload


def minimal_payload() -> dict:
    payload = base_payload()
    for field in ("population_size", "sampling_seed", "prior_virtual_run_ids", "readiness_policy"):
        payload.pop(field)
    return payload


def llm_payload(**overrides) -> dict:
    payload = base_payload(
        generator_backend="llm",
        respondent_profiles=[
            {
                "profile_id": "SYN-PROFILE-A",
                "attributes": {"role_level": "manager"},
                "knowledge_scope": ["own work"],
            },
            {"profile_id": "SYN-PROFILE-B", "scenario_notes": "joined recently"},
        ],
        llm_backend={"backend_id": "openai_responses", "model_id": "gpt-test"},
    )
    payload.pop("population_size")
    payload.update(overrides)
    return payload


class ConstantsAndHelpersTests(unittest.TestCase):
    def test_canonical_protocol_ref_joins_id_version_and_digest(self):
        protocol = {
            "protocol_id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "content_digest": PROTOCOL_DIGEST,
            "material_revision": False,
        }
        self.assertEqual(canonical_protocol_ref(protocol), PROTOCOL_REF)

    def test_default_limits_and_profile_pin_fields(self):
        self.assertEqual(
            _DEFAULT_LIMITS,
            {
                "max_questions": 64,
                "max_research_object_references": 128,
                "max_resources": 0,
                "max_attention_items": 128,
                "max_project_guards": 128,
                "max_effective_constraints": 256,
            },
        )
        self.assertEqual(
            _PROFILE_PIN_FIELDS,
            ("profile_id", "profile_type", "profile_version", "manifest_sha256"),
        )

    def test_nonempty_returns_value_unchanged(self):
        self.assertEqual(_nonempty(" x ", "field"), " x ")

    def test_nonempty_rejects_blank_and_non_strings(self):
        for value in ("", "   ", None, 3):
            with self.subTest(value=value):
                with self.assertRaises(LocalApplicationError) as caught:
                    _nonempty(value, "the_field")
                self.assertEqual(caught.exception.code, PAYLOAD_CODE)
                self.assertEqual(caught.exception.message, "the_field must be a non-empty string")

    def test_string_list_returns_copy(self):
        value = ["a", "b"]
        result = _string_list(value, "f")
        self.assertEqual(result, value)
        self.assertIsNot(result, value)

    def test_string_list_rejects_non_list_blank_and_duplicates(self):
        for value in ("a", ["a", ""], ["a", 1], ["a", "a"]):
            with self.subTest(value=value):
                with self.assertRaises(LocalApplicationError) as caught:
                    _string_list(value, "f")
                self.assertEqual(
                    caught.exception.message, "f must be an array of unique non-empty strings"
                )

    def test_contains_profile_identifier_detects_sensitive_keys_and_text(self):
        positives = (
            {"Email": "x"},
            {"nested": {"full_name": "x"}},
            [{"staff_id": 1}],
            "contact someone@example.com",
            "employee id: AB123",
            "Staff-number=XY-99",
            {"note": ["reach me at a.b@c.org"]},
        )
        for value in positives:
            with self.subTest(value=value):
                self.assertTrue(_contains_profile_identifier(value))

    def test_contains_profile_identifier_ignores_benign_values(self):
        for value in ({"role_level": "manager"}, ["own work"], "employee", 42, None, 1.5):
            with self.subTest(value=value):
                self.assertFalse(_contains_profile_identifier(value))


class StructuralPayloadAcceptTests(unittest.TestCase):
    def test_minimal_payload_receives_structural_defaults(self):
        payload = minimal_payload()
        normalized = _payload(payload)
        self.assertEqual(normalized["population_size"], 8)
        self.assertEqual(normalized["generator_backend"], "structural")
        self.assertEqual(
            normalized["readiness_policy"],
            {
                "require_standard": True,
                "require_stress": True,
                "blocking_severities": ["critical"],
            },
        )
        self.assertEqual(normalized["prior_virtual_run_ids"], [])
        self.assertEqual(normalized["stress_faults"], [])
        self.assertEqual(normalized["synthetic_population"], {})
        self.assertNotIn("sampling_seed", normalized)
        self.assertNotIn("respondent_profiles", normalized)
        self.assertNotIn("llm_backend", normalized)
        self.assertEqual(normalized["protocol"], payload["protocol"])
        self.assertIsNot(normalized["protocol"], payload["protocol"])

    def test_full_structural_payload_is_normalized_without_mutating_input(self):
        payload = base_payload(
            scenario_class="STRESS",
            stress_faults=["required_missing", "unknown"],
            prior_virtual_run_ids=["RUN-1"],
            synthetic_population={
                "composition_intent": "mixed",
                "scenario_dimensions": ["branching"],
                "forbidden_inference_dimensions": ["real-person-identity"],
            },
            purpose="Check branching",
            readiness_policy={
                "require_standard": False,
                "require_stress": True,
                "blocking_severities": ["minor", "major"],
            },
        )
        original = deepcopy(payload)
        normalized = _payload(payload)
        self.assertEqual(payload, original)
        self.assertEqual(normalized["scenario_class"], "STRESS")
        self.assertEqual(normalized["stress_faults"], ["required_missing", "unknown"])
        self.assertEqual(normalized["prior_virtual_run_ids"], ["RUN-1"])
        self.assertEqual(normalized["population_size"], 6)
        self.assertEqual(normalized["sampling_seed"], 41)
        self.assertEqual(normalized["purpose"], "Check branching")
        self.assertEqual(
            normalized["synthetic_population"],
            payload["synthetic_population"],
        )
        self.assertFalse(normalized["readiness_policy"]["require_standard"])

    def test_material_revision_protocol_requires_and_keeps_decision_id(self):
        payload = base_payload()
        payload["protocol"].update(
            material_revision=True, material_revision_decision_id="DEC-PROTOCOL-MAT-1"
        )
        normalized = _payload(payload)
        self.assertEqual(
            normalized["protocol"]["material_revision_decision_id"], "DEC-PROTOCOL-MAT-1"
        )

    def test_boundary_values_are_accepted(self):
        for overrides in (
            {"population_size": 1},
            {"population_size": 128},
            {"core_method_revision": 0},
            {"prior_virtual_run_ids": [f"RUN-{i}" for i in range(16)]},
        ):
            with self.subTest(overrides=overrides):
                _payload(base_payload(**overrides))


class StructuralPayloadRejectTests(unittest.TestCase):
    def assert_rejected(self, payload, message, code=PAYLOAD_CODE):
        with self.assertRaises(LocalApplicationError) as caught:
            _payload(payload)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.message, message)

    def test_non_mapping_payload(self):
        self.assert_rejected(
            ["not", "a", "mapping"],
            "virtual_runner.survey.execute payload must be an object",
        )

    def test_unknown_fields_are_listed_sorted(self):
        self.assert_rejected(
            base_payload(zeta=1, commit_id="C-1"),
            "unsupported or authority-like Virtual Runner payload fields: commit_id, zeta",
        )

    def test_missing_fields_are_listed_sorted(self):
        payload = base_payload()
        del payload["run_spec_id"]
        del payload["protocol"]
        self.assert_rejected(
            payload, "missing Virtual Runner payload fields: protocol, run_spec_id"
        )

    def test_scenario_class(self):
        self.assert_rejected(
            base_payload(scenario_class="REAL"), "scenario_class must be STANDARD or STRESS"
        )

    def test_blank_identifiers(self):
        for field in ("instrument_id", "core_method_id", "run_spec_id"):
            with self.subTest(field=field):
                self.assert_rejected(
                    base_payload(**{field: " "}), f"{field} must be a non-empty string"
                )

    def test_versions_must_be_semver(self):
        for field in ("instrument_version", "run_spec_version"):
            for value in ("1.0", "01.0.0", "v1.0.0"):
                with self.subTest(field=field, value=value):
                    self.assert_rejected(base_payload(**{field: value}), f"{field} must be SemVer")

    def test_instrument_digest_shape(self):
        self.assert_rejected(
            base_payload(instrument_digest="sha256:" + "A" * 64),
            "instrument_digest must be a sha256 digest",
        )

    def test_core_method_revision(self):
        for value in (-1, True, "0", 1.0):
            with self.subTest(value=value):
                self.assert_rejected(
                    base_payload(core_method_revision=value),
                    "core_method_revision must be a non-negative integer",
                )

    def test_protocol_shape(self):
        message = (
            "protocol must carry exact id/version/digest plus material-revision metadata; "
            "approval is derived from the approved Core Method"
        )
        good = base_payload()["protocol"]
        missing = dict(good)
        del missing["material_revision"]
        for protocol in ("ref", {**good, "approval_status": "approved"}, missing):
            with self.subTest(protocol=protocol):
                self.assert_rejected(base_payload(protocol=protocol), message)

    def test_protocol_fields(self):
        good = base_payload()["protocol"]
        cases = (
            ({"protocol_id": ""}, "protocol.protocol_id must be a non-empty string"),
            ({"version": "1"}, "protocol version/content_digest are invalid"),
            ({"content_digest": "sha256:xyz"}, "protocol version/content_digest are invalid"),
            ({"material_revision": "no"}, "protocol.material_revision must be boolean"),
            (
                {"material_revision": True},
                "protocol.material_revision_decision_id must be a non-empty string",
            ),
        )
        for change, message in cases:
            with self.subTest(change=change):
                self.assert_rejected(base_payload(protocol={**good, **change}), message)

    def test_evidence_gap_refs_shape(self):
        message = "evidence_gap_refs must contain exact Research Method Evidence Gap references"
        gap = base_payload()["evidence_gap_refs"][0]
        for gaps in ([], "GAP-1", [{**gap, "extra": 1}], ["GAP-1"]):
            with self.subTest(gaps=gaps):
                self.assert_rejected(base_payload(evidence_gap_refs=gaps), message)

    def test_evidence_gap_ref_fields(self):
        gap = base_payload()["evidence_gap_refs"][0]
        self.assert_rejected(
            base_payload(evidence_gap_refs=[gap, {**gap, "source_handoff_id": ""}]),
            "evidence_gap_refs[1].source_handoff_id must be a non-empty string",
        )
        self.assert_rejected(
            base_payload(evidence_gap_refs=[{**gap, "source_handoff_digest": "sha256:1"}]),
            "evidence_gap_refs[0].source_handoff_digest is invalid",
        )

    def test_population_size(self):
        for value in (0, 129, True, "8"):
            with self.subTest(value=value):
                self.assert_rejected(
                    base_payload(population_size=value),
                    "population_size must be an integer from 1 through 128",
                )

    def test_stress_faults(self):
        self.assert_rejected(
            base_payload(stress_faults=["required_missing", "required_missing"]),
            "stress_faults must be an array of unique non-empty strings",
        )
        self.assert_rejected(
            base_payload(stress_faults=["meltdown"]),
            "stress_faults contains an unsupported structural fault",
        )

    def test_prior_virtual_run_ids(self):
        self.assert_rejected(
            base_payload(prior_virtual_run_ids=[f"RUN-{i}" for i in range(17)]),
            "prior_virtual_run_ids may contain at most 16 Run IDs",
        )
        self.assert_rejected(
            base_payload(prior_virtual_run_ids="RUN-1"),
            "prior_virtual_run_ids must be an array of unique non-empty strings",
        )

    def test_readiness_policy(self):
        good = base_payload()["readiness_policy"]
        for policy in (
            "strict",
            {"require_standard": True, "require_stress": True},
            {**good, "require_standard": 1},
            {**good, "require_stress": None},
        ):
            with self.subTest(policy=policy):
                self.assert_rejected(
                    base_payload(readiness_policy=policy), "readiness_policy is invalid"
                )
        self.assert_rejected(
            base_payload(readiness_policy={**good, "blocking_severities": "critical"}),
            "readiness_policy.blocking_severities must be an array of unique non-empty strings",
        )
        self.assert_rejected(
            base_payload(readiness_policy={**good, "blocking_severities": ["fatal"]}),
            "readiness_policy.blocking_severities contains an unsupported severity",
        )

    def test_synthetic_population(self):
        message = "synthetic_population may configure only structural test dimensions"
        for synth in ("x", {"persona": "CEO"}):
            with self.subTest(synth=synth):
                self.assert_rejected(base_payload(synthetic_population=synth), message)
        self.assert_rejected(
            base_payload(synthetic_population={"composition_intent": ""}),
            "synthetic_population.composition_intent must be a non-empty string",
        )
        self.assert_rejected(
            base_payload(synthetic_population={"scenario_dimensions": ["a", "a"]}),
            "synthetic_population.scenario_dimensions must be an array of unique non-empty strings",
        )

    def test_generator_backend(self):
        for value in ("gpt", ["llm"]):
            with self.subTest(value=value):
                self.assert_rejected(
                    base_payload(generator_backend=value),
                    "generator_backend must be structural or llm",
                )

    def test_minimum_valid_response_count_checked_before_backend(self):
        for value in (0, True, "1"):
            with self.subTest(value=value):
                self.assert_rejected(
                    base_payload(minimum_valid_response_count=value),
                    "minimum_valid_response_count must be a positive integer",
                )

    def test_llm_fields_are_rejected_for_structural_backend(self):
        message = "LLM respondent fields are only valid when generator_backend=llm"
        for overrides in (
            {"respondent_profiles": [{"profile_id": "SYN-PROFILE-A"}]},
            {"llm_backend": {}},
            {"analysis_items": []},
            {"minimum_valid_response_count": 1},
        ):
            with self.subTest(overrides=overrides):
                self.assert_rejected(base_payload(**overrides), message)

    def test_blank_purpose(self):
        self.assert_rejected(base_payload(purpose=" "), "purpose must be a non-empty string")


class LlmPayloadAcceptTests(unittest.TestCase):
    def test_llm_payload_receives_backend_defaults(self):
        payload = llm_payload()
        normalized = _payload(payload)
        self.assertEqual(normalized["generator_backend"], "llm")
        self.assertEqual(normalized["population_size"], 2)
        self.assertEqual(normalized["minimum_valid_response_count"], 1)
        self.assertIsNone(normalized["analysis_items"])
        self.assertEqual(
            normalized["llm_backend"],
            {
                "backend_id": "openai_responses",
                "model_id": "gpt-test",
                "credential_env": "OPENAI_API_KEY",
                "endpoint": "https://api.openai.com/v1/responses",
                "timeout_seconds": 30,
                "max_transport_retries": 1,
                "max_repair_attempts": 1,
            },
        )
        self.assertEqual(
            normalized["respondent_profiles"],
            [
                {
                    "profile_id": "SYN-PROFILE-A",
                    "attributes": {"role_level": "manager"},
                    "knowledge_scope": ["own work"],
                },
                {
                    "profile_id": "SYN-PROFILE-B",
                    "attributes": {},
                    "knowledge_scope": [],
                    "scenario_notes": "joined recently",
                },
            ],
        )
        self.assertNotIn("endpoint", payload["llm_backend"])

    def test_llm_payload_with_explicit_options(self):
        payload = llm_payload(
            population_size=2,
            minimum_valid_response_count=2,
            analysis_items=[{"item_id": "X"}],
            llm_backend={
                "backend_id": "openai_responses",
                "model_id": "gpt-test",
                "temperature": 2,
                "top_p": 0.0,
                "max_output_tokens": 1,
                "timeout_seconds": 0.5,
                "max_transport_retries": 0,
                "max_repair_attempts": 0,
            },
        )
        payload["respondent_profiles"][1]["scenario_notes"] = None
        normalized = _payload(payload)
        self.assertEqual(normalized["minimum_valid_response_count"], 2)
        self.assertEqual(normalized["analysis_items"], [{"item_id": "X"}])
        self.assertEqual(normalized["llm_backend"]["timeout_seconds"], 0.5)
        self.assertNotIn("scenario_notes", normalized["respondent_profiles"][1])


class LlmPayloadRejectTests(unittest.TestCase):
    def assert_rejected(self, payload, code, message):
        with self.assertRaises(LocalApplicationError) as caught:
            _payload(payload)
        self.assertEqual((caught.exception.code, caught.exception.message), (code, message))

    def test_llm_backend_requires_standard_without_faults(self):
        self.assert_rejected(
            llm_payload(scenario_class="STRESS"),
            PAYLOAD_CODE,
            "LLM Virtual Respondent backend currently supports scenario_class STANDARD only",
        )
        self.assert_rejected(
            llm_payload(stress_faults=["unknown"]),
            PAYLOAD_CODE,
            "stress_faults belong to the structural generator and are not accepted by the LLM backend",
        )

    def test_profile_count_bounds(self):
        message = (
            "respondent_profiles must contain 1 through 8 explicit synthetic profiles "
            "for the bounded LLM backend"
        )
        too_many = [{"profile_id": f"SYN-PROFILE-{i}"} for i in range(9)]
        for profiles in ([], "SYN-PROFILE-A", too_many):
            with self.subTest(profiles=profiles):
                self.assert_rejected(
                    llm_payload(respondent_profiles=profiles), "PROFILE_INVALID", message
                )

    def test_profile_shape_and_ids(self):
        cases = (
            (
                [{"profile_id": "SYN-PROFILE-A", "name": "x"}],
                "respondent_profiles[0] has unsupported fields",
            ),
            (["SYN-PROFILE-A"], "respondent_profiles[0] has unsupported fields"),
            (
                [{"profile_id": "PROFILE-A"}],
                "synthetic profile IDs must be unique and use the SYN-PROFILE- namespace",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A"}, {"profile_id": "SYN-PROFILE-A"}],
                "synthetic profile IDs must be unique and use the SYN-PROFILE- namespace",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A", "attributes": ["x"]}],
                "respondent_profiles[0].attributes must be an object",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A", "attributes": {"email": "x"}}],
                "synthetic profiles must not contain direct real-person identifiers",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A", "knowledge_scope": "own work"}],
                "respondent_profiles[0].knowledge_scope must be an array of strings",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A", "knowledge_scope": [" "]}],
                "respondent_profiles[0].knowledge_scope must be an array of strings",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A", "knowledge_scope": ["mail a@b.io"]}],
                "synthetic profile free text must not contain direct real-person identifiers",
            ),
            (
                [{"profile_id": "SYN-PROFILE-A", "scenario_notes": "employee number 12345"}],
                "synthetic profile free text must not contain direct real-person identifiers",
            ),
        )
        for profiles, message in cases:
            with self.subTest(message=message, profiles=profiles):
                self.assert_rejected(
                    llm_payload(respondent_profiles=profiles), "PROFILE_INVALID", message
                )

    def test_blank_profile_id_and_notes_use_payload_code(self):
        self.assert_rejected(
            llm_payload(respondent_profiles=[{"profile_id": ""}]),
            PAYLOAD_CODE,
            "respondent_profiles[0].profile_id must be a non-empty string",
        )
        self.assert_rejected(
            llm_payload(
                respondent_profiles=[{"profile_id": "SYN-PROFILE-A", "scenario_notes": ""}]
            ),
            PAYLOAD_CODE,
            "respondent_profiles[0].scenario_notes must be a non-empty string",
        )

    def test_population_size_must_match_profiles(self):
        self.assert_rejected(
            llm_payload(population_size=3),
            "PROFILE_INVALID",
            "population_size must equal the number of explicit respondent_profiles for the LLM backend",
        )

    def test_minimum_valid_cannot_exceed_profiles(self):
        self.assert_rejected(
            llm_payload(minimum_valid_response_count=3),
            "PROFILE_INVALID",
            "minimum_valid_response_count cannot exceed respondent profile count",
        )

    def test_analysis_items_must_be_list(self):
        self.assert_rejected(
            llm_payload(analysis_items={"item_id": "X"}),
            PAYLOAD_CODE,
            "analysis_items must be an array when supplied",
        )

    def test_backend_configuration_presence_and_identity(self):
        for backend in (None, {"backend_id": "openai_responses", "model_id": "m", "api_key": "x"}):
            with self.subTest(backend=backend):
                self.assert_rejected(
                    llm_payload(llm_backend=backend),
                    "BACKEND_UNAVAILABLE",
                    "llm_backend configuration is missing or contains unsupported fields",
                )
        self.assert_rejected(
            llm_payload(llm_backend={"backend_id": "anthropic", "model_id": "m"}),
            "BACKEND_UNAVAILABLE",
            "only the openai_responses production backend is configured",
        )
        self.assert_rejected(
            llm_payload(llm_backend={"backend_id": "", "model_id": "m"}),
            PAYLOAD_CODE,
            "llm_backend.backend_id must be a non-empty string",
        )
        self.assert_rejected(
            llm_payload(llm_backend={"backend_id": "openai_responses"}),
            PAYLOAD_CODE,
            "llm_backend.model_id must be a non-empty string",
        )

    def test_backend_trust_boundaries(self):
        base = {"backend_id": "openai_responses", "model_id": "m"}
        self.assert_rejected(
            llm_payload(llm_backend={**base, "credential_env": "OTHER_KEY"}),
            "BACKEND_UNAVAILABLE",
            "llm_backend.credential_env is not allowed",
        )
        self.assert_rejected(
            llm_payload(llm_backend={**base, "endpoint": "https://example.test/v1"}),
            "BACKEND_UNAVAILABLE",
            "llm_backend.endpoint is not allowed",
        )

    def test_backend_numeric_bounds(self):
        base = {"backend_id": "openai_responses", "model_id": "m"}
        cases = (
            (
                {"max_transport_retries": 2},
                "llm_backend.max_transport_retries must be 0 or 1 for the bounded LLM backend",
            ),
            (
                {"max_repair_attempts": True},
                "llm_backend.max_repair_attempts must be 0 or 1 for the bounded LLM backend",
            ),
            (
                {"timeout_seconds": 0},
                "llm_backend.timeout_seconds must be greater than 0 and at most 30",
            ),
            (
                {"timeout_seconds": 31},
                "llm_backend.timeout_seconds must be greater than 0 and at most 30",
            ),
            (
                {"timeout_seconds": "10"},
                "llm_backend.timeout_seconds must be greater than 0 and at most 30",
            ),
            ({"temperature": "hot"}, "llm_backend.temperature must be numeric when supplied"),
            ({"top_p": False}, "llm_backend.top_p must be numeric when supplied"),
            ({"temperature": 2.5}, "llm_backend.temperature must be between 0 and 2"),
            ({"top_p": 1.1}, "llm_backend.top_p must be between 0 and 1"),
            ({"max_output_tokens": 0}, "llm_backend.max_output_tokens must be a positive integer"),
            (
                {"max_output_tokens": 1.5},
                "llm_backend.max_output_tokens must be a positive integer",
            ),
        )
        for change, message in cases:
            with self.subTest(change=change):
                self.assert_rejected(
                    llm_payload(llm_backend={**base, **change}), PAYLOAD_CODE, message
                )


if __name__ == "__main__":
    unittest.main()
