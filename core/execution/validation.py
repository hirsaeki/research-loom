from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

from core.runtime.transition_models import StateView

from .models import CapabilityExecutionError, ExecutionFailureCode


_SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "packages"


def _load_schema(name: str) -> Mapping[str, Any]:
    return json.loads((_SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _digest(document: Mapping[str, Any], field: str) -> str:
    payload = deepcopy(dict(document))
    payload.pop(field, None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def _canonical(value: Any) -> bytes:
    return rfc8785.dumps(value)


def _guard_id_sequence(context: Mapping[str, Any]) -> list[str]:
    constraints = context["project_constraints"]
    return [
        str(guard["guard_id"])
        for key in ("requirements", "prohibitions", "must_not_claim")
        for guard in constraints[key]
    ]


def _guard_ids(context: Mapping[str, Any]) -> set[str]:
    return set(_guard_id_sequence(context))


def _schema_error(
    validator: Draft202012Validator,
    document: Mapping[str, Any],
) -> str | None:
    errors = sorted(
        validator.iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.path),
    )
    if not errors:
        return None
    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path) or "$"
    return f"{path}: {error.message}"


class CanonicalCapabilityExecutionValidator:
    """Production validation for the generic PR9 execution envelopes."""

    def __init__(self) -> None:
        checker = FormatChecker()
        self._descriptor = Draft202012Validator(
            _load_schema("capability-descriptor.schema.json"),
            format_checker=checker,
        )
        self._context = Draft202012Validator(
            _load_schema("capability-context-pack.schema.json"),
            format_checker=checker,
        )
        self._invocation = Draft202012Validator(
            _load_schema("capability-invocation.schema.json"),
            format_checker=checker,
        )
        self._handoff = Draft202012Validator(
            _load_schema("capability-handoff.schema.json"),
            format_checker=checker,
        )

    def validate_documents(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> None:
        """Validate all state-independent PR9 schemas, digests and bindings."""
        error = _schema_error(self._descriptor, descriptor)
        if error:
            raise CapabilityExecutionError(
                ExecutionFailureCode.DESCRIPTOR_INVALID,
                error,
            )
        if descriptor.get("descriptor_digest") != _digest(
            descriptor,
            "descriptor_digest",
        ):
            raise CapabilityExecutionError(
                "CAP-DESCRIPTOR-DIGEST-001",
                "descriptor digest is invalid",
            )
        functions = [
            str(item["function_id"])
            for item in descriptor["declared_functions"]
        ]
        if len(functions) != len(set(functions)):
            raise CapabilityExecutionError(
                "CAP-DESCRIPTOR-IDENTITY-001",
                "descriptor function identities are not unique",
            )

        error = _schema_error(self._context, context)
        if error:
            raise CapabilityExecutionError(
                ExecutionFailureCode.CONTEXT_INVALID,
                error,
            )
        if context.get("context_pack_digest") != _digest(
            context,
            "context_pack_digest",
        ):
            raise CapabilityExecutionError(
                "CAP-CONTEXT-DIGEST-001",
                "Context Pack digest is invalid",
            )
        self._validate_context_intrinsic(context)

        error = _schema_error(self._invocation, invocation)
        if error:
            raise CapabilityExecutionError(
                ExecutionFailureCode.INVOCATION_INVALID,
                error,
            )
        if invocation.get("invocation_digest") != _digest(
            invocation,
            "invocation_digest",
        ):
            raise CapabilityExecutionError(
                "CAP-INVOCATION-DIGEST-001",
                "Invocation digest is invalid",
            )
        self._validate_invocation_semantics(descriptor, invocation, context)

    def validate_state_binding(
        self,
        context: Mapping[str, Any],
        state: StateView,
    ) -> None:
        """Validate current authoritative State pins without mutating State."""
        if context["project_id"] != state.project_ref:
            raise CapabilityExecutionError(
                "CAP-CONTEXT-BINDING-001",
                "Context Pack project does not match Research State",
            )
        pins = context["pins"]
        snapshot = pins["research_snapshot"]
        current = state.current_snapshot
        if (
            snapshot["snapshot_id"] != current.get("id")
            or snapshot["revision"] != current.get("revision", 0)
            or snapshot["content_digest"] != current.get("content_digest")
        ):
            raise CapabilityExecutionError(
                ExecutionFailureCode.STALE_STATE,
                "Context Pack Research Snapshot pin is stale",
            )
        if (
            pins["project_config"]["configuration_digest"]
            != state.project_config_digest
        ):
            raise CapabilityExecutionError(
                ExecutionFailureCode.STALE_STATE,
                "Context Pack Project Config pin is stale",
            )
        if (
            pins["effective_profile_set"]["content_digest"]
            != state.effective_profile_set_digest
        ):
            raise CapabilityExecutionError(
                ExecutionFailureCode.STALE_STATE,
                "Context Pack Effective Profile Set pin is stale",
            )

    def validate_preflight(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context: Mapping[str, Any],
        state: StateView,
    ) -> None:
        """Validate state-independent documents and current State binding."""
        self.validate_documents(descriptor, invocation, context)
        self.validate_state_binding(context, state)

    def _validate_context_intrinsic(
        self,
        context: Mapping[str, Any],
    ) -> None:
        bounds = context["bounds"]
        actual = {
            "max_questions": len(context["question_ids"]),
            "max_research_object_references": len(
                context["research_object_references"]
            ),
            "max_resources": len(context["resources"]),
            "max_attention_items": len(context["research_attention"]),
            "max_project_guards": sum(
                len(context["project_constraints"][key])
                for key in (
                    "requirements",
                    "prohibitions",
                    "must_not_claim",
                )
            ),
            "max_effective_constraints": len(
                context["effective_constraints"]
            ),
        }
        if any(actual[key] > bounds[key] for key in actual):
            raise CapabilityExecutionError(
                "CAP-CONTEXT-BOUND-001",
                "Context Pack exceeds its declared bounds",
            )
        identity_sequences = (
            [item["reference_id"] for item in context["resources"]],
            [item["attention_id"] for item in context["research_attention"]],
            _guard_id_sequence(context),
            [item["path"] for item in context["effective_constraints"]],
        )
        for values in identity_sequences:
            if len(values) != len(set(values)):
                raise CapabilityExecutionError(
                    "CAP-CONTEXT-IDENTITY-001",
                    "Context Pack contains duplicate bounded identities",
                )
        for resource in context["resources"]:
            if (
                resource["evidentiary_use"] == "candidate_source"
                and resource["reference_type"] != "source"
            ):
                raise CapabilityExecutionError(
                    "CAP-RESOURCE-001",
                    "only source resources may be evidence candidates",
                )

    def _validate_invocation_semantics(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> None:
        capability = invocation["capability"]
        if (
            capability["capability_id"] != descriptor["capability_id"]
            or capability["capability_version"]
            != descriptor["capability_version"]
            or capability["descriptor_digest"]
            != descriptor["descriptor_digest"]
        ):
            raise CapabilityExecutionError(
                "CAP-DESCRIPTOR-BINDING-001",
                "Invocation descriptor binding is invalid",
            )
        function = next(
            (
                item
                for item in descriptor["declared_functions"]
                if item["function_id"] == capability["function_id"]
            ),
            None,
        )
        if (
            function is None
            or invocation["execution_mode"]
            not in function["supported_execution_modes"]
        ):
            raise CapabilityExecutionError(
                "CAP-DESCRIPTOR-BINDING-001",
                "Invocation function or execution mode is not declared",
            )
        expected_context = {
            "context_pack_id": context["context_pack_id"],
            "context_pack_digest": context["context_pack_digest"],
        }
        if (
            invocation["project_id"] != context["project_id"]
            or invocation["context_pack"] != expected_context
            or _canonical(invocation["pins"]) != _canonical(context["pins"])
        ):
            raise CapabilityExecutionError(
                "CAP-PIN-001",
                "Invocation and Context Pack pins do not match",
            )
        authorization = invocation["runtime_authorization_evidence"]
        if (
            authorization["capability_id"] != capability["capability_id"]
            or authorization["function_id"] != capability["function_id"]
            or invocation["execution_mode"]
            not in authorization["execution_modes"]
        ):
            raise CapabilityExecutionError(
                "CAP-AUTH-001",
                "authorization evidence does not cover capability/function/mode",
            )
        resources = {
            item["reference_id"] for item in context["resources"]
        }
        if not resources.issubset(
            set(authorization["resource_reference_ids"])
        ):
            raise CapabilityExecutionError(
                "CAP-AUTH-001",
                "authorization evidence does not cover all Context Pack resources",
            )

    def validate_handoff(
        self,
        handoff: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> None:
        """Validate a returned PR9 Handoff before capability normalization."""
        error = _schema_error(self._handoff, handoff)
        if error:
            raise CapabilityExecutionError(
                ExecutionFailureCode.HANDOFF_INVALID,
                error,
            )
        if handoff.get("handoff_digest") != _digest(
            handoff,
            "handoff_digest",
        ):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-DIGEST-001",
                "Handoff digest is invalid",
            )
        if (
            handoff["invocation_id"] != invocation["invocation_id"]
            or handoff["run_id"] != invocation["run_id"]
            or handoff["project_id"] != invocation["project_id"]
        ):
            raise CapabilityExecutionError(
                "CAP-PIN-001",
                "Handoff run/invocation/project binding is invalid",
            )
        if (
            _canonical(handoff["capability"])
            != _canonical(invocation["capability"])
            or handoff["execution_mode"] != invocation["execution_mode"]
        ):
            raise CapabilityExecutionError(
                "CAP-DESCRIPTOR-BINDING-001",
                "Handoff capability binding is invalid",
            )
        expected_pins = {
            "invocation_digest": invocation["invocation_digest"],
            "context_pack_digest": context["context_pack_digest"],
            "project_config_digest": context["pins"]["project_config"][
                "configuration_digest"
            ],
            "effective_profile_set_digest": context["pins"][
                "effective_profile_set"
            ]["content_digest"],
            "research_snapshot": context["pins"]["research_snapshot"],
        }
        if _canonical(handoff["input_pins"]) != _canonical(expected_pins):
            raise CapabilityExecutionError(
                "CAP-PIN-001",
                "Handoff input pins are invalid",
            )
        provenance = handoff["provenance"]
        if provenance["trace_id"] != invocation["trace"]["trace_id"]:
            raise CapabilityExecutionError(
                "CAP-HANDOFF-PROVENANCE-001",
                "Handoff trace provenance is invalid",
            )
        expected_inputs = {
            invocation["capability"]["descriptor_digest"],
            context["context_pack_digest"],
            invocation["invocation_digest"],
        }
        if set(provenance["input_content_digests"]) != expected_inputs:
            raise CapabilityExecutionError(
                "CAP-HANDOFF-PROVENANCE-001",
                "Handoff input digest provenance is invalid",
            )
        preserved = handoff["preserved_context"]
        if (
            set(preserved["research_attention_ids"])
            != {
                item["attention_id"]
                for item in context["research_attention"]
            }
            or set(preserved["project_guard_ids"]) != _guard_ids(context)
            or set(preserved["effective_constraint_paths"])
            != {item["path"] for item in context["effective_constraints"]}
        ):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-PRESERVE-001",
                "Handoff dropped governance context",
            )
        self._validate_handoff_outputs(handoff, context)

    def _validate_handoff_outputs(
        self,
        handoff: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> None:
        outputs = handoff["outputs"]
        id_fields = {
            "observations": "observation_id",
            "source_captures": "capture_id",
            "evidence_candidates": "evidence_candidate_id",
            "candidate_findings": "candidate_finding_id",
            "counterevidence": "counterevidence_id",
            "conflicts": "conflict_id",
            "unknowns": "unknown_id",
            "evidence_gaps": "gap_id",
            "candidate_next_actions": "proposal_id",
            "candidate_next_methods": "proposal_id",
        }
        ids = [
            item[field]
            for collection, field in id_fields.items()
            for item in outputs[collection]
        ]
        if len(ids) != len(set(ids)):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-IDENTITY-001",
                "Handoff output identities are not globally unique",
            )
        evidence_ids = {
            item["evidence_candidate_id"]
            for item in outputs["evidence_candidates"]
        }
        counter_ids = {
            item["counterevidence_id"]
            for item in outputs["counterevidence"]
        }
        question_ids = set(context["question_ids"])
        all_ids = set(ids)
        if any(
            not set(item.get("evidence_candidate_ids", ())).issubset(
                evidence_ids
            )
            for item in outputs["observations"]
        ):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-REF-001",
                "observation references unknown evidence output",
            )
        for finding in outputs["candidate_findings"]:
            if (
                not set(finding["question_ids"]).issubset(question_ids)
                or not set(
                    finding["supporting_evidence_candidate_ids"]
                ).issubset(evidence_ids)
                or not set(
                    finding["counterevidence_candidate_ids"]
                ).issubset(counter_ids)
            ):
                raise CapabilityExecutionError(
                    "CAP-HANDOFF-REF-001",
                    "candidate finding contains an invalid reference",
                )
        if any(
            not set(item["question_ids"]).issubset(question_ids)
            for item in outputs["evidence_gaps"]
        ):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-REF-001",
                "evidence gap references an unknown question",
            )
        if any(
            not set(item["related_output_ids"]).issubset(all_ids)
            for item in outputs["conflicts"]
        ):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-REF-001",
                "conflict references unknown output",
            )
        if handoff["execution_mode"] in {"virtual", "synthetic_test"}:
            epistemic = (
                outputs["observations"]
                + outputs["evidence_candidates"]
                + outputs["candidate_findings"]
                + outputs["counterevidence"]
            )
            if any(
                item["epistemic_mode"] != "synthetic"
                for item in epistemic
            ):
                raise CapabilityExecutionError(
                    "CAP-MODE-001",
                    "virtual/synthetic_test output may not be labeled empirical",
                )
        validation = handoff["validation"]
        if (
            validation["status"] == "valid" and validation["issues"]
        ) or (
            validation["status"] in {"partial", "rejected"}
            and not validation["issues"]
        ):
            raise CapabilityExecutionError(
                "CAP-HANDOFF-VALIDATION-001",
                "Handoff validation status/issues are inconsistent",
            )

        resources = {
            item["reference_id"]: item for item in context["resources"]
        }
        captures = {
            item["capture_id"]: item for item in outputs["source_captures"]
        }
        for capture in captures.values():
            origin = capture["origin"]
            if origin["origin_type"] == "project_source_reference":
                resource = resources.get(origin["resource_reference_id"])
                if (
                    not resource
                    or resource["reference_type"] != "source"
                    or resource["evidentiary_use"] != "candidate_source"
                ):
                    raise CapabilityExecutionError(
                        "CAP-HANDOFF-REF-001",
                        "source capture references an ineligible resource",
                    )
        for item in (
            outputs["evidence_candidates"] + outputs["counterevidence"]
        ):
            basis = item["source_basis"]
            resource = None
            if basis["basis_type"] == "resource_reference":
                resource = resources.get(basis["resource_reference_id"])
            else:
                capture = captures.get(basis["capture_id"])
                if capture is None:
                    raise CapabilityExecutionError(
                        "CAP-HANDOFF-REF-001",
                        "evidence basis references an unknown capture",
                    )
                origin = capture["origin"]
                if origin["origin_type"] == "acquired_source":
                    continue
                resource = resources.get(origin["resource_reference_id"])
            if (
                not resource
                or resource["reference_type"] != "source"
                or resource["evidentiary_use"] != "candidate_source"
            ):
                raise CapabilityExecutionError(
                    "CAP-RESOURCE-001",
                    "evidence output is based on a non-evidentiary resource",
                )
