from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from core.conversation import CapabilityMaterialization, canonical_digest
from core.execution import CapabilityContextExtensionRegistry, CapabilityExecutionService, CapabilityRegistry
from core.runtime import CapabilityNormalizationBoundary
from plugins.local_application.facade import LocalApplicationError, _jsonable
from plugins.local_survey_store import LocalSurveyStoreError
from plugins.survey_virtual_runner.adapter import StructuralSurveyVirtualRunnerAdapter
from plugins.survey_virtual_runner.llm_adapter import LlmSurveyVirtualRunnerAdapter
from plugins.survey_virtual_runner.llm_backend import OpenAIResponsesVirtualRespondentBackend
from plugins.survey_virtual_runner.contracts import SurveyVirtualRunnerContextValidator
from plugins.survey_virtual_runner.normalization import SurveyVirtualRunnerNormalizer
from .virtual_runner_input import _payload

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR_PATH = ROOT / "core/packages/virtual-runner/virtual-runner-capability-descriptor.json"


class VirtualRunnerExecuteMixin:
    def _virtual_respondent_backend(self, payload: Mapping[str, Any]):
        del payload
        return OpenAIResponsesVirtualRespondentBackend()

    def run_survey_virtual(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = _payload(payload)
        state = self._state()
        try:
            record = self._survey_store().load_instrument(self._project_id, str(payload["instrument_id"]), str(payload["instrument_version"]))
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if record is None:
            raise LocalApplicationError("APPLICATION-SURVEY-INSTRUMENT-NOT-FOUND-001", "Survey Instrument revision was not found")
        questionnaire = record["questionnaire"]
        if questionnaire["content_digest"] != payload["instrument_digest"]:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "Instrument digest is stale or does not match the exact PR40 registry revision")
        design_ref = record["design_ref"]
        try:
            design_record = self._survey_store().load_design(self._project_id, str(design_ref["survey_design_id"]), str(design_ref["version"]))
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if design_record is None:
            raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "pinned Survey Design revision is missing")

        descriptor = json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))
        context_pack_id = self._application.ids.new("CTX-VR-")
        context, extension, _method = self._build_context(state, record, design_record, payload, context_pack_id=context_pack_id)

        registry = CapabilityRegistry()
        if payload.get("generator_backend") == "llm":
            adapter = LlmSurveyVirtualRunnerAdapter(
                execution_store=self._application.execution_store,
                clock=self._application.clock,
                backend=self._virtual_respondent_backend(payload),
            )
        else:
            adapter = StructuralSurveyVirtualRunnerAdapter(execution_store=self._application.execution_store, clock=self._application.clock)
        registry.register(adapter, descriptor)
        execution = CapabilityExecutionService(
            registry,
            self._application.execution_store,
            self._application.state_repository,
            self._application.authorization,
            self._application.execution_store,
            CapabilityNormalizationBoundary((SurveyVirtualRunnerNormalizer(),)),
            self._application.clock,
            artifact_store=self._application.execution_store,
            context_extension_registry=CapabilityContextExtensionRegistry((SurveyVirtualRunnerContextValidator(),)),
            context_extension_store=self._application.context_extension_store,
        )

        materialization = CapabilityMaterialization(descriptor=descriptor, context_pack=context, context_extension=extension, lineage_ref=state.lineage_ref, execution_mode="virtual")
        invocation_id = self._application.ids.new("INV-")
        run_id = self._application.ids.new("RUN-")
        proposal = {"project_id": self._project_id, "route": {"capability": {"capability_id": "virtual-runner", "capability_version": "0.1.0", "descriptor_digest": descriptor["descriptor_digest"], "function_id": "execute"}}}
        authorization = self._application.authorization.evidence_for(proposal, materialization, invocation_id=invocation_id, run_id=run_id)
        invocation = {
            "schema_version": "0.1.0",
            "invocation_id": invocation_id,
            "run_id": run_id,
            "project_id": self._project_id,
            "capability": deepcopy(proposal["route"]["capability"]),
            "execution_mode": "virtual",
            "context_pack": {"context_pack_id": context_pack_id, "context_pack_digest": context["context_pack_digest"]},
            "pins": deepcopy(context["pins"]),
            "runtime_authorization_evidence": deepcopy(dict(authorization)),
            "trace": {"trace_id": self._application.ids.new("TRACE-VR-")},
        }
        invocation["invocation_digest"] = canonical_digest(invocation)
        before = (str(state.current_snapshot["id"]), str(state.current_snapshot["content_digest"]))
        result = execution.execute_managed(descriptor, invocation, context, lineage_ref=state.lineage_ref, context_extension=extension)
        after_state = self._state()
        after = (str(after_state.current_snapshot["id"]), str(after_state.current_snapshot["content_digest"]))
        if before != after:
            raise LocalApplicationError("VR-EPISTEMIC-FIREWALL-001", "Virtual Runner execution mutated authoritative Research State")

        response_dataset = None
        analysis_spec = None
        aggregate_result = None
        completion_ok = result.run.status.value == "COMPLETED"
        if completion_ok:
            response_dataset = self.capture_virtual_run_response_dataset(
                run_id,
                instrument_ref={
                    "id": questionnaire["questionnaire_id"],
                    "version": questionnaire["version"],
                    "content_digest": questionnaire["content_digest"],
                },
            )
            if payload.get("generator_backend") == "llm":
                minimum_valid = int(payload.get("minimum_valid_response_count", 1))
                completion_ok = int(response_dataset["accepted_count"]) >= minimum_valid
                if completion_ok and hasattr(self, "capture_survey_analysis_spec") and hasattr(self, "run_survey_aggregation"):
                    analysis_spec = self.capture_survey_analysis_spec({
                        "dataset_id": response_dataset["dataset_id"],
                        "dataset_digest": response_dataset["content_digest"],
                        **({"analysis_items": deepcopy(payload["analysis_items"])} if payload.get("analysis_items") is not None else {}),
                    })
                    aggregate_result = self.run_survey_aggregation({
                        "analysis_spec_id": analysis_spec["analysis_spec_id"],
                        "analysis_spec_digest": analysis_spec["content_digest"],
                        "dataset_id": response_dataset["dataset_id"],
                        "dataset_digest": response_dataset["content_digest"],
                    })
        return {
            "status": "SUCCEEDED" if completion_ok else "ERROR",
            "project_id": self._project_id,
            "run_id": run_id,
            "execution_mode": "virtual",
            "scenario_class": payload["scenario_class"],
            "generator_backend": payload.get("generator_backend", "structural"),
            "instrument_pin": {"id": questionnaire["questionnaire_id"], "version": questionnaire["version"], "content_digest": questionnaire["content_digest"]},
            "execution_result": _jsonable(result),
            "response_dataset": response_dataset,
            "analysis_spec": analysis_spec,
            "aggregate_result": aggregate_result,
            "research_state_mutation_performed": False,
            "real_execution_started": False,
        }
