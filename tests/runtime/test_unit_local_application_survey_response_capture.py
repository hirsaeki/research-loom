"""Characterization tests for ``plugins/local_application/survey/survey_response_capture.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They pin the module helpers, ``SurveyResponseCaptureMixin`` Dataset capture
(accept/reject partitioning, duplicate handling, participant uniqueness and
REAL batch response reuse), single-response capture, and the Virtual Runner
Dataset capture/verified-reuse boundary, driven through a real
``LocalApplicationFacade`` built with the Survey Virtual Runner fixtures.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.survey import survey_response_capture
from plugins.local_application.survey.survey_response_capture import (
    SurveyResponseCaptureMixin,
    _canonical_raw,
    _issue,
    _raw_response_key,
    _real_response_identity,
    _real_response_provenance,
)
from plugins.local_survey_response_store import LocalSurveyResponseStoreError
from tests.runtime.survey_virtual_runner_test_support import (
    SurveyVirtualRunnerTestBase,
    execution_payload,
    make_virtual_app,
)
from tests.runtime.test_survey_production import state_signature
from tests.runtime.test_survey_response_dataset import intake, raw_response

REAL_FORMAT = "provider-neutral-json@0.1.0"
REUSE_REAL = "APPLICATION-SURVEY-REAL-INTAKE-REUSE-001"
REUSE_VIRTUAL = "APPLICATION-SURVEY-RESPONSE-REUSE-001"
RUN = "APPLICATION-SURVEY-RESPONSE-RUN-001"
DUPLICATE = "SURVEY_RESPONSE_DUPLICATE_RECORD"
DIGEST = "sha256:" + "a" * 64


class _StoreProxy:
    def __init__(self, store, **overrides) -> None:
        self._store = store
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._store, name)


class HelperTests(unittest.TestCase):
    def test_issue_includes_response_id_only_when_given(self) -> None:
        self.assertEqual(
            _issue("CODE", "message"),
            {"code": "CODE", "severity": "error", "message": "message"},
        )
        self.assertEqual(_issue("CODE", "m", response_id="")["code"], "CODE")
        self.assertNotIn("response_id", _issue("CODE", "m", response_id=""))
        self.assertEqual(_issue("CODE", "m", response_id="R-1")["response_id"], "R-1")

    def test_canonical_raw_is_sorted_compact_and_unicode_preserving(self) -> None:
        self.assertEqual(_canonical_raw({"b": 1, "a": ["é", None]}), '{"a":["é",null],"b":1}')

    def test_raw_response_key_requires_non_empty_strings(self) -> None:
        self.assertEqual(
            _raw_response_key({"identity_namespace": "ns", "response_id": "R"}), ("ns", "R")
        )
        for raw in (
            None,
            [],
            {"identity_namespace": "ns"},
            {"identity_namespace": "", "response_id": "R"},
            {"identity_namespace": "ns", "response_id": 1},
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(_raw_response_key(raw))

    def test_real_provenance_passes_through_other_formats_as_a_copy(self) -> None:
        source = {"intake_format": "other", "intake_file": "a.json", "nested": {"x": 1}}
        projected = _real_response_provenance(source)
        self.assertEqual(projected, source)
        projected["nested"]["x"] = 2
        self.assertEqual(source["nested"]["x"], 1)

    def test_real_provenance_drops_legacy_acquisition_fields(self) -> None:
        self.assertEqual(
            _real_response_provenance(
                {
                    "intake_format": REAL_FORMAT,
                    "intake_file": "batch.json",
                    "intake_file_digest": DIGEST,
                    "producer": "p",
                }
            ),
            {"intake_format": REAL_FORMAT, "producer": "p"},
        )
        self.assertEqual(
            _real_response_provenance({"intake_format": REAL_FORMAT}),
            {"intake_format": REAL_FORMAT},
        )

    def test_real_provenance_rejects_invalid_acquisition_fields(self) -> None:
        for extra in (
            {"intake_file": "batch.json"},
            {"intake_file_digest": DIGEST},
            {"intake_file": " ", "intake_file_digest": DIGEST},
            {"intake_file": 1, "intake_file_digest": DIGEST},
            {"intake_file": "batch.json", "intake_file_digest": "sha256:XYZ"},
            {"intake_file": "batch.json", "intake_file_digest": 7},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(LocalApplicationError) as caught:
                    _real_response_provenance({"intake_format": REAL_FORMAT, **extra})
                self.assertEqual(caught.exception.code, REUSE_REAL)
                self.assertEqual(
                    caught.exception.message, "legacy REAL response acquisition metadata is invalid"
                )

    def test_real_identity_ignores_ingest_metadata_and_acquisition(self) -> None:
        response = {
            "response_id": "R-1",
            "ingested_at": "2026-01-01T00:00:00Z",
            "content_digest": DIGEST,
            "registry_digest": DIGEST,
            "source_provenance": {
                "intake_format": REAL_FORMAT,
                "intake_file": "batch.json",
                "intake_file_digest": DIGEST,
            },
        }
        self.assertEqual(
            _real_response_identity(response),
            {"response_id": "R-1", "source_provenance": {"intake_format": REAL_FORMAT}},
        )
        self.assertIn("ingested_at", response)

    def test_dataset_capture_result_projects_public_fields(self) -> None:
        dataset = {
            "project_id": "PRJ-1",
            "dataset_id": "SRD-1",
            "content_digest": DIGEST,
            "registry_digest": DIGEST,
            "instrument_ref": {"id": "QNR-1"},
            "response_origin": "synthetic",
            "epistemic_status": "SYNTHETIC_TEST_ONLY",
            "response_count": 2,
            "accepted_count": 1,
            "rejected_count": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "validation_summary": {"issue_count": 1},
            "source_run_ids": [],
            "source_provenance": {},
            "captured_against": {"lineage_ref": "LIN-1"},
            "accepted_response_refs": ["not projected"],
        }
        result = SurveyResponseCaptureMixin._dataset_capture_result(dataset, status="X")
        self.assertEqual(result["status"], "X")
        self.assertNotIn("accepted_response_refs", result)
        self.assertFalse(result["research_state_mutation_performed"])
        self.assertEqual(result["accepted_count"], 1)
        result["instrument_ref"]["id"] = "changed"
        self.assertEqual(dataset["instrument_ref"]["id"], "QNR-1")


class _Base(SurveyVirtualRunnerTestBase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = make_virtual_app(temp.name)
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")
        self.questionnaire = self._capture(self.facade)

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(LocalApplicationError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


def _contributor(response_id, participant_id, namespace="synthetic:test"):
    return raw_response(
        response_id,
        participant_id,
        namespace=namespace,
        role="Contributor",
        answers={"role": "contributor"},
    )


class DatasetCaptureTests(_Base):
    def test_accepts_and_rejects_without_state_mutation(self) -> None:
        before = state_signature(self.app)
        captured = self.facade.capture_survey_response_dataset(
            intake(
                self.questionnaire,
                responses=[
                    _contributor("SYN-A", "SYN-P-A"),
                    raw_response(
                        "SYN-BAD", "SYN-P-BAD", answers={"role": "manager", "usefulness": 99}
                    ),
                ],
            )
        )
        self.assertEqual(captured["status"], "CAPTURED")
        self.assertTrue(captured["dataset_id"].startswith("SRD-"))
        self.assertEqual(captured["response_count"], 2)
        self.assertEqual(captured["accepted_count"], 1)
        self.assertEqual(captured["rejected_count"], 1)
        self.assertIn(
            "SURVEY_RESPONSE_OUT_OF_RANGE", captured["validation_summary"]["issue_code_counts"]
        )
        self.assertEqual(captured["source_run_ids"], [])
        self.assertEqual(captured["source_provenance"], {})
        self.assertFalse(captured["research_state_mutation_performed"])
        stored = self.facade._survey_response_store().load_dataset("PRJ-1", captured["dataset_id"])
        self.assertEqual(stored["capture_origin"], "test_probe")
        self.assertEqual(len(stored["rejected_response_refs"]), 1)
        self.assertEqual(
            stored["rejected_inputs"][0]["canonical_response_ref"],
            stored["rejected_response_refs"][0],
        )
        self.assertEqual(state_signature(self.app), before)

    def test_refs_are_sorted_and_digest_is_order_independent(self) -> None:
        first, second = _contributor("SYN-B", "SYN-P-B"), _contributor("SYN-A", "SYN-P-A")
        a = self.facade.capture_survey_response_dataset(
            intake(self.questionnaire, responses=[first, second])
        )
        b = self.facade.capture_survey_response_dataset(
            intake(self.questionnaire, responses=[second, first])
        )
        self.assertEqual(a["content_digest"], b["content_digest"])
        stored = self.facade._survey_response_store().load_dataset("PRJ-1", a["dataset_id"])
        self.assertEqual(
            [ref["response_id"] for ref in stored["accepted_response_refs"]], ["SYN-A", "SYN-B"]
        )

    def test_responses_must_be_an_array(self) -> None:
        error = self.assertCode(
            "APPLICATION-SURVEY-INPUT-001",
            self.facade.capture_survey_response_dataset,
            intake(self.questionnaire, responses={"not": "a list"}),
        )
        self.assertEqual(error.message, "responses must be an array")

    def test_duplicate_canonical_response_id_is_rejected_in_batch(self) -> None:
        record = _contributor("SYN-A", "SYN-P-A")
        captured = self.facade.capture_survey_response_dataset(
            intake(self.questionnaire, responses=[record, deepcopy(record)])
        )
        self.assertEqual((captured["accepted_count"], captured["rejected_count"]), (1, 1))
        stored = self.facade._survey_response_store().load_dataset("PRJ-1", captured["dataset_id"])
        rejected = stored["rejected_inputs"][0]
        self.assertNotIn("canonical_response_ref", rejected)
        self.assertEqual(rejected["issues"][-1]["code"], DUPLICATE)
        self.assertEqual(rejected["issues"][-1]["response_id"], "SYN-A")

    def test_duplicate_malformed_record_gets_a_duplicate_issue(self) -> None:
        malformed = {
            "response_id": "SYN-M",
            "identity_namespace": "synthetic:test",
            "participant_id": "SYN-P-M",
            "answers": "not an object",
        }
        captured = self.facade.capture_survey_response_dataset(
            intake(self.questionnaire, responses=[malformed, deepcopy(malformed)])
        )
        self.assertEqual((captured["accepted_count"], captured["rejected_count"]), (0, 2))
        stored = self.facade._survey_response_store().load_dataset("PRJ-1", captured["dataset_id"])
        duplicate_flags = sorted(
            any(issue["code"] == DUPLICATE for issue in item["issues"])
            for item in stored["rejected_inputs"]
        )
        self.assertEqual(duplicate_flags, [False, True])
        self.assertEqual(captured["validation_summary"]["issue_code_counts"][DUPLICATE], 1)

    def test_unique_participant_enforcement_rejects_the_second_response(self) -> None:
        def payload(prefix):
            return intake(
                self.questionnaire,
                responses=[
                    _contributor(f"{prefix}-A", "SYN-P-1"),
                    _contributor(f"{prefix}-B", "SYN-P-1"),
                ],
            )

        relaxed = self.facade._capture_dataset(payload("SYN-RELAXED"))
        self.assertEqual(relaxed["accepted_count"], 2)
        # The rejected canonical response is persisted, so it needs a fresh response_id.
        strict = self.facade._capture_dataset(
            payload("SYN-STRICT"), enforce_unique_participant=True
        )
        self.assertEqual((strict["accepted_count"], strict["rejected_count"]), (1, 1))
        self.assertIn(
            "SURVEY_RESPONSE_DUPLICATE_IDENTITY",
            strict["validation_summary"]["issue_code_counts"],
        )

    def test_explicit_dataset_id_is_used(self) -> None:
        captured = self.facade._capture_dataset(
            intake(self.questionnaire, responses=[_contributor("SYN-A", "SYN-P-A")]),
            dataset_id="SRD-EXPLICIT",
        )
        self.assertEqual(captured["dataset_id"], "SRD-EXPLICIT")

    def test_dataset_validation_failure_is_translated(self) -> None:
        with patch.object(
            survey_response_capture, "validate_dataset", side_effect=ValueError("bad dataset")
        ):
            error = self.assertCode(
                "APPLICATION-SURVEY-RESPONSE-DATASET-001",
                self.facade.capture_survey_response_dataset,
                intake(self.questionnaire, responses=[]),
            )
        self.assertEqual(error.message, "bad dataset")

    def test_store_capture_error_is_translated(self) -> None:
        def fail(*_args):
            raise LocalSurveyResponseStoreError("STORE-X", "denied")

        proxy = _StoreProxy(self.facade._survey_response_store(), capture_dataset=fail)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            self.assertCode(
                "STORE-X",
                self.facade.capture_survey_response_dataset,
                intake(self.questionnaire, responses=[]),
            )

    def test_state_change_during_capture_is_reported(self) -> None:
        real = survey_response_capture._snapshot
        calls = {"n": 0}

        def drifting(state):
            calls["n"] += 1
            value = real(state)
            return {**value, "snapshot_ref": "DRIFT"} if calls["n"] == 3 else value

        with patch.object(survey_response_capture, "_snapshot", side_effect=drifting):
            self.assertCode(
                "APPLICATION-SURVEY-STATE-MUTATION-001",
                self.facade.capture_survey_response_dataset,
                intake(self.questionnaire, responses=[]),
            )


class SingleResponseCaptureTests(_Base):
    def _payload(self, response):
        value = intake(self.questionnaire, responses=[])
        value.pop("responses")
        value["response"] = response
        return value

    def test_wraps_one_response_and_echoes_its_id(self) -> None:
        result = self.facade.capture_survey_response(
            self._payload(_contributor("SYN-ONE", "SYN-P-ONE"))
        )
        self.assertEqual(result["response_id"], "SYN-ONE")
        self.assertEqual((result["response_count"], result["accepted_count"]), (1, 1))

    def test_unidentifiable_response_echoes_none(self) -> None:
        result = self.facade.capture_survey_response(self._payload("not a mapping"))
        self.assertIsNone(result["response_id"])
        self.assertEqual(result["rejected_count"], 1)
        result = self.facade.capture_survey_response(self._payload({"response_id": 5}))
        self.assertIsNone(result["response_id"])

    def test_dataset_only_field_is_unknown(self) -> None:
        payload = self._payload(_contributor("SYN-ONE", "SYN-P-ONE"))
        payload["responses"] = []
        self.assertCode(
            "APPLICATION-SURVEY-INPUT-001", self.facade.capture_survey_response, payload
        )


class RealBatchReuseTests(_Base):
    NAMESPACE = "real:test"

    def _payload(self, responses, **provenance):
        return intake(
            self.questionnaire,
            origin="real",
            responses=responses,
            capture_origin="survey_real_intake",
            source_provenance={"intake_format": REAL_FORMAT, **provenance},
        )

    def _record(self, role="contributor"):
        return raw_response(
            "R-1", "P-1", namespace=self.NAMESPACE, role=role, answers={"role": role}
        )

    def _stored_response(self):
        return self.facade.show_survey_response("R-1", identity_namespace=self.NAMESPACE)[
            "response"
        ]

    def test_reuse_requires_the_real_file_intake_boundary(self) -> None:
        good = self._payload([self._record()])
        cases = (
            intake(self.questionnaire, responses=[]),
            {**good, "capture_origin": "operator_conversation"},
            {**good, "source_provenance": {"intake_format": "other"}},
        )
        for payload in cases:
            with self.subTest(payload=payload.get("capture_origin")):
                error = self.assertCode(
                    REUSE_REAL, self.facade._capture_dataset, payload, reuse_real_responses=True
                )
                self.assertEqual(
                    error.message, "batch response reuse requires the REAL file intake boundary"
                )

    def test_identical_answer_is_reused_across_batches(self) -> None:
        first = self.facade._capture_dataset(
            self._payload([self._record()], batch="B1"), reuse_real_responses=True
        )
        stored = self._stored_response()
        self.assertEqual(stored["source_provenance"], {"intake_format": REAL_FORMAT})
        self.assertEqual(first["source_provenance"]["batch"], "B1")
        second = self.facade._capture_dataset(
            self._payload([self._record()], batch="B2"), reuse_real_responses=True
        )
        self.assertEqual(second["status"], "CAPTURED")
        self.assertNotEqual(second["dataset_id"], first["dataset_id"])
        self.assertEqual(second["accepted_count"], 1)
        self.assertEqual(self._stored_response()["ingested_at"], stored["ingested_at"])

    def test_changed_answer_for_existing_identity_fails(self) -> None:
        self.facade._capture_dataset(self._payload([self._record()]), reuse_real_responses=True)
        error = self.assertCode(
            DUPLICATE,
            self.facade._capture_dataset,
            self._payload([self._record(role="manager")]),
            reuse_real_responses=True,
        )
        self.assertEqual(
            error.message,
            "immutable Survey response_id already exists with different content: R-1",
        )

    def test_malformed_record_for_existing_identity_fails(self) -> None:
        self.facade._capture_dataset(self._payload([self._record()]), reuse_real_responses=True)
        malformed = {
            "response_id": "R-1",
            "identity_namespace": self.NAMESPACE,
            "participant_id": "P-1",
            "answers": "oops",
        }
        self.assertCode(
            DUPLICATE,
            self.facade._capture_dataset,
            self._payload([malformed]),
            reuse_real_responses=True,
        )

    def test_duplicates_within_a_new_batch_stay_visible_rejections(self) -> None:
        captured = self.facade._capture_dataset(
            self._payload([self._record(), self._record()]), reuse_real_responses=True
        )
        self.assertEqual((captured["accepted_count"], captured["rejected_count"]), (1, 1))

    def test_store_error_while_loading_existing_answers_is_translated(self) -> None:
        def fail(*_args):
            raise LocalSurveyResponseStoreError("LOAD-X", "unreadable")

        proxy = _StoreProxy(self.facade._survey_response_store(), load_responses=fail)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            self.assertCode(
                "LOAD-X",
                self.facade._capture_dataset,
                self._payload([self._record()]),
                reuse_real_responses=True,
            )


class VirtualRunDatasetTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        result = self.facade.submit_action(
            {
                "action_type": "virtual_runner.survey.execute",
                "payload": execution_payload(
                    scenario="STANDARD",
                    instrument_version=self.questionnaire["version"],
                    instrument_digest=self.questionnaire["content_digest"],
                ),
                "actor_id": "HUMAN-VR",
            }
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        self.run_id = result["run_id"]
        self.first = result["response_dataset"]
        self.instrument_ref = {
            "id": self.questionnaire["questionnaire_id"],
            "version": self.questionnaire["version"],
            "content_digest": self.questionnaire["content_digest"],
        }
        self.store = self.facade._survey_response_store()

    def _capture_run(self, run_id=None):
        return self.facade.capture_virtual_run_response_dataset(
            run_id or self.run_id, instrument_ref=self.instrument_ref
        )

    def test_runner_capture_binds_the_response_artifact(self) -> None:
        self.assertEqual(self.first["status"], "CAPTURED")
        self.assertEqual(self.first["dataset_id"], f"SRD-{self.run_id}")
        self.assertEqual(self.first["source_run_ids"], [self.run_id])
        provenance = self.first["source_provenance"]
        self.assertEqual(provenance["producer"], "survey_virtual_runner.structural@0.1.0")
        self.assertEqual(provenance["response_artifact_id"], f"ART-VR-RESP-{self.run_id}")
        self.assertEqual(provenance["scenario_class"], "STANDARD")
        self.assertEqual(provenance["generator_backend"], "structural")

    def test_repeat_capture_reuses_the_verified_dataset(self) -> None:
        reused = self._capture_run()
        self.assertEqual(reused["status"], "ALREADY_CAPTURED")
        for key in ("dataset_id", "content_digest", "registry_digest", "created_at"):
            self.assertEqual(reused[key], self.first[key])

    def test_fresh_capture_when_no_dataset_is_stored(self) -> None:
        proxy = _StoreProxy(self.store, load_dataset=lambda *_args: None)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            with self.assertRaises(LocalApplicationError) as caught:
                self._capture_run()
        # The fresh-capture path rebuilds the same identity, which the store refuses.
        self.assertEqual(caught.exception.code, "SURVEY-RESPONSE-DATASET-IMMUTABLE-001")

    def test_unknown_or_foreign_run_is_rejected(self) -> None:
        error = self.assertCode(RUN, self._capture_run, "RUN-UNKNOWN")
        self.assertEqual(error.message, "Virtual Runner source Run was not found")
        foreign = SimpleNamespace(project_ref="PRJ-OTHER")
        with patch.object(self.app.execution_store, "load_run", return_value=foreign):
            self.assertCode(RUN, self._capture_run)

    def test_incomplete_or_non_virtual_run_is_rejected(self) -> None:
        run = self.app.execution_store.load_run(self.run_id)
        for status, mode in (("RUNNING", "virtual"), ("COMPLETED", "real")):
            fake = SimpleNamespace(project_ref=run.project_ref, status=status, execution_mode=mode)
            with self.subTest(status=status, mode=mode):
                with patch.object(self.app.execution_store, "load_run", return_value=fake):
                    error = self.assertCode(RUN, self._capture_run)
                self.assertEqual(
                    error.message,
                    "Survey response Dataset can only be captured from a completed virtual Run",
                )

    def test_wrong_instrument_pin_is_rejected(self) -> None:
        self.instrument_ref = {**self.instrument_ref, "content_digest": "sha256:" + "0" * 64}
        self.assertCode("APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001", self._capture_run)

    def _artifacts(self, mutate):
        artifacts = tuple(self.app.execution_store.artifacts_for(self.run_id))
        return patch.object(
            self.app.execution_store,
            "artifacts_for",
            return_value=tuple(mutate(item) for item in artifacts),
        )

    def test_missing_or_misrolled_response_artifact_is_rejected(self) -> None:
        for mutate in (
            lambda item: replace(item, artifact_id=item.artifact_id + "-X"),
            lambda item: replace(item, role="survey_virtual.other"),
        ):
            with self._artifacts(mutate):
                error = self.assertCode(RUN, self._capture_run)
            self.assertEqual(
                error.message, "Virtual Runner response artifact is missing or has the wrong role"
            )

    def test_artifact_instrument_digest_mismatch_is_rejected(self) -> None:
        def mutate(item):
            provenance = {**dict(item.provenance), "instrument_digest": "sha256:" + "1" * 64}
            return replace(item, provenance=provenance)

        with self._artifacts(mutate):
            self.assertCode("APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001", self._capture_run)

    def test_unreadable_or_off_contract_batch_is_rejected(self) -> None:
        cases = (
            (b"\xff", "Virtual Runner response artifact is not valid UTF-8 JSON"),
            (b"{not json", "Virtual Runner response artifact is not valid UTF-8 JSON"),
            (
                b"[]",
                "Virtual Runner response artifact does not satisfy the PR41 response batch boundary",
            ),
            (
                json.dumps(
                    {
                        "object_type": "survey_virtual_response_batch",
                        "evidence_status": "EMPIRICAL",
                        "responses": [],
                    }
                ).encode(),
                "Virtual Runner response artifact does not satisfy the PR41 response batch boundary",
            ),
        )
        for content, message in cases:
            with self.subTest(content=content[:12]):
                with patch.object(
                    self.app.execution_store,
                    "load_artifact",
                    return_value=SimpleNamespace(content=content),
                ):
                    error = self.assertCode(RUN, self._capture_run)
                self.assertEqual(error.message, message)

    def test_dataset_lookup_store_error_is_translated(self) -> None:
        def fail(*_args):
            raise LocalSurveyResponseStoreError("DS-X", "unreadable")

        proxy = _StoreProxy(self.store, load_dataset=fail)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            self.assertCode("DS-X", self._capture_run)

    def _reuse_error(self, *, dataset=None, load_responses=None):
        stored = self.store.load_dataset("PRJ-1", self.first["dataset_id"])
        overrides = {"load_dataset": lambda *_args: deepcopy(dataset or stored)}
        if load_responses is not None:
            overrides["load_responses"] = load_responses
        proxy = _StoreProxy(self.store, **overrides)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            return self.assertCode(REUSE_VIRTUAL, self._capture_run)

    def test_reuse_rejects_identity_mismatches(self) -> None:
        stored = self.store.load_dataset("PRJ-1", self.first["dataset_id"])
        for field, value in (
            ("project_id", "PRJ-OTHER"),
            ("dataset_id", "SRD-OTHER"),
            ("response_origin", "real"),
            ("epistemic_status", "EMPIRICAL"),
            ("source_run_ids", ["RUN-OTHER"]),
            ("capture_origin", "test_probe"),
            ("response_count", 0),
        ):
            with self.subTest(field=field):
                error = self._reuse_error(dataset={**stored, field: value})
                self.assertEqual(
                    error.message,
                    "existing SurveyResponseDataset does not match the requested Virtual Runner identity",
                )

    def test_reuse_rejects_incomplete_response_set(self) -> None:
        def partial(project_id, keys):
            values = self.store.load_responses(project_id, keys)
            values.pop(next(iter(values)))
            return values

        error = self._reuse_error(load_responses=partial)
        self.assertEqual(error.message, "existing SurveyResponseDataset response set is incomplete")

    def test_reuse_rejects_raw_content_drift(self) -> None:
        def drifted(project_id, keys):
            values = self.store.load_responses(project_id, keys)
            values[next(iter(values))]["raw_input"]["tampered"] = True
            return values

        error = self._reuse_error(load_responses=drifted)
        self.assertEqual(
            error.message,
            "existing SurveyResponseDataset raw response content does not match the producer artifact",
        )

    def test_reuse_rejects_canonical_binding_drift(self) -> None:
        for mutate in (
            lambda response: response.update({"content_digest": "sha256:" + "0" * 64}),
            lambda response: response.update({"source_run_id": "RUN-OTHER"}),
            lambda response: response["source_provenance"].update({"scenario_class": "STRESS"}),
        ):

            def tampered(project_id, keys, mutate=mutate):
                values = self.store.load_responses(project_id, keys)
                mutate(values[next(iter(values))]["response"])
                return values

            with self.subTest(mutate=mutate):
                error = self._reuse_error(load_responses=tampered)
                self.assertEqual(
                    error.message,
                    "existing SurveyResponseDataset canonical response binding does not match the producer artifact",
                )

    def test_reuse_translates_store_errors(self) -> None:
        def fail(*_args):
            raise LocalSurveyResponseStoreError("RESP-X", "unreadable")

        stored = self.store.load_dataset("PRJ-1", self.first["dataset_id"])
        proxy = _StoreProxy(self.store, load_dataset=lambda *_a: stored, load_responses=fail)
        with patch.object(self.facade, "_survey_response_store", return_value=proxy):
            self.assertCode("RESP-X", self._capture_run)


if __name__ == "__main__":
    unittest.main()
