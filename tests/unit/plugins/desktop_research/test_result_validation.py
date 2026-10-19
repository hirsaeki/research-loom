"""Characterization tests for ``plugins/desktop_research/result_validation.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They start from the production golden and inaccessible Desktop Research flows
in ``tests.runtime.test_desktop_research`` and pin which stable error codes
``DesktopResearchResultValidator.validate`` returns for each tampering, plus
the capture-provenance diagnostic reasons and the module helpers.
"""

from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

from plugins.desktop_research import result_validation
from plugins.desktop_research.attempts import reconstruct_attempts
from plugins.desktop_research.digest import canonical_extension_digest
from plugins.desktop_research.result_validation import (
    DesktopResearchResultValidator,
    _add,
    _exact,
    _outputs,
    _utc,
)
from tests.runtime.test_desktop_research import Flow

PROVENANCE = "DR-CAPTURE-PROVENANCE-001"
CITATION = "DR-CITATION-001"
TRACE = "DR-SEARCH-TRACE-001"
BUDGET = "DR-CAPTURE-BUDGET-001"
COVERAGE = "DR-COVERAGE-001"
NULL = "DR-NULL-001"
GAP = "DR-EVIDENCE-GAP-001"
BINDING = "DR-RESULT-BINDING-001"


class _ArtifactStoreView:
    """Read-only view over a real store with per-artifact metadata/payload overrides."""

    def __init__(self, store, *, metadata=None, payloads=None) -> None:
        self._store = store
        self._metadata = metadata or {}
        self._payloads = payloads or {}

    def artifacts_for(self, run_id):
        return [
            self._metadata[item.artifact_id](item) if item.artifact_id in self._metadata else item
            for item in self._store.artifacts_for(run_id)
        ]

    def load_artifact(self, ref):
        if ref in self._payloads:
            override = self._payloads[ref]
            if isinstance(override, Exception):
                raise override
            return override(self._store.load_artifact(ref))
        return self._store.load_artifact(ref)


class _DiagnosticRecorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[tuple[str, str, dict]] = []
        self.fail = fail

    def store_diagnostic(self, run_id, kind, payload):
        self.records.append((run_id, kind, payload))
        if self.fail:
            raise RuntimeError("diagnostic store unavailable")


class HelperTests(unittest.TestCase):
    def test_utc_accepts_only_utc_offsets(self) -> None:
        self.assertTrue(_utc("2026-08-27T00:00:00Z"))
        self.assertTrue(_utc("2026-08-27T00:00:00+00:00"))
        self.assertFalse(_utc("2026-08-27T09:00:00+09:00"))
        self.assertFalse(_utc("2026-08-27T00:00:00"))
        self.assertFalse(_utc("not a timestamp"))

    def test_exact_locator_specificity(self) -> None:
        self.assertFalse(_exact(""))
        self.assertFalse(_exact("   "))
        self.assertFalse(_exact("https://example.test"))
        self.assertFalse(_exact("https://example.test/"))
        self.assertTrue(_exact("https://example.test/page"))
        self.assertTrue(_exact("https://example.test/?q=1"))
        self.assertTrue(_exact("http://example.test/#frag"))
        self.assertTrue(_exact("doi:10.1000/xyz"))
        self.assertTrue(_exact("ftp://example.test/"))

    def test_add_rejects_uncataloged_codes_and_deduplicates(self) -> None:
        codes: list[str] = []
        _add(codes, CITATION)
        _add(codes, CITATION)
        _add(codes, TRACE)
        self.assertEqual(codes, [CITATION, TRACE])
        with self.assertRaisesRegex(RuntimeError, "uncataloged Desktop Research error: DR-NOPE"):
            _add(codes, "DR-NOPE")

    def test_outputs_indexes_every_handoff_collection_by_kind_and_id(self) -> None:
        collections = {
            "observations": ("observation_id", "observation"),
            "source_captures": ("capture_id", "source_capture"),
            "evidence_candidates": ("evidence_candidate_id", "evidence_candidate"),
            "candidate_findings": ("candidate_finding_id", "candidate_finding"),
            "counterevidence": ("counterevidence_id", "counterevidence"),
            "conflicts": ("conflict_id", "conflict"),
            "unknowns": ("unknown_id", "unknown"),
            "evidence_gaps": ("gap_id", "evidence_gap"),
            "candidate_next_actions": ("proposal_id", "next_action"),
            "candidate_next_methods": ("proposal_id", "next_method"),
        }
        handoff = {
            "outputs": {
                name: [{field: f"ID-{kind}"}] for name, (field, kind) in collections.items()
            }
        }
        index = _outputs(handoff)
        self.assertEqual(set(index), {(kind, f"ID-{kind}") for _, kind in collections.values()})
        self.assertEqual(index[("unknown", "ID-unknown")], {"unknown_id": "ID-unknown"})


class ValidatorCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.golden = Flow(run_id="RUN-DR-UNIT-GOLDEN")
        cls.golden_handoff, cls.golden_extension = cls.golden.build_golden()
        cls.blocked = Flow(run_id="RUN-DR-UNIT-BLOCKED")
        cls.blocked_handoff, cls.blocked_extension = cls.blocked.build_inaccessible()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.golden.close()
        cls.blocked.close()

    def setUp(self) -> None:
        self.handoff = deepcopy(self.golden_handoff)
        self.extension = deepcopy(self.golden_extension)
        self.context_extension = deepcopy(self.golden.context_extension)
        self.flow = self.golden

    def use_blocked(self) -> None:
        self.handoff = deepcopy(self.blocked_handoff)
        self.extension = deepcopy(self.blocked_extension)
        self.context_extension = deepcopy(self.blocked.context_extension)
        self.flow = self.blocked

    def attempts(self) -> dict:
        return deepcopy(dict(reconstruct_attempts(self.flow.ops, self.flow.prepared.run.run_id)))

    def validate(
        self,
        *,
        refresh: bool = True,
        artifacts=None,
        diagnostics=None,
        run_id: str | None = None,
        context_pack=None,
    ) -> tuple[str, ...]:
        if refresh and isinstance(self.extension, dict):
            self.extension["extension_digest"] = canonical_extension_digest(self.extension)
        validator = DesktopResearchResultValidator(
            artifacts if artifacts is not None else self.flow.exec_store,
            self.flow.ops,
            diagnostics,
        )
        return validator.validate(
            self.handoff,
            self.extension,
            context_pack if context_pack is not None else self.flow.context,
            self.context_extension,
            run_id=run_id or self.flow.prepared.run.run_id,
        )

    def capture_reasons(self, **kwargs) -> tuple[tuple[str, ...], dict[str, list[str]]]:
        recorder = _DiagnosticRecorder()
        codes = self.validate(diagnostics=recorder, **kwargs)
        reasons: dict[str, list[str]] = {}
        for run_id, kind, payload in recorder.records:
            self.assertEqual(run_id, self.flow.prepared.run.run_id)
            self.assertEqual(kind, "desktop_research.capture_provenance_validation")
            self.assertEqual(payload["error_code"], PROVENANCE)
            reasons[payload["capture_id"]] = payload["reasons"]
        return codes, reasons

    def detail(self, index: int = 0) -> dict:
        return self.extension["source_capture_details"][index]


class AcceptanceAndBindingTests(ValidatorCase):
    def test_golden_and_inaccessible_flows_are_accepted(self) -> None:
        self.assertEqual(self.validate(), ())
        self.use_blocked()
        self.assertEqual(self.validate(), ())

    def test_valid_result_records_no_diagnostics(self) -> None:
        codes, reasons = self.capture_reasons()
        self.assertEqual((codes, reasons), ((), {}))

    def test_missing_extension_is_a_binding_error(self) -> None:
        self.extension = None
        self.assertEqual(self.validate(), (BINDING,))

    def test_schema_invalid_extension_short_circuits(self) -> None:
        del self.extension["null_results"]
        self.handoff["outputs"]["candidate_next_methods"] = []
        self.assertEqual(self.validate(), (BINDING,))

    def test_stale_extension_digest(self) -> None:
        self.extension["coverage_assessment"]["saturation"]["rationale"] = "edited"
        self.assertEqual(self.validate(refresh=False), ("DR-RESULT-DIGEST-001",))

    def test_binding_mismatches(self) -> None:
        cases = {
            "handoff_binding": lambda: self.extension["handoff_binding"].update(
                {"function_id": "other"}
            ),
            "capability_version": lambda: self.handoff["capability"].update(
                {"capability_version": "9.9.9"}
            ),
            "context_binding": lambda: self.context_extension["context_binding"].update(
                {"context_pack_digest": "sha256:" + "0" * 64}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.setUp()
                mutate()
                self.assertEqual(self.validate(), (BINDING,))

    def test_run_id_argument_must_match_handoff(self) -> None:
        codes = self.validate(run_id="RUN-DR-OTHER")
        self.assertEqual(codes[0], BINDING)
        self.assertIn(PROVENANCE, codes)


class CaptureProvenanceTests(ValidatorCase):
    def test_capture_detail_set_must_match_handoff_captures(self) -> None:
        self.handoff["outputs"]["source_captures"].append(
            dict(self.handoff["outputs"]["source_captures"][0], capture_id="CAP-EXTRA")
        )
        codes, reasons = self.capture_reasons()
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(reasons, {})

    def test_detail_without_handoff_capture(self) -> None:
        self.handoff["outputs"]["source_captures"] = self.handoff["outputs"]["source_captures"][:1]
        codes, reasons = self.capture_reasons()
        self.assertIn(PROVENANCE, codes)
        self.assertIn(CITATION, codes)
        self.assertEqual(
            reasons, {"CAP-2": ["capture detail has no matching Handoff source_capture"]}
        )

    def test_source_category_outside_allowlist(self) -> None:
        self.context_extension["allowed_source_categories"] = ["web"]
        codes, reasons = self.capture_reasons()
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(
            reasons,
            {
                "CAP-1": ["source_category is outside the Context allowlist"],
                "CAP-2": ["source_category is outside the Context allowlist"],
            },
        )

    def test_locator_and_timestamp_reasons(self) -> None:
        detail = self.detail(1)
        detail["exact_locator"] = "https://example.test/"
        detail["acquired_at"] = "2026-08-27T09:00:00+09:00"
        detail["original_capture"]["content_digest"] = "sha256:" + "f" * 64
        codes, reasons = self.capture_reasons()
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(
            reasons["CAP-2"],
            [
                "exact_locator does not match the Handoff locator",
                "acquired_at is not an RFC3339 UTC timestamp",
                "exact_locator is not sufficiently specific",
                "original_capture digest does not match Handoff source_capture",
                "original_capture metadata digest does not match declaration",
            ],
        )

    def test_unspecific_locator_shared_with_handoff(self) -> None:
        self.detail(0)["exact_locator"] = "https://example.test"
        self.handoff["outputs"]["source_captures"][0]["locator"] = "https://example.test"
        _, reasons = self.capture_reasons()
        self.assertEqual(reasons, {"CAP-1": ["exact_locator is not sufficiently specific"]})

    def test_missing_artifact_metadata(self) -> None:
        self.detail(0)["text_rendition"]["content_reference"] = "ART-MISSING"
        codes, reasons = self.capture_reasons()
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(reasons, {"CAP-1": ["text_rendition artifact metadata is missing"]})

    def test_metadata_mismatches_skip_payload_loading(self) -> None:
        ref = self.detail(0)["original_capture"]["content_reference"]
        view = _ArtifactStoreView(
            self.flow.exec_store,
            metadata={
                ref: lambda meta: replace(
                    meta,
                    run_id="RUN-OTHER",
                    role="other.role",
                    digest="sha256:" + "e" * 64,
                    media_type="application/pdf",
                    size=meta.size + 1,
                )
            },
            payloads={ref: AssertionError("payload must not be loaded")},
        )
        codes, reasons = self.capture_reasons(artifacts=view)
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(
            reasons,
            {
                "CAP-1": [
                    "original_capture artifact is bound to another Run",
                    "original_capture artifact role is incorrect",
                    "original_capture metadata digest does not match declaration",
                    "original_capture metadata media_type does not match declaration",
                    "original_capture metadata size does not match declaration",
                ]
            },
        )

    def test_payload_loading_failure(self) -> None:
        ref = self.detail(1)["text_rendition"]["content_reference"]
        view = _ArtifactStoreView(self.flow.exec_store, payloads={ref: OSError("gone")})
        codes, reasons = self.capture_reasons(artifacts=view)
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(reasons, {"CAP-2": ["text_rendition artifact loading failed: OSError"]})

    def test_stored_payload_mismatches(self) -> None:
        original_ref = self.detail(0)["original_capture"]["content_reference"]
        text_ref = self.detail(0)["text_rendition"]["content_reference"]
        view = _ArtifactStoreView(
            self.flow.exec_store,
            payloads={
                original_ref: lambda payload: replace(
                    payload, digest="sha256:" + "d" * 64, content=payload.content + b"!"
                ),
                text_ref: lambda payload: replace(
                    payload, content=b"\xff" * len(payload.content), media_type="text/html"
                ),
            },
        )
        codes, reasons = self.capture_reasons(artifacts=view)
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(
            reasons,
            {
                "CAP-1": [
                    "original_capture stored digest does not match declaration",
                    "original_capture stored byte length does not match declaration",
                    "text_rendition is not valid UTF-8",
                    "text_rendition media_type is not text/plain",
                ]
            },
        )

    def test_inline_text_must_match_stored_text(self) -> None:
        self.detail(0)["text_rendition"]["inline_text"] = "different text"
        codes, reasons = self.capture_reasons()
        self.assertEqual(codes, (PROVENANCE, CITATION))
        self.assertEqual(
            reasons, {"CAP-1": ["text_rendition inline_text does not match stored UTF-8 text"]}
        )

    def test_matching_inline_text_is_accepted(self) -> None:
        text_ref = self.detail(0)["text_rendition"]["content_reference"]
        stored = self.flow.exec_store.load_artifact(text_ref).content.decode("utf-8")
        self.detail(0)["text_rendition"]["inline_text"] = stored
        self.assertEqual(self.validate(), ())

    def test_diagnostic_store_failure_does_not_mask_codes(self) -> None:
        self.context_extension["allowed_source_categories"] = ["web"]
        recorder = _DiagnosticRecorder(fail=True)
        self.assertEqual(self.validate(diagnostics=recorder), (PROVENANCE, CITATION))
        self.assertEqual(len(recorder.records), 2)


class BudgetTests(ValidatorCase):
    def test_each_budget_limit(self) -> None:
        cases = {
            "max_acquired_source_captures": 1,
            "max_search_trace_entries": 2,
            "max_text_rendition_bytes": 100,
            "max_capture_artifacts": 3,
            "max_original_capture_bytes": 45,
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                self.setUp()
                self.context_extension["budget"][key] = value
                self.assertEqual(self.validate(), (BUDGET,))

    def test_limits_are_inclusive(self) -> None:
        self.context_extension["budget"].update(
            {
                "max_acquired_source_captures": 2,
                "max_search_trace_entries": 3,
                "max_text_rendition_bytes": 111,
                "max_capture_artifacts": 4,
                "max_original_capture_bytes": 46,
            }
        )
        self.assertEqual(self.validate(), ())

    def test_capture_artifact_limit_defaults_to_twice_capture_limit(self) -> None:
        del self.context_extension["budget"]["max_capture_artifacts"]
        self.assertEqual(self.validate(), ())

    def test_original_byte_limit_is_optional(self) -> None:
        del self.context_extension["budget"]["max_original_capture_bytes"]
        self.assertEqual(self.validate(), ())
        self.context_extension["budget"]["max_original_capture_bytes"] = None
        self.assertEqual(self.validate(), ())


class CitationTests(ValidatorCase):
    def citation(self, index: int = 0) -> dict:
        return self.extension["citation_details"][index]

    def test_citation_tampering(self) -> None:
        cases = {
            "duplicate id": lambda: self.citation(1).update({"citation_id": "CIT-1"}),
            "unknown output": lambda: self.citation(0).update({"handoff_output_id": "EVC-NOPE"}),
            "unknown capture": lambda: self.citation(0).update({"capture_id": "CAP-NOPE"}),
            "wrong basis": lambda: self.citation(0).update({"capture_id": "CAP-2"}),
            "text digest": lambda: self.citation(0).update(
                {"text_rendition_digest": "sha256:" + "c" * 64}
            ),
            "excerpt locator": lambda: self.citation(0).update(
                {"excerpt_locator": "https://example.test/source-a#other"}
            ),
            "excerpt text": lambda: self.citation(0).update({"excerpt": "not in the text"}),
            "required citation missing": lambda: self.extension["citation_details"].pop(),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.setUp()
                mutate()
                self.assertEqual(self.validate(), (CITATION,))

    def test_non_capture_basis_does_not_require_citation(self) -> None:
        self.handoff["outputs"]["counterevidence"][0]["source_basis"] = {
            "basis_type": "external_reference"
        }
        self.extension["citation_details"].pop()
        self.assertEqual(self.validate(), ())


class SearchTraceTests(ValidatorCase):
    def entry(self, index: int) -> dict:
        return self.extension["search_trace"]["entries"][index]

    def test_trace_entry_tampering(self) -> None:
        cases = {
            "duplicate entry id": lambda: self.entry(1).update({"trace_entry_id": "ATT-1"}),
            "unknown dimension": lambda: self.entry(0).update(
                {"coverage_dimension_ids": ["COV-SUPPORT", "COV-NOPE"]}
            ),
            "unknown related output": lambda: self.entry(0).update(
                {"related_handoff_output_ids": ["EVC-1", "NOPE"]}
            ),
            "unknown capture": lambda: self.entry(2).update({"source_capture_ids": ["CAP-NOPE"]}),
            "strategy mismatch": lambda: self.entry(0).update({"strategy": "something else"}),
            "outcome mismatch": lambda: self.entry(2).update({"outcome": "unavailable"}),
            "capture ids mismatch": lambda: self.entry(0).update({"source_capture_ids": []}),
            "unsuccessful ids": lambda: self.extension["search_trace"].update(
                {"unsuccessful_entry_ids": []}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.setUp()
                mutate()
                self.assertIn(TRACE, self.validate())

    def test_strategy_mismatch_is_trace_only(self) -> None:
        self.entry(0)["strategy"] = "something else"
        self.assertEqual(self.validate(), (TRACE,))

    def test_attempt_ledger_failure_is_a_trace_error(self) -> None:
        with patch.object(
            result_validation, "reconstruct_attempts", side_effect=ValueError("corrupt ledger")
        ):
            codes = self.validate()
        self.assertIn(TRACE, codes)
        self.assertIn(NULL, codes)

    def test_incomplete_attempt_is_a_trace_error(self) -> None:
        attempts = self.attempts()
        attempts["ATT-3"]["completed_at"] = None
        with patch.object(result_validation, "reconstruct_attempts", return_value=attempts):
            self.assertEqual(self.validate(), (TRACE,))

    def test_unrecorded_trace_entry_is_a_trace_error(self) -> None:
        attempts = self.attempts()
        del attempts["ATT-3"]
        with patch.object(result_validation, "reconstruct_attempts", return_value=attempts):
            codes = self.validate()
        self.assertEqual(codes[0], TRACE)
        self.assertIn(NULL, codes)

    def test_captured_attempt_must_reference_a_handoff_capture(self) -> None:
        attempts = self.attempts()
        attempts["ATT-1"]["resulting_capture_id"] = "CAP-NOPE"
        self.entry(0)["source_capture_ids"] = ["CAP-NOPE"]
        with patch.object(result_validation, "reconstruct_attempts", return_value=attempts):
            self.assertEqual(self.validate(), (TRACE,))


class NullResultTests(ValidatorCase):
    def null(self) -> dict:
        return self.extension["null_results"][0]

    def test_null_result_tampering(self) -> None:
        cases = {
            "duplicate id": lambda: self.extension["null_results"].append(deepcopy(self.null())),
            "unknown question": lambda: self.null().update({"question_ids": ["RQ-NOPE"]}),
            "unknown projection": lambda: self.null()["handoff_projection"].update(
                {"output_id": "OBS-NOPE"}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.setUp()
                mutate()
                self.assertEqual(self.validate(), (NULL,))

    def test_null_result_requires_a_no_relevant_source_attempt(self) -> None:
        attempts = self.attempts()
        attempts["ATT-3"]["outcome"] = "duplicate"
        self.entry_outcome("duplicate")
        with patch.object(result_validation, "reconstruct_attempts", return_value=attempts):
            self.assertEqual(self.validate(), (NULL,))

    def entry_outcome(self, outcome: str) -> None:
        self.extension["search_trace"]["entries"][2]["outcome"] = outcome


class GapAndCoverageTests(ValidatorCase):
    def test_evidence_gap_assessment_tampering(self) -> None:
        cases = {
            "missing": lambda: self.extension["evidence_gap_assessments"].clear(),
            "duplicate": lambda: self.extension["evidence_gap_assessments"].append(
                deepcopy(self.extension["evidence_gap_assessments"][0])
            ),
            "unknown dimension": lambda: self.extension["evidence_gap_assessments"][0].update(
                {"coverage_dimension_ids": ["COV-NOPE"]}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.setUp()
                mutate()
                self.assertEqual(self.validate(), (GAP,))

    def dimensions(self) -> list:
        return self.extension["coverage_assessment"]["dimensions"]

    def test_coverage_dimension_tampering(self) -> None:
        cases = {
            "missing dimension": lambda: self.dimensions().pop(),
            "duplicate dimension": lambda: self.dimensions().append(deepcopy(self.dimensions()[0])),
            "unknown trace entry": lambda: self.dimensions()[0].update(
                {"trace_entry_ids": ["ATT-NOPE"]}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.setUp()
                mutate()
                self.assertEqual(self.validate(), (COVERAGE,))

    def test_covered_dimension_requires_a_captured_attempt(self) -> None:
        self.use_blocked()
        self.dimensions()[1]["status"] = "covered"
        self.assertEqual(self.validate(), (COVERAGE,))

    def test_blocked_attempt_must_be_visible_or_limit_coverage(self) -> None:
        self.use_blocked()
        self.extension["search_trace"]["entries"][0]["related_handoff_output_ids"] = []
        self.assertEqual(self.validate(), ())
        self.dimensions()[0]["status"] = "covered"
        self.assertEqual(self.validate(), (COVERAGE,))


class StoppingTests(ValidatorCase):
    def stop(self) -> dict:
        return self.extension["coverage_assessment"]["stopping_recommendation"]

    def make_stop_acceptable(self) -> None:
        self.stop()["stop_recommended"] = True
        self.extension["evidence_gap_assessments"][0]["materiality"] = "non_material"
        self.extension["coverage_assessment"]["remaining_information_value"]["level"] = "low"

    def test_well_founded_stop_is_accepted(self) -> None:
        self.make_stop_acceptable()
        self.assertEqual(self.validate(), ())

    def test_source_count_only_basis(self) -> None:
        self.stop()["basis"] = ["source_count"]
        self.assertEqual(self.validate(), ("DR-STOP-BASIS-001",))

    def test_source_count_with_other_basis_is_allowed(self) -> None:
        self.stop()["basis"] = ["source_count", "coverage"]
        self.assertEqual(self.validate(), ())

    def test_stop_after_operational_termination(self) -> None:
        self.make_stop_acceptable()
        with patch.object(
            result_validation, "operational_terminations", return_value=({"reason": "budget"},)
        ):
            self.assertEqual(self.validate(), ("DR-STOP-BASIS-001",))

    def test_operational_termination_without_stop_is_allowed(self) -> None:
        with patch.object(
            result_validation, "operational_terminations", return_value=({"reason": "budget"},)
        ) as terminations:
            self.assertEqual(self.validate(), ())
        terminations.assert_not_called()

    def test_stop_with_material_or_unknown_gap(self) -> None:
        for materiality in ("material", "unknown"):
            with self.subTest(materiality=materiality):
                self.setUp()
                self.make_stop_acceptable()
                self.extension["evidence_gap_assessments"][0]["materiality"] = materiality
                self.assertEqual(self.validate(), ("DR-STOP-GAP-001",))

    def test_stop_with_high_or_unknown_remaining_information_value(self) -> None:
        for level in ("high", "unknown"):
            with self.subTest(level=level):
                self.setUp()
                self.make_stop_acceptable()
                self.extension["coverage_assessment"]["remaining_information_value"]["level"] = (
                    level
                )
                self.assertEqual(self.validate(), ("DR-STOP-RIV-001",))

    def test_next_method_ids_must_match_handoff(self) -> None:
        self.extension["candidate_next_method_ids"] = []
        self.assertEqual(self.validate(), ("DR-NEXT-METHOD-001",))


class CodeOrderTests(ValidatorCase):
    def test_codes_follow_validation_order(self) -> None:
        self.context_extension["allowed_source_categories"] = ["web"]
        self.context_extension["budget"]["max_search_trace_entries"] = 1
        self.extension["evidence_gap_assessments"][0]["coverage_dimension_ids"] = ["COV-NOPE"]
        self.extension["candidate_next_method_ids"] = []
        self.extension["coverage_assessment"]["stopping_recommendation"]["basis"] = ["source_count"]
        self.extension["handoff_binding"]["function_id"] = "other"
        self.assertEqual(
            self.validate(refresh=False),
            (
                "DR-RESULT-DIGEST-001",
                BINDING,
                PROVENANCE,
                BUDGET,
                CITATION,
                GAP,
                "DR-STOP-BASIS-001",
                "DR-NEXT-METHOD-001",
            ),
        )


if __name__ == "__main__":
    unittest.main()
