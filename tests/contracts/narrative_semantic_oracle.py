from __future__ import annotations

from copy import deepcopy
from typing import Any


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["path"]: entry for entry in catalog["constraint_paths"]}


def catalog_cross_reference_errors(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    vocabularies = catalog.get("vocabularies", {})
    shapes = catalog.get("value_shapes", {})
    for entry in catalog.get("constraint_paths", []):
        shape = entry.get("value_shape")
        if shape == "enum_set":
            vocabulary = entry.get("vocabulary")
            if vocabulary not in vocabularies:
                errors.append(f"missing vocabulary for {entry.get('path')}: {vocabulary}")
        elif shape not in shapes:
            errors.append(f"missing value shape for {entry.get('path')}: {shape}")
    return errors


def _unique_strings(value: Any, allowed: set[str]) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item in allowed for item in value)
    )


def _valid_stage(item: Any, vocabularies: dict[str, list[str]]) -> bool:
    if not isinstance(item, dict) or set(item) != {"id", "semantic_role", "consumes", "requires", "produces"}:
        return False
    if not isinstance(item["id"], str) or not item["id"]:
        return False
    if item["semantic_role"] not in vocabularies["semantic_role"]:
        return False
    if not _unique_strings(item["consumes"], set(vocabularies["research_input_kind"])):
        return False
    if not _unique_strings(item["requires"], set(vocabularies["research_input_kind"])):
        return False
    if not _unique_strings(item["produces"], set(vocabularies["narrative_product"])):
        return False
    return True


def _valid_dependency(item: Any, vocabularies: dict[str, list[str]]) -> bool:
    return (
        isinstance(item, dict)
        and set(item) == {"from_stage", "to_stage", "relation"}
        and isinstance(item["from_stage"], str)
        and bool(item["from_stage"])
        and isinstance(item["to_stage"], str)
        and bool(item["to_stage"])
        and item["from_stage"] != item["to_stage"]
        and item["relation"] in vocabularies["dependency_relation"]
    )


def _valid_section_purpose(item: Any, vocabularies: dict[str, list[str]]) -> bool:
    return (
        isinstance(item, dict)
        and set(item) == {"id", "purpose_role", "stage_ids"}
        and isinstance(item["id"], str)
        and bool(item["id"])
        and item["purpose_role"] in vocabularies["section_purpose_role"]
        and isinstance(item["stage_ids"], list)
        and bool(item["stage_ids"])
        and len(item["stage_ids"]) == len(set(item["stage_ids"]))
        and all(isinstance(stage_id, str) and stage_id for stage_id in item["stage_ids"])
    )


def narrative_constraint_error(profile: dict[str, Any], catalog: dict[str, Any]) -> str | None:
    catalog_errors = catalog_cross_reference_errors(catalog)
    if catalog_errors:
        raise AssertionError("invalid Narrative semantics catalog: " + "; ".join(catalog_errors))
    index = catalog_index(catalog)
    vocabularies = catalog["vocabularies"]
    for constraint in profile.get("constraints", []):
        path = constraint["path"]
        if not path.startswith("narrative."):
            continue
        if profile["profile_type"] != "narrative":
            return "PROFILE-NARRATIVE-OWNER-001"
        spec = index.get(path)
        if spec is None:
            return "PROFILE-NARRATIVE-PATH-001"
        if constraint["merge_strategy"] != spec["merge_strategy"]:
            return "PROFILE-NARRATIVE-MERGE-001"
        value = constraint["value"]
        if not isinstance(value, list):
            return "PROFILE-NARRATIVE-VALUE-001"
        shape = spec["value_shape"]
        if shape == "enum_set":
            if not _unique_strings(value, set(vocabularies[spec["vocabulary"]])):
                return "PROFILE-NARRATIVE-VALUE-001"
        elif shape == "stage_set":
            if any(not _valid_stage(item, vocabularies) for item in value):
                return "PROFILE-NARRATIVE-VALUE-001"
            ids = [item["id"] for item in value]
            if len(ids) != len(set(ids)):
                return "PROFILE-NARRATIVE-IDENTITY-001"
        elif shape == "dependency_set":
            if any(not _valid_dependency(item, vocabularies) for item in value):
                return "PROFILE-NARRATIVE-VALUE-001"
            identities = [(item["from_stage"], item["to_stage"]) for item in value]
            if len(identities) != len(set(identities)):
                return "PROFILE-NARRATIVE-IDENTITY-001"
        elif shape == "section_purpose_set":
            if any(not _valid_section_purpose(item, vocabularies) for item in value):
                return "PROFILE-NARRATIVE-VALUE-001"
            ids = [item["id"] for item in value]
            if len(ids) != len(set(ids)):
                return "PROFILE-NARRATIVE-IDENTITY-001"
        else:
            raise AssertionError(f"unknown Narrative value_shape: {shape}")
    return None


def _structured_values(profiles: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for profile in profiles:
        for constraint in profile.get("constraints", []):
            if constraint["path"] == path:
                result.extend(constraint["value"])
    return result


def _normalized_stage(stage: dict[str, Any]) -> tuple[Any, ...]:
    return (
        stage["semantic_role"],
        tuple(sorted(stage["consumes"])),
        tuple(sorted(stage["requires"])),
        tuple(sorted(stage["produces"])),
    )


def _normalized_purpose(purpose: dict[str, Any]) -> tuple[Any, ...]:
    return purpose["purpose_role"], tuple(sorted(purpose["stage_ids"]))


def narrative_composition_error(profiles: list[dict[str, Any]], catalog: dict[str, Any]) -> str | None:
    for profile in profiles:
        error = narrative_constraint_error(profile, catalog)
        if error:
            return error

    stages = _structured_values(profiles, "narrative.stages.definitions")
    by_stage: dict[str, tuple[Any, ...]] = {}
    for stage in stages:
        normalized = _normalized_stage(stage)
        if stage["id"] in by_stage and by_stage[stage["id"]] != normalized:
            return "PROFILE-NARRATIVE-IDENTITY-001"
        by_stage[stage["id"]] = normalized

    purposes = _structured_values(profiles, "narrative.section_purposes.definitions")
    by_purpose: dict[str, tuple[Any, ...]] = {}
    for purpose in purposes:
        normalized = _normalized_purpose(purpose)
        if purpose["id"] in by_purpose and by_purpose[purpose["id"]] != normalized:
            return "PROFILE-NARRATIVE-IDENTITY-001"
        by_purpose[purpose["id"]] = normalized

    dependencies = _structured_values(profiles, "narrative.dependencies.required")
    by_edge: dict[tuple[str, str], str] = {}
    for dep in dependencies:
        edge = (dep["from_stage"], dep["to_stage"])
        if edge in by_edge and by_edge[edge] != dep["relation"]:
            return "PROFILE-NARRATIVE-IDENTITY-001"
        by_edge[edge] = dep["relation"]
        if dep["from_stage"] not in by_stage or dep["to_stage"] not in by_stage:
            return "PROFILE-NARRATIVE-REF-001"

    for purpose in purposes:
        if any(stage_id not in by_stage for stage_id in purpose["stage_ids"]):
            return "PROFILE-NARRATIVE-REF-001"

    graph = {stage_id: [] for stage_id in by_stage}
    for from_stage, to_stage in by_edge:
        graph[from_stage].append(to_stage)
    visiting: set[str] = set()
    done: set[str] = set()

    def dfs(stage_id: str) -> bool:
        if stage_id in visiting:
            return False
        if stage_id in done:
            return True
        visiting.add(stage_id)
        for nxt in graph[stage_id]:
            if not dfs(nxt):
                return False
        visiting.remove(stage_id)
        done.add(stage_id)
        return True

    if not all(dfs(stage_id) for stage_id in graph):
        return "NARRATIVE-DEPENDENCY-CYCLE-001"
    return None


def apply_mutations(base: dict[str, Any], mutations: list[dict[str, Any]]) -> dict[str, Any]:
    state = deepcopy(base)
    for mutation in mutations:
        parts = mutation["path"].split(".")
        parent: Any = state
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        leaf = parts[-1]
        if mutation["op"] == "set":
            if isinstance(parent, list):
                parent[int(leaf)] = deepcopy(mutation["value"])
            else:
                parent[leaf] = deepcopy(mutation["value"])
        elif mutation["op"] == "remove":
            if isinstance(parent, list):
                parent.pop(int(leaf))
            else:
                parent.pop(leaf, None)
        else:
            raise AssertionError(f"unknown mutation op: {mutation['op']}")
    return state


def narrative_projection_error(state: dict[str, Any], profile: dict[str, Any]) -> str | None:
    constraints = {item["path"]: item["value"] for item in profile.get("constraints", [])}
    projection = state["projection"]

    prohibited = set(constraints["narrative.authority.prohibited_actions"])
    if state["research_state_digest_before"] != state["research_state_digest_after"]:
        return "NARRATIVE-AUTHORITY-001"
    if prohibited.intersection(projection.get("authority_actions", [])):
        return "NARRATIVE-AUTHORITY-001"

    required_preservation = set(constraints["narrative.preservation.required_content"])
    preservation = projection.get("required_preservation", [])
    represented_types = {item.get("content") for item in preservation if item.get("effect_preserved") is True}
    if not required_preservation.issubset(represented_types):
        return "NARRATIVE-PRESERVATION-001"
    if any(item.get("content") in required_preservation and not item.get("effect_preserved") for item in preservation):
        return "NARRATIVE-PRESERVATION-001"

    authoritative = set(state["authoritative_connections"])
    represented = set(projection.get("represented_connections", []))
    if represented != authoritative:
        return "NARRATIVE-CONNECTION-001"

    non_normative_hints = set(constraints["narrative.projection.non_normative_hints"])
    for hint in projection.get("hints", []):
        if hint.get("kind") in non_normative_hints and hint.get("treatment") != "projection_hint":
            return "NARRATIVE-PROJECTION-HINT-001"
    return None
