from __future__ import annotations

from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .transition_models import (
    ReductionResult,
    StateTransitionRequest,
    ValidationIssue,
    ValidationStage,
)


class CanonicalResearchObjectSchemaValidator:
    """Validate runtime Core objects against the PR3 canonical JSON Schema.

    The schema document is injected by composition/root code. The runtime does
    not discover files or reach into a storage adapter, keeping validation
    deterministic and packaging/storage choices outside the reducer.
    """

    def __init__(self, research_object_schema: Mapping[str, Any]) -> None:
        Draft202012Validator.check_schema(research_object_schema)
        self._validator = Draft202012Validator(
            research_object_schema,
            format_checker=FormatChecker(),
        )

    def validate_request(self, request: StateTransitionRequest) -> tuple[ValidationIssue, ...]:
        objects: list[Mapping[str, Any]] = []
        for action in request.actions:
            obj = action.object_payload()
            if obj is not None:
                objects.append(obj)
            treatments = action.payload.get("treatments", ())
            if isinstance(treatments, (list, tuple)):
                for treatment in treatments:
                    if isinstance(treatment, Mapping):
                        derived = treatment.get("derived_object")
                        if isinstance(derived, Mapping):
                            objects.append(derived)
        return self._validate(objects)

    def validate_reduction(self, reduction: ReductionResult) -> tuple[ValidationIssue, ...]:
        objects: list[Mapping[str, Any]] = [*reduction.object_revisions]
        if reduction.new_snapshot is not None:
            objects.append(reduction.new_snapshot)
        objects.extend(reduction.audit_events)
        return self._validate(objects)

    def _validate(self, objects: Iterable[Mapping[str, Any]]) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        for obj in objects:
            errors = sorted(
                self._validator.iter_errors(obj),
                key=lambda error: tuple(str(item) for item in error.absolute_path),
            )
            for error in errors:
                path = ".".join(str(item) for item in error.absolute_path) or "$"
                issues.append(ValidationIssue(
                    error_code="RT-SCHEMA-CORE-001",
                    stage=ValidationStage.SCHEMA,
                    message=f"Canonical Core object schema violation at {path}: {error.message}",
                    affected_refs=(str(obj.get("id", "")),),
                ))
        return tuple(issues)
