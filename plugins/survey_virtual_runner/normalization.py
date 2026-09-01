from __future__ import annotations

import hashlib
from typing import Any, Mapping

from core.runtime.transition_models import (
    ObjectRef,
    StateDeltaProposal,
    TransitionAction,
    TransitionKind,
)


def _id(prefix: str, basis: str) -> str:
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


class SurveyVirtualRunnerNormalizer:
    """Normalize only an operational next-action candidate; never synthetic research content."""

    def supports(self, capability_contract_id: str, function_id: str, contract_version: str) -> bool:
        return (capability_contract_id, function_id, contract_version) == (
            "virtual-runner",
            "execute",
            "0.1.0",
        )

    def validate_extension(self, handoff, extension, context):
        del context
        if not isinstance(extension, Mapping):
            return ("VR-RESULT-BINDING-001: Survey Virtual Runner result extension is required",)
        if extension.get("extension_type") != "survey_virtual_runner_result":
            return ("VR-RESULT-BINDING-001: unsupported Virtual Runner result extension",)
        if extension.get("evidence_status") != "SYNTHETIC_TEST_ONLY":
            return ("VR-EPISTEMIC-FIREWALL-001: result extension is not synthetic-test-only",)
        if extension.get("research_state_mutation_performed") is not False:
            return ("VR-EPISTEMIC-FIREWALL-001: Virtual Runner claims Research State mutation",)
        if extension.get("real_execution_started") is not False:
            return ("VR-REAL-ISOLATION-001: Virtual Runner claims REAL execution started",)
        result = extension.get("virtual_runner_result")
        if not isinstance(result, Mapping) or result.get("candidate_analyses") or result.get("candidate_findings"):
            return ("VR-EPISTEMIC-FIREWALL-001: Survey production binding must not emit synthetic research findings",)
        binding = extension.get("handoff_binding")
        if not isinstance(binding, Mapping):
            return ("VR-RESULT-BINDING-001: Handoff binding is missing",)
        for field in ("handoff_id", "handoff_digest", "run_id", "invocation_id"):
            if binding.get(field) != handoff.get(field):
                return (f"VR-RESULT-BINDING-001: {field} does not bind the exact Handoff",)
        return ()

    def normalize(
        self,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> StateDeltaProposal:
        if extension is None:
            raise ValueError("Survey Virtual Runner result extension is required")
        method = extension["input_pins"]["core_method"]
        readiness = extension["readiness_assessment"]
        run_id = str(handoff["run_id"])
        action_id = _id("NXT-VR", run_id)
        target = {"kind": "method", "id": str(method["method_id"])}
        ready = readiness["status"] == "CANDIDATE_READY"
        obj = {
            "schema_version": "0.1.0",
            "id": action_id,
            "kind": "next_action",
            "revision": 0,
            "project_id": str(context["project_ref"]),
            "action_type": "review",
            "target": target,
            "instruction": (
                "Review candidate pre-REAL readiness and make any required Human Decision before a separate REAL Survey invocation."
                if ready
                else "Review Virtual Runner defects and candidate change requests before revising the canonical Instrument and starting a new Virtual Run."
            ),
            "reason": (
                "Virtual readiness is candidate-only and cannot start REAL Survey."
                if ready
                else "The current exact Instrument/Run requirements are not yet candidate-ready."
            ),
            "priority": "medium" if ready else "high",
            "status": "open",
        }
        action = TransitionAction(
            TransitionKind.CREATE_OBJECT,
            {"object": obj},
            source_refs=(str(handoff["handoff_id"]),),
        )
        proposal = StateDeltaProposal(
            proposal_id=_id("SDP-VR", run_id),
            project_ref=str(context["project_ref"]),
            lineage_ref=str(context["lineage_ref"]),
            source_refs=(str(handoff["handoff_id"]), run_id),
            proposed_actions=(action,),
            affected_refs=(ObjectRef("next_action", action_id),),
            rationale=(
                "Expose only an operational candidate next action. Synthetic Survey responses, "
                "analyses, findings, and readiness remain outside authoritative Research State."
            ),
            required_human_decision_kinds=(),
            current_snapshot_ref=str(context["current_snapshot_ref"]),
            current_snapshot_digest=str(context["current_snapshot_digest"]),
            provenance={
                "capability_id": "virtual-runner",
                "run_id": run_id,
                "evidence_status": "SYNTHETIC_TEST_ONLY",
                "research_state_mutation_performed": False,
            },
            candidate_only=True,
        )
        return proposal.with_calculated_digest()
