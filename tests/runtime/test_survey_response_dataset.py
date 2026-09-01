from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    execution_payload,
    make_virtual_app,
)
from tests.runtime.test_survey_production import (
    NullResolver,
    adopt_rq,
    design_payload,
    initialize_workspace,
    instrument_payload,
    profile_provider,
    run_cli,
    state_signature,
)


def intake(questionnaire, *, origin="synthetic", responses, **extra):
    value = {
        "instrument_id": questionnaire["questionnaire_id"],
        "instrument_version": questionnaire["version"],
        "instrument_digest": questionnaire["content_digest"],
        "response_origin": origin,
        "epistemic_status": "SYNTHETIC_TEST_ONLY" if origin == "synthetic" else "EMPIRICAL",
        "responses": responses,
        "capture_origin": "test_probe",
    }
    value.update(extra)
    return value


def raw_response(
    response_id="SYN-R-1",
    participant_id="SYN-P-1",
    namespace="synthetic:test",
    *,
    role="Manager",
    answers=None,
):
    result = {
        "response_id": response_id,
        "participant_id": participant_id,
        "identity_namespace": namespace,
        "answers": {
            "role": role,
            "usefulness": 4,
            "count": 2,
            "notes": "bounded note",
        },
    }
    if answers is not None:
        result["answers"] = deepcopy(answers)
    return result


class SurveyResponseDatasetProductionTests(SurveyVirtualRunnerTestBase):
    def test_provider_neutral_normalize_capture_show_and_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            before = state_signature(app)
            payload = intake(questionnaire, responses=[raw_response()])

            normalized = facade.normalize_survey_response({
                "instrument_id": questionnaire["questionnaire_id"],
                "instrument_version": questionnaire["version"],
                "instrument_digest": questionnaire["content_digest"],
                "response_origin": "synthetic",
                "epistemic_status": "SYNTHETIC_TEST_ONLY",
                "response": raw_response(),
                "capture_origin": "test_probe",
            })
            response = normalized["normalization"]["canonical_response"]
            self.assertEqual(response["validation"]["status"], "accepted")
            self.assertEqual(next(item for item in response["answers"] if item["response_key"] == "role")["value"], "manager")
            self.assertTrue(any(item["code"] == "SURVEY_RESPONSE_LABEL_MAPPED" for item in response["normalization_events"]))

            captured = facade.capture_survey_response_dataset(payload)
            self.assertEqual(captured["accepted_count"], 1)
            self.assertEqual(captured["rejected_count"], 0)
            shown = facade.show_survey_response("SYN-R-1")
            self.assertEqual(shown["raw_input"]["answers"]["role"], "Manager")
            self.assertEqual(shown["response"]["instrument_ref"]["content_digest"], questionnaire["content_digest"])
            dataset_id = captured["dataset_id"]
            shown_dataset = facade.show_survey_response_dataset(dataset_id, limit=1)
            self.assertEqual(shown_dataset["dataset"]["response_count"], 1)
            self.assertEqual(shown_dataset["entries"][0]["kind"], "accepted_response")
            self.assertEqual(state_signature(app), before)
            app.close()

            reopened = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                reopened_response = reopened_facade.show_survey_response("SYN-R-1")
                reopened_dataset = reopened_facade.show_survey_response_dataset(dataset_id)
                self.assertEqual(reopened_response["response"]["content_digest"], shown["response"]["content_digest"])
                self.assertEqual(reopened_dataset["dataset"]["content_digest"], captured["content_digest"])
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_branching_missing_and_invalid_values_are_preserved_without_entering_valid_population(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            before = state_signature(app)
            records = [
                raw_response("SYN-SKIP", "SYN-P-SKIP", role="Contributor", answers={"role": "Contributor"}),
                raw_response("SYN-MISS", "SYN-P-MISS", role="Manager", answers={"role": "manager"}),
                raw_response("SYN-BAD", "SYN-P-BAD", answers={"role": "manager", "usefulness": 99}),
                raw_response("SYN-UNK", "SYN-P-UNK", answers={"role": {"state": "unknown"}}),
            ]
            captured = facade.capture_survey_response_dataset(intake(questionnaire, responses=records))
            self.assertEqual(captured["accepted_count"], 2)
            self.assertEqual(captured["rejected_count"], 2)
            self.assertIn("SURVEY_RESPONSE_REQUIRED_MISSING", captured["validation_summary"]["issue_code_counts"])
            self.assertIn("SURVEY_RESPONSE_OUT_OF_RANGE", captured["validation_summary"]["issue_code_counts"])
            skipped = facade.show_survey_response("SYN-SKIP")["response"]
            q2 = next(item for item in skipped["answers"] if item["response_key"] == "usefulness")
            self.assertEqual(q2["state"], "not_asked")
            self.assertEqual(state_signature(app), before)
            app.close()

    def test_real_namespace_is_future_compatible_and_mixed_origin_input_is_rejected_lane_only(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)

            real = raw_response(
                "R-EXTERNAL-1",
                "PARTICIPANT-1",
                namespace="real:future-adapter",
                role="Contributor",
                answers={"role": "contributor"},
            )
            real_capture = facade.capture_survey_response_dataset(
                intake(questionnaire, origin="real", responses=[real])
            )
            self.assertEqual(real_capture["accepted_count"], 1)
            self.assertEqual(facade.show_survey_response("R-EXTERNAL-1")["response"]["epistemic_status"], "EMPIRICAL")
            self.assertFalse(facade.show_survey_response("R-EXTERNAL-1")["response"]["verified_evidence_claimed"])

            synthetic = raw_response("SYN-OK", "SYN-P-OK", role="Contributor", answers={"role": "contributor"})
            wrong_namespace = raw_response("SYN-WRONG", "P-WRONG", namespace="real:wrong", role="Contributor", answers={"role": "contributor"})
            mixed = facade.capture_survey_response_dataset(
                intake(questionnaire, responses=[synthetic, wrong_namespace])
            )
            self.assertEqual(mixed["accepted_count"], 1)
            self.assertEqual(mixed["rejected_count"], 1)
            self.assertIn("SURVEY_RESPONSE_ORIGIN_MISMATCH", mixed["validation_summary"]["issue_code_counts"])
            app.close()

    def test_duplicate_response_id_rejected_and_dataset_digest_stable_across_input_order(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            first = raw_response("SYN-A", "SYN-P-A", role="Contributor", answers={"role": "contributor"})
            second = raw_response("SYN-B", "SYN-P-B", role="Contributor", answers={"role": "contributor"})
            a = facade.capture_survey_response_dataset(intake(questionnaire, responses=[first, second]))
            b = facade.capture_survey_response_dataset(intake(questionnaire, responses=[second, first]))
            self.assertEqual(a["content_digest"], b["content_digest"])

            duplicate = facade.capture_survey_response_dataset(intake(questionnaire, responses=[first, deepcopy(first)]))
            self.assertEqual(duplicate["accepted_count"], 1)
            self.assertEqual(duplicate["rejected_count"], 1)
            self.assertIn("SURVEY_RESPONSE_DUPLICATE_RECORD", duplicate["validation_summary"]["issue_code_counts"])
            app.close()

    def test_instrument_digest_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            value = intake(questionnaire, responses=[raw_response()])
            value["instrument_digest"] = "sha256:" + "0" * 64
            with self.assertRaises(LocalApplicationError) as caught:
                facade.capture_survey_response_dataset(value)
            self.assertEqual(caught.exception.code, "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001")
            app.close()

    def test_existing_action_submit_cli_exposes_capture_and_bounded_show(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = initialize_workspace(root)
            rq_id = adopt_rq(workspace)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                facade.capture_survey_design(design_payload(rq_id=rq_id))
                captured = facade.capture_survey_instrument(
                    instrument_payload(rq_id=rq_id)
                )
                questionnaire = facade.show_survey_instrument(
                    captured["instrument_id"], captured["version"]
                )["instrument"]["questionnaire"]

            action = {
                "action_type": "survey_response_dataset.capture",
                "payload": intake(questionnaire, responses=[raw_response()]),
                "actor_id": "HUMAN-SURVEY",
            }
            code, captured_dataset = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps(action),
            )
            self.assertEqual(code, 0)
            self.assertEqual(captured_dataset["accepted_count"], 1)

            show_action = {
                "action_type": "survey_response_dataset.show",
                "payload": {
                    "dataset_id": captured_dataset["dataset_id"],
                    "limit": 1,
                    "offset": 0,
                },
                "actor_id": "HUMAN-SURVEY",
            }
            code, shown = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps(show_action),
            )
            self.assertEqual(code, 0)
            self.assertEqual(shown["pagination"]["returned"], 1)
            self.assertEqual(shown["dataset"]["accepted_count"], 1)

    def test_virtual_standard_and_stress_flow_through_canonical_dataset_without_run_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_virtual_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            questionnaire = self._capture(facade)
            before = state_signature(app)

            standard = facade.submit_action({
                "action_type": "virtual_runner.survey.execute",
                "payload": execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                ),
                "actor_id": "HUMAN-VR",
            })
            standard_ds = standard["response_dataset"]
            self.assertEqual(standard_ds["response_origin"], "synthetic")
            self.assertEqual(standard_ds["epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertEqual(standard_ds["source_run_ids"], [standard["run_id"]])
            self.assertEqual(standard_ds["rejected_count"], 0)
            standard_artifacts = app.execution_store.artifacts_for(standard["run_id"])
            self.assertFalse(any(item.role == "survey_response_dataset" for item in standard_artifacts))

            stress = facade.submit_action({
                "action_type": "virtual_runner.survey.execute",
                "payload": execution_payload(
                    scenario="STRESS",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                    prior=(standard["run_id"],),
                ),
                "actor_id": "HUMAN-VR",
            })
            stress_ds = stress["response_dataset"]
            self.assertGreater(stress_ds["rejected_count"], 0)
            codes = set(stress_ds["validation_summary"]["issue_code_counts"])
            self.assertTrue({
                "SURVEY_RESPONSE_INVALID_CHOICE",
                "SURVEY_RESPONSE_REQUIRED_MISSING",
                "SURVEY_RESPONSE_BRANCH_VIOLATION",
                "SURVEY_RESPONSE_MALFORMED",
            } <= codes)
            shown = facade.show_survey_response_dataset(stress_ds["dataset_id"], limit=100)
            self.assertEqual(shown["dataset"]["source_run_ids"], [stress["run_id"]])
            self.assertEqual(state_signature(app), before)
            app.close()
