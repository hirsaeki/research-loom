from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from plugins.local_application.facade import LocalApplicationError


class VirtualRunnerInspectionMixin:
    def show_run(self, run_id: str) -> Mapping[str, Any]:
        result = deepcopy(dict(super().show_run(run_id)))
        run = result.get("run")
        if not isinstance(run, Mapping) or run.get("capability_id") != "virtual-runner":
            return result
        metas = [meta for meta in self._application.execution_store.artifacts_for(str(run_id)) if meta.role == "survey_virtual.virtual_runner_result"]
        if not metas and run.get("status") != "COMPLETED":
            return result
        if len(metas) != 1:
            raise LocalApplicationError("APPLICATION-RUN-INSPECTION-001", "completed Virtual Runner Run must have exactly one persisted result artifact")
        payload = self._application.execution_store.load_artifact(metas[0].artifact_id)
        try:
            extension = json.loads(payload.content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError("APPLICATION-RUN-INSPECTION-001", "Virtual Runner result artifact is unreadable") from exc
        if not isinstance(extension, Mapping):
            raise LocalApplicationError("APPLICATION-RUN-INSPECTION-001", "Virtual Runner result artifact is malformed")
        virtual_result = extension["virtual_runner_result"]
        result["virtual_runner"] = {
            "execution_mode": "virtual",
            "scenario_class": virtual_result["scenario_class"],
            "evidence_status": extension["evidence_status"],
            "completion_status": virtual_result["completion_status"],
            "input_pins": deepcopy(extension["input_pins"]),
            "synthetic_population": deepcopy(extension["synthetic_population"]),
            "generation_provenance": deepcopy(extension["generation_provenance"]),
            "synthetic_outputs": deepcopy(virtual_result["synthetic_outputs"]),
            "validation_failures": deepcopy(extension["validation_failures"]),
            "preservation_events": deepcopy(extension["preservation_events"]),
            "defects": deepcopy(extension["defects"]),
            "warnings": deepcopy(extension["warnings"]),
            "unresolved_ambiguities": deepcopy(virtual_result["unresolved_ambiguities"]),
            "candidate_change_requests": deepcopy(extension["candidate_change_requests"]),
            "readiness_assessment": deepcopy(extension["readiness_assessment"]),
            "execution_trace": deepcopy(virtual_result["execution_trace"]),
            "research_state_mutation_performed": False,
            "real_execution_started": False,
        }
        return result
