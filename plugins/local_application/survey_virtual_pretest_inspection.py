from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from core.conversation.validation import canonical_digest
from plugins.local_survey_analysis_store import LocalSurveyAnalysisStoreError
from plugins.local_survey_response_store import LocalSurveyResponseStoreError

from .facade import LocalApplicationError


_ERROR = "APPLICATION-SURVEY-VIRTUAL-PRETEST-001"


def _ref(value: Mapping[str, Any]) -> dict[str, str]:
    return {"id": str(value["id"]), "content_digest": str(value["content_digest"])}


def _load_json_artifact(facade, run_id: str, role: str) -> dict[str, Any] | None:
    metas = [
        item
        for item in facade._application.execution_store.artifacts_for(run_id)
        if item.role == role
    ]
    if not metas:
        return None
    if len(metas) != 1:
        raise LocalApplicationError(_ERROR, f"Virtual Survey Run must have exactly one {role} artifact")
    try:
        payload = facade._application.execution_store.load_artifact(metas[0].artifact_id)
        value = json.loads(payload.content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LocalApplicationError(_ERROR, f"Virtual Survey artifact is unreadable: {role}") from exc
    if not isinstance(value, Mapping):
        raise LocalApplicationError(_ERROR, f"Virtual Survey artifact is malformed: {role}")
    return deepcopy(dict(value))


def _answer_projection(answer: Mapping[str, Any], question: Mapping[str, Any]) -> dict[str, Any]:
    state = str(answer["state"])
    value = deepcopy(answer.get("value")) if state == "answered" else None
    labels = {
        str(option.get("value", option.get("option_id"))): str(option.get("label", option.get("value", option.get("option_id", ""))))
        for option in question.get("response_options", ())
        if isinstance(option, Mapping)
    }
    display_label: Any = None
    if state == "answered" and labels:
        if isinstance(value, list):
            display_label = [labels.get(str(item), str(item)) for item in value]
        else:
            display_label = labels.get(str(value), str(value))
    return {
        "question_id": str(answer["question_id"]),
        "response_key": str(answer["response_key"]),
        "question_prompt": str(question.get("text", "")),
        "stable_value": value,
        "display_label": display_label,
        "response_state": state,
    }


def _producer_from_raw(raw: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    provenance = raw.get("provenance")
    return provenance if isinstance(provenance, Mapping) else None


class SurveyVirtualPretestInspectionMixin:
    """Joined, read-only Human inspection for one LLM Survey Virtual pretest Run."""

    def show_survey_virtual_pretest(
        self,
        run_id: str,
        *,
        aggregate_result_id: str | None = None,
    ) -> Mapping[str, Any]:
        before = deepcopy(self._state().current_snapshot)
        base = super().show_run(run_id)
        run = base.get("run")
        virtual = base.get("virtual_runner")
        if (
            not isinstance(run, Mapping)
            or run.get("capability_id") != "virtual-runner"
            or run.get("execution_mode") != "virtual"
            or run.get("status") != "COMPLETED"
            or not isinstance(virtual, Mapping)
            or virtual.get("generator_backend") != "llm"
        ):
            raise LocalApplicationError(_ERROR, "joined Survey pretest inspection requires one completed LLM Virtual Respondent Run")

        generation = _load_json_artifact(self, run_id, "survey_virtual.generation_report")
        if generation is None:
            raise LocalApplicationError(_ERROR, "LLM Virtual Respondent generation report is missing")
        profiles = generation.get("respondent_profiles")
        attempts = generation.get("generation_attempts")
        plan = virtual.get("respondent_plan")
        input_pins = virtual.get("input_pins")
        if (
            generation.get("generator_backend") != "llm"
            or not isinstance(profiles, list)
            or not isinstance(attempts, list)
            or not isinstance(plan, Mapping)
            or not isinstance(input_pins, Mapping)
        ):
            raise LocalApplicationError(_ERROR, "LLM respondent plan or generation report is malformed")
        backend_pin = input_pins.get("backend")
        if (
            not isinstance(backend_pin, Mapping)
            or generation.get("backend_config_digest") != backend_pin.get("backend_config_digest")
            or generation.get("prompt_template") != input_pins.get("prompt_template")
        ):
            raise LocalApplicationError(_ERROR, "generation report backend or prompt pin does not match the Virtual Run")

        plan_digests: dict[str, str] = {}
        for item in plan.get("profile_digests", ()):
            if not isinstance(item, Mapping):
                raise LocalApplicationError(_ERROR, "respondent plan profile digest binding is malformed")
            profile_id = str(item.get("profile_id", ""))
            digest = str(item.get("content_digest", ""))
            if not profile_id or not digest or profile_id in plan_digests:
                raise LocalApplicationError(_ERROR, "respondent plan has invalid or duplicate profile binding")
            plan_digests[profile_id] = digest

        profile_map: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            if not isinstance(profile, Mapping):
                raise LocalApplicationError(_ERROR, "generation report profile is malformed")
            profile_id = str(profile.get("profile_id", ""))
            expected = plan_digests.get(profile_id)
            if expected is None or canonical_digest(profile) != expected or profile_id in profile_map:
                raise LocalApplicationError(_ERROR, "generation report profile does not match the pinned respondent plan")
            profile_map[profile_id] = deepcopy(dict(profile))
        if set(profile_map) != set(map(str, plan.get("profile_ids", ()))):
            raise LocalApplicationError(_ERROR, "generation report profiles do not match the pinned respondent plan")

        attempt_map: dict[str, dict[str, Any]] = {}
        explicit_lineage_expected = False
        for ordinal, attempt in enumerate(attempts, start=1):
            if not isinstance(attempt, Mapping):
                raise LocalApplicationError(_ERROR, "generation attempt is malformed")
            profile_id = str(attempt.get("respondent_profile_id", ""))
            if profile_id not in profile_map or profile_id in attempt_map:
                raise LocalApplicationError(_ERROR, "generation attempts violate the one-profile/one-response interaction contract")
            if attempt.get("respondent_profile_digest") not in (None, plan_digests[profile_id]):
                raise LocalApplicationError(_ERROR, "generation attempt profile digest does not match the respondent plan")
            if attempt.get("response_ref") is not None or attempt.get("generation_attempt_id") is not None:
                explicit_lineage_expected = True
            item = deepcopy(dict(attempt))
            item["_ordinal"] = ordinal
            attempt_map[profile_id] = item
        if set(attempt_map) != set(profile_map):
            raise LocalApplicationError(_ERROR, "every pinned profile must have exactly one generation attempt")
        if explicit_lineage_expected:
            for profile_id, attempt in attempt_map.items():
                if (
                    not attempt.get("generation_attempt_id")
                    or attempt.get("respondent_profile_digest") != plan_digests[profile_id]
                    or (attempt.get("status") == "generated" and not isinstance(attempt.get("response_ref"), Mapping))
                ):
                    raise LocalApplicationError(_ERROR, "explicit generation lineage is incomplete")

        dataset_ref = virtual.get("response_dataset_ref")
        if not isinstance(dataset_ref, Mapping):
            raise LocalApplicationError(_ERROR, "LLM Virtual Respondent Run has no canonical SurveyResponseDataset")
        try:
            dataset = self._survey_response_store().load_dataset(self._project_id, str(dataset_ref["dataset_id"]))
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if dataset is None or str(dataset["content_digest"]) != str(dataset_ref["content_digest"]):
            raise LocalApplicationError(_ERROR, "Run Dataset ref does not match the exact stored SurveyResponseDataset")
        if (
            dataset.get("source_run_ids") != [str(run_id)]
            or dataset.get("response_origin") != "synthetic"
            or dataset.get("epistemic_status") != "SYNTHETIC_TEST_ONLY"
            or dataset.get("source_provenance", {}).get("generator_backend") != "llm"
        ):
            raise LocalApplicationError(_ERROR, "SurveyResponseDataset source Run or synthetic provenance does not match the inspected Run")
        if dataset.get("instrument_ref") != input_pins.get("instrument"):
            raise LocalApplicationError(_ERROR, "SurveyResponseDataset Instrument pin does not match the Virtual Run")
        questionnaire = self._questionnaire_for_dataset(dataset)
        question_map = {str(item["question_id"]): item for item in questionnaire.get("questions", ())}

        canonical_by_profile: dict[str, dict[str, Any]] = {}
        unbound_responses: list[dict[str, Any]] = []
        accepted, rejected = self._dataset_population(dataset)
        for response in [*accepted, *rejected]:
            producer = response.get("source_provenance", {}).get("producer")
            if not isinstance(producer, Mapping) or producer.get("producer_type") != "virtual_respondent":
                unbound_responses.append(deepcopy(response))
                continue
            ref = producer.get("respondent_profile_ref")
            if not isinstance(ref, Mapping):
                unbound_responses.append(deepcopy(response))
                continue
            profile_id = str(ref.get("profile_id", ""))
            if profile_id not in profile_map or str(ref.get("profile_digest", "")) != plan_digests[profile_id]:
                raise LocalApplicationError(_ERROR, "canonical SurveyResponse profile ref is unknown or digest-mismatched")
            if profile_id in canonical_by_profile:
                raise LocalApplicationError(_ERROR, "one Synthetic Profile is bound to multiple canonical SurveyResponses")
            if (
                str(response.get("source_run_id", "")) != str(run_id)
                or str(producer.get("source_run_id", "")) != str(run_id)
            ):
                raise LocalApplicationError(_ERROR, "canonical SurveyResponse producer Run binding is inconsistent")
            attempt = attempt_map[profile_id]
            attempt_ref = producer.get("generation_attempt_ref")
            if not isinstance(attempt_ref, Mapping) or str(attempt_ref.get("attempt_id", "")) != str(attempt.get("generation_attempt_id", "")):
                raise LocalApplicationError(_ERROR, "canonical SurveyResponse generation-attempt binding is inconsistent")
            if producer.get("parsed_answer_payload_digest") != attempt.get("parsed_answer_payload_digest"):
                raise LocalApplicationError(_ERROR, "canonical SurveyResponse parsed payload digest does not match its generation attempt")
            expected_response = attempt.get("response_ref")
            if not isinstance(expected_response, Mapping) or (
                str(expected_response.get("response_id", "")) != str(response["response_id"])
                or str(expected_response.get("identity_namespace", "")) != str(response["identity_namespace"])
            ):
                raise LocalApplicationError(_ERROR, "generation attempt response ref does not match the canonical SurveyResponse")
            canonical_by_profile[profile_id] = response

        raw_rejection_by_profile: dict[str, dict[str, Any]] = {}
        for item in dataset.get("rejected_inputs", ()):
            if not isinstance(item, Mapping) or item.get("canonical_response_ref") is not None:
                continue
            raw = item.get("raw_input")
            producer = _producer_from_raw(raw)
            if not isinstance(producer, Mapping):
                continue
            if producer.get("producer_type") != "virtual_respondent":
                if explicit_lineage_expected:
                    raise LocalApplicationError(_ERROR, "rejected raw response producer type is inconsistent")
                continue
            ref = producer.get("respondent_profile_ref")
            if not isinstance(ref, Mapping):
                continue
            profile_id = str(ref.get("profile_id", ""))
            if profile_id not in profile_map or str(ref.get("profile_digest", "")) != plan_digests[profile_id]:
                raise LocalApplicationError(_ERROR, "rejected raw response profile ref is unknown or digest-mismatched")
            if profile_id in canonical_by_profile or profile_id in raw_rejection_by_profile:
                raise LocalApplicationError(_ERROR, "one Synthetic Profile resolves to multiple response records")
            attempt = attempt_map[profile_id]
            attempt_ref = producer.get("generation_attempt_ref")
            expected_response = attempt.get("response_ref")
            if (
                str(producer.get("source_run_id", "")) != str(run_id)
                or not isinstance(attempt_ref, Mapping)
                or str(attempt_ref.get("attempt_id", "")) != str(attempt.get("generation_attempt_id", ""))
                or producer.get("parsed_answer_payload_digest") != attempt.get("parsed_answer_payload_digest")
                or not isinstance(expected_response, Mapping)
                or not isinstance(raw, Mapping)
                or str(expected_response.get("response_id", "")) != str(raw.get("response_id", ""))
                or str(expected_response.get("identity_namespace", "")) != str(raw.get("identity_namespace", ""))
            ):
                raise LocalApplicationError(_ERROR, "rejected raw response generation lineage is inconsistent")
            raw_rejection_by_profile[profile_id] = deepcopy(dict(item))

        if explicit_lineage_expected and unbound_responses:
            raise LocalApplicationError(_ERROR, "new LLM Virtual Respondent Run contains canonical responses without explicit profile lineage")
        binding_status = "explicit" if explicit_lineage_expected else "unavailable"

        respondents: list[dict[str, Any]] = []
        for profile_id in map(str, plan.get("profile_ids", ())):
            profile = profile_map[profile_id]
            attempt = attempt_map[profile_id]
            profile_projection = {
                "profile_id": profile_id,
                "profile_digest": plan_digests[profile_id],
                "attributes": deepcopy(profile.get("attributes", {})),
                "knowledge_scope": deepcopy(profile.get("knowledge_scope", [])),
                **({"scenario_notes": deepcopy(profile["scenario_notes"])} if profile.get("scenario_notes") is not None else {}),
            }
            row: dict[str, Any] = {
                "profile": profile_projection,
                "generation_status": str(attempt.get("status")),
                "generation_attempt_ref": (
                    {"attempt_id": str(attempt["generation_attempt_id"]), "ordinal": int(attempt["_ordinal"])}
                    if attempt.get("generation_attempt_id")
                    else {"ordinal": int(attempt["_ordinal"])}
                ),
                "response": None,
            }
            if attempt.get("status") == "failed":
                row["failure_code"] = attempt.get("failure_code")
                row["failure_message"] = attempt.get("failure_message")
            elif binding_status == "explicit" and profile_id in canonical_by_profile:
                response = canonical_by_profile[profile_id]
                row["response"] = {
                    "response_id": response["response_id"],
                    "participant_id": response["participant_id"],
                    "identity_namespace": response["identity_namespace"],
                    "validation_status": response["validation"]["status"],
                    "answers": [
                        _answer_projection(answer, question_map[str(answer["question_id"])])
                        for answer in response["answers"]
                    ],
                    "validation_issues": deepcopy(response["validation"]["issues"]),
                }
            elif binding_status == "explicit" and profile_id in raw_rejection_by_profile:
                rejected_item = raw_rejection_by_profile[profile_id]
                raw = rejected_item.get("raw_input")
                row["response"] = {
                    "response_id": raw.get("response_id") if isinstance(raw, Mapping) else None,
                    "validation_status": "rejected",
                    "canonical_response": None,
                    "raw_input_digest": rejected_item["raw_input_digest"],
                    "raw_response": deepcopy(raw),
                    "validation_issues": deepcopy(rejected_item.get("issues", [])),
                }
            elif binding_status == "explicit" and attempt.get("status") == "generated":
                raise LocalApplicationError(_ERROR, "generated profile has no uniquely bound canonical or rejected response")
            respondents.append(row)

        aggregate = None
        analysis_spec_ref = None
        aggregate_ref = None
        try:
            candidates = self._survey_analysis_store().find_results_by_dataset(
                self._project_id, str(dataset["dataset_id"])
            )
        except LocalSurveyAnalysisStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        selected = None
        if aggregate_result_id:
            selected = next((item for item in candidates if str(item["aggregate_result_id"]) == aggregate_result_id), None)
            if selected is None:
                raise LocalApplicationError(_ERROR, "requested SurveyAggregateResult is not bound to the Run Dataset")
        elif len(candidates) == 1:
            selected = candidates[0]
        elif len(candidates) > 1:
            raise LocalApplicationError(_ERROR, "multiple SurveyAggregateResults exist; aggregate_result_id is required")
        if selected is not None:
            if selected.get("dataset_ref") != {"id": dataset["dataset_id"], "content_digest": dataset["content_digest"]}:
                raise LocalApplicationError(_ERROR, "SurveyAggregateResult Dataset binding does not match the Run Dataset")
            if selected.get("instrument_ref") != dataset["instrument_ref"]:
                raise LocalApplicationError(_ERROR, "SurveyAggregateResult Instrument binding does not match the Run Dataset")
            aggregate_ref = {"id": selected["aggregate_result_id"], "content_digest": selected["content_digest"]}
            analysis_spec_ref = deepcopy(selected["analysis_spec_ref"])
            spec = self._load_spec_exact(str(analysis_spec_ref["id"]), str(analysis_spec_ref["content_digest"]))
            if spec.get("dataset_ref") != {"id": dataset["dataset_id"], "content_digest": dataset["content_digest"]} or spec.get("instrument_ref") != dataset["instrument_ref"]:
                raise LocalApplicationError(_ERROR, "SurveyAnalysisSpec binding does not match the Run Dataset")
            aggregate = self.show_survey_aggregate_result(str(selected["aggregate_result_id"]), limit=100, offset=0)

        after = deepcopy(self._state().current_snapshot)
        if before != after:
            raise LocalApplicationError(_ERROR, "Survey Virtual pretest inspection mutated Research State")
        return {
            "status": "OK",
            "project_id": self._project_id,
            "run_id": str(run_id),
            "execution_mode": "virtual",
            "scenario_class": virtual["scenario_class"],
            "generator_backend": "llm",
            "instrument_ref": deepcopy(dataset["instrument_ref"]),
            "interaction_model": plan.get("interaction_model"),
            "synthetic_firewall": {
                "response_origin": "synthetic",
                "epistemic_status": "SYNTHETIC_TEST_ONLY",
                "population_estimate": False,
                "empirical_evidence": False,
                "validity_certification": False,
            },
            "generation_summary": deepcopy(virtual["generation_summary"]),
            "profile_response_binding": binding_status,
            "respondents": respondents,
            "unbound_responses": (
                [
                    {
                        "response_id": response["response_id"],
                        "validation_status": response["validation"]["status"],
                    }
                    for response in unbound_responses
                ]
                if binding_status == "unavailable"
                else []
            ),
            "dataset_ref": {"id": dataset["dataset_id"], "content_digest": dataset["content_digest"]},
            "analysis_spec_ref": analysis_spec_ref,
            "aggregate_result_ref": aggregate_ref,
            "aggregate_inspection": aggregate,
            "research_state_mutation_performed": False,
            "validity_judgment_performed": False,
            "instrument_revision_performed": False,
        }
