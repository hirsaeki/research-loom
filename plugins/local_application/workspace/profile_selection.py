"""Profile assignment search over requested profile ranges (#494)."""

from __future__ import annotations

from typing import Any

from plugins.local_application.workspace.workspace import LocalWorkspaceError

from .profile_resolution_support import (
    CORE_CONTRACTS,
    MAX_PROFILE_RESOLUTION_STATES,
    TYPE_RANK,
    _key,
    _pin,
    _satisfies,
    _semver,
)


def _assignment_valid(assignment, requests) -> bool:
    selected = {key: candidate for key, candidate in assignment.items() if candidate is not None}
    requested_keys = {_key(request) for request in requests}
    for request in requests:
        candidate = selected.get(_key(request))
        if candidate is None or not _satisfies(
            str(candidate["manifest"]["profile_version"]), str(request["version"])
        ):
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
        if not _satisfies(
            CORE_CONTRACTS["research_contract"], str(compat["research_contract"])
        ) or not _satisfies(
            CORE_CONTRACTS["invariant_contract"], str(compat["invariant_contract"])
        ):
            return False
        for relation in ("extends", "requires"):
            for dependency in manifest.get(relation, []):
                dep_key = _key(dependency)
                if relation == "extends" and dependency["profile_type"] != manifest["profile_type"]:
                    return False
                target = selected.get(dep_key)
                if target is None or not _satisfies(
                    str(target["manifest"]["profile_version"]), str(dependency["version"])
                ):
                    return False
                if dep_key not in reachable:
                    reachable.add(dep_key)
                    frontier.append(dep_key)
    if set(selected) != reachable:
        return False
    graph = {key: [] for key in selected}
    for key, candidate in selected.items():
        for relation in ("extends", "requires"):
            graph[key].extend(
                _key(dependency) for dependency in candidate["manifest"].get(relation, [])
            )
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

    initial_requirements: dict[tuple[str, str], list[str]] = {}
    for request in requests:
        initial_requirements.setdefault(_key(request), []).append(str(request["version"]))
    visited_states = 0

    def search(
        assignment: dict[tuple[str, str], dict[str, Any]],
        requirements: dict[tuple[str, str], list[str]],
    ):
        nonlocal visited_states
        visited_states += 1
        if visited_states > MAX_PROFILE_RESOLUTION_STATES:
            raise LocalWorkspaceError(
                "PROFILE-RESOLUTION-LIMIT-001",
                f"Profile dependency resolution visited {visited_states} states, exceeding the "
                f"{MAX_PROFILE_RESOLUTION_STATES}-state search budget; pin dependency versions, "
                "narrow version ranges, or reduce the candidate set and retry. "
                "No Effective Profile Set was written.",
            )
        for key, required_versions in requirements.items():
            selected = assignment.get(key)
            if selected is not None:
                version = str(selected["manifest"]["profile_version"])
                if not all(_satisfies(version, requirement) for requirement in required_versions):
                    return None
                continue
            possible = by_key.get(key, [])
            if not any(
                all(
                    _satisfies(str(candidate["manifest"]["profile_version"]), requirement)
                    for requirement in required_versions
                )
                for candidate in possible
            ):
                return None

        unresolved = sorted(
            (key for key in requirements if key not in assignment),
            key=lambda key: (TYPE_RANK[key[0]], key[1]),
        )
        if not unresolved:
            return dict(assignment) if _assignment_valid(assignment, requests) else None

        key = unresolved[0]
        required_versions = requirements[key]
        candidates_for_key = sorted(
            (
                candidate
                for candidate in by_key.get(key, [])
                if all(
                    _satisfies(str(candidate["manifest"]["profile_version"]), requirement)
                    for requirement in required_versions
                )
            ),
            key=lambda candidate: _semver(candidate["manifest"]["profile_version"]),
            reverse=True,
        )
        for candidate in candidates_for_key:
            manifest = candidate["manifest"]
            compat = manifest["core_compatibility"]
            if not _satisfies(
                CORE_CONTRACTS["research_contract"], str(compat["research_contract"])
            ) or not _satisfies(
                CORE_CONTRACTS["invariant_contract"], str(compat["invariant_contract"])
            ):
                continue
            next_requirements = {item: list(versions) for item, versions in requirements.items()}
            invalid_relation = False
            for relation in ("extends", "requires"):
                for dependency in manifest.get(relation, []):
                    if (
                        relation == "extends"
                        and dependency["profile_type"] != manifest["profile_type"]
                    ):
                        invalid_relation = True
                        break
                    next_requirements.setdefault(_key(dependency), []).append(
                        str(dependency["version"])
                    )
                if invalid_relation:
                    break
            if invalid_relation:
                continue
            winner = search({**assignment, key: candidate}, next_requirements)
            if winner is not None:
                return winner
        return None

    winner = search({}, initial_requirements)
    if winner is None:
        raise LocalWorkspaceError(
            "PROFILE-VERSION-001",
            "no compatible Profile resolution exists for the requested generation",
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
                        sources.append(
                            {
                                "relation": relation,
                                "introduced_by": _pin(introduced),
                                "required_version": dependency["version"],
                            }
                        )
        sources.sort(
            key=lambda source: (
                relation_rank[source["relation"]],
                TYPE_RANK[
                    (source.get("introduced_by") or {"profile_type": "research"})["profile_type"]
                ],
                (source.get("introduced_by") or {}).get("profile_id", ""),
                source["required_version"],
            )
        )
        output.append({**_pin(candidate), "selection_provenance": sources})
    return output, selected
