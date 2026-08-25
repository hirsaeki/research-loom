from __future__ import annotations

from typing import Any, Mapping, Sequence

from .ports import CapabilityResultNormalizer
from .transition_models import StateDeltaProposal, StateView


class NormalizationRejected(RuntimeError):
    pass


class CapabilityNormalizationBoundary:
    """Validate a PR9 Handoff and normalize it to a generic StateDeltaProposal.

    Concrete capability validators/normalizers are supplied from the outside.
    This module has no imports from plugins or concrete Survey/Delphi/Case/etc.
    """

    def __init__(self, normalizers: Sequence[CapabilityResultNormalizer]) -> None:
        self._normalizers = tuple(normalizers)

    def normalize(
        self,
        handoff: Mapping[str, Any],
        *,
        extension: Mapping[str, Any] | None,
        state: StateView,
        context: Mapping[str, Any] | None = None,
    ) -> StateDeltaProposal:
        _validate_outer_handoff(handoff, state)
        capability = handoff.get("capability")
        if not isinstance(capability, Mapping):
            raise NormalizationRejected("PR9 Handoff capability binding is missing")
        capability_id = str(capability.get("capability_id", ""))
        function_id = str(capability.get("function_id", ""))
        contract_version = str(capability.get("capability_version", ""))
        normalizer = next(
            (
                item
                for item in self._normalizers
                if item.supports(capability_id, function_id, contract_version)
            ),
            None,
        )
        if normalizer is None:
            raise NormalizationRejected(
                "unknown/unsupported capability result extension has no registered canonical normalizer"
            )
        merged_context = {
            "project_ref": state.project_ref,
            "lineage_ref": state.lineage_ref,
            "current_snapshot_ref": str(state.current_snapshot["id"]),
            "current_snapshot_digest": str(state.current_snapshot["content_digest"]),
            **dict(context or {}),
        }
        extension_issues = normalizer.validate_extension(handoff, extension, merged_context)
        if extension_issues:
            raise NormalizationRejected("; ".join(extension_issues))
        proposal = normalizer.normalize(handoff, extension, merged_context)
        _validate_proposal(proposal, state)
        return proposal


def _validate_outer_handoff(handoff: Mapping[str, Any], state: StateView) -> None:
    if handoff.get("schema_version") != "0.1.0":
        raise NormalizationRejected("unsupported PR9 Handoff schema_version")
    if handoff.get("project_id") != state.project_ref:
        raise NormalizationRejected("Capability Handoff project does not match current Research State")
    validation = handoff.get("validation")
    if not isinstance(validation, Mapping) or validation.get("status") == "rejected":
        raise NormalizationRejected("rejected/invalid Capability Handoff cannot enter normalization")
    boundary = handoff.get("adoption_boundary")
    expected = {
        "research_state_mutation_performed": False,
        "outputs_are_candidates": True,
        "human_decision_required_for_authoritative_transition": True,
    }
    if not isinstance(boundary, Mapping) or any(boundary.get(key) != value for key, value in expected.items()):
        raise NormalizationRejected("Capability Handoff violated the candidate-only PR9 adoption boundary")
    pins = handoff.get("input_pins")
    snapshot = pins.get("research_snapshot") if isinstance(pins, Mapping) else None
    if not isinstance(snapshot, Mapping):
        raise NormalizationRejected("Capability Handoff is missing its pinned Research Snapshot")
    if snapshot.get("snapshot_id") != state.current_snapshot.get("id") or snapshot.get("content_digest") != state.current_snapshot.get("content_digest"):
        raise NormalizationRejected("Capability Handoff is stale relative to the current Research Snapshot")
    if pins.get("project_config_digest") != state.project_config_digest:
        raise NormalizationRejected("Capability Handoff Project Config pin is stale")
    if pins.get("effective_profile_set_digest") != state.effective_profile_set_digest:
        raise NormalizationRejected("Capability Handoff Effective Profile Set pin is stale")


def _validate_proposal(proposal: StateDeltaProposal, state: StateView) -> None:
    if not proposal.candidate_only:
        raise NormalizationRejected("normalizer output must remain candidate-only")
    if proposal.project_ref != state.project_ref or proposal.lineage_ref != state.lineage_ref:
        raise NormalizationRejected("StateDeltaProposal project/lineage binding is stale or mismatched")
    if proposal.current_snapshot_ref != state.current_snapshot.get("id") or proposal.current_snapshot_digest != state.current_snapshot.get("content_digest"):
        raise NormalizationRejected("StateDeltaProposal is not bound to the current Research Snapshot")
    if proposal.proposal_digest != proposal.calculated_digest():
        raise NormalizationRejected("StateDeltaProposal digest is invalid")
