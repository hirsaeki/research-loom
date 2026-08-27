"""Production storage-neutral Human Decision Gate boundary (PR26)."""

from core.runtime import Actor, CommitReceipt

from .models import (
    DecisionGateResult, DecisionResolutionResult, HumanDecisionError,
    request_digest, response_digest, with_request_digest, with_response_digest,
)
from .service import HumanDecisionService as _HumanDecisionService, make_response


class _RecoveringHumanDecisionService(_HumanDecisionService):
    def resolve(self, response):
        self._validate_response_envelope(response)
        request_id = str(response["request_id"])
        resolution_fn = getattr(self._store, "resolution", None)
        if resolution_fn is not None:
            resolution = resolution_fn(request_id)
            if resolution is not None and resolution["status"] in {
                "RESOLVED", "DECLINED", "REVISION_REQUESTED", "STALE", "CANCELLED"
            }:
                if resolution.get("response_digest") != response.get("response_digest"):
                    raise HumanDecisionError(
                        "DECISION-TERMINAL-001",
                        "Human Decision Request already has a different terminal response",
                    )
                request = self._store.get_request(request_id)
                if request is None:
                    raise HumanDecisionError("DECISION-REQUEST-UNKNOWN", "Human Decision Request does not resolve")
                receipt_wire = resolution.get("commit_receipt")
                receipt = None
                if receipt_wire is not None:
                    actor = receipt_wire.get("actor", {})
                    receipt = CommitReceipt(
                        transition_id=str(receipt_wire["transition_id"]),
                        commit_id=str(receipt_wire["commit_id"]),
                        prior_snapshot_ref=str(receipt_wire["prior_snapshot_ref"]),
                        prior_snapshot_digest=str(receipt_wire["prior_snapshot_digest"]),
                        new_snapshot_ref=receipt_wire.get("new_snapshot_ref"),
                        new_snapshot_digest=receipt_wire.get("new_snapshot_digest"),
                        lineage_ref=str(receipt_wire["lineage_ref"]),
                        applied_typed_actions=tuple(receipt_wire.get("applied_typed_actions", ())),
                        resolving_decision_refs=tuple(receipt_wire.get("resolving_decision_refs", ())),
                        bundle_digest=str(receipt_wire["bundle_digest"]),
                        timestamp=str(receipt_wire["timestamp"]),
                        actor=Actor(str(actor["actor_id"]), str(actor["actor_type"])),
                        idempotency_key=str(receipt_wire["idempotency_key"]),
                    )
                return DecisionResolutionResult(
                    str(resolution["status"]), request, response, commit_receipt=receipt
                )
        return super().resolve(response)


def HumanDecisionService(*, store, state_transition_service, clock, state_provider=None):
    """Construct the service with an explicit Research State read port."""
    if state_provider is None:
        state_provider = state_transition_service._repository
    return _RecoveringHumanDecisionService(
        store=store,
        state_provider=state_provider,
        state_transition_service=state_transition_service,
        clock=clock,
    )


__all__ = [
    "DecisionGateResult", "DecisionResolutionResult", "HumanDecisionError",
    "HumanDecisionService", "make_response", "request_digest", "response_digest",
    "with_request_digest", "with_response_digest",
]
