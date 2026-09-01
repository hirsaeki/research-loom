from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.desktop_research import DesktopResearchResultValidator
from plugins.local_execution_store import LocalExecutionStoreConfig, LocalExecutionStoreError
from test_desktop_research import Flow
from test_external_desktop_research_intake import (
    ExternalDesktopResearchIntakeTests,
    golden_submission,
    refresh,
)
from test_external_desktop_research_intake_atomicity import (
    ExternalDesktopResearchAtomicityTests,
)


class DesktopResearchRetentionTests(unittest.TestCase):
    def test_oversized_original_uses_managed_payload_and_public_reads_hide_locator(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=32,
                )
                run_id = helper.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 2,
                        "max_capture_artifacts": 4,
                        "max_original_capture_bytes": 64,
                        "max_text_rendition_bytes": 16,
                    },
                )
                original_bytes = b"0123456789-large-original"
                raw, text = helper.write_pair(root, "large", original_bytes, b"quote")
                captured = facade.capture_external_source(
                    run_id,
                    helper.capture_input("CAP-LARGE", raw, text),
                )["capture"]

                artifacts = app.execution_store.artifacts_for(run_id)
                original = next(
                    item for item in artifacts
                    if item.role == "desktop_research.original_capture"
                )
                self.assertEqual(original.size, len(original_bytes))
                self.assertEqual(
                    original.digest,
                    "sha256:" + hashlib.sha256(original_bytes).hexdigest(),
                )
                self.assertTrue(original.storage_locator.startswith("external-original://sha256/"))
                self.assertEqual(
                    app.execution_store.load_artifact(original.artifact_id).content,
                    original_bytes,
                )
                self.assertEqual(
                    captured["original_capture"]["content_digest"],
                    original.digest,
                )

                shown = facade.show_run(run_id)
                self.assertNotIn("storage_locator", str(shown))
                materials = facade.list_external_materials(limit=10)
                self.assertNotIn("storage_locator", str(materials))
                self.assertEqual(materials["materials"][0]["original_digest"], original.digest)
            finally:
                facade.close()

    def test_large_original_same_digest_groups_across_runs(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=32,
                )
                policy = {
                    "max_acquired_source_captures": 2,
                    "max_capture_artifacts": 4,
                    "max_original_capture_bytes": 128,
                    "max_text_rendition_bytes": 32,
                }
                run_a = helper.prepare(facade, policy)
                run_b = helper.prepare(facade, policy)
                content = b"same-large-original-bytes"
                raw_a, text_a = helper.write_pair(root, "same-a", content, b"text-a")
                raw_b, text_b = helper.write_pair(root, "same-b", content, b"text-b")
                facade.capture_external_source(
                    run_a,
                    helper.capture_input("CAP-A", raw_a, text_a),
                )
                facade.capture_external_source(
                    run_b,
                    helper.capture_input("CAP-B", raw_b, text_b),
                )

                inventory = facade.list_external_materials(limit=10)
                self.assertEqual(len(inventory["materials"]), 1)
                material = inventory["materials"][0]
                self.assertEqual(set(material["run_ids"]), {run_a, run_b})
                self.assertEqual(len(material["captures"]), 2)
            finally:
                facade.close()

    def test_explicit_original_budget_rejects_without_partial_capture(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=32,
                )
                run_id = helper.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 1,
                        "max_capture_artifacts": 2,
                        "max_original_capture_bytes": 12,
                        "max_text_rendition_bytes": 16,
                    },
                )
                raw, text = helper.write_pair(root, "too-large", b"x" * 13, b"quote")
                with self.assertRaises(Exception):
                    facade.capture_external_source(
                        run_id,
                        helper.capture_input("CAP-TOO-LARGE", raw, text),
                    )
                self.assertEqual(app.execution_store.artifacts_for(run_id), ())
                self.assertFalse((app.execution_store.root / "large-originals").exists())
            finally:
                facade.close()

    def test_failed_second_metadata_write_preserves_preexisting_large_payload(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=32,
                )
                policy = {
                    "max_acquired_source_captures": 1,
                    "max_capture_artifacts": 2,
                    "max_original_capture_bytes": 128,
                    "max_text_rendition_bytes": 32,
                }
                content = b"preexisting-large-original"
                run_a = helper.prepare(facade, policy)
                raw_a, text_a = helper.write_pair(root, "preexisting-a", content, b"text-a")
                facade.capture_external_source(
                    run_a,
                    helper.capture_input("CAP-A", raw_a, text_a),
                )
                original_a = next(
                    item
                    for item in app.execution_store.artifacts_for(run_a)
                    if item.role == "desktop_research.original_capture"
                )
                payload_path = app.execution_store._locator_path(
                    original_a.storage_locator,
                    original_a.digest,
                )
                self.assertTrue(payload_path.exists())

                run_b = helper.prepare(facade, policy)
                raw_b, text_b = helper.write_pair(root, "preexisting-b", content, b"text-b")
                real_register = app.execution_store._register_output_artifact_in_transaction
                calls = 0

                def fail_second(artifact):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise LocalExecutionStoreError("injected metadata failure")
                    return real_register(artifact)

                with patch.object(
                    app.execution_store,
                    "_register_output_artifact_in_transaction",
                    side_effect=fail_second,
                ):
                    with self.assertRaises(Exception):
                        facade.capture_external_source(
                            run_b,
                            helper.capture_input("CAP-B", raw_b, text_b),
                        )

                self.assertEqual(app.execution_store.artifacts_for(run_b), ())
                self.assertTrue(payload_path.exists())
                self.assertEqual(
                    app.execution_store.load_artifact(original_a.artifact_id).content,
                    content,
                )
            finally:
                facade.close()

    def test_missing_coverage_is_unknown_and_newline_citation_validates_candidate_only(self):
        helper = ExternalDesktopResearchIntakeTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                run_id = helper.prepare(facade)["run_id"]
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                })
                raw = root / "captures/raw/source-a.html"
                text = root / "captures/text/source-a.txt"
                raw.parent.mkdir(parents=True, exist_ok=True)
                text.parent.mkdir(parents=True, exist_ok=True)
                original_bytes = b"original"
                text_bytes = b"Source A contains the exact supporting\nexcerpt used here."
                raw.write_bytes(original_bytes)
                text.write_bytes(text_bytes)
                captured = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1",
                    "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                })["capture"]
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "outcome": "source_captured",
                    "resulting_capture_id": "CAP-1",
                })
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                })
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "outcome": "no_relevant_source",
                })
                before = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                handoff, extension = golden_submission(app, run_id, captured)
                raw_excerpt = extension["citation_details"][0]["excerpt"]
                original_digest = captured["original_capture"]["content_digest"]
                text_digest = captured["text_rendition"]["content_digest"]
                extension["coverage_assessment"]["dimensions"] = [
                    item
                    for item in extension["coverage_assessment"]["dimensions"]
                    if item["dimension_id"] != "COV-COUNTER"
                ]
                refresh(extension, "extension_digest")

                result = facade.collect_external(
                    run_id,
                    {"handoff": handoff, "extension": extension},
                )
                proposal = result["execution_result"]["state_delta_proposal"]
                after = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                dimensions = proposal["provenance"]["desktop_research"]["coverage_assessment"]["dimensions"]
                counter = next(item for item in dimensions if item["dimension_id"] == "COV-COUNTER")
                self.assertEqual(counter["status"], "unknown")
                self.assertTrue(proposal["candidate_only"])
                self.assertEqual(extension["citation_details"][0]["excerpt"], raw_excerpt)
                self.assertEqual(
                    captured["original_capture"]["content_digest"],
                    original_digest,
                )
                self.assertEqual(captured["text_rendition"]["content_digest"], text_digest)
                artifacts = app.execution_store.artifacts_for(run_id)
                original = next(item for item in artifacts if item.role == "desktop_research.original_capture")
                rendition = next(item for item in artifacts if item.role == "desktop_research.text_rendition")
                self.assertEqual(app.execution_store.load_artifact(original.artifact_id).content, original_bytes)
                self.assertEqual(app.execution_store.load_artifact(rendition.artifact_id).content, text_bytes)
                self.assertEqual(
                    (before["id"], before["content_digest"]),
                    (after["id"], after["content_digest"]),
                )
            finally:
                facade.close()

    def test_malformed_coverage_and_non_whitespace_citation_still_fail_closed(self):
        flow = Flow()
        try:
            handoff, extension = flow.build_golden()
            validator = DesktopResearchResultValidator(flow.exec_store, flow.ops)
            bad_coverage = dict(extension)
            bad_coverage["coverage_assessment"] = dict(extension["coverage_assessment"])
            bad_coverage["coverage_assessment"]["dimensions"] = [
                *extension["coverage_assessment"]["dimensions"],
                {
                    "dimension_id": "COV-UNKNOWN",
                    "status": "unknown",
                    "trace_entry_ids": [],
                    "rationale": "unknown dimension fixture",
                },
            ]
            refresh(bad_coverage, "extension_digest")
            coverage_codes = validator.validate(
                handoff,
                bad_coverage,
                flow.context,
                flow.context_extension,
                run_id=flow.prepared.run.run_id,
            )
            self.assertIn("DR-COVERAGE-001", coverage_codes)

            bad_citation = dict(extension)
            bad_citation["citation_details"] = [dict(item) for item in extension["citation_details"]]
            bad_citation["citation_details"][0]["excerpt"] = "substantially different supporting excerpt"
            refresh(bad_citation, "extension_digest")
            citation_codes = validator.validate(
                handoff,
                bad_citation,
                flow.context,
                flow.context_extension,
                run_id=flow.prepared.run.run_id,
            )
            self.assertIn("DR-CITATION-001", citation_codes)
        finally:
            flow.close()


if __name__ == "__main__":
    unittest.main()
