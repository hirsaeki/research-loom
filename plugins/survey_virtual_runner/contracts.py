from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from core.conversation.validation import canonical_digest
from core.execution.models import ExecutionIssue
from plugins.local_application.survey_validation import validate_questionnaire


ROOT = Path(__file__).resolve().parents[2]
VR_SCHEMA = json.loads(
    (ROOT / "core/packages/virtual-runner/virtual-runner-contract.schema.json").read_text(
        encoding="utf-8"
    )
)
RM_SCHEMA = json.loads(
    (ROOT / "core/packages/research-method/research-method-context-extension.schema.json").read_text(
        encoding="utf-8"
    )
)
SURVEY_SCHEMA = json.loads(
    (ROOT / "core/packages/survey/survey-contract.schema.json").read_text(encoding="utf-8")
)
_VR_VALIDATOR = Draft202012Validator(VR_SCHEMA, format_checker=FormatChecker())
_RM_VALIDATOR = Draft202012Validator(RM_SCHEMA, format_checker=FormatChecker())
_SURVEY_VALIDATOR = Draft202012Validator(SURVEY_SCHEMA, format_checker=FormatChecker())


def document_digest(document: Mapping[str, Any], field: str) -> str:
    payload = deepcopy(dict(document))
    payload.pop(field, None)
    return canonical_digest(payload)


def first_schema_error(validator, document: Mapping[str, Any]) -> str | None:
    errors = sorted(
        validator.iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if not errors:
        return None
    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path) or "$"
    return f"{path}: {error.message}"


def validate_virtual_document(document: Mapping[str, Any]) -> str | None:
    error = first_schema_error(_VR_VALIDATOR, document)
    if error:
        return error
    if document.get("object_type") == "virtual_runner_context":
        if document.get("extension_digest") != document_digest(document, "extension_digest"):
            return "virtual_runner_context extension_digest does not match content"
    elif document.get("object_type") == "virtual_runner_result":
        if document.get("extension_digest") != document_digest(document, "extension_digest"):
            return "virtual_runner_result extension_digest does not match content"
    return None


def validate_research_method_context(document: Mapping[str, Any]) -> str | None:
    error = first_schema_error(_RM_VALIDATOR, document)
    if error:
        return error
    if document.get("extension_digest") != document_digest(document, "extension_digest"):
        return "Research Method Context extension digest does not match content"
    return None


def validate_survey_context(document: Mapping[str, Any]) -> str | None:
    error = first_schema_error(_SURVEY_VALIDATOR, document)
    if error:
        return error
    if document.get("object_type") != "survey_context_extension":
        return "Survey binding must be a survey_context_extension"
    if document.get("extension_digest") != document_digest(document, "extension_digest"):
        return "Survey Context extension digest does not match content"
    return None


def issue(code: str, message: str) -> ExecutionIssue:
    return ExecutionIssue(code, message)


class SurveyVirtualRunnerContextValidator:
    """Validate the production Survey binding without redefining Virtual Runner authority."""

    def supports(self, capability_id: str, capability_version: str, function_id: str) -> bool:
        return (capability_id, capability_version, function_id) == (
            "virtual-runner",
            "0.1.0",
            "execute",
        )

    def validate(self, descriptor, invocation, context_pack, extension, state):
        issues: list[ExecutionIssue] = []
        if not isinstance(extension, Mapping):
            return (issue("VR-CONTEXT-BINDING-001", "Survey Virtual Runner binding is missing"),)
        if extension.get("schema_version") != "0.1.0" or extension.get("binding_type") != "survey_virtual_runner":
            return (issue("VR-CONTEXT-BINDING-001", "unsupported Survey Virtual Runner binding"),)
        if extension.get("extension_digest") != document_digest(extension, "extension_digest"):
            issues.append(issue("VR-CONTEXT-DIGEST-001", "Survey Virtual Runner binding digest is invalid"))

        if descriptor.get("capability_id") != "virtual-runner" or invocation["execution_mode"] != "virtual":
            issues.append(issue("VR-CONTEXT-BINDING-001", "Virtual Runner execution binding is not virtual-runner/virtual"))
        if extension.get("scenario_class") not in {"STANDARD", "STRESS"}:
            issues.append(issue("VR-CONTEXT-BINDING-001", "scenario_class must be STANDARD or STRESS"))

        expected_binding = {
            "context_pack_id": context_pack["context_pack_id"],
            "context_pack_digest": context_pack["context_pack_digest"],
            "project_id": context_pack["project_id"],
        }
        if extension.get("context_pack_binding") != expected_binding:
            issues.append(issue("VR-CONTEXT-BINDING-001", "Survey Virtual Runner binding does not pin the exact Context Pack"))

        research_method = extension.get("research_method_context")
        if not isinstance(research_method, Mapping):
            issues.append(issue("VR-METHOD-BINDING-001", "Research Method execute context is missing"))
        else:
            error = validate_research_method_context(research_method)
            if error:
                issues.append(issue("VR-METHOD-BINDING-001", error))
            elif research_method.get("context_binding") != expected_binding:
                issues.append(issue("VR-METHOD-BINDING-001", "Research Method context does not bind the exact PR9 Context Pack"))

        survey = extension.get("survey_context")
        if not isinstance(survey, Mapping):
            issues.append(issue("VR-CONTEXT-BINDING-001", "Survey Context extension is missing"))
        else:
            error = validate_survey_context(survey)
            if error:
                issues.append(issue("VR-CONTEXT-BINDING-001", error))

        instrument = extension.get("instrument")
        design = extension.get("design")
        if not isinstance(instrument, Mapping) or not isinstance(design, Mapping):
            issues.append(issue("VR-CONTEXT-BINDING-001", "exact Survey Design/Instrument payloads are missing"))
        else:
            try:
                schema_error = first_schema_error(_SURVEY_VALIDATOR, instrument)
                if schema_error:
                    raise ValueError(schema_error)
                if instrument.get("object_type") != "survey_questionnaire":
                    raise ValueError("pinned Survey Instrument is not a survey_questionnaire")
                validate_questionnaire(
                    instrument,
                    {"rq_ids": list(context_pack["question_ids"])},
                    state,
                )
            except Exception as exc:
                issues.append(issue("VR-CONTEXT-BINDING-001", f"pinned Survey Instrument is invalid: {exc}"))

        method_ref = extension.get("core_method_ref")
        effective = {
            (str(obj.get("kind")), str(obj.get("id")), int(obj.get("revision", -1))): obj
            for obj in state.objects
        }
        if not isinstance(method_ref, Mapping):
            issues.append(issue("VR-METHOD-BINDING-001", "approved Core Method pin is missing"))
        else:
            method = effective.get(("method", str(method_ref.get("method_id")), int(method_ref.get("revision", -1))))
            if method is None or method.get("adoption_state") != "approved":
                issues.append(issue("VR-METHOD-BINDING-001", "approved Core Method pin does not resolve in Research State"))
            elif not set(context_pack["question_ids"]).issubset(set(map(str, method.get("question_ids", ())))):
                issues.append(issue("VR-METHOD-BINDING-001", "approved Core Method does not cover all pinned Survey RQs"))

        snapshot = context_pack["pins"]["research_snapshot"]
        if (
            str(snapshot["snapshot_id"]) != str(state.current_snapshot["id"])
            or str(snapshot["content_digest"]) != str(state.current_snapshot["content_digest"])
        ):
            issues.append(issue("VR-CONTEXT-BINDING-001", "Research Snapshot pin is stale"))

        return tuple(issues)
