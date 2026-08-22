from __future__ import annotations

from copy import deepcopy
from typing import Iterable

import rfc8785


AUTHORITATIVE_STATES = {
    "research_question": {"approved", "revised", "rejected", "closed", "out_of_scope"},
    "method": {"approved", "rejected"},
    "finding": {"approved", "rejected"},
    "recommendation": {"approved", "rejected"},
}


def _by_kind_id(objects: Iterable[dict]) -> dict[tuple[str, str], dict]:
    return {(obj["kind"], obj["id"]): obj for obj in objects}


def _same_object_revision(left: dict, right: dict) -> bool:
    return left.get("kind") == right.get("kind") and left.get("id") == right.get("id") and left.get("revision") == right.get("revision")


def _human_decision_for(obj: dict, objects: list[dict]) -> bool:
    decision_ids = set(obj.get("decision_ids", []))
    for decision in objects:
        if decision.get("kind") != "decision" or decision.get("id") not in decision_ids:
            continue
        if decision.get("actor_type") != "human":
            continue
        if any(subject.get("kind") == obj.get("kind") and subject.get("id") == obj.get("id") for subject in decision.get("subjects", [])):
            return True
    return False


def _graph_violations(objects: list[dict]) -> set[str]:
    index = _by_kind_id(objects)
    violations: set[str] = set()
    dangling = False

    for obj in objects:
        kind = obj.get("kind")
        if kind == "evidence":
            source = index.get(("source", obj.get("source_id")))
            if source is None or not obj.get("locator"):
                violations.add("CORE-TRACE-001")
                dangling = True
            publication_artifact = index.get(("artifact", obj.get("source_id")))
            if publication_artifact is not None and publication_artifact.get("lane") == "publication":
                violations.add("CORE-FW-001")

        elif kind == "finding":
            for question_id in obj.get("question_ids", []):
                if ("research_question", question_id) not in index:
                    violations.add("CORE-TRACE-002")
                    dangling = True

        elif kind == "argument":
            support_found = False
            for finding_id in obj.get("finding_ids", []):
                if ("finding", finding_id) in index:
                    support_found = True
                else:
                    dangling = True
            for evidence_id in obj.get("evidence_ids", []):
                if ("evidence", evidence_id) in index:
                    support_found = True
                else:
                    dangling = True
            if not support_found:
                violations.add("CORE-TRACE-003")

        elif kind == "recommendation":
            for finding_id in obj.get("finding_ids", []):
                if ("finding", finding_id) not in index:
                    violations.add("CORE-TRACE-004")
                    dangling = True

        elif kind == "artifact":
            if obj.get("lane") == "publication" and obj.get("evidence_eligible") is not False:
                violations.add("CORE-FW-001")
            if obj.get("artifact_class") in {"generated", "published"}:
                snapshot_id = obj.get("source_snapshot_id")
                if ("snapshot", snapshot_id) not in index:
                    violations.add("CORE-PROV-001")
                    dangling = True

        elif kind == "snapshot":
            seen: set[tuple[str, str, int]] = set()
            for member in obj.get("members", []):
                key = (member["kind"], member["id"], member["revision"])
                if key in seen:
                    violations.add("CORE-PROV-004")
                seen.add(key)

    if dangling:
        violations.add("CORE-REF-001")
    return violations


def _history_violations(prior_objects: list[dict], objects: list[dict]) -> set[str]:
    prior = _by_kind_id(prior_objects)
    current = _by_kind_id(objects)
    violations: set[str] = set()

    # Persisted Research Snapshots are immutable at one object revision.
    for key, before in prior.items():
        after = current.get(key)
        if before.get("kind") == "snapshot" and after is not None:
            if _same_object_revision(before, after) and canonical_object_bytes(before) != canonical_object_bytes(after):
                violations.add("CORE-PROV-002")

    # Audit history is append-only: every prior event must still exist byte-for-byte.
    for key, before in prior.items():
        if before.get("kind") != "audit_event":
            continue
        after = current.get(key)
        if after is None or canonical_object_bytes(before) != canonical_object_bytes(after):
            violations.add("CORE-PROV-003")

    for key, after in current.items():
        before = prior.get(key)
        if before is None:
            continue

        kind = after.get("kind")
        if kind == "evidence":
            became_verified = before.get("verification_status") != "verified" and after.get("verification_status") == "verified"
            promoted_mode = before.get("evidence_mode") == "synthetic" and after.get("evidence_mode") == "empirical"
            strengthened_kind = before.get("evidence_kind") in {"counterevidence", "conflict", "null", "unknown", "limitation"} and after.get("evidence_kind") == "supporting"
            removed_limitations = not set(before.get("limitations", [])).issubset(set(after.get("limitations", [])))

            if promoted_mode:
                violations.add("CORE-EPI-001")
            if promoted_mode or strengthened_kind or removed_limitations or became_verified:
                if not _human_decision_for(after, objects):
                    violations.add("CORE-EPI-002")
            if became_verified and not _human_decision_for(after, objects):
                violations.add("CORE-AUTH-001")

        if kind in AUTHORITATIVE_STATES:
            before_state = before.get("adoption_state")
            after_state = after.get("adoption_state")
            if before_state != after_state and after_state in AUTHORITATIVE_STATES[kind]:
                if not _human_decision_for(after, objects):
                    violations.add("CORE-AUTH-001")

    return violations


def evaluate_core_invariants(objects: list[dict], prior_objects: list[dict] | None = None) -> set[str]:
    """Evaluate only the invariant semantics exercised by canonical fixtures.

    This module is a test oracle. It deliberately does not expose a runtime
    validator API and does not attempt to define persistence behavior.
    """
    if prior_objects is not None:
        return _history_violations(prior_objects, objects)
    return _graph_violations(objects)


def canonical_object_bytes(obj: dict) -> bytes:
    return rfc8785.dumps(deepcopy(obj))


def canonical_state_bytes(objects: list[dict]) -> bytes:
    ordered = sorted(deepcopy(objects), key=lambda obj: (obj["kind"], obj["id"], obj["revision"]))
    return rfc8785.dumps(ordered)
