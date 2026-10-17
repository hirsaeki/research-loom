"""Typed action ingress fields shared by the facade and the Virtual Runner ingress."""

from __future__ import annotations

# Fields a caller may put in an action draft.
INGRESS_FIELDS = {"action_type", "payload", "rationale", "actor_id", "conversation_id"}

# Payload fields only the authority pipeline may set; a caller supplying one is rejected.
AUTHORITY_PAYLOAD_FIELDS = {
    "decision_reference_ids",
    "state_transition_request",
    "commit_bundle",
    "commit_id",
    "new_snapshot_id",
    "runtime_authorization_evidence",
    "authorization_evidence",
    "capability_implementation",
    "implementation_id",
}
