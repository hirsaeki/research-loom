from __future__ import annotations

from copy import deepcopy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from research_method_oracle import canonical_digest, context_error, descriptor_error, result_error

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages"
RM = PKG / "research-method"
FIX = ROOT / "core/fixtures/capabilities/valid"
CONV = ROOT / "core/fixtures/conversation/valid"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def refresh(document):
    document["extension_digest"] = canonical_digest(document, "extension_digest")


class ResearchMethodContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.descriptor_schema = load(PKG / "capability-descriptor.schema.json")
        cls.context_pack_schema = load(PKG / "capability-context-pack.schema.json")
        cls.context_schema = load(RM / "research-method-context-extension.schema.json")
        cls.result_schema = load(RM / "research-method-result-extension.schema.json")
        cls.conversation_schema = load(PKG / "work-conversation.schema.json")
        cls.descriptor = load(FIX / "generic-research-method-capability-descriptor.json")
        cls.context = load(FIX / "generic-research-method-context-pack.json")
        cls.gap_handoff = load(FIX / "generic-capability-handoff.json")
        cls.context_extension = load(FIX / "generic-research-method-context-extension.json")
        cls.result_extension = load(FIX / "generic-research-method-result-extension.json")
        cls.routing = load(CONV / "research-method-routing.json")

    def _context_error(self, extension, mode="real", handoff=None, context=None):
        return context_error(
            self.context if context is None else context,
            extension,
            mode,
            [self.gap_handoff if handoff is None else handoff],
        )

    def test_schemas_and_semantics_catalog(self):
        Draft202012Validator.check_schema(self.context_schema)
        Draft202012Validator.check_schema(self.result_schema)
        semantics = yaml.safe_load((RM / "research-method-semantics.yaml").read_text(encoding="utf-8"))
        self.assertEqual(semantics["handoff"]["canonical_wire_format"], "capability-handoff@0.1.0")
        self.assertFalse(semantics["method_authority"]["capability_self_adopts_method"])
        self.assertFalse(semantics["conversation_boundary"]["confirmation_is_human_decision"])
        self.assertEqual(len({e["id"] for e in semantics["errors"]}), len(semantics["errors"]))

    def test_descriptor_conventions_and_digest(self):
        errors = list(Draft202012Validator(self.descriptor_schema).iter_errors(self.descriptor))
        self.assertEqual(errors, [])
        self.assertEqual(descriptor_error(self.descriptor), None)
        self.assertEqual(self.descriptor["descriptor_digest"], canonical_digest(self.descriptor, "descriptor_digest"))

    def test_valid_real_execute_context(self):
        pack_errors = list(Draft202012Validator(self.context_pack_schema, format_checker=FormatChecker()).iter_errors(self.context))
        self.assertEqual(pack_errors, [])
        self.assertEqual(self.context["context_pack_digest"], canonical_digest(self.context, "context_pack_digest"))
        errors = list(Draft202012Validator(self.context_schema).iter_errors(self.context_extension))
        self.assertEqual(errors, [])
        self.assertEqual(self._context_error(self.context_extension), None)

    def test_evidence_gap_target_is_required_and_source_bound(self):
        case = deepcopy(self.context_extension)
        case["targets"]["evidence_gap_refs"] = []
        refresh(case)
        errors = list(Draft202012Validator(self.context_schema).iter_errors(case))
        self.assertTrue(errors)

        case = deepcopy(self.context_extension)
        case["targets"]["evidence_gap_refs"][0]["gap_id"] = "GAP-NOT-THERE"
        refresh(case)
        self.assertEqual(self._context_error(case), "RM-CONTEXT-BINDING-001")

        case = deepcopy(self.context_extension)
        case["targets"]["evidence_gap_refs"][0]["source_handoff_digest"] = "sha256:" + "0" * 64
        refresh(case)
        self.assertEqual(self._context_error(case), "RM-CONTEXT-BINDING-001")

        context = deepcopy(self.context)
        context["resources"][0]["digest"] = "sha256:" + "0" * 64
        context["context_pack_digest"] = canonical_digest(context, "context_pack_digest")
        case = deepcopy(self.context_extension)
        case["context_binding"]["context_pack_digest"] = context["context_pack_digest"]
        refresh(case)
        self.assertEqual(self._context_error(case, context=context), "RM-CONTEXT-BINDING-001")

        source_handoff = deepcopy(self.gap_handoff)
        source_handoff["outputs"]["evidence_gaps"][0]["statement"] = "Tampered after the Handoff digest was computed."
        # Keep all Context Pack bindings valid and do not refresh handoff_digest:
        # only RFC 8785 Handoff digest recomputation should detect this mutation.
        self.assertEqual(self._context_error(self.context_extension, handoff=source_handoff), "RM-CONTEXT-BINDING-001")

    def test_schema_enforces_function_specific_inputs(self):
        validator = Draft202012Validator(self.context_schema)

        def assert_rule(document, validator_name, path):
            errors = list(validator.iter_errors(document))
            self.assertTrue(
                any(error.validator == validator_name and list(error.absolute_path) == path for error in errors),
                [f"{error.validator}:{list(error.absolute_path)}:{error.message}" for error in errors],
            )

        execute = deepcopy(self.context_extension)
        execute["run_spec"] = None
        refresh(execute)
        assert_rule(execute, "not", ["run_spec"])

        instrument_control = deepcopy(execute)
        instrument_control["function_id"] = "instrument_design"
        refresh(instrument_control)
        self.assertEqual(list(validator.iter_errors(instrument_control)), [])

        method_design = deepcopy(self.context_extension)
        method_design["function_id"] = "method_design"
        method_design["run_spec"] = None
        method_design["prior_run_result_refs"] = [{"id":"RRES-OLD","version":"1.0.0","content_digest":"sha256:"+"c"*64}]
        refresh(method_design)
        assert_rule(method_design, "maxItems", ["prior_run_result_refs"])

        analyze_control = deepcopy(method_design)
        analyze_control["function_id"] = "analyze"
        refresh(analyze_control)
        self.assertEqual(list(validator.iter_errors(analyze_control)), [])

        analyze = deepcopy(self.context_extension)
        analyze["function_id"] = "analyze"
        analyze["prior_run_result_refs"] = []
        refresh(analyze)
        assert_rule(analyze, "minItems", ["prior_run_result_refs"])

        execute_control = deepcopy(analyze)
        execute_control["function_id"] = "execute"
        refresh(execute_control)
        self.assertEqual(list(validator.iter_errors(execute_control)), [])

    def test_real_execute_requires_adopted_method_and_human_decisions(self):
        case = deepcopy(self.context_extension)
        case["method_basis"]["core_method_ref"]["adoption_state"] = "candidate"
        refresh(case)
        self.assertEqual(self._context_error(case), "RM-REAL-EXECUTION-001")

        case = deepcopy(self.context_extension)
        case["human_decision_bindings"]["method_adoption_decision_ids"] = []
        refresh(case)
        self.assertEqual(self._context_error(case), "RM-METHOD-DECISION-001")

        case = deepcopy(self.context_extension)
        case["human_decision_bindings"]["material_protocol_revision_decision_ids"] = []
        refresh(case)
        self.assertEqual(self._context_error(case), "RM-PROTOCOL-DECISION-001")

    def test_virtual_execute_may_test_candidate_design(self):
        case = deepcopy(self.context_extension)
        case["method_basis"] = {"method_design_ref":{"method_design_id":"MD-1","version":"0.1.0","content_digest":"sha256:"+"b"*64,"authoritative_method":False}}
        case["protocol_basis"]["approval_status"] = "candidate"
        case["human_decision_bindings"] = {"method_adoption_decision_ids":[],"material_protocol_revision_decision_ids":[]}
        refresh(case)
        self.assertEqual(self._context_error(case, "virtual"), None)

    def test_instrument_design_requires_method_and_protocol(self):
        validator = Draft202012Validator(self.context_schema)
        instrument = deepcopy(self.context_extension)
        instrument["function_id"] = "instrument_design"
        instrument["run_spec"] = None
        refresh(instrument)
        self.assertEqual(list(validator.iter_errors(instrument)), [])
        self.assertEqual(self._context_error(instrument), None)

        missing_method = deepcopy(instrument)
        missing_method["method_basis"] = None
        refresh(missing_method)
        method_errors = list(validator.iter_errors(missing_method))
        self.assertTrue(any(error.validator == "not" and list(error.absolute_path) == ["method_basis"] for error in method_errors), method_errors)
        self.assertEqual(self._context_error(missing_method), "RM-FUNCTION-001")

        missing_protocol = deepcopy(instrument)
        missing_protocol["protocol_basis"] = None
        refresh(missing_protocol)
        protocol_errors = list(validator.iter_errors(missing_protocol))
        self.assertTrue(any(error.validator == "not" and list(error.absolute_path) == ["protocol_basis"] for error in protocol_errors), protocol_errors)
        self.assertEqual(self._context_error(missing_protocol), "RM-FUNCTION-001")

    def test_function_specific_inputs(self):
        case = deepcopy(self.context_extension)
        case["function_id"] = "analyze"
        refresh(case)
        self.assertEqual(self._context_error(case), "RM-FUNCTION-001")
        case["prior_run_result_refs"] = [{"id":"RRES-OLD","version":"1.0.0","content_digest":"sha256:"+"c"*64}]
        refresh(case)
        self.assertEqual(self._context_error(case), None)

    def _handoff(self, mode="real", function_id="execute"):
        return {
            "handoff_id":"HND-RM-001","handoff_digest":"sha256:"+"8"*64,"invocation_id":"INV-RM-001","run_id":"RUN-RM-001",
            "capability":{"capability_id":"fixture.research-method","function_id":function_id},"execution_mode":mode,
            "outputs":{"candidate_findings":[{"candidate_finding_id":"CFND-RM-1"}],"candidate_next_actions":[{"proposal_id":"NA-RM-1"}],"candidate_next_methods":[{"proposal_id":"NM-RM-1"}]}
        }

    def test_result_schema_binding_raw_data_and_candidates(self):
        validator = Draft202012Validator(self.result_schema, format_checker=FormatChecker())
        self.assertEqual(list(validator.iter_errors(self.result_extension)), [])
        self.assertEqual(result_error(self.result_extension, self._handoff(), self.context, self.context_extension), None)

    def test_result_function_mismatch_is_stable_binding_error(self):
        case = deepcopy(self.context_extension)
        case["function_id"] = "method_design"
        case["protocol_basis"] = None
        case["run_spec"] = None
        refresh(case)
        self.assertEqual(result_error(self.result_extension, self._handoff(), self.context, case), "RM-RESULT-BINDING-001")

    def test_result_requires_exact_runspec_and_protocol_identity(self):
        case = deepcopy(self.result_extension)
        case["run_results"][0]["run_spec_ref"]["id"] = "RSPEC-OTHER"
        refresh(case)
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-PROTOCOL-001")

        case = deepcopy(self.result_extension)
        case["run_results"][0]["protocol_ref"]["version"] = "9.9.9"
        refresh(case)
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-PROTOCOL-001")

    def test_virtual_or_synthetic_cannot_be_empirical(self):
        self.assertEqual(result_error(self.result_extension, self._handoff("virtual"), self.context, self.context_extension), "RM-EPISTEMIC-MODE-001")
        case = deepcopy(self.result_extension)
        case["run_results"][0]["raw_data_refs"][0]["epistemic_mode"] = "synthetic"
        refresh(case)
        self.assertEqual(result_error(case, self._handoff("virtual"), self.context, self.context_extension), None)

    def test_partial_failed_runs_preserve_missingness_or_limitations(self):
        case = deepcopy(self.result_extension)
        case["run_results"][0]["missing_data"] = []
        case["run_results"][0]["validity_report"]["limitations"] = []
        case["run_results"][0]["validity_report"]["threats"] = []
        refresh(case)
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-COMPLETION-001")

    def test_raw_data_and_analysis_never_auto_adopt(self):
        case = deepcopy(self.result_extension)
        case["run_results"][0]["raw_data_refs"][0]["evidence_adoption_performed"] = True
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-RESULT-DIGEST-001")
        refresh(case)
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-RAW-EVIDENCE-001")

        case = deepcopy(self.result_extension)
        case["candidate_analyses"][0]["core_analysis_adoption_performed"] = True
        refresh(case)
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-ANALYSIS-001")

    def test_pr9_candidate_reference_sets_are_exact(self):
        case = deepcopy(self.result_extension)
        case["candidate_next_action_ids"] = []
        refresh(case)
        self.assertEqual(result_error(case, self._handoff(), self.context, self.context_extension), "RM-HANDOFF-CANDIDATE-001")

    def test_pr10_routing_preserves_human_decision_boundary(self):
        proposal = self.routing["action_proposal"]
        validator = Draft202012Validator(self.conversation_schema, format_checker=FormatChecker())
        self.assertEqual(list(validator.iter_errors(proposal)), [])
        self.assertEqual(proposal["route"]["invocation_contract"], "capability-invocation@0.1.0")
        self.assertEqual(proposal["route"]["capability"]["function_id"], "execute")
        self.assertEqual(proposal["route"]["execution_mode"], "real")
        self.assertTrue(proposal["human_decision_boundary"]["required"])
        self.assertFalse(proposal["human_decision_boundary"]["confirmation_is_human_decision"])
        self.assertEqual(set(proposal["human_decision_boundary"]["decision_reference_ids"]), {"DEC-METHOD-1","DEC-PROTOCOL-1"})
        self.assertEqual(proposal["route"]["context_pack"]["context_pack_id"], self.context["context_pack_id"])
        self.assertEqual(proposal["route"]["context_pack"]["context_pack_digest"], self.context["context_pack_digest"])
        self.assertEqual(proposal["action"]["payload"]["context_extension_digest"], self.context_extension["extension_digest"])


if __name__ == "__main__":
    unittest.main()
