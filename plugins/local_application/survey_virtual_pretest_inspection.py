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
        "question_type": str(question.get("question_type", "")),
        "stable_value": value,
        "display_label": display_label,
        "response_state": state,
    }


def _producer_from_raw(raw: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    provenance = raw.get("provenance")
    return provenance if isinstance(provenance, Mapping) else None


def _issue_code_counts(respondents: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in respondents:
        response = row.get("response")
        if not isinstance(response, Mapping):
            continue
        for issue in response.get("validation_issues", ()):
            if not isinstance(issue, Mapping):
                continue
            code = str(issue.get("code", ""))
            if code:
                counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _state_counts(respondents: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for row in respondents:
        response = row.get("response")
        if not isinstance(response, Mapping):
            continue
        for answer in response.get("answers", ()):
            if not isinstance(answer, Mapping):
                continue
            key = str(answer.get("response_key", ""))
            state = str(answer.get("response_state", ""))
            if key and state:
                bucket = result.setdefault(key, {})
                bucket[state] = bucket.get(state, 0) + 1
    return {key: dict(sorted(value.items())) for key, value in sorted(result.items())}


def _answers_by_key(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    response = row.get("response")
    if not isinstance(response, Mapping):
        return {}
    answers = response.get("answers")
    if not isinstance(answers, list):
        return {}
    return {str(item["response_key"]): item for item in answers if isinstance(item, Mapping) and item.get("response_key")}


def _answer_semantics(answer: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if answer is None:
        return None
    return {
        "response_key": str(answer.get("response_key", "")),
        "stable_value": deepcopy(answer.get("stable_value")),
        "response_state": str(answer.get("response_state", "")),
    }


def _aggregate_key(item: Mapping[str, Any]) -> str:
    if item.get("item_id"):
        return str(item["item_id"])
    return "|".join(
        str(item.get(field, ""))
        for field in ("analysis_type", "question_id", "row_question_id", "column_question_id")
    )


def _comparison_item(item: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    value = deepcopy(dict(item))
    value.pop("provenance", None)
    if value.get("analysis_type") == "frequency":
        for category in value.get("categories", ()):
            if isinstance(category, dict):
                category.pop("label", None)
    if value.get("analysis_type") == "free_text_listing":
        for row in value.get("rows", ()):
            if isinstance(row, dict):
                for field in ("response_id", "participant_id", "identity_namespace"):
                    row.pop(field, None)
    return value


def _all_aggregate_items(facade, aggregate_ref: Mapping[str, Any]) -> list[dict[str, Any]]:
    aggregate_result_id = str(aggregate_ref["id"])
    expected_digest = str(aggregate_ref["content_digest"])
    offset = 0
    total: int | None = None
    result: list[dict[str, Any]] = []
    while total is None or offset < total:
        page = facade.show_survey_aggregate_result(
            aggregate_result_id,
            limit=100,
            offset=offset,
        )
        summary = page.get("aggregate_result")
        pagination = page.get("pagination")
        items = page.get("result_items")
        if (
            not isinstance(summary, Mapping)
            or str(summary.get("content_digest", "")) != expected_digest
            or not isinstance(pagination, Mapping)
            or not isinstance(items, list)
        ):
            raise LocalApplicationError(_ERROR, "SurveyAggregateResult pagination is malformed or stale")
        page_total = pagination.get("total")
        returned = pagination.get("returned")
        if (
            not isinstance(page_total, int)
            or isinstance(page_total, bool)
            or page_total < 0
            or not isinstance(returned, int)
            or isinstance(returned, bool)
            or returned != len(items)
        ):
            raise LocalApplicationError(_ERROR, "SurveyAggregateResult pagination metadata is invalid")
        if total is None:
            total = page_total
        elif page_total != total:
            raise LocalApplicationError(_ERROR, "SurveyAggregateResult pagination total changed during inspection")
        if returned == 0 and offset < total:
            raise LocalApplicationError(_ERROR, "SurveyAggregateResult pagination ended before total items were read")
        result.extend(deepcopy(items))
        offset += returned
    if total is None or len(result) != total:
        raise LocalApplicationError(_ERROR, "SurveyAggregateResult pagination did not resolve the complete result")
    return result


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
            "comparison_pins": {
                "respondent_plan": deepcopy(input_pins.get("respondent_plan")),
                "backend": deepcopy(input_pins.get("backend")),
                "prompt_template": deepcopy(input_pins.get("prompt_template")),
            },
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

    def compare_survey_virtual_pretests(
        self,
        run_a_id: str,
        run_b_id: str,
        *,
        aggregate_a_result_id: str | None = None,
        aggregate_b_result_id: str | None = None,
    ) -> Mapping[str, Any]:
        if str(run_a_id) == str(run_b_id):
            raise LocalApplicationError(_ERROR, "run_a_id and run_b_id must identify different Runs")
        before = deepcopy(self._state().current_snapshot)
        left = self.show_survey_virtual_pretest(run_a_id, aggregate_result_id=aggregate_a_result_id)
        right = self.show_survey_virtual_pretest(run_b_id, aggregate_result_id=aggregate_b_result_id)

        mismatches: list[dict[str, Any]] = []
        if left.get("profile_response_binding") != "explicit" or right.get("profile_response_binding") != "explicit":
            mismatches.append({
                "pin": "profile_response_binding",
                "left": left.get("profile_response_binding"),
                "right": right.get("profile_response_binding"),
                "reason": "explicit profile-response lineage is required for revision comparison",
            })
        left_pins = left.get("comparison_pins") if isinstance(left.get("comparison_pins"), Mapping) else {}
        right_pins = right.get("comparison_pins") if isinstance(right.get("comparison_pins"), Mapping) else {}
        for pin in ("respondent_plan", "backend", "prompt_template"):
            if left_pins.get(pin) != right_pins.get(pin):
                mismatches.append({
                    "pin": pin,
                    "left": deepcopy(left_pins.get(pin)),
                    "right": deepcopy(right_pins.get(pin)),
                    "reason": "revision comparison requires the same pinned synthetic condition",
                })

        base = {
            "status": "OK",
            "object_type": "survey_virtual_pretest_comparison",
            "project_id": self._project_id,
            "run_refs": {"a": str(run_a_id), "b": str(run_b_id)},
            "instrument_refs": {"a": deepcopy(left["instrument_ref"]), "b": deepcopy(right["instrument_ref"])},
            "comparison_pins": {"a": deepcopy(dict(left_pins)), "b": deepcopy(dict(right_pins))},
            "synthetic_firewall": deepcopy(left["synthetic_firewall"]),
            "comparability": {
                "status": "COMPARABLE" if not mismatches else "NON_COMPARABLE",
                "mismatches": mismatches,
            },
            "research_state_mutation_performed": False,
            "validity_judgment_performed": False,
            "instrument_revision_performed": False,
        }
        if mismatches:
            after = deepcopy(self._state().current_snapshot)
            if before != after:
                raise LocalApplicationError(_ERROR, "Survey Virtual pretest comparison mutated Research State")
            return base

        left_rows = {str(item["profile"]["profile_id"]): item for item in left["respondents"]}
        right_rows = {str(item["profile"]["profile_id"]): item for item in right["respondents"]}
        if set(left_rows) != set(right_rows):
            raise LocalApplicationError(_ERROR, "comparable respondent plans produced different profile identities")

        per_profile: list[dict[str, Any]] = []
        free_text_changes: list[dict[str, Any]] = []
        for profile_id in left_rows:
            a = left_rows[profile_id]
            b = right_rows[profile_id]
            changes: list[dict[str, Any]] = []
            if a.get("generation_status") != b.get("generation_status"):
                changes.append({"kind": "generation_status", "before": a.get("generation_status"), "after": b.get("generation_status")})
            ar = a.get("response") if isinstance(a.get("response"), Mapping) else {}
            br = b.get("response") if isinstance(b.get("response"), Mapping) else {}
            if ar.get("validation_status") != br.get("validation_status"):
                changes.append({"kind": "validation_status", "before": ar.get("validation_status"), "after": br.get("validation_status")})
            aa = _answers_by_key(a)
            ba = _answers_by_key(b)
            for key in sorted(set(aa) | set(ba)):
                av = aa.get(key)
                bv = ba.get(key)
                if _answer_semantics(av) != _answer_semantics(bv):
                    change = {
                        "kind": "answer",
                        "response_key": key,
                        "before": deepcopy(av),
                        "after": deepcopy(bv),
                    }
                    changes.append(change)
                    qtype = str((bv or av or {}).get("question_type", ""))
                    if qtype == "free_text":
                        free_text_changes.append({"profile_id": profile_id, **deepcopy(change)})
            per_profile.append({
                "profile_id": profile_id,
                "profile_digest": a["profile"]["profile_digest"],
                "changed": bool(changes),
                "changes": changes,
            })

        left_issue_counts = _issue_code_counts(left["respondents"])
        right_issue_counts = _issue_code_counts(right["respondents"])
        left_states = _state_counts(left["respondents"])
        right_states = _state_counts(right["respondents"])
        state_changes = [
            {"response_key": key, "before": deepcopy(left_states.get(key, {})), "after": deepcopy(right_states.get(key, {}))}
            for key in sorted(set(left_states) | set(right_states))
            if left_states.get(key, {}) != right_states.get(key, {})
        ]

        aggregate_changes: list[dict[str, Any]] = []
        left_aggregate_ref = left.get("aggregate_result_ref")
        right_aggregate_ref = right.get("aggregate_result_ref")
        if isinstance(left_aggregate_ref, Mapping) and isinstance(right_aggregate_ref, Mapping):
            left_items = {
                _aggregate_key(item): item
                for item in _all_aggregate_items(self, left_aggregate_ref)
                if isinstance(item, Mapping)
            }
            right_items = {
                _aggregate_key(item): item
                for item in _all_aggregate_items(self, right_aggregate_ref)
                if isinstance(item, Mapping)
            }
            for key in sorted(set(left_items) | set(right_items)):
                before_item = _comparison_item(left_items.get(key))
                after_item = _comparison_item(right_items.get(key))
                if before_item != after_item:
                    aggregate_changes.append({
                        "item_key": key,
                        "analysis_type": str((after_item or before_item or {}).get("analysis_type", "")),
                        "before": before_item,
                        "after": after_item,
                    })

        frequency_changes = [item for item in aggregate_changes if item["analysis_type"] in {"frequency", "cross_tab"}]
        scale_changes = [item for item in aggregate_changes if item["analysis_type"] == "scale_summary"]
        aggregate_missingness_changes = [item for item in aggregate_changes if item["analysis_type"] == "missingness"]
        free_text_aggregate_changes = [item for item in aggregate_changes if item["analysis_type"] == "free_text_listing"]

        base["comparison"] = {
            "generation_summary": {"before": deepcopy(left["generation_summary"]), "after": deepcopy(right["generation_summary"])},
            "validation": {
                "issue_code_counts": {"before": left_issue_counts, "after": right_issue_counts},
                "branch_rule_violations": {
                    "before": left_issue_counts.get("SURVEY_RESPONSE_BRANCH_VIOLATION", 0),
                    "after": right_issue_counts.get("SURVEY_RESPONSE_BRANCH_VIOLATION", 0),
                },
            },
            "response_state_changes": state_changes,
            "missingness_changes": {
                "response_states": state_changes,
                "aggregate": aggregate_missingness_changes,
            },
            "response_distribution_changes": frequency_changes,
            "scale_distribution_changes": scale_changes,
            "per_profile_changes": per_profile,
            "aggregate_changes": aggregate_changes,
            "answer_pattern_signals": {
                "per_profile_changes": [row for row in per_profile if row["changed"]],
                "free_text_changes": free_text_changes,
                "free_text_aggregate_changes": free_text_aggregate_changes,
            },
        }
        after = deepcopy(self._state().current_snapshot)
        if before != after:
            raise LocalApplicationError(_ERROR, "Survey Virtual pretest comparison mutated Research State")
        return base
