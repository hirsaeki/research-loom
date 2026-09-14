from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

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
        enriched_details["available_actions"] = material_recovery_action_guidance()
        enriched_recovery["recovery_failure_details"] = enriched_details
        result["finding_recovery"] = enriched_recovery
        return result
