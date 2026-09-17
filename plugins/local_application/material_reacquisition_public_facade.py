from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from plugins.local_execution_store import result_extensions_for_run

from .historical_result_recovery_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .material_reacquisition_facade import material_recovery_action_guidance


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Final public facade for bounded historical material reacquisition guidance."""

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        result = deepcopy(dict(super().show_run(run_id)))
        recovery = result.get("finding_recovery")
        if not isinstance(recovery, Mapping):
            return result
        if recovery.get("recovery_failure_class") != "material_recovery_required":
            return result
        failure_details = recovery.get("recovery_failure_details")
        if not isinstance(failure_details, Mapping):
            return result
        enriched_recovery = deepcopy(dict(recovery))
        enriched_details = deepcopy(dict(failure_details))
        capture_id = enriched_details.get("capture_id")
        artifact_kind = enriched_details.get("artifact_kind")
        if isinstance(capture_id, str) and artifact_kind in {"original", "rendition"}:
            extensions = result_extensions_for_run(
                self._application.execution_store, run_id, limit=3
            )
            if len(extensions) == 1 and isinstance(extensions[0], Mapping):
                details = extensions[0].get("source_capture_details")
                if isinstance(details, list):
                    matches = [
                        item
                        for item in details
                        if isinstance(item, Mapping) and item.get("capture_id") == capture_id
                    ]
                    if len(matches) == 1:
                        detail = matches[0]
                        key = "original_capture" if artifact_kind == "original" else "text_rendition"
                        binding = detail.get(key)
                        if isinstance(binding, Mapping):
                            enriched_details["exact_locator"] = detail.get("exact_locator")
                            enriched_details["media_type"] = binding.get("media_type")
                        filename_field = (
                            "original_source_filename"
                            if artifact_kind == "original"
                            else "text_rendition_source_filename"
                        )
                        artifact_id = enriched_details.get("artifact_id")
                        source_filename = None
                        for artifact in self._application.execution_store.artifacts_for(run_id):
                            if artifact.artifact_id == artifact_id:
                                value = artifact.provenance.get(filename_field)
                                if isinstance(value, str) and value:
                                    source_filename = value
                                break
                        enriched_details["source_filename"] = source_filename
        enriched_details["available_actions"] = material_recovery_action_guidance()
        enriched_recovery["recovery_failure_details"] = enriched_details
        result["finding_recovery"] = enriched_recovery
        return result
