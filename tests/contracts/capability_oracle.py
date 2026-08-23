from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import rfc8785

DIGEST_FIELDS = {
    "descriptor": "descriptor_digest",
    "context": "context_pack_digest",
    "invocation": "invocation_digest",
    "handoff": "handoff_digest",
}


def canonical_digest(document: dict[str, Any], digest_field: str) -> str:
    payload = deepcopy(document)
    payload.pop(digest_field, None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def expected_descriptor_digest(document):
    return canonical_digest(document, "descriptor_digest")


def expected_context_pack_digest(document):
    return canonical_digest(document, "context_pack_digest")


def expected_invocation_digest(document):
    return canonical_digest(document, "invocation_digest")


def expected_handoff_digest(document):
    return canonical_digest(document, "handoff_digest")


def refresh_digest(target, document):
    digest_field = DIGEST_FIELDS[target]
    document[digest_field] = canonical_digest(document, digest_field)


def apply_fixture_mutation(document, mutation):
    result = deepcopy(document)
    if mutation["op"] != "set":
        raise ValueError(f"unsupported fixture mutation: {mutation['op']}")
    cursor = result
    for part in mutation["path"][:-1]:
        cursor = cursor[part]
    cursor[mutation["path"][-1]] = deepcopy(mutation["value"])
    return result


def _canonical(value):
    return rfc8785.dumps(value)


def _profile_pin(profile):
    return {
        key: profile[key]
        for key in (
            "profile_id",
            "profile_type",
            "profile_version",
            "manifest_sha256",
        )
    }


def _flatten_guard_ids(constraints):
    return [
        guard["guard_id"]
        for key in ("requirements", "prohibitions", "must_not_claim")
        for guard in constraints[key]
    ]


def _has_duplicates(values):
    return len(values) != len(set(values))


def descriptor_semantic_error(descriptor):
    if descriptor["descriptor_digest"] != expected_descriptor_digest(descriptor):
        return "CAP-DESCRIPTOR-DIGEST-001"

    function_ids = [
        function["function_id"] for function in descriptor["declared_functions"]
    ]
    if _has_duplicates(function_ids):
        return "CAP-DESCRIPTOR-IDENTITY-001"


def context_semantic_error(
    context,
    project_config,
    effective_profile_set,
    core_objects,
):
    if context["context_pack_digest"] != expected_context_pack_digest(context):
        return "CAP-CONTEXT-DIGEST-001"

    reference_ids = [resource["reference_id"] for resource in context["resources"]]
    attention_ids = [
        attention["attention_id"] for attention in context["research_attention"]
    ]
    guard_ids = _flatten_guard_ids(context["project_constraints"])
    constraint_paths = [
        constraint["path"] for constraint in context["effective_constraints"]
    ]
    if any(
        _has_duplicates(values)
        for values in (
            reference_ids,
            attention_ids,
            guard_ids,
            constraint_paths,
        )
    ):
        return "CAP-CONTEXT-IDENTITY-001"

    bounds = context["bounds"]
    actual = {
        "max_questions": len(context["question_ids"]),
        "max_research_object_references": len(
            context["research_object_references"]
        ),
        "max_resources": len(context["resources"]),
        "max_attention_items": len(context["research_attention"]),
        "max_project_guards": sum(
            len(context["project_constraints"][key])
            for key in ("requirements", "prohibitions", "must_not_claim")
        ),
        "max_effective_constraints": len(context["effective_constraints"]),
    }
    if any(actual[key] > bounds[key] for key in actual):
        return "CAP-CONTEXT-BOUND-001"

    if context["project_id"] != project_config["project"]["project_id"]:
        return "CAP-CONTEXT-BINDING-001"

    if (
        context["pins"]["project_config"]["configuration_digest"]
        != project_config["configuration_digest"]
    ):
        return "CAP-PIN-001"

    effective_pin = context["pins"]["effective_profile_set"]
    if effective_pin["schema_version"] != effective_profile_set["schema_version"]:
        return "CAP-PIN-001"

    expected_effective_digest = "sha256:" + hashlib.sha256(
        rfc8785.dumps(effective_profile_set)
    ).hexdigest()
    if effective_pin["content_digest"] != expected_effective_digest:
        return "CAP-PIN-001"

    if effective_pin["core_contracts"] != effective_profile_set["core_contracts"]:
        return "CAP-PIN-001"

    expected_profile_pins = [
        _profile_pin(profile) for profile in effective_profile_set["effective_profiles"]
    ]
    if _canonical(effective_pin["profile_pins"]) != _canonical(
        expected_profile_pins
    ):
        return "CAP-PIN-001"

    if _canonical(context["research_attention"]) != _canonical(
        project_config["research_attention"]
    ):
        return "CAP-CONTEXT-BINDING-001"

    if _canonical(context["project_constraints"]) != _canonical(
        project_config["project_constraints"]
    ):
        return "CAP-CONTEXT-BINDING-001"

    if _canonical(context["effective_constraints"]) != _canonical(
        effective_profile_set["effective_constraints"]
    ):
        return "CAP-CONTEXT-BINDING-001"

    questions = {
        item["question_id"]
        for item in project_config["research_questions"]["references"]
    }
    if not set(context["question_ids"]).issubset(questions):
        return "CAP-CONTEXT-BINDING-001"

    index = {
        (obj["kind"], obj["id"], obj["revision"]): obj for obj in core_objects
    }
    for ref in context["research_object_references"]:
        if (ref["kind"], ref["id"], ref["revision"]) not in index:
            return "CAP-CONTEXT-BINDING-001"

    snapshot_pin = context["pins"]["research_snapshot"]
    snapshot = index.get(
        (
            "snapshot",
            snapshot_pin["snapshot_id"],
            snapshot_pin["revision"],
        )
    )
    if snapshot is None:
        return "CAP-PIN-001"

    expected_snapshot_digest = "sha256:" + hashlib.sha256(
        rfc8785.dumps(snapshot)
    ).hexdigest()
    if snapshot_pin["content_digest"] != expected_snapshot_digest:
        return "CAP-PIN-001"

    configured = {
        resource["reference_id"]: resource
        for resource in project_config["resource_references"]
    }
    for resource in context["resources"]:
        source = configured.get(resource["reference_id"])
        if source is None:
            return "CAP-CONTEXT-BINDING-001"
        for key in ("reference_type", "object_id", "locator", "digest"):
            if resource.get(key) != source.get(key):
                return "CAP-CONTEXT-BINDING-001"
        if (
            resource["evidentiary_use"] == "candidate_source"
            and resource["reference_type"] != "source"
        ):
            return "CAP-RESOURCE-001"


def invocation_semantic_error(invocation, descriptor, context):
    if invocation["invocation_digest"] != expected_invocation_digest(invocation):
        return "CAP-INVOCATION-DIGEST-001"

    capability = invocation["capability"]
    if (
        capability["capability_id"],
        capability["capability_version"],
        capability["descriptor_digest"],
    ) != (
        descriptor["capability_id"],
        descriptor["capability_version"],
        descriptor["descriptor_digest"],
    ):
        return "CAP-DESCRIPTOR-BINDING-001"

    function = next(
        (
            item
            for item in descriptor["declared_functions"]
            if item["function_id"] == capability["function_id"]
        ),
        None,
    )
    if (
        function is None
        or invocation["execution_mode"]
        not in function["supported_execution_modes"]
    ):
        return "CAP-DESCRIPTOR-BINDING-001"

    expected_context_ref = {
        "context_pack_id": context["context_pack_id"],
        "context_pack_digest": context["context_pack_digest"],
    }
    if (
        invocation["project_id"] != context["project_id"]
        or invocation["context_pack"] != expected_context_ref
        or _canonical(invocation["pins"]) != _canonical(context["pins"])
    ):
        return "CAP-PIN-001"

    authorization = invocation["runtime_authorization_evidence"]
    if (
        authorization["capability_id"] != capability["capability_id"]
        or authorization["function_id"] != capability["function_id"]
        or invocation["execution_mode"] not in authorization["execution_modes"]
    ):
        return "CAP-AUTH-001"

    context_reference_ids = {
        resource["reference_id"] for resource in context["resources"]
    }
    if not context_reference_ids.issubset(
        set(authorization["resource_reference_ids"])
    ):
        return "CAP-AUTH-001"


def _resource_index(context):
    return {resource["reference_id"]: resource for resource in context["resources"]}


def _capture_index(handoff):
    return {
        capture["capture_id"]: capture
        for capture in handoff["outputs"]["source_captures"]
    }


def _basis_is_evidence_eligible(basis, context, handoff):
    resources = _resource_index(context)
    if basis["basis_type"] == "resource_reference":
        resource = resources.get(basis["resource_reference_id"])
    else:
        capture = _capture_index(handoff).get(basis["capture_id"])
        if capture is None:
            return False
        origin = capture["origin"]
        if origin["origin_type"] == "acquired_source":
            return True
        resource = resources.get(origin["resource_reference_id"])
    return bool(
        resource
        and resource["reference_type"] == "source"
        and resource["evidentiary_use"] == "candidate_source"
    )


def handoff_semantic_error(handoff, invocation, context):
    if handoff["handoff_digest"] != expected_handoff_digest(handoff):
        return "CAP-HANDOFF-DIGEST-001"

    if (
        handoff["invocation_id"] != invocation["invocation_id"]
        or handoff["run_id"] != invocation["run_id"]
        or handoff["project_id"] != invocation["project_id"]
    ):
        return "CAP-PIN-001"

    if (
        _canonical(handoff["capability"])
        != _canonical(invocation["capability"])
        or handoff["execution_mode"] != invocation["execution_mode"]
    ):
        return "CAP-DESCRIPTOR-BINDING-001"

    expected_pins = {
        "invocation_digest": invocation["invocation_digest"],
        "context_pack_digest": context["context_pack_digest"],
        "project_config_digest": context["pins"]["project_config"][
            "configuration_digest"
        ],
        "effective_profile_set_digest": context["pins"]["effective_profile_set"][
            "content_digest"
        ],
        "research_snapshot": context["pins"]["research_snapshot"],
    }
    if _canonical(handoff["input_pins"]) != _canonical(expected_pins):
        return "CAP-PIN-001"

    provenance = handoff["provenance"]
    if provenance["trace_id"] != invocation["trace"]["trace_id"]:
        return "CAP-HANDOFF-PROVENANCE-001"
    expected_input_digests = {
        invocation["capability"]["descriptor_digest"],
        context["context_pack_digest"],
        invocation["invocation_digest"],
    }
    if set(provenance["input_content_digests"]) != expected_input_digests:
        return "CAP-HANDOFF-PROVENANCE-001"

    preserved = handoff["preserved_context"]
    if (
        set(preserved["research_attention_ids"])
        != {item["attention_id"] for item in context["research_attention"]}
        or set(preserved["project_guard_ids"])
        != set(_flatten_guard_ids(context["project_constraints"]))
        or set(preserved["effective_constraint_paths"])
        != {item["path"] for item in context["effective_constraints"]}
    ):
        return "CAP-HANDOFF-PRESERVE-001"

    outputs = handoff["outputs"]
    fields = {
        "observations": "observation_id",
        "source_captures": "capture_id",
        "evidence_candidates": "evidence_candidate_id",
        "candidate_findings": "candidate_finding_id",
        "counterevidence": "counterevidence_id",
        "conflicts": "conflict_id",
        "unknowns": "unknown_id",
        "evidence_gaps": "gap_id",
        "candidate_next_actions": "proposal_id",
        "candidate_next_methods": "proposal_id",
    }
    output_ids = [
        item[field]
        for collection, field in fields.items()
        for item in outputs[collection]
    ]
    if _has_duplicates(output_ids):
        return "CAP-HANDOFF-IDENTITY-001"

    resources = _resource_index(context)
    for capture in outputs["source_captures"]:
        origin = capture["origin"]
        if origin["origin_type"] == "project_source_reference":
            resource = resources.get(origin["resource_reference_id"])
            if (
                not resource
                or resource["reference_type"] != "source"
                or resource["evidentiary_use"] != "candidate_source"
            ):
                return "CAP-HANDOFF-REF-001"

    evidence_ids = {
        item["evidence_candidate_id"] for item in outputs["evidence_candidates"]
    }
    counterevidence_ids = {
        item["counterevidence_id"] for item in outputs["counterevidence"]
    }
    question_ids = set(context["question_ids"])
    all_output_ids = set(output_ids)

    for observation in outputs["observations"]:
        if not set(observation.get("evidence_candidate_ids", [])).issubset(
            evidence_ids
        ):
            return "CAP-HANDOFF-REF-001"

    for finding in outputs["candidate_findings"]:
        if (
            not set(finding["question_ids"]).issubset(question_ids)
            or not set(finding["supporting_evidence_candidate_ids"]).issubset(
                evidence_ids
            )
            or not set(finding["counterevidence_candidate_ids"]).issubset(
                counterevidence_ids
            )
        ):
            return "CAP-HANDOFF-REF-001"

    if any(
        not set(gap["question_ids"]).issubset(question_ids)
        for gap in outputs["evidence_gaps"]
    ):
        return "CAP-HANDOFF-REF-001"

    if any(
        not set(conflict["related_output_ids"]).issubset(all_output_ids)
        for conflict in outputs["conflicts"]
    ):
        return "CAP-HANDOFF-REF-001"

    evidentiary_outputs = (
        outputs["observations"]
        + outputs["evidence_candidates"]
        + outputs["candidate_findings"]
        + outputs["counterevidence"]
    )
    if handoff["execution_mode"] in {"virtual", "synthetic_test"} and any(
        item["epistemic_mode"] != "synthetic" for item in evidentiary_outputs
    ):
        return "CAP-MODE-001"

    evidence_bearing_outputs = (
        outputs["evidence_candidates"] + outputs["counterevidence"]
    )
    if any(
        not _basis_is_evidence_eligible(item["source_basis"], context, handoff)
        for item in evidence_bearing_outputs
    ):
        return "CAP-RESOURCE-001"

    validation = handoff["validation"]
    if (
        validation["status"] == "valid"
        and validation["issues"]
    ) or (
        validation["status"] in {"partial", "rejected"}
        and not validation["issues"]
    ):
        return "CAP-HANDOFF-VALIDATION-001"


def semantic_case_error(
    target,
    document,
    *,
    descriptor,
    context,
    invocation,
    project_config,
    effective_profile_set,
    core_objects,
):
    if target == "descriptor":
        return descriptor_semantic_error(document)
    if target == "context":
        return context_semantic_error(
            document,
            project_config,
            effective_profile_set,
            core_objects,
        )
    if target == "invocation":
        return invocation_semantic_error(document, descriptor, context)
    if target == "handoff":
        return handoff_semantic_error(document, invocation, context)
    raise ValueError(f"unknown semantic case target: {target}")
