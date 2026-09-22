from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.runtime import canonical_digest

_SUPPORTED_ACTION_KINDS = {"CREATE_OBJECT", "REVISE_OBJECT"}
_ERROR = "APPLICATION-CANDIDATE-PROJECTION-001"


def build_candidate_projection(
    candidate: Mapping[str, Any],
    state: Any,
) -> dict[str, Any]:
    """Project candidate target values beside the current authoritative values."""
    if candidate.get("candidate_only") is not True:
        raise ConversationRuntimeError(_ERROR, "candidate_only must be true")
    if candidate.get("project_ref") != state.project_ref:
        raise ConversationRuntimeError(_ERROR, "candidate project binding is invalid")
    lineage_ref = candidate.get("lineage_ref")
    if not isinstance(lineage_ref, str) or not lineage_ref:
        raise ConversationRuntimeError(_ERROR, "candidate lineage binding is invalid")

    proposal_id = candidate.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise ConversationRuntimeError(_ERROR, "candidate proposal identity is invalid")
    supplied_digest = candidate.get("proposal_digest")
    basis = deepcopy(dict(candidate))
    basis.pop("proposal_digest", None)
    if not isinstance(supplied_digest, str) or canonical_digest(basis) != supplied_digest:
        raise ConversationRuntimeError(_ERROR, "candidate proposal digest is invalid")

    snapshot_ref = candidate.get("current_snapshot_ref")
    snapshot_digest = candidate.get("current_snapshot_digest")
    if not isinstance(snapshot_ref, str) or not snapshot_ref:
        raise ConversationRuntimeError(_ERROR, "candidate snapshot identity is invalid")
    if not isinstance(snapshot_digest, str) or not snapshot_digest:
        raise ConversationRuntimeError(_ERROR, "candidate snapshot digest is invalid")

    current: dict[tuple[str, str], Mapping[str, Any]] = {}
    for obj in state.effective_objects():
        kind = obj.get("kind")
        object_id = obj.get("id")
        if not isinstance(kind, str) or not isinstance(object_id, str):
            continue
        key = (kind, object_id)
        if key in current:
            raise ConversationRuntimeError(_ERROR, "current object identity is ambiguous")
        current[key] = obj

    affected = candidate.get("affected_refs")
    actions = candidate.get("proposed_actions")
    if not isinstance(affected, list) or not isinstance(actions, list) or not actions:
        raise ConversationRuntimeError(_ERROR, "candidate action structure is malformed")
    affected_refs = {
        (ref.get("kind"), ref.get("id"))
        for ref in affected
        if isinstance(ref, Mapping)
        and isinstance(ref.get("kind"), str)
        and isinstance(ref.get("id"), str)
    }

    subjects: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping) or action.get("kind") not in _SUPPORTED_ACTION_KINDS:
            raise ConversationRuntimeError(_ERROR, "candidate contains an unsupported action")
        payload = action.get("payload")
        obj = payload.get("object") if isinstance(payload, Mapping) else None
        if not isinstance(obj, Mapping):
            raise ConversationRuntimeError(_ERROR, "candidate object payload is malformed")
        kind = obj.get("kind")
        object_id = obj.get("id")
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(object_id, str)
            or not object_id
            or obj.get("project_id") != state.project_ref
        ):
            raise ConversationRuntimeError(_ERROR, "candidate object identity or project is invalid")
        key = (kind, object_id)
        if key not in affected_refs:
            raise ConversationRuntimeError(_ERROR, "candidate affected_refs do not bind its object")
        subjects.append({
            "subject": {"kind": kind, "id": object_id},
            "current_value": deepcopy(current.get(key)),
            "candidate_value": deepcopy(dict(obj)),
        })

    return {
        "candidate_only": True,
        "proposal_id": proposal_id,
        "bound_lineage_ref": lineage_ref,
        "bound_to_current_lineage": lineage_ref == state.lineage_ref,
        "bound_snapshot": {
            "snapshot_id": snapshot_ref,
            "content_digest": snapshot_digest,
        },
        "bound_to_current_snapshot": (
            snapshot_ref == str(state.current_snapshot["id"])
            and snapshot_digest == str(state.current_snapshot["content_digest"])
        ),
        "subjects": subjects,
    }
