from __future__ import annotations

import copy
import hashlib
import json

ERROR_IDS = {
    "RL-DIGEST-001",
    "RL-PARENT-001",
    "RL-BASELINE-STALE-001",
    "RL-PROJECT-MISMATCH-001",
    "RL-TREATMENT-001",
    "RL-HUMAN-DECISION-001",
    "RL-OBJECT-IDENTITY-001",
    "RL-INVALIDATED-LEAK-001",
    "RL-REPLAY-RUN-ID-001",
    "RL-REPLAY-CONTEXT-001",
    "RL-REPLAY-HANDOFF-001",
    "RL-ACTIVE-SELECTION-001",
    "RL-AUTO-MERGE-001",
    "RL-VIRTUAL-REAL-001",
    "RL-CONFIG-PROFILE-PIN-001",
    "RL-DOWNSTREAM-STALE-001",
    "RL-COMPARISON-READONLY-001",
    "RL-CONVERSATION-DECISION-001",
}


def canonical_digest(doc: dict, field: str) -> str:
    """Return the deterministic SHA-256 digest excluding the digest field."""
    value = copy.deepcopy(doc)
    value.pop(field, None)
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def digest_error(doc: dict) -> str | None:
    """Validate the digest field selected by canonical object type."""
    fields = {
        "research_lineage": "lineage_digest",
        "fork_proposal": "proposal_digest",
        "fork_plan": "plan_digest",
        "impact_assessment": "assessment_digest",
        "recovery_request": "request_digest",
        "replay_plan": "plan_digest",
        "active_lineage_selection": "selection_digest",
        "lineage_comparison": "comparison_digest",
    }
    field = fields[doc["object_type"]]
    if doc[field] != canonical_digest(doc, field):
        return "RL-DIGEST-001"
    return None


def lineage_error(lineage: dict, known_parent: dict | None = None) -> str | None:
    """Validate lineage ancestry, project identity, and execution mode."""
    if error := digest_error(lineage):
        return error
    mode = lineage["execution_mode"]
    if (
        lineage["baseline_snapshot"]["execution_mode"] != mode
        or lineage["current_snapshot"]["execution_mode"] != mode
    ):
        return "RL-VIRTUAL-REAL-001"
    if lineage["lineage_kind"] == "primary":
        return None
    if not lineage.get("parent_lineage_ref") or known_parent is None:
        return "RL-PARENT-001"
    if lineage["parent_lineage_ref"] != known_parent["lineage_id"]:
        return "RL-PARENT-001"
    if lineage["project_ref"] != known_parent["project_ref"]:
        return "RL-PROJECT-MISMATCH-001"
    if known_parent["execution_mode"] != mode:
        return "RL-VIRTUAL-REAL-001"
    return None


def fork_plan_error(
    plan: dict, proposal: dict, parent: dict, effective_refs: set[str]
) -> str | None:
    """Validate baseline, exact pins, treatments, decisions, and invalidation."""
    if error := digest_error(plan):
        return error
    if plan["project_ref"] != parent["project_ref"]:
        return "RL-PROJECT-MISMATCH-001"
    if proposal["project_ref"] != parent["project_ref"]:
        return "RL-PROJECT-MISMATCH-001"
    if (
        plan["parent_lineage_ref"] != parent["lineage_id"]
        or proposal["requested_baseline_lineage"] != parent["lineage_id"]
    ):
        return "RL-PARENT-001"
    if plan["approved_baseline"] != proposal["baseline_snapshot"]:
        return "RL-BASELINE-STALE-001"

    expected_pins = {
        (parent["project_config"]["ref"], parent["project_config"]["content_digest"]),
        (
            parent["effective_profile_set"]["ref"],
            parent["effective_profile_set"]["content_digest"],
        ),
    }
    actual_pins = {(pin["ref"], pin["content_digest"]) for pin in plan["exact_input_pins"]}
    if len(plan["exact_input_pins"]) != len(actual_pins) or actual_pins != expected_pins:
        return "RL-CONFIG-PROFILE-PIN-001"

    allowed_treatments = {"PRESERVE", "RECONFIRM", "INVALIDATE"}
    proposal_refs = set(proposal["affected_refs"])
    treatment_refs = [treatment["source_ref"] for treatment in plan["treatments"]]
    if (
        any(treatment["treatment"] not in allowed_treatments for treatment in plan["treatments"])
        or len(treatment_refs) != len(set(treatment_refs))
        or set(treatment_refs) != proposal_refs
    ):
        return "RL-TREATMENT-001"

    required = set(plan["required_human_decision_refs"])
    used: set[str] = set()
    for treatment in plan["treatments"]:
        decision = treatment.get("human_decision_ref")
        if treatment["treatment"] in {"RECONFIRM", "INVALIDATE"} and not decision:
            return "RL-HUMAN-DECISION-001"
        if decision and decision not in required:
            return "RL-HUMAN-DECISION-001"
        if decision:
            used.add(decision)
        if (
            treatment["treatment"] == "INVALIDATE"
            and treatment["source_ref"] in effective_refs
        ):
            return "RL-INVALIDATED-LEAK-001"
    if required != used:
        return "RL-HUMAN-DECISION-001"
    return None


def revision_collision_error(records: list[dict]) -> str | None:
    """Reject identical kind/id/revision tuples with differing content digests."""
    seen: dict[tuple[str, str, int], str] = {}
    for record in records:
        key = (record["kind"], record["id"], record["revision"])
        if key in seen and seen[key] != record["content_digest"]:
            return "RL-OBJECT-IDENTITY-001"
        seen[key] = record["content_digest"]
    return None


def replay_error(
    plan: dict, execution: dict, source_lineage: dict, target_lineage: dict
) -> str | None:
    """Validate replay project, lineage, mode, new IDs, Context Packs, and Handoffs."""
    if error := digest_error(plan):
        return error
    if (
        plan["project_ref"] != source_lineage["project_ref"]
        or plan["project_ref"] != target_lineage["project_ref"]
    ):
        return "RL-PROJECT-MISMATCH-001"
    if (
        plan["source_lineage_ref"] != source_lineage["lineage_id"]
        or plan["target_lineage_ref"] != target_lineage["lineage_id"]
    ):
        return "RL-PARENT-001"
    if (
        source_lineage["execution_mode"] != target_lineage["execution_mode"]
        or plan["baseline_snapshot"]["execution_mode"]
        != source_lineage["execution_mode"]
    ):
        return "RL-VIRTUAL-REAL-001"
    if set(execution["source_old_run_ids"]) & set(execution["target_new_run_ids"]):
        return "RL-REPLAY-RUN-ID-001"
    if execution["context_pack_policy"] != "rebuild_from_target_lineage":
        return "RL-REPLAY-CONTEXT-001"
    if set(execution["old_handoff_refs"]) & set(execution["target_handoff_refs"]):
        return "RL-REPLAY-HANDOFF-001"
    return None


def selection_error(selection: dict) -> str | None:
    """Validate explicit active-lineage authority and Human Decision resolution."""
    if error := digest_error(selection):
        return error
    if not selection["authority_confirmed"]:
        return "RL-ACTIVE-SELECTION-001"
    if selection["unresolved_human_decision_refs"]:
        return "RL-ACTIVE-SELECTION-001"
    if not selection.get("resolving_human_decision_ref"):
        return "RL-HUMAN-DECISION-001"
    return None


def comparison_error(comparison: dict) -> str | None:
    """Ensure lineage comparison stays read-only and never auto-adopts either side."""
    if error := digest_error(comparison):
        return error
    if comparison["automatic_adoption_performed"]:
        return "RL-AUTO-MERGE-001"
    if not comparison["read_only"]:
        return "RL-COMPARISON-READONLY-001"
    return None


def downstream_error(
    binding: dict, active_lineage: dict, active_snapshot: dict
) -> str | None:
    """Check Research Package lineage/snapshot freshness after selection."""
    if binding["status_against_active_lineage"] != "current":
        return None
    stale = (
        binding["source_lineage_ref"] != active_lineage["lineage_id"]
        or binding["source_lineage_digest"] != active_lineage["lineage_digest"]
        or binding["source_snapshot_ref"] != active_snapshot["snapshot_id"]
        or binding["source_snapshot_digest"] != active_snapshot["content_digest"]
    )
    if stale:
        return "RL-DOWNSTREAM-STALE-001"
    return None


def virtual_real_error(parent: dict, child: dict) -> str | None:
    """Reject Fork as a VIRTUAL-to-REAL promotion mechanism."""
    if parent["execution_mode"] != child["execution_mode"]:
        return "RL-VIRTUAL-REAL-001"
    return None


def conversation_error(route: dict) -> str | None:
    """Keep conversational confirmation separate from Core Human Decision."""
    proposal = route["action_proposal"]
    if proposal["commitment_mode"] != "proposal_only":
        return "RL-CONVERSATION-DECISION-001"
    if proposal["human_decision_boundary"]["confirmation_is_human_decision"]:
        return "RL-CONVERSATION-DECISION-001"
    return None
