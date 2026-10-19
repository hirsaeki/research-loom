"""Characterization tests for ``plugins.local_application.virtual_runner.virtual_runner_inspection`` (#507).

They pin how ``show_run_stage`` decorates ``show_run`` results for Virtual
Runner Runs: pass-through for other capabilities and unfinished runs, the
single-result-artifact rule, unreadable or malformed artifacts, the projection
of the persisted extension, and the Survey response dataset / aggregate result
lookups (including the legacy by-source-run fallback). In-memory stand-ins
replace the execution store and the Survey stores.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from plugins.application_errors import LocalApplicationError
from plugins.local_application.virtual_runner.virtual_runner_inspection import (
    VirtualRunnerInspectionMixin,
    show_run_stage,
)

RESULT_ROLE = "survey_virtual.virtual_runner_result"
INSPECTION_CODE = "APPLICATION-RUN-INSPECTION-001"


class FakeExecutionStore:
    def __init__(self, artifacts=()) -> None:
        self.artifacts = list(artifacts)

    def artifacts_for(self, run_id):
        return [meta for meta, _content in self.artifacts]

    def load_artifact(self, artifact_id):
        content = next(
            content for meta, content in self.artifacts if meta.artifact_id == artifact_id
        )
        return SimpleNamespace(content=content)


class FakeResponseStore:
    def __init__(self, datasets=None, legacy=()) -> None:
        self.datasets = dict(datasets or {})
        self.legacy = list(legacy)
        self.calls: list[tuple] = []

    def load_dataset(self, project_id, dataset_id):
        self.calls.append(("load", project_id, dataset_id))
        return self.datasets.get(dataset_id)

    def find_datasets_by_source_run(self, project_id, run_id):
        self.calls.append(("legacy", project_id, run_id))
        return list(self.legacy)


class FakeAnalysisStore:
    def __init__(self, results=()) -> None:
        self.results = list(results)

    def find_results_by_dataset(self, project_id, dataset_id):
        return [item for item in self.results if item["dataset_id"] == dataset_id]


class BareFacade:
    _project_id = "PRJ-1"

    def __init__(self, artifacts=()) -> None:
        self._application = SimpleNamespace(execution_store=FakeExecutionStore(artifacts))


class SurveyFacade(BareFacade):
    def __init__(self, artifacts=(), *, response_store, analysis_store=None) -> None:
        super().__init__(artifacts)
        self.response_store = response_store
        self.analysis_store = analysis_store or FakeAnalysisStore()

    def _survey_response_store(self):
        return self.response_store

    def _survey_analysis_store(self):
        return self.analysis_store


class ResponseOnlyFacade(BareFacade):
    def __init__(self, artifacts=(), *, response_store) -> None:
        super().__init__(artifacts)
        self.response_store = response_store

    def _survey_response_store(self):
        return self.response_store


def meta(artifact_id="ART-1", role=RESULT_ROLE):
    return SimpleNamespace(artifact_id=artifact_id, role=role)


def extension(**overrides) -> dict:
    value = {
        "virtual_runner_result": {
            "scenario_class": "STANDARD",
            "completion_status": "complete",
            "synthetic_outputs": [{"id": "OUT-1"}],
            "unresolved_ambiguities": [],
            "execution_trace": [{"step": "generate"}],
        },
        "evidence_status": "SYNTHETIC_TEST_ONLY",
        "input_pins": {"instrument": {"id": "QNR-1"}},
        "synthetic_population": {"population_size": 2},
        "generation_provenance": {"generator": "structural"},
        "validation_failures": [],
        "preservation_events": [],
        "defects": [],
        "warnings": ["w"],
        "candidate_change_requests": [],
        "readiness_assessment": {"status": "CANDIDATE_BLOCKED"},
    }
    value.update(overrides)
    return value


def encoded(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def proceed_with(run):
    calls = []

    def proceed(run_id):
        calls.append(run_id)
        return {"run": run, "artifacts": []}

    proceed.calls = calls  # type: ignore[attr-defined]
    return proceed


VR_COMPLETED = {"capability_id": "virtual-runner", "status": "COMPLETED"}


class PassThroughTests(unittest.TestCase):
    def test_other_capability_or_missing_run_is_returned_unchanged(self):
        for run in (None, {"capability_id": "desktop-research", "status": "COMPLETED"}):
            with self.subTest(run=run):
                proceed = proceed_with(run)
                result = show_run_stage(BareFacade([(meta(), b"not json")]), proceed, "RUN-1")
                self.assertEqual(result, {"run": run, "artifacts": []})
                self.assertEqual(proceed.calls, ["RUN-1"])

    def test_unfinished_virtual_run_without_result_is_returned_unchanged(self):
        run = {"capability_id": "virtual-runner", "status": "RUNNING"}
        result = show_run_stage(BareFacade([(meta(role="other"), b"")]), proceed_with(run), "RUN-1")
        self.assertNotIn("virtual_runner", result)

    def test_stage_table(self):
        self.assertIs(VirtualRunnerInspectionMixin._STAGES["show_run"], show_run_stage)


class ResultArtifactRejectTests(unittest.TestCase):
    def assert_rejected(self, facade, run, message):
        with self.assertRaises(LocalApplicationError) as caught:
            show_run_stage(facade, proceed_with(run), "RUN-1")
        self.assertEqual(
            (caught.exception.code, caught.exception.message), (INSPECTION_CODE, message)
        )

    def test_completed_run_needs_exactly_one_result_artifact(self):
        message = "completed Virtual Runner Run must have exactly one persisted result artifact"
        self.assert_rejected(BareFacade(), VR_COMPLETED, message)
        two = [(meta("ART-1"), encoded(extension())), (meta("ART-2"), encoded(extension()))]
        self.assert_rejected(
            BareFacade(two), {"capability_id": "virtual-runner", "status": "FAILED"}, message
        )

    def test_unreadable_result_artifact(self):
        for content in (b"\xff\xfe", b"{not json"):
            with self.subTest(content=content):
                self.assert_rejected(
                    BareFacade([(meta(), content)]),
                    VR_COMPLETED,
                    "Virtual Runner result artifact is unreadable",
                )

    def test_non_object_result_artifact(self):
        self.assert_rejected(
            BareFacade([(meta(), encoded([1, 2]))]),
            VR_COMPLETED,
            "Virtual Runner result artifact is malformed",
        )

    def test_missing_or_mistyped_fields_are_reported_as_malformed(self):
        # #577: a structurally broken artifact is malformed, not a bare KeyError.
        def without(key):
            value = extension()
            del value[key]
            return value

        def without_result_key(key):
            value = extension()
            del value["virtual_runner_result"][key]
            return value

        cases = {
            "missing extension field": without("defects"),
            "missing virtual_runner_result": without("virtual_runner_result"),
            "missing result field": without_result_key("execution_trace"),
            "non-object virtual_runner_result": extension(virtual_runner_result=[1]),
            "non-object respondent_plan": extension(respondent_plan=[1]),
        }
        for name, value in cases.items():
            with self.subTest(name):
                self.assert_rejected(
                    BareFacade([(meta(), encoded(value))]),
                    VR_COMPLETED,
                    "Virtual Runner result artifact is malformed",
                )


class ProjectionTests(unittest.TestCase):
    def test_structural_projection_without_survey_stores(self):
        artifacts = [(meta("ART-X", role="other"), b""), (meta(), encoded(extension()))]
        result = show_run_stage(BareFacade(artifacts), proceed_with(VR_COMPLETED), "RUN-1")
        self.assertEqual(result["run"], VR_COMPLETED)
        self.assertEqual(
            result["virtual_runner"],
            {
                "execution_mode": "virtual",
                "scenario_class": "STANDARD",
                "evidence_status": "SYNTHETIC_TEST_ONLY",
                "completion_status": "complete",
                "input_pins": {"instrument": {"id": "QNR-1"}},
                "synthetic_population": {"population_size": 2},
                "generation_provenance": {"generator": "structural"},
                "generator_backend": "structural",
                "respondent_plan": None,
                "generation_attempts": [],
                "generation_summary": {
                    "requested": 0,
                    "generated": 0,
                    "valid": None,
                    "rejected": None,
                    "failed": 0,
                },
                "response_dataset_ref": None,
                "aggregate_result_ref": None,
                "synthetic_outputs": [{"id": "OUT-1"}],
                "validation_failures": [],
                "preservation_events": [],
                "defects": [],
                "warnings": ["w"],
                "unresolved_ambiguities": [],
                "candidate_change_requests": [],
                "readiness_assessment": {"status": "CANDIDATE_BLOCKED"},
                "execution_trace": [{"step": "generate"}],
                "research_state_mutation_performed": False,
                "real_execution_started": False,
            },
        )

    def test_unfinished_run_with_result_artifact_is_still_projected(self):
        run = {"capability_id": "virtual-runner", "status": "FAILED"}
        result = show_run_stage(
            BareFacade([(meta(), encoded(extension()))]), proceed_with(run), "RUN-1"
        )
        self.assertEqual(result["virtual_runner"]["completion_status"], "complete")

    def llm_extension(self):
        return extension(
            generator_backend="llm",
            respondent_plan={"profile_ids": ["SYN-PROFILE-A", "SYN-PROFILE-B", "SYN-PROFILE-C"]},
            generation_attempts=[
                {"profile_id": "SYN-PROFILE-A", "status": "generated"},
                {"profile_id": "SYN-PROFILE-B", "status": "generated"},
                {"profile_id": "SYN-PROFILE-C", "status": "failed"},
            ],
        )

    def test_llm_projection_with_dataset_and_latest_aggregate(self):
        dataset = {
            "dataset_id": "SRD-RUN-1",
            "content_digest": "sha256:ds",
            "accepted_count": "2",
            "rejected_count": 0,
        }
        response_store = FakeResponseStore({"SRD-RUN-1": dataset})
        analysis_store = FakeAnalysisStore(
            [
                {"dataset_id": "SRD-RUN-1", "aggregate_result_id": "AGG-1", "content_digest": "d1"},
                {"dataset_id": "SRD-RUN-1", "aggregate_result_id": "AGG-2", "content_digest": "d2"},
                {"dataset_id": "SRD-OTHER", "aggregate_result_id": "AGG-3", "content_digest": "d3"},
            ]
        )
        facade = SurveyFacade(
            [(meta(), encoded(self.llm_extension()))],
            response_store=response_store,
            analysis_store=analysis_store,
        )
        vr = show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")["virtual_runner"]
        self.assertEqual(vr["generator_backend"], "llm")
        self.assertEqual(
            vr["generation_summary"],
            {"requested": 3, "generated": 2, "valid": 2, "rejected": 0, "failed": 1},
        )
        self.assertEqual(
            vr["response_dataset_ref"], {"dataset_id": "SRD-RUN-1", "content_digest": "sha256:ds"}
        )
        self.assertEqual(
            vr["aggregate_result_ref"], {"aggregate_result_id": "AGG-2", "content_digest": "d2"}
        )
        self.assertEqual(response_store.calls, [("load", "PRJ-1", "SRD-RUN-1")])

    def test_dataset_without_aggregates(self):
        dataset = {
            "dataset_id": "SRD-RUN-1",
            "content_digest": "c",
            "accepted_count": 1,
            "rejected_count": 1,
        }
        facade = SurveyFacade(
            [(meta(), encoded(extension()))],
            response_store=FakeResponseStore({"SRD-RUN-1": dataset}),
        )
        vr = show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")["virtual_runner"]
        self.assertIsNone(vr["aggregate_result_ref"])
        self.assertEqual(vr["generation_summary"]["rejected"], 1)

    def test_legacy_dataset_fallback(self):
        legacy = {
            "dataset_id": "SRD-LEGACY",
            "content_digest": "c",
            "accepted_count": 1,
            "rejected_count": 0,
        }
        store = FakeResponseStore(legacy=[legacy])
        facade = ResponseOnlyFacade([(meta(), encoded(extension()))], response_store=store)
        vr = show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")["virtual_runner"]
        self.assertEqual(vr["response_dataset_ref"]["dataset_id"], "SRD-LEGACY")
        self.assertIsNone(vr["aggregate_result_ref"])
        self.assertEqual(
            store.calls, [("load", "PRJ-1", "SRD-RUN-1"), ("legacy", "PRJ-1", "RUN-1")]
        )

    def test_no_dataset_found(self):
        facade = SurveyFacade([(meta(), encoded(extension()))], response_store=FakeResponseStore())
        vr = show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")["virtual_runner"]
        self.assertIsNone(vr["response_dataset_ref"])
        self.assertIsNone(vr["generation_summary"]["valid"])

    def test_multiple_legacy_datasets_are_rejected(self):
        store = FakeResponseStore(legacy=[{"dataset_id": "A"}, {"dataset_id": "B"}])
        facade = SurveyFacade([(meta(), encoded(extension()))], response_store=store)
        with self.assertRaises(LocalApplicationError) as caught:
            show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")
        self.assertEqual(caught.exception.code, INSPECTION_CODE)
        self.assertEqual(
            caught.exception.message,
            "Virtual Runner Run resolves to multiple Survey response datasets",
        )

    def test_projection_is_a_deep_copy(self):
        value = extension()
        facade = BareFacade([(meta(), encoded(value))])
        first = show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")
        first["virtual_runner"]["warnings"].append("mutated")
        second = show_run_stage(facade, proceed_with(VR_COMPLETED), "RUN-1")
        self.assertEqual(second["virtual_runner"]["warnings"], ["w"])


if __name__ == "__main__":
    unittest.main()
