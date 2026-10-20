"""Profile manifest semantic validation and candidate loading (#494)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from core.resources import resource_path
from plugins.local_application.workspace.workspace import LocalWorkspaceError

from .profile_resolution_support import (
    CORE_CONTRACTS,
    NARRATIVE_SEMANTICS,
    PROFILE_MANIFEST_SCHEMA,
    RESEARCH_QUALITY_POLICY,
    STRENGTHENING_REGISTRY,
    _keyver,
    _load_json,
    _satisfies,
    _sha256,
    _validate_schema,
)


def _unique_strings(value: Any, allowed: set[str]) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
        and all(item in allowed for item in value)
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
    if not _satisfies(
        CORE_CONTRACTS["research_contract"], str(compat["research_contract"])
    ) or not _satisfies(CORE_CONTRACTS["invariant_contract"], str(compat["invariant_contract"])):
        raise LocalWorkspaceError(
            "PROFILE-CORE-COMPAT-001", "Profile is incompatible with current Core contracts"
        )

    research_contract = yaml.safe_load(RESEARCH_QUALITY_POLICY.read_text(encoding="utf-8"))
    research_paths = {item["path"]: item for item in research_contract["constraint_paths"]}
    research_vocabularies = research_contract["vocabularies"]
    for constraint in manifest.get("constraints", []):
        path = str(constraint["path"])
        if not path.startswith("research_quality."):
            continue
        if manifest["profile_type"] != "research":
            raise LocalWorkspaceError(
                "PROFILE-RESEARCH-QUALITY-OWNER-001",
                "research_quality.* constraints are owned by Research Profiles",
            )
        spec = research_paths.get(path)
        if spec is None:
            raise LocalWorkspaceError(
                "PROFILE-RESEARCH-QUALITY-PATH-001",
                f"unknown canonical Research quality path {path}",
            )
        if constraint["merge_strategy"] != spec["merge_strategy"]:
            raise LocalWorkspaceError(
                "PROFILE-RESEARCH-QUALITY-MERGE-001", f"wrong merge strategy for {path}"
            )
        value = constraint["value"]
        if spec["value_shape"] == "enum_set":
            if not _unique_strings(value, set(research_vocabularies[spec["vocabulary"]])):
                raise LocalWorkspaceError(
                    "PROFILE-RESEARCH-QUALITY-VALUE-001",
                    f"Research quality vocabulary violation at {path}",
                )
        elif spec["value_shape"] == "integer":
            minimum = int(spec.get("minimum", 0))
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise LocalWorkspaceError(
                    "PROFILE-RESEARCH-QUALITY-VALUE-001",
                    f"Research quality threshold violation at {path}",
                )
        else:
            raise LocalWorkspaceError(
                "PROFILE-RESEARCH-QUALITY-VALUE-001",
                f"unsupported Research quality value shape at {path}",
            )

    narrative_contract = yaml.safe_load(NARRATIVE_SEMANTICS.read_text(encoding="utf-8"))
    narrative_paths = {item["path"]: item for item in narrative_contract["constraint_paths"]}
    vocabularies = narrative_contract["vocabularies"]
    for constraint in manifest.get("constraints", []):
        path = str(constraint["path"])
        if not path.startswith("narrative."):
            continue
        if manifest["profile_type"] != "narrative":
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-OWNER-001",
                "narrative.* constraints are owned by Narrative Profiles",
            )
        spec = narrative_paths.get(path)
        if spec is None:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-PATH-001", f"unknown canonical Narrative path {path}"
            )
        if constraint["merge_strategy"] != spec["merge_strategy"]:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-MERGE-001", f"wrong merge strategy for {path}"
            )
        value = constraint["value"]
        if not isinstance(value, list):
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-VALUE-001", f"Narrative value for {path} must be a list"
            )
        shape = spec["value_shape"]
        if shape == "enum_set":
            if not _unique_strings(value, set(vocabularies[spec["vocabulary"]])):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-VALUE-001", f"Narrative vocabulary violation at {path}"
                )
        elif shape == "stage_set":
            if any(not _valid_narrative_stage(item, vocabularies) for item in value):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-VALUE-001", f"Narrative stage definition violation at {path}"
                )
            identities = [item["id"] for item in value]
            if len(identities) != len(set(identities)):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-IDENTITY-001",
                    f"duplicate Narrative stage identity at {path}",
                )
        elif shape == "dependency_set":
            if any(not _valid_narrative_dependency(item, vocabularies) for item in value):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-VALUE-001",
                    f"Narrative dependency definition violation at {path}",
                )
            identities = [(item["from_stage"], item["to_stage"]) for item in value]
            if len(identities) != len(set(identities)):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-IDENTITY-001",
                    f"duplicate Narrative dependency identity at {path}",
                )
        elif shape == "section_purpose_set":
            if any(not _valid_narrative_purpose(item, vocabularies) for item in value):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-VALUE-001",
                    f"Narrative section-purpose definition violation at {path}",
                )
            identities = [item["id"] for item in value]
            if len(identities) != len(set(identities)):
                raise LocalWorkspaceError(
                    "PROFILE-NARRATIVE-IDENTITY-001",
                    f"duplicate Narrative section-purpose identity at {path}",
                )
        else:
            raise LocalWorkspaceError(
                "PROFILE-NARRATIVE-VALUE-001", f"unsupported Narrative value shape at {path}"
            )

    registry = yaml.safe_load(STRENGTHENING_REGISTRY.read_text(encoding="utf-8"))
    declarations = {str(item["id"]): item for item in manifest.get("constraints", [])}
    for strengthening in manifest.get("core_invariant_strengthenings", []):
        invariant = registry["invariants"].get(strengthening["invariant_id"])
        binding = strengthening["validator_binding"]
        matched_form = None
        matched_validator = None
        if invariant and invariant.get("strengthening_policy") == "registered_forms":
            for validator in invariant.get("validators", []):
                if (
                    validator["validator_id"] != binding["validator_id"]
                    or validator["validator_version"] != binding["validator_version"]
                ):
                    continue
                for form in validator.get("approved_forms", []):
                    if form["form_id"] == binding["form_id"]:
                        matched_validator = validator
                        matched_form = form
                        break
        if matched_form is None or matched_validator is None:
            raise LocalWorkspaceError(
                "PROFILE-CORE-STRENGTHENING-001", "Profile strengthening is not registered"
            )
        applicability = matched_validator.get("applicability", {})
        prefix = applicability.get("profile_id_prefix")
        prefixes = applicability.get("profile_id_prefixes")
        profile_id = str(manifest["profile_id"])
        if isinstance(prefix, str) and not profile_id.startswith(prefix):
            raise LocalWorkspaceError(
                "PROFILE-CORE-STRENGTHENING-001",
                "Profile strengthening is outside the registered applicability",
            )
        if isinstance(prefixes, list) and (
            not prefixes
            or any(not isinstance(item, str) or not item for item in prefixes)
            or not any(profile_id.startswith(item) for item in prefixes)
        ):
            raise LocalWorkspaceError(
                "PROFILE-CORE-STRENGTHENING-001",
                "Profile strengthening is outside the registered applicability",
            )
        referenced = []
        for constraint_id in strengthening["constraint_ids"]:
            declaration = declarations.get(str(constraint_id))
            if declaration is None:
                raise LocalWorkspaceError(
                    "PROFILE-MANIFEST-REF-001",
                    "Profile strengthening references an unknown constraint",
                )
            referenced.append(declaration)
        for required in matched_form.get("required_constraints", []):
            match = next(
                (
                    item
                    for item in referenced
                    if item["path"] == required["path"]
                    and item["merge_strategy"] == required["merge_strategy"]
                ),
                None,
            )
            if match is None or (
                "const" in required.get("value_schema", {})
                and match["value"] != required["value_schema"]["const"]
            ):
                raise LocalWorkspaceError(
                    "PROFILE-CORE-STRENGTHENING-001",
                    "Profile strengthening does not satisfy its registered form",
                )


def _load_candidates(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    identities: dict[tuple[str, str, str], str] = {}
    profile_root = resource_path("profiles").resolve()
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
            raise LocalWorkspaceError(
                "PROFILE-MANIFEST-SOURCE-001", "Profile manifest may not be a symlink"
            )
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
        raise LocalWorkspaceError(
            "PROFILE-CANDIDATE-EMPTY-001", "at least one Profile manifest is required"
        )
    return candidates
