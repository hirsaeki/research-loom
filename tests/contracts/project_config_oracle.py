from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib

import rfc8785

PROFILE_CATEGORIES = ("research", "organization", "narrative", "publication")


def expected_configuration_digest(config: dict) -> str:
    """Return the fixture contract digest for Project Config content."""
    payload = deepcopy(config)
    payload.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def refresh_configuration_digest(config: dict) -> dict:
    config["configuration_digest"] = expected_configuration_digest(config)
    return config


def flatten_profile_requests(config: dict) -> list[dict]:
    """Project categories are presentation only; PR 4 receives direct requests."""
    requests: list[dict] = []
    for category in PROFILE_CATEGORIES:
        requests.extend(deepcopy(config["profile_requests"][category]))
    return requests


def _duplicates(values) -> bool:
    values = list(values)
    return len(values) != len(set(values))


def _local_identity_error(config: dict) -> str | None:
    domains = [
        (item["question_id"] for item in config["research_questions"]["references"]),
        (item["seed_id"] for item in config["research_questions"]["seeds"]),
        (item["attention_id"] for item in config["research_attention"]),
        (item["reference_id"] for item in config["resource_references"]),
        (item["capability_id"] for item in config["capability_hints"]),
    ]
    guards = [
        guard["guard_id"]
        for category in ("requirements", "prohibitions", "must_not_claim")
        for guard in config["project_constraints"][category]
    ]
    domains.append(iter(guards))
    if any(_duplicates(values) for values in domains):
        return "PROJECT-CONFIG-IDENTITY-001"
    return None


def _profile_request_identity_error(config: dict) -> str | None:
    keys = [
        (request["profile_type"], request["profile_id"])
        for request in flatten_profile_requests(config)
    ]
    if _duplicates(keys):
        return "PROJECT-PROFILE-REQUEST-IDENTITY-001"
    return None


def _reference_error(config: dict) -> str | None:
    question_ids = {item["question_id"] for item in config["research_questions"]["references"]}
    seeds = {item["seed_id"] for item in config["research_questions"]["seeds"]}
    resource_ids = {item["reference_id"] for item in config["resource_references"]}

    for seed in config["research_questions"]["seeds"]:
        parent = seed.get("parent_seed_id")
        if parent is not None and parent not in seeds:
            return "PROJECT-CONFIG-REF-001"

    for attention in config["research_attention"]:
        if not set(attention.get("source_reference_ids", [])) <= resource_ids:
            return "PROJECT-CONFIG-REF-001"
        if not set(attention.get("related_question_ids", [])) <= question_ids:
            return "PROJECT-CONFIG-REF-001"
        if not set(attention.get("related_question_seed_ids", [])) <= seeds:
            return "PROJECT-CONFIG-REF-001"

    if not set(config["provenance"]["source_reference_ids"]) <= resource_ids:
        return "PROJECT-CONFIG-REF-001"
    return None


def project_config_semantic_error(config: dict) -> str | None:
    """Thin fixture oracle; it is not a production Project Config validator."""
    if config.get("configuration_digest") != expected_configuration_digest(config):
        return "PROJECT-CONFIG-DIGEST-001"

    error = _profile_request_identity_error(config)
    if error:
        return error

    error = _local_identity_error(config)
    if error:
        return error

    in_scope = set(config["scope"]["in_scope"])
    out_of_scope = set(config["scope"]["out_of_scope"])
    if in_scope & out_of_scope:
        return "PROJECT-CONFIG-SCOPE-001"

    return _reference_error(config)


def project_profile_binding_error(config: dict, effective_profile_set: dict) -> str | None:
    """Bind categorized Project requests losslessly to PR 4 requested_profiles only."""
    project_requests = Counter(
        (item["profile_type"], item["profile_id"], item["version"])
        for item in flatten_profile_requests(config)
    )
    effective_requests = Counter(
        (item["profile_type"], item["profile_id"], item["version"])
        for item in effective_profile_set["requested_profiles"]
    )
    if project_requests != effective_requests:
        return "PROJECT-PROFILE-BINDING-001"
    return None


def project_core_binding_error(config: dict, core_objects: list[dict]) -> str | None:
    """Check only Project Config references that claim to target existing Core objects."""
    by_id = {obj["id"]: obj for obj in core_objects}
    project_id = config["project"]["project_id"]
    project = by_id.get(project_id)
    if project is None or project.get("kind") != "project":
        return "PROJECT-CORE-BINDING-001"

    for ref in config["research_questions"]["references"]:
        question = by_id.get(ref["question_id"])
        if question is None or question.get("kind") != "research_question" or question.get("project_id") != project_id:
            return "PROJECT-CORE-BINDING-001"

    expected_kinds = {"source": "source", "artifact": "artifact"}
    for ref in config["resource_references"]:
        expected = expected_kinds.get(ref["reference_type"])
        object_id = ref.get("object_id")
        if expected is None or object_id is None:
            continue
        obj = by_id.get(object_id)
        if obj is None or obj.get("kind") != expected or obj.get("project_id") != project_id:
            return "PROJECT-CORE-BINDING-001"
    return None


def apply_fixture_mutation(config: dict, mutation: str) -> dict:
    """Apply only the named synthetic mutations listed in projects/fixtures."""
    out = deepcopy(config)
    if mutation == "none":
        return out
    if mutation == "change-title-without-rehash":
        out["project"]["title"] += " changed"
        return out
    if mutation == "duplicate-narrative-request":
        duplicate = deepcopy(out["profile_requests"]["narrative"][0])
        duplicate["version"] = ">=1.0.0 <2.0.0"
        out["profile_requests"]["narrative"].append(duplicate)
        return out
    if mutation == "copy-in-scope-to-out-of-scope":
        out["scope"]["out_of_scope"].append(out["scope"]["in_scope"][0])
        return out
    if mutation == "replace-attention-source-reference-with-missing-id":
        out["research_attention"][0]["source_reference_ids"][0] = "REF-MISSING"
        return out
    if mutation == "duplicate-attention-item":
        out["research_attention"].append(deepcopy(out["research_attention"][0]))
        return out
    raise ValueError(f"unknown Project Config fixture mutation: {mutation}")
