from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Iterable

import rfc8785


AUTHORITATIVE_STATES = {
    "research_question": {"approved", "revised", "rejected", "closed", "out_of_scope"},
    "method": {"approved", "rejected"},
    "finding": {"approved", "rejected"},
    "recommendation": {"approved", "rejected"},
}

MATERIAL_REVISION_METADATA_FIELDS = {
    "schema_version",
    "revision",
    "decision_ids",
    "adoption_state",
}

# Synthetic contract-fixture vocabulary only. These sentinel bindings make the
# Core phrase "resolving Decision" executable without defining a production
# Decision enum or runtime API. Implementations may use different vocabulary if
# they preserve equivalent transition/qualification semantics.
FIXTURE_RESEARCH_STATE_DECISIONS = {
    "approved": ("research_adoption", "approve"),
    "rejected": ("research_adoption", "reject"),
    "closed": ("research_adoption", "close"),
    "out_of_scope": ("research_adoption", "out_of_scope"),
    "revised": ("research_revision", "revise"),
}
FIXTURE_RESEARCH_REVISION_DECISION = ("research_revision", "revise")
FIXTURE_EVIDENCE_QUALIFICATION_DECISION = ("evidence_qualification", "verify")
FIXTURE_EVIDENCE_RECLASSIFICATION_DECISION = ("evidence_reclassification", "reclassify")

SCALAR_REFERENCE_FIELDS = {
    "research_question": {"parent_question_id": "research_question"},
    "claim": {"question_id": "research_question"},
    "evidence": {"source_id": "source"},
    "analysis": {"method_id": "method"},
    "argument": {"conclusion_claim_id": "claim"},
    "artifact": {"source_snapshot_id": "snapshot"},
    "snapshot": {"prior_snapshot_id": "snapshot"},
    "audit_event": {"previous_event_id": "audit_event"},
}

LIST_REFERENCE_FIELDS = {
    "claim": {
        "supporting_evidence_ids": "evidence",
        "challenging_evidence_ids": "evidence",
    },
    "method": {"question_ids": "research_question"},
    "analysis": {
        "question_ids": "research_question",
        "evidence_ids": "evidence",
    },
    "finding": {
        "question_ids": "research_question",
        "evidence_ids": "evidence",
        "analysis_ids": "analysis",
        "counter_evidence_ids": "evidence",
    },
    "counter_review": {"evidence_ids": "evidence"},
    "argument": {
        "question_ids": "research_question",
        "premise_claim_ids": "claim",
        "finding_ids": "finding",
        "evidence_ids": "evidence",
        "counter_review_ids": "counter_review",
    },
    "contribution": {"finding_ids": "finding"},
    "recommendation": {"finding_ids": "finding"},
    "next_action": {"blocked_by": "next_action"},
}

OBJECT_REFERENCE_FIELDS = {
    "counter_review": {"target": False},
    "next_action": {"target": False},
    "decision": {"subjects": True},
    "audit_event": {"subjects": True},
}


def core_reference_rule_names() -> set[str]:
    """Return the complete schema-reference rule inventory exercised by fixtures."""
    names = {"base.decision_ids", "base.project_id", "snapshot.members"}
    for kind, fields in SCALAR_REFERENCE_FIELDS.items():
        names.update(f"{kind}.{field}" for field in fields)
    for kind, fields in LIST_REFERENCE_FIELDS.items():
        names.update(f"{kind}.{field}" for field in fields)
    for kind, fields in OBJECT_REFERENCE_FIELDS.items():
        names.update(f"{kind}.{field}" for field in fields)
    return names


def _by_kind_id(objects: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """Index fixture objects by canonical `(kind, id)` identity."""
    return {(obj["kind"], obj["id"]): obj for obj in objects}


def _by_kind_id_revision(objects: Iterable[dict]) -> dict[tuple[str, str, int], dict]:
    """Index fixture objects by exact canonical object revision identity."""
    return {(obj["kind"], obj["id"], obj["revision"]): obj for obj in objects}


def _human_decision_for(
    obj: dict,
    objects: list[dict],
    expected_binding: tuple[str, str] | None = None,
) -> bool:
    """Check for a referenced human Decision that resolves the expected action."""
    decision_ids = set(obj.get("decision_ids", []))
    for decision in objects:
        if decision.get("kind") != "decision" or decision.get("id") not in decision_ids:
            continue
        if decision.get("actor_type") != "human":
            continue
        if not any(
            subject.get("kind") == obj.get("kind") and subject.get("id") == obj.get("id")
            for subject in decision.get("subjects", [])
        ):
            continue
        if expected_binding is not None:
            expected_kind, expected_choice = expected_binding
            if decision.get("decision_kind") != expected_kind or decision.get("choice") != expected_choice:
                continue
        return True
    return False


def _material_research_payload(obj: dict) -> dict:
    """Return research-semantic fields used to detect a material object revision."""
    return {
        key: deepcopy(value)
        for key, value in obj.items()
        if key not in MATERIAL_REVISION_METADATA_FIELDS
    }


def fixture_object_digest(obj: dict) -> str:
    """Return the fixture-only SHA-256 digest of RFC 8785 canonical object bytes."""
    return "sha256:" + hashlib.sha256(canonical_object_bytes(obj)).hexdigest()


def core_reference_violations(
    objects: list[dict],
    *,
    include_snapshot_members: bool = True,
) -> set[str]:
    """Resolve every schema-defined Core research-object reference in one context."""
    index = _by_kind_id(objects)
    revision_index = _by_kind_id_revision(objects)
    unresolved = False

    def require(kind: str, object_id: str | None) -> None:
        nonlocal unresolved
        if object_id is not None and (kind, object_id) not in index:
            unresolved = True

    def require_object_ref(ref: dict | None) -> None:
        nonlocal unresolved
        if ref is not None and (ref.get("kind"), ref.get("id")) not in index:
            unresolved = True

    for obj in objects:
        kind = obj.get("kind")

        if "project_id" in obj:
            require("project", obj.get("project_id"))
        for decision_id in obj.get("decision_ids", []):
            require("decision", decision_id)

        for field, target_kind in SCALAR_REFERENCE_FIELDS.get(kind, {}).items():
            if field in obj:
                require(target_kind, obj.get(field))

        for field, target_kind in LIST_REFERENCE_FIELDS.get(kind, {}).items():
            for object_id in obj.get(field, []):
                require(target_kind, object_id)

        for field, is_list in OBJECT_REFERENCE_FIELDS.get(kind, {}).items():
            refs = obj.get(field, []) if is_list else [obj.get(field)]
            for ref in refs:
                require_object_ref(ref)

        if kind == "snapshot" and include_snapshot_members:
            members = obj.get("members", [])
            counts: dict[tuple[str, str, int], int] = {}
            for member in members:
                key = (member["kind"], member["id"], member["revision"])
                counts[key] = counts.get(key, 0) + 1
            for member in members:
                key = (member["kind"], member["id"], member["revision"])
                # Duplicate member identity is already a CORE-PROV-004 failure;
                # do not add a secondary dangling-reference result for it.
                if counts[key] > 1:
                    continue
                if key not in revision_index:
                    unresolved = True

    return {"CORE-REF-001"} if unresolved else set()


def snapshot_member_digest_violations(objects: list[dict]) -> set[str]:
    """Validate optional snapshot-member digests against exact fixture revisions."""
    revision_index = _by_kind_id_revision(objects)
    for obj in objects:
        if obj.get("kind") != "snapshot":
            continue
        seen: set[tuple[str, str, int]] = set()
        for member in obj.get("members", []):
            key = (member["kind"], member["id"], member["revision"])
            if key in seen:
                continue
            seen.add(key)
            target = revision_index.get(key)
            if target is not None and "digest" in member:
                if member["digest"] != fixture_object_digest(target):
                    return {"CORE-PROV-004"}
    return set()


def _graph_violations(objects: list[dict]) -> set[str]:
    """Evaluate graph-local Core invariant violations for one synthetic state."""
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
            declared_support = bool(obj.get("finding_ids") or obj.get("evidence_ids"))
            unresolved_support = False
            for finding_id in obj.get("finding_ids", []):
                if ("finding", finding_id) not in index:
                    unresolved_support = True
                    dangling = True
            for evidence_id in obj.get("evidence_ids", []):
                if ("evidence", evidence_id) not in index:
                    unresolved_support = True
                    dangling = True
            if not declared_support or unresolved_support:
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

    violations |= snapshot_member_digest_violations(objects)

    # Project-shaped states are complete fixture contexts and therefore receive
    # the exhaustive generic reference audit in addition to specialized rules.
    # Some focused history fixtures omit Project intentionally; their reference
    # forms are covered independently by reference-cases.json.
    if any(obj.get("kind") == "project" for obj in objects):
        violations |= core_reference_violations(objects)

    if dangling:
        violations.add("CORE-REF-001")
    return violations


def _history_violations(prior_objects: list[dict], objects: list[dict]) -> set[str]:
    """Evaluate history-sensitive Core invariant violations across two states."""
    prior = _by_kind_id(prior_objects)
    current = _by_kind_id(objects)
    violations: set[str] = set()

    # Persisted Research Snapshots are immutable and cannot disappear in place.
    # Reusing a snapshot identity with any changed payload, including a revision
    # bump, is mutation in place; changed snapshot content requires a new id.
    for key, before in prior.items():
        if before.get("kind") != "snapshot":
            continue
        after = current.get(key)
        if after is None or canonical_object_bytes(before) != canonical_object_bytes(after):
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
        kind = after.get("kind")

        if before is None:
            initially_authoritative = (
                kind in AUTHORITATIVE_STATES
                and after.get("adoption_state") in AUTHORITATIVE_STATES[kind]
            )
            initially_verified_evidence = (
                kind == "evidence"
                and after.get("verification_status") == "verified"
            )
            if initially_authoritative:
                binding = FIXTURE_RESEARCH_STATE_DECISIONS[after["adoption_state"]]
                if not _human_decision_for(after, objects, binding):
                    violations.add("CORE-AUTH-001")
            if initially_verified_evidence:
                if not _human_decision_for(after, objects, FIXTURE_EVIDENCE_QUALIFICATION_DECISION):
                    violations.add("CORE-AUTH-001")
            continue

        if kind == "evidence":
            became_verified = before.get("verification_status") != "verified" and after.get("verification_status") == "verified"
            promoted_mode = before.get("evidence_mode") == "synthetic" and after.get("evidence_mode") == "empirical"
            strengthened_kind = before.get("evidence_kind") in {"counterevidence", "conflict", "null", "unknown", "limitation"} and after.get("evidence_kind") == "supporting"
            removed_limitations = not set(before.get("limitations", [])).issubset(set(after.get("limitations", [])))
            epistemic_change = promoted_mode or strengthened_kind or removed_limitations or became_verified

            if promoted_mode:
                violations.add("CORE-EPI-001")
            if epistemic_change:
                binding = (
                    FIXTURE_EVIDENCE_QUALIFICATION_DECISION
                    if became_verified
                    else FIXTURE_EVIDENCE_RECLASSIFICATION_DECISION
                )
                revision_advanced = after.get("revision", -1) > before.get("revision", -1)
                if not revision_advanced or not _human_decision_for(after, objects, binding):
                    violations.add("CORE-EPI-002")
            if became_verified and not _human_decision_for(after, objects, FIXTURE_EVIDENCE_QUALIFICATION_DECISION):
                violations.add("CORE-AUTH-001")

        if kind in AUTHORITATIVE_STATES:
            before_state = before.get("adoption_state")
            after_state = after.get("adoption_state")
            authoritative_transition = (
                before_state != after_state
                and after_state in AUTHORITATIVE_STATES[kind]
            )
            materially_revised = (
                _material_research_payload(before)
                != _material_research_payload(after)
            )
            if authoritative_transition:
                binding = FIXTURE_RESEARCH_STATE_DECISIONS[after_state]
                if not _human_decision_for(after, objects, binding):
                    violations.add("CORE-AUTH-001")
            elif materially_revised:
                if not _human_decision_for(after, objects, FIXTURE_RESEARCH_REVISION_DECISION):
                    violations.add("CORE-AUTH-001")

    return violations


def evaluate_core_invariants(objects: list[dict], prior_objects: list[dict] | None = None) -> set[str]:
    """Evaluate only the invariant semantics exercised by canonical fixtures.

    This module is a test oracle. It deliberately does not expose a runtime
    validator API and does not attempt to define persistence behavior.
    """
    violations = _graph_violations(objects)
    if prior_objects is not None:
        violations |= _history_violations(prior_objects, objects)
    return violations


def canonical_object_bytes(obj: dict) -> bytes:
    """Serialize one fixture object using RFC 8785 canonical JSON bytes."""
    return rfc8785.dumps(deepcopy(obj))


def canonical_state_bytes(objects: list[dict]) -> bytes:
    """Serialize a fixture state deterministically independent of object order."""
    ordered = sorted(deepcopy(objects), key=lambda obj: (obj["kind"], obj["id"], obj["revision"]))
    return rfc8785.dumps(ordered)
