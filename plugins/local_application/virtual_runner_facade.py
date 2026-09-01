from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from plugins.local_application.facade import LocalApplicationError, _AUTHORITY_PAYLOAD_FIELDS, _INGRESS_FIELDS
from plugins.local_application.survey_facade import LocalApplicationFacade as SurveyApplicationFacade
from .virtual_runner_binding import build_survey_virtual_extension
from .virtual_runner_input import _payload
from .virtual_runner_method_context import build_method_context
from .virtual_runner_resolve import resolve_virtual_inputs
from .virtual_runner_execute import VirtualRunnerExecuteMixin
from .virtual_runner_inspection import VirtualRunnerInspectionMixin

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR_PATH = ROOT / "core/packages/virtual-runner/virtual-runner-capability-descriptor.json"
_MAX_PRIOR_VIRTUAL_RUN_IDS = 16


class LocalApplicationFacade(VirtualRunnerInspectionMixin, VirtualRunnerExecuteMixin, SurveyApplicationFacade):
    """Final local Application Facade including the Survey Virtual Runner production binding."""

    def list_actions(self) -> Mapping[str, Any]:
        result = deepcopy(dict(super().list_actions()))
        result["actions"].append({
            "action_type": "virtual_runner.survey.execute",
            "payload_contract": "survey-virtual-runner-execution@0.1.0",
            "effect": "read_only",
            "confirmation_required": False,
            "route_category": "research_capability",
        })
        return result

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(draft_input, Mapping) and draft_input.get("action_type") == "virtual_runner.survey.execute":
            unknown = set(draft_input) - _INGRESS_FIELDS
            if unknown:
                raise LocalApplicationError(
                    "APPLICATION-INGRESS-001",
                    "typed action input contains caller-controlled authority or unknown fields: "
                    + ", ".join(sorted(map(str, unknown))),
                )
            payload = draft_input.get("payload")
            if not isinstance(payload, Mapping):
                raise LocalApplicationError("APPLICATION-INGRESS-001", "payload must be an object")
            forbidden = set(payload) & _AUTHORITY_PAYLOAD_FIELDS
            if forbidden:
                raise LocalApplicationError(
                    "APPLICATION-AUTHORITY-001",
                    "caller may not supply Harness authority metadata: "
                    + ", ".join(sorted(forbidden)),
                )
            normalized = _payload(payload)
            if len(normalized["prior_virtual_run_ids"]) > _MAX_PRIOR_VIRTUAL_RUN_IDS:
                raise LocalApplicationError(
                    "APPLICATION-VIRTUAL-PAYLOAD-001",
                    f"prior_virtual_run_ids may contain at most {_MAX_PRIOR_VIRTUAL_RUN_IDS} Run IDs",
                )
            return self.run_survey_virtual(normalized)
        return super().submit_action(draft_input)

    def _effective_profile_set(self, state) -> Mapping[str, Any]:
        if self._workspace_root is not None:
            path = self._workspace_root / "effective-profile-set.json"
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise LocalApplicationError(
                        "APPLICATION-VIRTUAL-PIN-001",
                        "workspace Effective Profile Set is unreadable",
                    ) from exc
                if isinstance(value, Mapping):
                    return value
        try:
            materializer = self._application.coordinator._materializers.resolve(
                "desktop_research.investigate@0.1.0"
            )
            provider = materializer._profiles
            return provider(state.project_ref, state.effective_profile_set_digest)
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-VIRTUAL-PIN-001",
                "current Effective Profile Set cannot be projected without creating a second authority",
            ) from exc

    def _build_context(self, state, record, design_record, payload, *, context_pack_id: str):
        (
            questionnaire,
            rq_ids,
            rq_objects,
            method,
            method_decisions,
            protocol,
            material_decisions,
            snapshot,
            effective,
            attention,
            project_constraints,
            effective_constraints,
        ) = resolve_virtual_inputs(self, state, record, design_record, payload)
        context, binding, protocol_ref, run_spec, research_method = build_method_context(
            state,
            record,
            payload,
            context_pack_id=context_pack_id,
            questionnaire=questionnaire,
            rq_ids=rq_ids,
            rq_objects=rq_objects,
            method=method,
            method_decisions=method_decisions,
            protocol=protocol,
            material_decisions=material_decisions,
            snapshot=snapshot,
            effective=effective,
            attention=attention,
            project_constraints=project_constraints,
            effective_constraints=effective_constraints,
        )
        extension = build_survey_virtual_extension(
            record,
            design_record,
            payload,
            context_pack_id=context_pack_id,
            binding=binding,
            questionnaire=questionnaire,
            method=method,
            protocol_ref=protocol_ref,
            run_spec=run_spec,
            research_method=research_method,
        )
        return context, extension, method
