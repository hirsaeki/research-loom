from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from plugins.local_execution_store import LocalExecutionStoreConfig
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
                large_root = app.execution_store.root / "large-originals"
                self.assertFalse(large_root.exists())
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
                raw.write_bytes(b"original")
                text.write_text("Source A contains the exact supporting\nexcerpt used here.", encoding="utf-8")
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
                    (before["id"], before["content_digest"]),
                    (after["id"], after["content_digest"]),
                )
            finally:
                facade.close()

    def test_non_whitespace_citation_difference_still_fails(self):
        self.assertIsNone(
            __import__("plugins.desktop_research.retention", fromlist=["_matching_whitespace_slice"])
            ._matching_whitespace_slice(
                "The agency should improve oversight over the program.",
                "The agency should substantially improve oversight over the program.",
            )
        )


if __name__ == "__main__":
    unittest.main()
