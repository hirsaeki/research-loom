from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation.validation import canonical_digest
from core.execution import ExecutionStyle
from core.execution.models import CapabilityExecutionError

from .llm_backend import VirtualRespondentBackend, VirtualRespondentBackendError
from .output_builder import build_output
from .provenance import build_virtual_context, generation_provenance, input_pins
from .response_validation import SurveyResponseValidator, stable_response_key
from .runtime_state import candidate_change_requests, defects_from_issues, readiness_assessment


def _record_from_payload(
    payload: Mapping[str, Any],
    instrument: Mapping[str, Any],
    *,
    index: int,
    namespace: str,
    producer_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    aliases = {}
    for question in instrument.get("questions", ()):
        stable = stable_response_key(question)
        aliases[str(question["question_id"])] = stable
        aliases[stable] = stable
    source_answers = payload.get("answers", {})
    answers = []
    if isinstance(source_answers, Mapping):
        iterable = [
            {"response_key": key, "state": (str(raw.get("state")) if isinstance(raw, Mapping) and "state" in raw else "answered"), "value": (None if isinstance(raw, Mapping) and "state" in raw else raw)}
            for key, raw in source_answers.items()
        ]
    elif isinstance(source_answers, list):
        iterable = source_answers
    else:
        iterable = []
    for item in iterable:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("response_key", ""))
        response_key = aliases.get(key, key)
        state = str(item.get("state", "answered"))
        answer = {"response_key": response_key, "state": state}
        if state == "answered":
            answer["value"] = deepcopy(item.get("value"))
        answers.append(answer)
    return {
        "schema_version": "0.1.0",
        "object_type": "survey_response_record",
        "response_id": f"SYN-RESP-{index + 1:04d}",
        "raw_data_ref_id": f"SYN-DATA-{index + 1:04d}",
        "participant_id": f"SYN-RESPONDENT-{index + 1:04d}",
        "identity_namespace": namespace,
        "epistemic_mode": "virtual",
        "synthetic": True,
        "response_status": "complete",
        "eligibility_status": "eligible",
        "duplicate_disposition": "not_duplicate",
        "verified_evidence_claimed": False,
        "dropout": False,
        "answers": answers,
        **({"producer_provenance": deepcopy(dict(producer_provenance))} if producer_provenance else {}),
    }


def _profile_digest_map(extension: Mapping[str, Any], profiles: list[Mapping[str, Any]]) -> dict[str, str]:
    plan = extension.get("respondent_plan")
    if not isinstance(plan, Mapping) or not isinstance(plan.get("profile_digests"), list):
        raise CapabilityExecutionError("VR-PROFILE-LINEAGE-001", "LLM respondent plan is missing profile digests")
    expected_ids = [str(profile.get("profile_id", "")) for profile in profiles]
    digests: dict[str, str] = {}
    for item in plan["profile_digests"]:
        if not isinstance(item, Mapping):
            raise CapabilityExecutionError("VR-PROFILE-LINEAGE-001", "LLM respondent plan contains malformed profile digest binding")
        profile_id = str(item.get("profile_id", ""))
        content_digest = str(item.get("content_digest", ""))
        if not profile_id or not content_digest.startswith("sha256:") or profile_id in digests:
            raise CapabilityExecutionError("VR-PROFILE-LINEAGE-001", "LLM respondent plan contains invalid or duplicate profile digest binding")
        digests[profile_id] = content_digest
    if set(digests) != set(expected_ids) or len(expected_ids) != len(set(expected_ids)):
        raise CapabilityExecutionError("VR-PROFILE-LINEAGE-001", "LLM respondent plan profile digest bindings do not match the explicit profiles")
    return digests


class LlmSurveyVirtualRunnerAdapter:
    implementation_id = "plugin.survey-virtual-runner.llm"
    implementation_version = "1.0.0"
    capability_id = "virtual-runner"
    capability_version = "0.1.0"
    supported_functions = ("execute",)
    supported_execution_modes = ("virtual",)
    execution_style = ExecutionStyle.MANAGED
    requires_context_extension = True

    def __init__(self, *, execution_store, clock, backend: VirtualRespondentBackend) -> None:
        self._execution_store = execution_store
        self._clock = clock
        self._backend = backend

    def execute(self, request):
        extension = getattr(request, "context_extension", None)
        if not isinstance(extension, Mapping):
            raise CapabilityExecutionError("VR-CONTEXT-BINDING-001", "Survey Virtual Runner requires its validated immutable Context extension")
        questionnaire = extension.get("instrument")
        population = extension.get("synthetic_population")
        profiles = extension.get("respondent_profiles")
        backend_config = extension.get("llm_backend_configuration")
        prompt_template = extension.get("prompt_template")
        if not all(isinstance(item, Mapping) for item in (questionnaire, population, backend_config, prompt_template)) or not isinstance(profiles, list):
            raise CapabilityExecutionError("VR-CONTEXT-BINDING-001", "LLM Virtual Respondent immutable execution inputs are incomplete")
        if str(backend_config.get("backend_id")) != str(self._backend.backend_id):
            raise CapabilityExecutionError("BACKEND_UNAVAILABLE", "configured Virtual Respondent backend does not match the bound production adapter")

        provenance = generation_provenance(request, extension)
        build_virtual_context(request, extension, provenance)
        pins = input_pins(request, extension, provenance)
        records: list[Any] = []
        generation_attempts: list[dict[str, Any]] = []
        profile_digests = _profile_digest_map(extension, profiles)
        for index, profile in enumerate(profiles):
            profile_id = str(profile["profile_id"])
            attempt_id = f"GEN-ATTEMPT-{index + 1:04d}"
            try:
                generated = self._backend.generate_response(
                    instrument=questionnaire,
                    profile=profile,
                    generation_config=backend_config,
                    prompt_template=prompt_template,
                )
            except VirtualRespondentBackendError as exc:
                generation_attempts.append({
                    "generation_attempt_id": attempt_id,
                    "respondent_profile_id": profile_id,
                    "respondent_profile_digest": profile_digests[profile_id],
                    "status": "failed",
                    "failure_code": exc.code,
                    "failure_message": exc.message,
                    "attempt_count": len(exc.attempts),
                    "generated_at": self._clock.now(),
                    "attempts": deepcopy(exc.attempts),
                })
                continue
            parsed_payload = generated.get("parsed_answer_payload")
            if not isinstance(parsed_payload, Mapping):
                raise CapabilityExecutionError(
                    "VR-PROFILE-LINEAGE-001",
                    "LLM generation result is missing a structured parsed answer payload",
                )
            parsed_digest = canonical_digest(parsed_payload)
            declared_parsed_digest = generated.get("parsed_answer_payload_digest")
            if declared_parsed_digest is not None and declared_parsed_digest != parsed_digest:
                raise CapabilityExecutionError(
                    "VR-PROFILE-LINEAGE-001",
                    "LLM generation result parsed answer payload digest is inconsistent",
                )
            record = _record_from_payload(
                parsed_payload,
                questionnaire,
                index=len(records),
                namespace=str(population["identity_namespace"]),
                producer_provenance={
                    "producer_type": "virtual_respondent",
                    "source_run_id": str(request.run.run_id),
                    "respondent_profile_ref": {
                        "profile_id": profile_id,
                        "profile_digest": profile_digests[profile_id],
                    },
                    "generation_attempt_ref": {"attempt_id": attempt_id},
                    "parsed_answer_payload_digest": parsed_digest,
                },
            )
            records.append(record)
            generation_attempts.append({
                "generation_attempt_id": attempt_id,
                "respondent_profile_id": profile_id,
                "respondent_profile_digest": profile_digests[profile_id],
                "status": "generated",
                "provider_request_id": generated.get("provider_request_id"),
                "attempt_count": len(generated.get("attempts", [])),
                "generated_at": self._clock.now(),
                "usage": deepcopy(generated.get("usage")),
                "attempts": deepcopy(generated.get("attempts", [])),
                "semantic_input_digest": generated.get("semantic_input_digest"),
                "request_digest": generated.get("request_digest"),
                "parsed_answer_payload_digest": parsed_digest,
                "provider_response_digest": generated.get("provider_response_digest"),
                "provider_response": deepcopy(generated.get("provider_response")),
                "response_ref": {
                    "response_id": record["response_id"],
                    "identity_namespace": record["identity_namespace"],
                },
            })

        validation = SurveyResponseValidator().validate(
            questionnaire,
            records,
            expected_epistemic_mode="virtual",
            expected_identity_namespace=str(population["identity_namespace"]),
        )
        defects = defects_from_issues(
            validation["issues"],
            run_id=str(request.run.run_id),
            instrument_id=str(extension["instrument_ref"]["id"]),
            expected_codes=set(),
        )
        changes = candidate_change_requests(defects)
        warnings = [
            "LLM Virtual Respondent outputs are synthetic test distributions, not population estimates.",
            *[
                f"preserved {item['kind']}: {item['detail']}"
                for item in validation["preservation_events"]
                if item["kind"] in {"unknown", "not_applicable", "prefer_not_to_answer"}
            ],
        ]
        failed = sum(1 for item in generation_attempts if item["status"] == "failed")
        if failed:
            warnings.append(f"{failed} synthetic respondent generation(s) failed and were preserved as generation diagnostics")
        readiness = readiness_assessment(
            scenario_class=str(extension["scenario_class"]),
            prior=[],
            defects=defects,
            policy=extension["runner_configuration"]["readiness_policy"],
        )
        return build_output(
            request,
            extension,
            records=records,
            validation=validation,
            defects=defects,
            warnings=warnings,
            change_requests=changes,
            readiness=readiness,
            provenance=provenance,
            pins=pins,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            generation_attempts=generation_attempts,
            respondent_profiles=profiles,
        )

    def cancel(self, run_id: str) -> None:
        del run_id
        return None
