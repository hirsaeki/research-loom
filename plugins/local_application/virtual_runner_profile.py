from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from plugins.local_application.facade import LocalApplicationError
from .virtual_runner_input import _PROFILE_PIN_FIELDS


def _profile_set_pin(effective: Mapping[str, Any], expected_digest: str) -> dict[str, Any]:
    if effective.get("content_digest") != expected_digest:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "Effective Profile Set does not match current Research State digest")
    profiles = effective.get("profile_pins")
    if profiles is None:
        profiles = effective.get("effective_profiles")
    if not isinstance(profiles, list):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "Effective Profile Set has no projectable profile pins")
    try:
        return {
            "schema_version": effective["schema_version"],
            "core_contracts": deepcopy(effective["core_contracts"]),
            "profile_pins": [{field: deepcopy(profile[field]) for field in _PROFILE_PIN_FIELDS} for profile in profiles],
            "content_digest": expected_digest,
        }
    except (KeyError, TypeError) as exc:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "Effective Profile Set profile pins are malformed") from exc


def _approved_decision_for(state, decision_id: str, *, subject_kind: str, subject_id: str) -> bool:
    decision = state.decision(decision_id)
    if decision is None or decision.get("actor_type") != "human":
        return False
    subjects = {(str(item.get("kind")), str(item.get("id"))) for item in decision.get("subjects", ()) if isinstance(item, Mapping)}
    return (
        decision.get("decision_kind") == "research_adoption"
        and decision.get("choice") == "approve"
        and (subject_kind, subject_id) in subjects
    )
