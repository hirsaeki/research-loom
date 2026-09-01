from __future__ import annotations

from typing import Any, Mapping

from core.execution import ExecutionStyle
from core.execution.models import CapabilityExecutionError

from .generation import generate_records
from .output_builder import build_output
from .provenance import build_virtual_context, generation_provenance, input_pins
from .response_validation import SurveyResponseValidator
from .runtime_state import (
    candidate_change_requests,
    defects_from_issues,
    expected_issue_codes,
    prior_scenarios,
    readiness_assessment,
)


class StructuralSurveyVirtualRunnerAdapter:
    """Managed structural Survey binding for the canonical Virtual Runner backend."""

    implementation_id = "plugin.survey-virtual-runner.structural"
    implementation_version = "0.1.0"
    capability_id = "virtual-runner"
    capability_version = "0.1.0"
    supported_functions = ("execute",)
    supported_execution_modes = ("virtual",)
    execution_style = ExecutionStyle.MANAGED
    requires_context_extension = True

    def __init__(self, *, execution_store, clock) -> None:
        self._execution_store = execution_store
        self._clock = clock

    def execute(self, request):
        extension = getattr(request, "context_extension", None)
        if not isinstance(extension, Mapping):
            raise CapabilityExecutionError(
                "VR-CONTEXT-BINDING-001",
                "Survey Virtual Runner requires its validated immutable Context extension",
            )
        questionnaire = extension.get("instrument")
        population = extension.get("synthetic_population")
        runner_configuration = extension.get("runner_configuration")
        if not isinstance(questionnaire, Mapping) or not isinstance(population, Mapping) or not isinstance(runner_configuration, Mapping):
            raise CapabilityExecutionError(
                "VR-CONTEXT-BINDING-001",
                "Survey Virtual Runner immutable execution inputs are incomplete",
            )

        provenance = generation_provenance(request, extension)
        build_virtual_context(request, extension, provenance)
        pins = input_pins(request, extension, provenance)
        prior = prior_scenarios(
            self._execution_store,
            runner_configuration.get("prior_virtual_run_ids", ()),
            current_pins=pins,
        )

        records, injected = generate_records(
            questionnaire,
            scenario_class=str(extension["scenario_class"]),
            population_size=int(population["population_size"]),
            identity_namespace=str(population["identity_namespace"]),
            stress_faults=runner_configuration.get("stress_faults", ()),
        )
        validation = SurveyResponseValidator().validate(
            questionnaire,
            records,
            expected_epistemic_mode="virtual",
            expected_identity_namespace=str(population["identity_namespace"]),
        )
        expected = expected_issue_codes(injected)
        defects = defects_from_issues(
            validation["issues"],
            run_id=str(request.run.run_id),
            instrument_id=str(extension["instrument_ref"]["id"]),
            expected_codes=expected,
        )
        changes = candidate_change_requests(defects)
        warnings = [
            f"preserved {item['kind']}: {item['detail']}"
            for item in validation["preservation_events"]
            if item["kind"] in {"unknown", "not_applicable", "prefer_not_to_answer"}
        ]
        if any(item.get("disposition") == "open" for item in defects):
            warnings.append("one or more unexpected Virtual Runner defects remain open")
        readiness = readiness_assessment(
            scenario_class=str(extension["scenario_class"]),
            prior=prior,
            defects=defects,
            policy=runner_configuration["readiness_policy"],
        )
        return build_output(
            request,
            extension,
            records=records,
            validation=validation,
            defects=defects,
            warnings=warnings,
            change_requests=changes,
            readiness=readiness,
            provenance=provenance,
            pins=pins,
        )

    def cancel(self, run_id: str) -> None:
        del run_id
        return None
