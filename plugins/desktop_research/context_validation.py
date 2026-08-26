from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from core.execution.models import ExecutionIssue
from core.runtime.transition_models import StateView

from .digest import canonical_extension_digest


ROOT = Path(__file__).resolve().parents[2]
DR = ROOT / "core" / "packages" / "desktop-research"
CONTEXT_SCHEMA = json.loads(
    (DR / "desktop-research-context-extension.schema.json").read_text(encoding="utf-8")
)
_CONTEXT_VALIDATOR = Draft202012Validator(
    CONTEXT_SCHEMA,
    format_checker=FormatChecker(),
)

_ACTIVE_ROLES = {"research_context", "candidate_source", "research_artifact"}
_ALL_ROLES = set(CONTEXT_SCHEMA["$defs"]["resource_role"]["enum"])
_REQUIRED_FORBIDDEN = _ALL_ROLES - _ACTIVE_ROLES
_AUTHORITATIVE_RQ_STATES = {"approved", "revised"}


def _first_schema_error(document: Mapping[str, Any]) -> str | None:
    errors = sorted(
        _CONTEXT_VALIDATOR.iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if not errors:
        return None
    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path) or "$"
    return f"{path}: {error.message}"


def _issue(code: str, message: str) -> ExecutionIssue:
    return ExecutionIssue(code, message)


class DesktopResearchContextValidator:
    """Production PR11 Desktop Research Context-extension validator."""

    def supports(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
    ) -> bool:
        return (capability_id, capability_version, function_id) == (
            "desktop-research",
            "0.1.0",
            "investigate",
        )

    def validate(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        extension: Mapping[str, Any],
        state: StateView,
    ) -> tuple[ExecutionIssue, ...]:
        issues: list[ExecutionIssue] = []
        schema_error = _first_schema_error(extension)
        if schema_error:
            return (_issue("DR-CONTEXT-BINDING-001", schema_error),)

        if extension.get("extension_digest") != canonical_extension_digest(extension):
            issues.append(
                _issue(
                    "DR-CONTEXT-DIGEST-001",
                    "Desktop Research Context extension digest is invalid",
                )
            )

        capability = invocation["capability"]
        if (
            descriptor.get("capability_id") != "desktop-research"
            or descriptor.get("capability_version") != "0.1.0"
            or capability.get("capability_id") != "desktop-research"
            or capability.get("capability_version") != "0.1.0"
            or capability.get("function_id") != "investigate"
        ):
            issues.append(
                _issue(
                    "DR-CONTEXT-BINDING-001",
                    "Desktop Context validator received a non-Desktop capability binding",
                )
            )

        expected_binding = {
            "context_pack_id": context_pack["context_pack_id"],
            "context_pack_digest": context_pack["context_pack_digest"],
            "project_id": context_pack["project_id"],
        }
        if extension["context_binding"] != expected_binding:
            issues.append(
                _issue(
                    "DR-CONTEXT-BINDING-001",
                    "Context extension does not bind the exact PR9 Context Pack/project",
                )
            )

        target = extension["target"]
        question_ids = set(context_pack["question_ids"])
        if target["target_type"] == "research_question":
            qid = str(target["question_id"])
            effective = {
                (str(obj.get("kind")), str(obj.get("id"))): obj
                for obj in state.effective_objects()
            }
            rq = effective.get(("research_question", qid))
            if (
                qid not in question_ids
                or rq is None
                or str(rq.get("adoption_state")) not in _AUTHORITATIVE_RQ_STATES
            ):
                issues.append(
                    _issue(
                        "DR-CONTEXT-BINDING-001",
                        "research_question target is not the adopted RQ pinned by current State",
                    )
                )
        else:
            attention_ids = {
                str(item["attention_id"])
                for item in context_pack["research_attention"]
            }
            if (
                target.get("authoritative_question") is not False
                or target["source_attention_id"] not in attention_ids
                or not set(target.get("related_question_ids", ())).issubset(
                    question_ids
                )
            ):
                issues.append(
                    _issue(
                        "DR-CONTEXT-BINDING-001",
                        "question candidate target crossed the non-authoritative target boundary",
                    )
                )

        bindings = extension["resource_role_bindings"]
        refs = [str(item["reference_id"]) for item in bindings]
        dimensions = [
            str(item["dimension_id"])
            for item in extension["coverage_dimensions"]
        ]
        if len(refs) != len(set(refs)) or len(dimensions) != len(set(dimensions)):
            issues.append(
                _issue(
                    "DR-CONTEXT-IDENTITY-001",
                    "Desktop resource-role or coverage identities are duplicated",
                )
            )

        resources = {
            str(item["reference_id"]): item
            for item in context_pack["resources"]
        }
        if set(refs) != set(resources):
            issues.append(
                _issue(
                    "DR-CONTEXT-RESOURCE-ROLE-001",
                    "every PR9 resource must have exactly one Desktop Research role",
                )
            )
        forbidden = set(extension["forbidden_resource_roles"])
        if not _REQUIRED_FORBIDDEN.issubset(forbidden):
            issues.append(
                _issue(
                    "DR-CONTEXT-RESOURCE-ROLE-001",
                    "Desktop forbidden roles do not fail closed over Writer/Publication/archive material",
                )
            )

        for binding in bindings:
            ref = str(binding["reference_id"])
            role = str(binding["role"])
            resource = resources.get(ref)
            if resource is None or role in forbidden or role not in _ACTIVE_ROLES:
                issues.append(
                    _issue(
                        "DR-CONTEXT-RESOURCE-ROLE-001",
                        f"invalid Desktop resource role binding for {ref}",
                    )
                )
                continue
            if role == "candidate_source" and not (
                resource["reference_type"] == "source"
                and resource["evidentiary_use"] == "candidate_source"
            ):
                issues.append(
                    _issue(
                        "DR-CONTEXT-RESOURCE-ROLE-001",
                        f"candidate_source role is not bound to an evidentiary source: {ref}",
                    )
                )
            elif (
                role == "research_artifact"
                and resource["reference_type"] != "artifact"
            ):
                issues.append(
                    _issue(
                        "DR-CONTEXT-RESOURCE-ROLE-001",
                        f"research_artifact role is not bound to an artifact: {ref}",
                    )
                )
            elif (
                role == "research_context"
                and resource["evidentiary_use"] != "context_only"
            ):
                issues.append(
                    _issue(
                        "DR-CONTEXT-RESOURCE-ROLE-001",
                        f"research_context resource is not context_only: {ref}",
                    )
                )

        budget = extension["budget"]
        candidate_sources = sum(
            item["role"] == "candidate_source" for item in bindings
        )
        artifacts = sum(item["role"] == "research_artifact" for item in bindings)
        if (
            len(resources) > budget["max_total_resources"]
            or candidate_sources > budget["max_candidate_source_resources"]
            or artifacts > budget["max_artifact_resources"]
            or budget["max_candidate_source_resources"]
            > budget["max_total_resources"]
            or budget["max_artifact_resources"] > budget["max_total_resources"]
        ):
            issues.append(
                _issue(
                    "DR-CONTEXT-BUDGET-001",
                    "bounded PR9 resources exceed the Desktop Research Context budget",
                )
            )

        result: list[ExecutionIssue] = []
        seen: set[tuple[str, str]] = set()
        for item in issues:
            key = (item.code, item.message)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return tuple(result)
