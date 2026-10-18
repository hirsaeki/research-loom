from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import rfc8785
import yaml

from core.resources import resource_path
from core.runtime import canonical_digest
from core.runtime.digests import jcs_digest
from plugins.local_application.workspace.workspace import LocalWorkspaceError

from .profile_manifests import _load_candidates
from .profile_resolution_support import (
    CORE_CONTRACTS,
    CORE_INVARIANTS,
    EPS_SCHEMA,
    MAX_EFFECTIVE_RESOURCE_BYTES,
    MAX_EFFECTIVE_RESOURCES,
    MAX_PROFILE_RESOURCE_BYTES,
    MAX_PROFILE_RESOURCES,
    TYPE_RANK,
    _flatten_requests,
    _keyver,
    _pin,
    _semver,
    _validate_schema,
)
from .profile_selection import _resolve_selected


def _canonicalize_set(values):
    unique: dict[bytes, Any] = {}
    for value in values:
        encoded = rfc8785.dumps(value)
        unique.setdefault(encoded, json.loads(encoded.decode("utf-8")))
    return [unique[key] for key in sorted(unique)]


def _compose_constraints(selected) -> list[dict[str, Any]]:
    groups: dict[str, list[tuple[dict[str, Any], Mapping[str, Any]]]] = {}
    for candidate in selected.values():
        for declaration in candidate["manifest"].get("constraints", []):
            groups.setdefault(str(declaration["path"]), []).append((candidate, declaration))
    result = []
    for path in sorted(groups):
        declarations = groups[path]
        strategy = declarations[0][1]["merge_strategy"]
        if any(item[1]["merge_strategy"] != strategy for item in declarations):
            raise LocalWorkspaceError(
                "PROFILE-COMP-STRATEGY-001", f"conflicting merge strategy at {path}"
            )
        values = [item[1]["value"] for item in declarations]
        if strategy == "union":
            value = _canonicalize_set(member for members in values for member in members)
            resolution = "single" if len(declarations) == 1 else "union"
        elif strategy == "intersection":
            sets = [{rfc8785.dumps(member) for member in members} for members in values]
            common = set.intersection(*sets) if sets else set()
            value = [json.loads(item.decode("utf-8")) for item in sorted(common)]
            resolution = "single" if len(declarations) == 1 else "intersection"
        elif strategy == "must_equal":
            if any(item != values[0] for item in values[1:]):
                raise LocalWorkspaceError(
                    "PROFILE-COMP-CONFLICT-001", f"must_equal conflict at {path}"
                )
            value = values[0]
            resolution = "single" if len(declarations) == 1 else "identical"
        elif strategy == "max":
            value = max(values)
            resolution = "single" if len(declarations) == 1 else "max"
        elif strategy == "min":
            value = min(values)
            resolution = "single" if len(declarations) == 1 else "min"
        elif strategy == "replace":
            if any(item != values[0] for item in values[1:]):
                raise LocalWorkspaceError(
                    "PROFILE-COMP-REPLACE-001", f"ambiguous replace at {path}"
                )
            value = values[0]
            resolution = "single" if len(declarations) == 1 else "identical"
        else:
            raise LocalWorkspaceError(
                "PROFILE-COMP-STRATEGY-001", f"unsupported merge strategy {strategy}"
            )
        provenance = [
            {**_pin(candidate), "constraint_id": declaration["id"]}
            for candidate, declaration in declarations
        ]
        provenance.sort(
            key=lambda item: (
                TYPE_RANK[item["profile_type"]],
                item["profile_id"],
                _semver(item["profile_version"]),
                item["manifest_sha256"],
                item["constraint_id"],
            )
        )
        result.append(
            {
                "path": path,
                "merge_strategy": strategy,
                "value": value,
                "resolution": resolution,
                "provenance": provenance,
            }
        )
    return result


def _normalized_resource_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise LocalWorkspaceError(
            "PROFILE-RESOURCE-READ-001", f"cannot read Profile resource {path}"
        ) from exc


def _effective_resources(selected) -> list[dict[str, Any]]:
    profile_root = resource_path("profiles").resolve()
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    resource_count = 0
    resource_bytes = 0
    for candidate in selected.values():
        manifest = candidate["manifest"]
        manifest_path = Path(candidate["path"])
        declarations = list(manifest.get("resources", []))
        if len(declarations) > MAX_PROFILE_RESOURCES:
            raise LocalWorkspaceError(
                "PROFILE-RESOURCE-BOUND-001", "Profile declares too many resources"
            )
        resource_count += len(declarations)
        if resource_count > MAX_EFFECTIVE_RESOURCES:
            raise LocalWorkspaceError(
                "PROFILE-RESOURCE-BOUND-001", "Effective Profile Set declares too many resources"
            )
        for declaration in declarations:
            declared_path = str(declaration["path"])
            raw_path = manifest_path.parent / declared_path
            if raw_path.is_symlink():
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-SOURCE-001", "Profile resource may not be a symlink"
                )
            try:
                path = raw_path.resolve(strict=True)
                path.relative_to(profile_root)
                byte_size = path.stat().st_size
            except (OSError, ValueError) as exc:
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-SOURCE-001",
                    "Profile resource must exist inside canonical profiles/",
                ) from exc
            if byte_size > MAX_PROFILE_RESOURCE_BYTES:
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-BOUND-001",
                    f"Profile resource exceeds size bound: {declared_path}",
                )
            resource_bytes += byte_size
            if resource_bytes > MAX_EFFECTIVE_RESOURCE_BYTES:
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-BOUND-001",
                    "Effective Profile Set resources exceed size bound",
                )
            expected = declaration.get("sha256")
            if not isinstance(expected, str):
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-DIGEST-001",
                    "production Profile resources require a sha256 pin",
                )
            payload = _normalized_resource_bytes(path)
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-DIGEST-001",
                    f"Profile resource digest mismatch: {declared_path}",
                )
            try:
                content = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LocalWorkspaceError(
                    "PROFILE-RESOURCE-ENCODING-001",
                    "production Profile resources must be UTF-8 text",
                ) from exc
            canonical_path = path.relative_to(profile_root).as_posix()
            role = str(declaration["role"])
            key = (canonical_path, role, actual)
            source = {**_pin(candidate), "declared_path": declared_path}
            item = grouped.setdefault(
                key,
                {
                    "path": canonical_path,
                    "role": role,
                    "sha256": actual,
                    "byte_length": len(payload),
                    "content": content,
                    "provenance": [],
                },
            )
            if source not in item["provenance"]:
                item["provenance"].append(source)
    result = list(grouped.values())
    for item in result:
        item["provenance"].sort(
            key=lambda source: (
                TYPE_RANK[source["profile_type"]],
                source["profile_id"],
                _semver(source["profile_version"]),
                source["manifest_sha256"],
                source["declared_path"],
            )
        )
    result.sort(key=lambda item: (item["path"], item["role"], item["sha256"]))
    return result


def _effective_invariants(selected) -> list[dict[str, Any]]:
    registry = yaml.safe_load(CORE_INVARIANTS.read_text(encoding="utf-8"))
    strengthenings: dict[str, list[dict[str, Any]]] = {}
    for candidate in selected.values():
        for strengthening in candidate["manifest"].get("core_invariant_strengthenings", []):
            strengthenings.setdefault(str(strengthening["invariant_id"]), []).append(
                {
                    **_pin(candidate),
                    "constraint_ids": list(strengthening["constraint_ids"]),
                    "validator_binding": deepcopy(strengthening["validator_binding"]),
                }
            )
    result = []
    for invariant in registry["invariants"]:
        provenance = strengthenings.get(str(invariant["id"]), [])
        provenance.sort(
            key=lambda item: (
                TYPE_RANK[item["profile_type"]],
                item["profile_id"],
                _semver(item["profile_version"]),
                item["manifest_sha256"],
            )
        )
        result.append(
            {
                "invariant_id": invariant["id"],
                "status": "strengthened" if provenance else "preserved",
                "provenance": provenance,
            }
        )
    return result


def _validate_effective_narrative(constraints: list[Mapping[str, Any]]) -> None:
    values = {str(item["path"]): item["value"] for item in constraints}
    stages = values.get("narrative.stages.definitions", [])
    dependencies = values.get("narrative.dependencies.required", [])
    purposes = values.get("narrative.section_purposes.definitions", [])
    stage_defs: dict[str, Any] = {}
    for stage in stages:
        if not isinstance(stage, Mapping) or not isinstance(stage.get("id"), str):
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-VALUE-001", "invalid Narrative stage definition"
            )
        identifier = str(stage["id"])
        if identifier in stage_defs and stage_defs[identifier] != stage:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-IDENTITY-001", f"divergent Narrative stage {identifier}"
            )
        stage_defs[identifier] = stage
    graph = {identifier: [] for identifier in stage_defs}
    edge_defs: dict[tuple[str, str], Any] = {}
    for edge in dependencies:
        if not isinstance(edge, Mapping) or not all(
            isinstance(edge.get(key), str) for key in ("from_stage", "to_stage", "relation")
        ):
            raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", "invalid Narrative dependency")
        source, target = str(edge["from_stage"]), str(edge["to_stage"])
        if source not in graph or target not in graph:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-REF-001", "Narrative dependency references an unknown stage"
            )
        identity = (source, target)
        if identity in edge_defs and edge_defs[identity] != edge:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-IDENTITY-001", "divergent Narrative dependency"
            )
        edge_defs[identity] = edge
        graph[source].append(target)
    purpose_defs: dict[str, Any] = {}
    for purpose in purposes:
        if (
            not isinstance(purpose, Mapping)
            or not isinstance(purpose.get("id"), str)
            or not isinstance(purpose.get("stage_ids"), list)
        ):
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-VALUE-001", "invalid Narrative section purpose"
            )
        identifier = str(purpose["id"])
        if identifier in purpose_defs and purpose_defs[identifier] != purpose:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-IDENTITY-001",
                f"divergent Narrative section purpose {identifier}",
            )
        if any(stage_id not in graph for stage_id in purpose["stage_ids"]):
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-REF-001", "Narrative section purpose references an unknown stage"
            )
        purpose_defs[identifier] = purpose
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise LocalWorkspaceError(
                "NARRATIVE-DEPENDENCY-CYCLE-001", "Narrative dependency graph contains a cycle"
            )
        if node in done:
            return
        visiting.add(node)
        for target in graph[node]:
            visit(target)
        visiting.remove(node)
        done.add(node)

    for node in graph:
        visit(node)


def resolve_effective_profile_set(
    project_config: Mapping[str, Any],
    manifest_files: Iterable[str | Path],
) -> dict[str, Any]:
    candidates = _load_candidates(manifest_files)
    requests = _flatten_requests(project_config)
    effective_profiles, selected = _resolve_selected(candidates, requests)
    effective_constraints = _compose_constraints(selected)
    _validate_effective_narrative(effective_constraints)
    effective_resources = _effective_resources(selected)
    eps = {
        "schema_version": "0.1.0",
        "core_contracts": deepcopy(CORE_CONTRACTS),
        "candidate_universe": [
            _pin(candidate)
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    TYPE_RANK[item["manifest"]["profile_type"]],
                    item["manifest"]["profile_id"],
                    _semver(item["manifest"]["profile_version"]),
                    item["manifest_sha256"],
                ),
            )
        ],
        "requested_profiles": deepcopy(requests),
        "effective_profiles": effective_profiles,
        "effective_constraints": effective_constraints,
        "core_invariants": _effective_invariants(selected),
    }
    if effective_resources:
        eps["effective_resources"] = effective_resources
    _validate_schema(eps, EPS_SCHEMA, "WORKSPACE-PROFILE-SET-SCHEMA-001")
    return eps


def target_project_config(
    current: Mapping[str, Any],
    replacements: Iterable[Mapping[str, Any]],
    additions: Iterable[Mapping[str, Any]] = (),
    *,
    publication_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target = deepcopy(dict(current))
    changed = False
    for replacement in replacements:
        old = replacement.get("from")
        new = replacement.get("to")
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-REQUEST-001", "each request replacement needs from/to objects"
            )
        profile_type = str(old.get("profile_type", ""))
        if (
            profile_type not in ("research", "organization", "narrative", "publication")
            or str(new.get("profile_type", "")) != profile_type
        ):
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-REQUEST-001",
                "request replacement must stay within one Profile type",
            )
        items = target["profile_requests"][profile_type]
        matches = [index for index, item in enumerate(items) if item == dict(old)]
        if len(matches) != 1:
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-REQUEST-001", "request replacement source must match exactly once"
            )
        items[matches[0]] = deepcopy(dict(new))
        changed = changed or dict(old) != dict(new)
    for addition in additions:
        if not isinstance(addition, Mapping):
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-REQUEST-001", "request addition must be an object"
            )
        item = deepcopy(dict(addition))
        profile_type = str(item.get("profile_type", ""))
        profile_id = str(item.get("profile_id", ""))
        if (
            profile_type not in ("research", "organization", "narrative", "publication")
            or not profile_id
        ):
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-REQUEST-001",
                "request addition must identify a supported Profile type and id",
            )
        items = target["profile_requests"][profile_type]
        if item in items:
            continue
        if any(str(existing.get("profile_id")) == profile_id for existing in items):
            raise LocalWorkspaceError(
                "PROFILE-ADVANCE-REQUEST-001",
                "request addition collides with an existing Profile id",
            )
        items.append(item)
        changed = True
    metadata_changed = publication_metadata is not None and dict(
        publication_metadata
    ) != current.get("publication_metadata", {})
    if metadata_changed:
        if set(publication_metadata) != {"research_group_type"} or publication_metadata.get(
            "research_group_type"
        ) not in {"G", "M"}:
            raise LocalWorkspaceError(
                "INPUT-RESEARCH-GROUP-TYPE",
                "Publication metadata requires an explicit G or M answer",
            )
        target["publication_metadata"] = deepcopy(dict(publication_metadata))
        major, minor, patch = str(current["config_version"]).split(".")
        target["config_version"] = f"{major}.{minor}.{int(patch) + 1}"
    if changed or metadata_changed:
        prior_digest = str(current["configuration_digest"])
        derived = target["provenance"].setdefault("derived_from_configuration_digests", [])
        if prior_digest not in derived:
            derived.append(prior_digest)
        notes = target["provenance"].setdefault("notes", [])
        if changed:
            note = "Profile generation advancement: direct Profile requests changed mechanically; other project semantics are unchanged."
            if note not in notes:
                notes.append(note)
        if metadata_changed:
            note = "Publication metadata advancement: explicit research group answer saved; research content is unchanged."
            if note not in notes:
                notes.append(note)
        target.pop("configuration_digest", None)
        target["configuration_digest"] = jcs_digest(target)
    return target


def exact_manifest_identity_map(
    manifest_files: Iterable[str | Path],
) -> dict[tuple[str, str, str], str]:
    return {
        _keyver(item["manifest"]): str(item["manifest_sha256"])
        for item in _load_candidates(manifest_files)
    }


def effective_profile_digest(eps: Mapping[str, Any]) -> str:
    return canonical_digest(eps)
