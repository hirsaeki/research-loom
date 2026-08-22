from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import re
from pathlib import Path

import rfc8785

ROOT = Path(__file__).resolve().parents[2]
TYPE_RANK = {name: i for i, name in enumerate(["research", "organization", "narrative", "publication"])}
COMPARATOR = re.compile(r"^(>=|>|<=|<|=)(\d+\.\d+\.\d+)$")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semver(text: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in text.split("."))  # type: ignore[return-value]


def satisfies(version: str, requirement: str) -> bool:
    v = semver(version)
    if re.fullmatch(r"\d+\.\d+\.\d+", requirement):
        return v == semver(requirement)
    for token in requirement.split():
        m = COMPARATOR.fullmatch(token)
        if not m:
            raise ValueError(f"unsupported range token: {token}")
        op, rhs_text = m.groups()
        rhs = semver(rhs_text)
        if op == ">=" and not (v >= rhs):
            return False
        if op == ">" and not (v > rhs):
            return False
        if op == "<=" and not (v <= rhs):
            return False
        if op == "<" and not (v < rhs):
            return False
        if op == "=" and not (v == rhs):
            return False
    return True


def key_of(obj) -> tuple[str, str]:
    return obj["profile_type"], obj["profile_id"]


def keyver_of(obj) -> tuple[str, str, str]:
    return obj["profile_type"], obj["profile_id"], obj["profile_version"]


def pin_tuple(obj) -> tuple[str, str, str, str]:
    return obj["profile_type"], obj["profile_id"], obj["profile_version"], obj["manifest_sha256"]


def pinned_ref(candidate):
    return {
        "profile_id": candidate["manifest"]["profile_id"],
        "profile_type": candidate["manifest"]["profile_type"],
        "profile_version": candidate["manifest"]["profile_version"],
        "manifest_sha256": candidate["manifest_sha256"],
    }


def canonical_profile_key(key: tuple[str, str]):
    return TYPE_RANK[key[0]], key[1]


def canonical_selection_key(src):
    relation_rank = {"requested": 0, "extends": 1, "requires": 2}
    intro = src.get("introduced_by") or {
        "profile_type": "research",
        "profile_id": "",
        "profile_version": "0.0.0",
        "manifest_sha256": "",
    }
    return (
        relation_rank[src["relation"]],
        TYPE_RANK[intro["profile_type"]],
        intro["profile_id"],
        semver(intro["profile_version"]),
        intro["manifest_sha256"],
        src["required_version"],
    )


def canonical_constraint_source_key(src):
    return (
        TYPE_RANK[src["profile_type"]],
        src["profile_id"],
        semver(src["profile_version"]),
        src["manifest_sha256"],
        src["constraint_id"],
    )


def canonical_json_bytes(value) -> bytes:
    return rfc8785.dumps(value)


def canonicalize_set_like(values):
    canonical = {}
    for value in values:
        encoded = canonical_json_bytes(value)
        canonical.setdefault(encoded, json.loads(encoded.decode("utf-8")))
    return [canonical[key] for key in sorted(canonical)]


def core_compatibility_error(manifest, core_contracts):
    compat = manifest["core_compatibility"]
    if not satisfies(core_contracts["research_contract"], compat["research_contract"]):
        return "PROFILE-CORE-COMPAT-001"
    if not satisfies(core_contracts["invariant_contract"], compat["invariant_contract"]):
        return "PROFILE-CORE-COMPAT-001"
    return None


def effective_identity_error(eps):
    candidate_seen = {}
    for ref in eps["candidate_universe"]:
        k = keyver_of(ref)
        h = ref["manifest_sha256"]
        if k in candidate_seen and candidate_seen[k] != h:
            return "PROFILE-CANDIDATE-IDENTITY-001"
        candidate_seen[k] = h
    for field, identity in [
        ("requested_profiles", lambda x: key_of(x)),
        ("effective_profiles", lambda x: key_of(x)),
        ("effective_constraints", lambda x: x["path"]),
        ("core_invariants", lambda x: x["invariant_id"]),
    ]:
        seen = set()
        for item in eps[field]:
            k = identity(item)
            if k in seen:
                return "PROFILE-EFFECTIVE-IDENTITY-001"
            seen.add(k)
    return None


def fixture_manifest_catalog():
    paths = list((ROOT / "profiles/fixtures/valid").glob("*.profile.json"))
    paths += list((ROOT / "profiles/fixtures/semantic/version-resolution/candidates").glob("*.profile.json"))
    catalog = {}
    for path in paths:
        manifest = load_json(path)
        catalog[(manifest["profile_type"], manifest["profile_id"], manifest["profile_version"], sha256_bytes(path))] = manifest
    return catalog


def effective_provenance_error(eps, manifest_catalog=None):
    selected = {pin_tuple(p): p for p in eps["effective_profiles"]}
    universe = {pin_tuple(p) for p in eps["candidate_universe"]}
    if not set(selected) <= universe:
        return "PROFILE-EFFECTIVE-PROVENANCE-001"

    catalog = fixture_manifest_catalog() if manifest_catalog is None else manifest_catalog
    expected_edges = []
    for intro_pin, intro in selected.items():
        manifest = catalog.get(intro_pin)
        if manifest is None:
            return "PROFILE-EFFECTIVE-PROVENANCE-001"
        for relation in ("extends", "requires"):
            for dep in manifest.get(relation, []):
                targets = [p for p in eps["effective_profiles"] if key_of(p) == key_of(dep)]
                if len(targets) != 1 or not satisfies(targets[0]["profile_version"], dep["version"]):
                    return "PROFILE-EFFECTIVE-PROVENANCE-001"
                expected_edges.append((pin_tuple(targets[0]), relation, intro_pin, dep["version"]))

    actual_edges = []
    for target in eps["effective_profiles"]:
        for source in target["selection_provenance"]:
            if source["relation"] == "requested":
                continue
            intro_pin = pin_tuple(source["introduced_by"])
            if intro_pin not in selected or not satisfies(target["profile_version"], source["required_version"]):
                return "PROFILE-EFFECTIVE-PROVENANCE-001"
            actual_edges.append((pin_tuple(target), source["relation"], intro_pin, source["required_version"]))
    if Counter(actual_edges) != Counter(expected_edges):
        return "PROFILE-EFFECTIVE-PROVENANCE-001"

    for constraint in eps["effective_constraints"]:
        for source in constraint["provenance"]:
            if pin_tuple(source) not in selected:
                return "PROFILE-EFFECTIVE-PROVENANCE-001"
    for invariant in eps["core_invariants"]:
        for source in invariant["provenance"]:
            if pin_tuple(source) not in selected:
                return "PROFILE-EFFECTIVE-PROVENANCE-001"
    return None


def requested_presence_error(eps):
    selected_by_key = {}
    for profile in eps["effective_profiles"]:
        selected_by_key.setdefault(key_of(profile), []).append(profile)

    expected = []
    for request in eps["requested_profiles"]:
        matches = [p for p in selected_by_key.get(key_of(request), []) if satisfies(p["profile_version"], request["version"])]
        if len(matches) != 1:
            return "PROFILE-EFFECTIVE-REQUEST-001"
        expected.append((pin_tuple(matches[0]), request["version"]))

    actual = []
    for profile in eps["effective_profiles"]:
        for source in profile["selection_provenance"]:
            if source["relation"] != "requested":
                continue
            if not satisfies(profile["profile_version"], source["required_version"]):
                return "PROFILE-EFFECTIVE-REQUEST-001"
            actual.append((pin_tuple(profile), source["required_version"]))

    if Counter(actual) != Counter(expected):
        return "PROFILE-EFFECTIVE-REQUEST-001"
    return None


def find_registry_form(registry, strengthening):
    inv = registry["invariants"].get(strengthening["invariant_id"])
    if not inv or inv.get("strengthening_policy") != "registered_forms":
        return None
    binding = strengthening["validator_binding"]
    for validator in inv.get("validators", []):
        if validator["validator_id"] != binding["validator_id"] or validator["validator_version"] != binding["validator_version"]:
            continue
        for form in validator.get("approved_forms", []):
            if form["form_id"] == binding["form_id"]:
                return form
    return None


def strengthening_error(manifest, registry):
    constraints = {c["id"]: c for c in manifest.get("constraints", [])}
    for strengthening in manifest.get("core_invariant_strengthenings", []):
        form = find_registry_form(registry, strengthening)
        if form is None:
            return "PROFILE-CORE-STRENGTHENING-001"
        referenced = []
        for cid in strengthening["constraint_ids"]:
            constraint = constraints.get(cid)
            if constraint is None:
                return "PROFILE-MANIFEST-REF-001"
            referenced.append(constraint)
        for required in form.get("required_constraints", []):
            match = next(
                (
                    c
                    for c in referenced
                    if c["path"] == required["path"] and c["merge_strategy"] == required["merge_strategy"]
                ),
                None,
            )
            if match is None:
                return "PROFILE-CORE-STRENGTHENING-001"
            value_schema = required.get("value_schema", {})
            if "const" in value_schema and match["value"] != value_schema["const"]:
                return "PROFILE-CORE-STRENGTHENING-001"
    return None


def constraint_composition_error(manifests):
    by_path = {}
    for manifest in manifests:
        for constraint in manifest.get("constraints", []):
            by_path.setdefault(constraint["path"], []).append((manifest, constraint))
    for declarations in by_path.values():
        strategies = {constraint["merge_strategy"] for _, constraint in declarations}
        if len(strategies) > 1:
            return "PROFILE-COMP-STRATEGY-001"
        strategy = next(iter(strategies))
        values = [constraint["value"] for _, constraint in declarations]
        if strategy == "replace" and any(value != values[0] for value in values[1:]):
            if len({manifest["profile_type"] for manifest, _ in declarations}) > 1:
                return "PROFILE-COMP-REPLACE-001"
        if strategy == "must_equal" and any(value != values[0] for value in values[1:]):
            return "PROFILE-COMP-CONFLICT-001"
    return None


def load_candidate(path: Path):
    return {"manifest": load_json(path), "manifest_sha256": sha256_bytes(path), "path": path}


def assignment_valid(assignment, requests, core_contracts):
    selected = {key: candidate for key, candidate in assignment.items() if candidate is not None}
    requested_keys = {key_of(request) for request in requests}
    for request in requests:
        candidate = selected.get(key_of(request))
        if candidate is None or not satisfies(candidate["manifest"]["profile_version"], request["version"]):
            return False
    reachable = set(requested_keys)
    frontier = list(requested_keys)
    while frontier:
        key = frontier.pop()
        candidate = selected.get(key)
        if candidate is None:
            return False
        manifest = candidate["manifest"]
        if core_compatibility_error(manifest, core_contracts):
            return False
        for relation in ("extends", "requires"):
            for dep in manifest.get(relation, []):
                dep_key = key_of(dep)
                if relation == "extends" and dep["profile_type"] != manifest["profile_type"]:
                    return False
                target = selected.get(dep_key)
                if target is None or not satisfies(target["manifest"]["profile_version"], dep["version"]):
                    return False
                if dep_key not in reachable:
                    reachable.add(dep_key)
                    frontier.append(dep_key)
    if set(selected) != reachable:
        return False

    graph = {key: [] for key in selected}
    for key, candidate in selected.items():
        for relation in ("extends", "requires"):
            for dep in candidate["manifest"].get(relation, []):
                graph[key].append(key_of(dep))
    visiting, done = set(), set()

    def dfs(key):
        if key in visiting:
            return False
        if key in done:
            return True
        visiting.add(key)
        for nxt in graph[key]:
            if not dfs(nxt):
                return False
        visiting.remove(key)
        done.add(key)
        return True

    return all(dfs(key) for key in graph)


def resolve_candidates(candidates, requests, core_contracts):
    by_key = {}
    identities = {}
    for candidate in candidates:
        keyver = keyver_of(candidate["manifest"])
        previous = identities.get(keyver)
        if previous is not None and previous != candidate["manifest_sha256"]:
            return None, "PROFILE-CANDIDATE-IDENTITY-001"
        identities[keyver] = candidate["manifest_sha256"]
        by_key.setdefault(key_of(candidate["manifest"]), []).append(candidate)
    keys = sorted(by_key, key=canonical_profile_key)
    choices = [[None] + sorted(by_key[key], key=lambda c: semver(c["manifest"]["profile_version"])) for key in keys]
    solutions = []
    for combo in itertools.product(*choices):
        assignment = dict(zip(keys, combo))
        if assignment_valid(assignment, requests, core_contracts):
            solutions.append(assignment)
    if not solutions:
        return None, "PROFILE-VERSION-001"
    absent = (-1, -1, -1)

    def vector(assignment):
        return tuple(
            absent if assignment[key] is None else semver(assignment[key]["manifest"]["profile_version"])
            for key in keys
        )

    winner = max(solutions, key=vector)
    selected = {key: candidate for key, candidate in winner.items() if candidate is not None}
    output = []
    for key in sorted(selected, key=canonical_profile_key):
        candidate = selected[key]
        sources = []
        for request in requests:
            if key_of(request) == key:
                sources.append({"relation": "requested", "required_version": request["version"]})
        for intro_candidate in selected.values():
            for relation in ("extends", "requires"):
                for dep in intro_candidate["manifest"].get(relation, []):
                    if key_of(dep) == key:
                        sources.append(
                            {
                                "relation": relation,
                                "introduced_by": pinned_ref(intro_candidate),
                                "required_version": dep["version"],
                            }
                        )
        sources.sort(key=canonical_selection_key)
        output.append({**pinned_ref(candidate), "selection_provenance": sources})
    return output, None


def canonical_compose_constraints(candidates):
    groups = {}
    for candidate in candidates:
        for declaration in candidate["manifest"].get("constraints", []):
            groups.setdefault(declaration["path"], []).append((candidate, declaration))
    result = []
    for path in sorted(groups):
        declarations = groups[path]
        strategy = declarations[0][1]["merge_strategy"]
        if any(item[1]["merge_strategy"] != strategy for item in declarations):
            raise ValueError("PROFILE-COMP-STRATEGY-001")
        values = [item[1]["value"] for item in declarations]
        if strategy == "union":
            members = [member for value in values for member in value]
            value = canonicalize_set_like(members)
            resolution = "single" if len(declarations) == 1 else "union"
        elif strategy == "intersection":
            encoded_sets = [{canonical_json_bytes(member) for member in value} for value in values]
            common = set.intersection(*encoded_sets) if encoded_sets else set()
            value = [json.loads(encoded.decode("utf-8")) for encoded in sorted(common)]
            resolution = "single" if len(declarations) == 1 else "intersection"
        elif strategy == "must_equal":
            if any(item != values[0] for item in values[1:]):
                raise ValueError("PROFILE-COMP-CONFLICT-001")
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
                raise ValueError("PROFILE-COMP-REPLACE-001")
            value = values[0]
            resolution = "single" if len(declarations) == 1 else "identical"
        else:
            raise ValueError(f"unsupported merge strategy: {strategy}")
        provenance = [{**pinned_ref(candidate), "constraint_id": decl["id"]} for candidate, decl in declarations]
        provenance.sort(key=canonical_constraint_source_key)
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
