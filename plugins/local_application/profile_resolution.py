from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785
import yaml

from core.runtime import canonical_digest
from plugins.local_application.workspace import LocalWorkspaceError

ROOT = Path(__file__).resolve().parents[2]
PROFILE_MANIFEST_SCHEMA = ROOT / "profiles/contracts/profile-manifest.schema.json"
EPS_SCHEMA = ROOT / "profiles/contracts/effective-profile-set.schema.json"
CORE_INVARIANTS = ROOT / "core/validators/non-overridable-invariants.yaml"
STRENGTHENING_REGISTRY = ROOT / "profiles/contracts/invariant-strengthening-validators.yaml"
NARRATIVE_SEMANTICS = ROOT / "profiles/contracts/narrative-semantics.yaml"
CORE_CONTRACTS = {"research_contract": "0.1.0", "invariant_contract": "0.1.0"}
TYPE_RANK = {name: i for i, name in enumerate(("research", "organization", "narrative", "publication"))}
_COMPARATOR = re.compile(r"^(>=|>|<=|<|=)(\d+\.\d+\.\d+)$")


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalWorkspaceError(code, f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise LocalWorkspaceError(code, f"JSON document must be an object: {path}")
    return value


def _validate_schema(value: Mapping[str, Any], schema_path: Path, code: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise LocalWorkspaceError(code, f"schema violation at {location}: {error.message}")


def _sha256(path: Path) -> str:
    # Git may materialize canonical JSON manifests with CRLF on Windows.
    # Profile identity pins describe repository content, not checkout line-ending policy.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _semver(text: str) -> tuple[int, int, int]:
    return tuple(int(item) for item in text.split("."))  # type: ignore[return-value]


def _satisfies(version: str, requirement: str) -> bool:
    value = _semver(version)
    if re.fullmatch(r"\d+\.\d+\.\d+", requirement):
        return value == _semver(requirement)
    for token in requirement.split():
        match = _COMPARATOR.fullmatch(token)
        if match is None:
            raise LocalWorkspaceError("PROFILE-VERSION-001", f"unsupported version requirement {requirement!r}")
        op, rhs_text = match.groups()
        rhs = _semver(rhs_text)
        if op == ">=" and not value >= rhs:
            return False
        if op == ">" and not value > rhs:
            return False
        if op == "<=" and not value <= rhs:
            return False
        if op == "<" and not value < rhs:
            return False
        if op == "=" and not value == rhs:
            return False
    return True


def _key(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value["profile_type"]), str(value["profile_id"])


def _keyver(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(value["profile_type"]), str(value["profile_id"]), str(value["profile_version"])


def _pin(candidate: Mapping[str, Any]) -> dict[str, Any]:
    manifest = candidate["manifest"]
    return {
        "profile_id": manifest["profile_id"],
        "profile_type": manifest["profile_type"],
        "profile_version": manifest["profile_version"],
        "manifest_sha256": candidate["manifest_sha256"],
    }


def _flatten_requests(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for profile_type in ("research", "organization", "narrative", "publication"):
        requests.extend(deepcopy(list(config["profile_requests"][profile_type])))
    return requests


def _unique_strings(value: Any, allowed: set[str]) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item in allowed for item in value)
    )


def _valid_narrative_stage(item: Any, vocabularies: Mapping[str, list[str]]) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == {"id", "semantic_role", "consumes", "requires", "produces"}
        and isinstance(item["id"], str)
        and bool(item["id"])
        and item["semantic_role"] in vocabularies["semantic_role"]
        and _unique_strings(item["consumes"], set(vocabularies["research_input_kind"]))
        and _unique_strings(item["requires"], set(vocabularies["research_input_kind"]))
        and _unique_strings(item["produces"], set(vocabularies["narrative_product"]))
    )


def _valid_narrative_dependency(item: Any, vocabularies: Mapping[str, list[str]]) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == {"from_stage", "to_stage", "relation"}
        and isinstance(item["from_stage"], str)
        and bool(item["from_stage"])
        and isinstance(item["to_stage"], str)
        and bool(item["to_stage"])
        and item["from_stage"] != item["to_stage"]
        and item["relation"] in vocabularies["dependency_relation"]
    )


def _valid_narrative_purpose(item: Any, vocabularies: Mapping[str, list[str]]) -> bool:
    return (
        isinstance(item, Mapping)
        and set(item) == {"id", "purpose_role", "stage_ids"}
        and isinstance(item["id"], str)
        and bool(item["id"])
        and item["purpose_role"] in vocabularies["section_purpose_role"]
        and isinstance(item["stage_ids"], list)
        and bool(item["stage_ids"])
        and len(item["stage_ids"]) == len(set(item["stage_ids"]))
        and all(isinstance(stage_id, str) and stage_id for stage_id in item["stage_ids"])
    )


def _validate_manifest_semantics(manifest: Mapping[str, Any]) -> None:
    compat = manifest["core_compatibility"]
    if not _satisfies(CORE_CONTRACTS["research_contract"], str(compat["research_contract"])) or not _satisfies(
        CORE_CONTRACTS["invariant_contract"], str(compat["invariant_contract"])
    ):
        raise LocalWorkspaceError("PROFILE-CORE-COMPAT-001", "Profile is incompatible with current Core contracts")

    narrative_contract = yaml.safe_load(NARRATIVE_SEMANTICS.read_text(encoding="utf-8"))
    narrative_paths = {item["path"]: item for item in narrative_contract["constraint_paths"]}
    vocabularies = narrative_contract["vocabularies"]
    for constraint in manifest.get("constraints", []):
        path = str(constraint["path"])
        if not path.startswith("narrative."):
            continue
        if manifest["profile_type"] != "narrative":
            raise LocalWorkspaceError("PROFILE-NARRATIVE-OWNER-001", "narrative.* constraints are owned by Narrative Profiles")
        spec = narrative_paths.get(path)
        if spec is None:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-PATH-001", f"unknown canonical Narrative path {path}")
        if constraint["merge_strategy"] != spec["merge_strategy"]:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-MERGE-001", f"wrong merge strategy for {path}")
        value = constraint["value"]
        if not isinstance(value, list):
            raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", f"Narrative value for {path} must be a list")
        shape = spec["value_shape"]
        if shape == "enum_set":
            if not _unique_strings(value, set(vocabularies[spec["vocabulary"]])):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", f"Narrative vocabulary violation at {path}")
        elif shape == "stage_set":
            if any(not _valid_narrative_stage(item, vocabularies) for item in value):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", f"Narrative stage definition violation at {path}")
            identities = [item["id"] for item in value]
            if len(identities) != len(set(identities)):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-IDENTITY-001", f"duplicate Narrative stage identity at {path}")
        elif shape == "dependency_set":
            if any(not _valid_narrative_dependency(item, vocabularies) for item in value):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", f"Narrative dependency definition violation at {path}")
            identities = [(item["from_stage"], item["to_stage"]) for item in value]
            if len(identities) != len(set(identities)):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-IDENTITY-001", f"duplicate Narrative dependency identity at {path}")
        elif shape == "section_purpose_set":
            if any(not _valid_narrative_purpose(item, vocabularies) for item in value):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", f"Narrative section-purpose definition violation at {path}")
            identities = [item["id"] for item in value]
            if len(identities) != len(set(identities)):
                raise LocalWorkspaceError("PROFILE-NARRATIVE-IDENTITY-001", f"duplicate Narrative section-purpose identity at {path}")
        else:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", f"unsupported Narrative value shape at {path}")

    registry = yaml.safe_load(STRENGTHENING_REGISTRY.read_text(encoding="utf-8"))
    declarations = {str(item["id"]): item for item in manifest.get("constraints", [])}
    for strengthening in manifest.get("core_invariant_strengthenings", []):
        invariant = registry["invariants"].get(strengthening["invariant_id"])
        binding = strengthening["validator_binding"]
        matched_form = None
        matched_validator = None
        if invariant and invariant.get("strengthening_policy") == "registered_forms":
            for validator in invariant.get("validators", []):
                if validator["validator_id"] != binding["validator_id"] or validator["validator_version"] != binding["validator_version"]:
                    continue
                for form in validator.get("approved_forms", []):
                    if form["form_id"] == binding["form_id"]:
                        matched_validator = validator
                        matched_form = form
                        break
        if matched_form is None or matched_validator is None:
            raise LocalWorkspaceError("PROFILE-CORE-STRENGTHENING-001", "Profile strengthening is not registered")
        prefix = matched_validator.get("applicability", {}).get("profile_id_prefix")
        if isinstance(prefix, str) and not str(manifest["profile_id"]).startswith(prefix):
            raise LocalWorkspaceError("PROFILE-CORE-STRENGTHENING-001", "Profile strengthening is outside the registered applicability")
        referenced = []
        for constraint_id in strengthening["constraint_ids"]:
            declaration = declarations.get(str(constraint_id))
            if declaration is None:
                raise LocalWorkspaceError("PROFILE-MANIFEST-REF-001", "Profile strengthening references an unknown constraint")
            referenced.append(declaration)
        for required in matched_form.get("required_constraints", []):
            match = next(
                (
                    item for item in referenced
                    if item["path"] == required["path"] and item["merge_strategy"] == required["merge_strategy"]
                ),
                None,
            )
            if match is None or ("const" in required.get("value_schema", {}) and match["value"] != required["value_schema"]["const"]):
                raise LocalWorkspaceError("PROFILE-CORE-STRENGTHENING-001", "Profile strengthening does not satisfy its registered form")


def _load_candidates(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    identities: dict[tuple[str, str, str], str] = {}
    profile_root = (ROOT / "profiles").resolve()
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve(strict=True)
        try:
            path.relative_to(profile_root)
        except ValueError as exc:
            raise LocalWorkspaceError(
                "PROFILE-MANIFEST-SOURCE-001",
                "production Profile resolution accepts only canonical repository Profile sources",
            ) from exc
        if path.is_symlink():
            raise LocalWorkspaceError("PROFILE-MANIFEST-SOURCE-001", "Profile manifest may not be a symlink")
        manifest = _load_json(path, "PROFILE-MANIFEST-READ-001")
        _validate_schema(manifest, PROFILE_MANIFEST_SCHEMA, "PROFILE-MANIFEST-SCHEMA-001")
        _validate_manifest_semantics(manifest)
        digest = _sha256(path)
        identity = _keyver(manifest)
        previous = identities.get(identity)
        if previous is not None and previous != digest:
            raise LocalWorkspaceError(
                "PROFILE-CANDIDATE-IDENTITY-001",
                "same Profile id/version was supplied with different manifest content",
            )
        if previous == digest:
            continue
        identities[identity] = digest
        candidates.append({"manifest": manifest, "manifest_sha256": digest, "path": str(path)})
    if not candidates:
        raise LocalWorkspaceError("PROFILE-CANDIDATE-EMPTY-001", "at least one Profile manifest is required")
    return candidates


def _assignment_valid(assignment, requests) -> bool:
    selected = {key: candidate for key, candidate in assignment.items() if candidate is not None}
    requested_keys = {_key(request) for request in requests}
    for request in requests:
        candidate = selected.get(_key(request))
        if candidate is None or not _satisfies(str(candidate["manifest"]["profile_version"]), str(request["version"])):
            return False
    reachable = set(requested_keys)
    frontier = list(requested_keys)
    while frontier:
        key = frontier.pop()
        candidate = selected.get(key)
        if candidate is None:
            return False
        manifest = candidate["manifest"]
        compat = manifest["core_compatibility"]
        if not _satisfies(CORE_CONTRACTS["research_contract"], str(compat["research_contract"])) or not _satisfies(
            CORE_CONTRACTS["invariant_contract"], str(compat["invariant_contract"])
        ):
            return False
        for relation in ("extends", "requires"):
            for dependency in manifest.get(relation, []):
                dep_key = _key(dependency)
                if relation == "extends" and dependency["profile_type"] != manifest["profile_type"]:
                    return False
                target = selected.get(dep_key)
                if target is None or not _satisfies(str(target["manifest"]["profile_version"]), str(dependency["version"])):
                    return False
                if dep_key not in reachable:
                    reachable.add(dep_key)
                    frontier.append(dep_key)
    if set(selected) != reachable:
        return False
    graph = {key: [] for key in selected}
    for key, candidate in selected.items():
        for relation in ("extends", "requires"):
            graph[key].extend(_key(dependency) for dependency in candidate["manifest"].get(relation, []))
    visiting: set[tuple[str, str]] = set()
    done: set[tuple[str, str]] = set()

    def visit(key: tuple[str, str]) -> bool:
        if key in visiting:
            return False
        if key in done:
            return True
        visiting.add(key)
        if not all(visit(target) for target in graph[key]):
            return False
        visiting.remove(key)
        done.add(key)
        return True

    return all(visit(key) for key in graph)


def _resolve_selected(candidates, requests):
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_key.setdefault(_key(candidate["manifest"]), []).append(candidate)
    keys = sorted(by_key, key=lambda key: (TYPE_RANK[key[0]], key[1]))
    choices = [[None] + sorted(by_key[key], key=lambda candidate: _semver(candidate["manifest"]["profile_version"])) for key in keys]
    valid = []
    for combination in itertools.product(*choices):
        assignment = dict(zip(keys, combination))
        if _assignment_valid(assignment, requests):
            valid.append(assignment)
    if not valid:
        raise LocalWorkspaceError("PROFILE-VERSION-001", "no compatible Profile resolution exists for the requested generation")
    absent = (-1, -1, -1)
    winner = max(
        valid,
        key=lambda assignment: tuple(
            absent if assignment[key] is None else _semver(assignment[key]["manifest"]["profile_version"])
            for key in keys
        ),
    )
    selected = {key: candidate for key, candidate in winner.items() if candidate is not None}
    output = []
    relation_rank = {"requested": 0, "extends": 1, "requires": 2}
    for key in sorted(selected, key=lambda item: (TYPE_RANK[item[0]], item[1])):
        candidate = selected[key]
        sources = []
        for request in requests:
            if _key(request) == key:
                sources.append({"relation": "requested", "required_version": request["version"]})
        for introduced in selected.values():
            for relation in ("extends", "requires"):
                for dependency in introduced["manifest"].get(relation, []):
                    if _key(dependency) == key:
                        sources.append({"relation": relation, "introduced_by": _pin(introduced), "required_version": dependency["version"]})
        sources.sort(
            key=lambda source: (
                relation_rank[source["relation"]],
                TYPE_RANK[(source.get("introduced_by") or {"profile_type": "research"})["profile_type"]],
                (source.get("introduced_by") or {}).get("profile_id", ""),
                source["required_version"],
            )
        )
        output.append({**_pin(candidate), "selection_provenance": sources})
    return output, selected


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
            raise LocalWorkspaceError("PROFILE-COMP-STRATEGY-001", f"conflicting merge strategy at {path}")
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
                raise LocalWorkspaceError("PROFILE-COMP-CONFLICT-001", f"must_equal conflict at {path}")
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
                raise LocalWorkspaceError("PROFILE-COMP-REPLACE-001", f"ambiguous replace at {path}")
            value = values[0]
            resolution = "single" if len(declarations) == 1 else "identical"
        else:
            raise LocalWorkspaceError("PROFILE-COMP-STRATEGY-001", f"unsupported merge strategy {strategy}")
        provenance = [{**_pin(candidate), "constraint_id": declaration["id"]} for candidate, declaration in declarations]
        provenance.sort(key=lambda item: (TYPE_RANK[item["profile_type"]], item["profile_id"], _semver(item["profile_version"]), item["manifest_sha256"], item["constraint_id"]))
        result.append({"path": path, "merge_strategy": strategy, "value": value, "resolution": resolution, "provenance": provenance})
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
        provenance.sort(key=lambda item: (TYPE_RANK[item["profile_type"]], item["profile_id"], _semver(item["profile_version"]), item["manifest_sha256"]))
        result.append({"invariant_id": invariant["id"], "status": "strengthened" if provenance else "preserved", "provenance": provenance})
    return result


def _validate_effective_narrative(constraints: list[Mapping[str, Any]]) -> None:
    values = {str(item["path"]): item["value"] for item in constraints}
    stages = values.get("narrative.stages.definitions", [])
    dependencies = values.get("narrative.dependencies.required", [])
    purposes = values.get("narrative.section_purposes.definitions", [])
    stage_defs: dict[str, Any] = {}
    for stage in stages:
        if not isinstance(stage, Mapping) or not isinstance(stage.get("id"), str):
            raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", "invalid Narrative stage definition")
        identifier = str(stage["id"])
        if identifier in stage_defs and stage_defs[identifier] != stage:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-IDENTITY-001", f"divergent Narrative stage {identifier}")
        stage_defs[identifier] = stage
    graph = {identifier: [] for identifier in stage_defs}
    edge_defs: dict[tuple[str, str], Any] = {}
    for edge in dependencies:
        if not isinstance(edge, Mapping) or not all(isinstance(edge.get(key), str) for key in ("from_stage", "to_stage", "relation")):
            raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", "invalid Narrative dependency")
        source, target = str(edge["from_stage"]), str(edge["to_stage"])
        if source not in graph or target not in graph:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-REF-001", "Narrative dependency references an unknown stage")
        identity = (source, target)
        if identity in edge_defs and edge_defs[identity] != edge:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-IDENTITY-001", "divergent Narrative dependency")
        edge_defs[identity] = edge
        graph[source].append(target)
    purpose_defs: dict[str, Any] = {}
    for purpose in purposes:
        if not isinstance(purpose, Mapping) or not isinstance(purpose.get("id"), str) or not isinstance(purpose.get("stage_ids"), list):
            raise LocalWorkspaceError("PROFILE-NARRATIVE-VALUE-001", "invalid Narrative section purpose")
        identifier = str(purpose["id"])
        if identifier in purpose_defs and purpose_defs[identifier] != purpose:
            raise LocalWorkspaceError("PROFILE-NARRATIVE-IDENTITY-001", f"divergent Narrative section purpose {identifier}")
        if any(stage_id not in graph for stage_id in purpose["stage_ids"]):
            raise LocalWorkspaceError("PROFILE-NARRATIVE-REF-001", "Narrative section purpose references an unknown stage")
        purpose_defs[identifier] = purpose
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise LocalWorkspaceError("NARRATIVE-DEPENDENCY-CYCLE-001", "Narrative dependency graph contains a cycle")
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
    _validate_schema(eps, EPS_SCHEMA, "WORKSPACE-PROFILE-SET-SCHEMA-001")
    return eps


def target_project_config(
    current: Mapping[str, Any],
    replacements: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    target = deepcopy(dict(current))
    changed = False
    for replacement in replacements:
        old = replacement.get("from")
        new = replacement.get("to")
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            raise LocalWorkspaceError("PROFILE-ADVANCE-REQUEST-001", "each request replacement needs from/to objects")
        profile_type = str(old.get("profile_type", ""))
        if profile_type not in ("research", "organization", "narrative", "publication") or str(new.get("profile_type", "")) != profile_type:
            raise LocalWorkspaceError("PROFILE-ADVANCE-REQUEST-001", "request replacement must stay within one Profile type")
        items = target["profile_requests"][profile_type]
        matches = [index for index, item in enumerate(items) if item == dict(old)]
        if len(matches) != 1:
            raise LocalWorkspaceError("PROFILE-ADVANCE-REQUEST-001", "request replacement source must match exactly once")
        items[matches[0]] = deepcopy(dict(new))
        changed = changed or dict(old) != dict(new)
    if changed:
        prior_digest = str(current["configuration_digest"])
        derived = target["provenance"].setdefault("derived_from_configuration_digests", [])
        if prior_digest not in derived:
            derived.append(prior_digest)
        notes = target["provenance"].setdefault("notes", [])
        note = "Profile generation advancement: direct Profile requests changed mechanically; other project semantics are unchanged."
        if note not in notes:
            notes.append(note)
        target.pop("configuration_digest", None)
        target["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(target)).hexdigest()
    return target


def exact_manifest_identity_map(manifest_files: Iterable[str | Path]) -> dict[tuple[str, str, str], str]:
    return {_keyver(item["manifest"]): str(item["manifest_sha256"]) for item in _load_candidates(manifest_files)}


def effective_profile_digest(eps: Mapping[str, Any]) -> str:
    return canonical_digest(eps)
