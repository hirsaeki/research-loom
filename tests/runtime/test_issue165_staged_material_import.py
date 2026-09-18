from __future__ import annotations

import shutil
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError
from plugins.local_execution_store import open_read_only_execution_store
import test_external_desktop_research_intake as intake


def _capture_source(root: Path, facade, run_id: str):
    facade.start_external_retrieval_attempt(
        run_id,
        {
            "attempt_id": "ATT-SOURCE",
            "strategy": "historical source capture",
            "coverage_dimension_ids": ["COV-SUPPORT"],
            "target_locator": "https://example.test/source-a",
        },
    )
    intake.ExternalDesktopResearchIntakeTests().write_capture_files(root)
    capture = facade.capture_external_source(
        run_id,
        {
            "capture_id": "CAP-1",
            "source_category": "other",
            "exact_locator": "https://example.test/source-a#section-1",
            "acquired_at": "2026-08-31T00:00:00Z",
            "original_file": "captures/raw/source-a.html",
            "original_media_type": "text/html",
            "text_rendition_file": "captures/text/source-a.txt",
            "provenance": {"retrieval_method": "historical fixture"},
        },
    )["capture"]
    facade.complete_external_retrieval_attempt(
        run_id,
        {
            "attempt_id": "ATT-SOURCE",
            "outcome": "source_captured",
            "resulting_capture_id": "CAP-1",
        },
    )
    return capture


class StagedMaterialImportAcceptanceTests(unittest.TestCase):
    def test_stage_verify_copy_delete_then_current_run_collects_candidate_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "previous-workspace"
            destination_root = root / "new-workspace"
            helper = intake.ExternalDesktopResearchIntakeTests()

            source_app, source = helper.make_facade(source_root)
            source_run = helper.prepare(source)["run_id"]
            _capture_source(source_root, source, source_run)
            source.close()
            source_app.close()

            destination_app, destination = helper.make_facade(destination_root)
            try:
                destination_run = helper.prepare(destination)["run_id"]
                before = destination_app.state_repository.load_state_view(
                    "PRJ-1", "LIN-1"
                ).current_snapshot

                # Ablation: a staged backing path is disposable and therefore cannot
                # itself be destination durability.
                disposable = destination.stage_external_material_source(source_root)
                disposable_root = destination_root / disposable["staged_source"]["root"]
                with open_read_only_execution_store(
                    disposable_root / "execution"
                ) as staged:
                    artifact = next(
                        item
                        for item in staged.artifacts_for(source_run)
                        if item.role == "desktop_research.original_capture"
                    )
                    backing = staged.verified_artifact_path(artifact.artifact_id)
                    self.assertTrue(backing.is_file())
                shutil.rmtree(disposable_root)
                self.assertFalse(backing.exists())

                staged = destination.stage_external_material_source(source_root)
                staged_root = destination_root / staged["staged_source"]["root"]
                shutil.rmtree(source_root)
                self.assertTrue(staged_root.is_dir())

                destination.start_external_retrieval_attempt(
                    destination_run,
                    {
                        "attempt_id": "ATT-1",
                        "strategy": "reuse verified staged material",
                        "coverage_dimension_ids": ["COV-SUPPORT"],
                        "target_locator": "https://example.test/source-a",
                    },
                )
                imported = destination.import_staged_external_material(
                    staged["stage_id"],
                    source_run_id=source_run,
                    source_capture_id="CAP-1",
                    destination_run_id=destination_run,
                )
                capture = imported["destination"]["capture"]
                self.assertFalse(imported["research_state_mutation_performed"])
                self.assertFalse(imported["source_authority_imported"])
                self.assertNotIn(
                    str(staged_root),
                    repr(
                        destination_app.execution_store.artifacts_for(
                            destination_run
                        )
                    ),
                )

                shutil.rmtree(staged_root)
                shown = destination.show_external_material(
                    destination_run, "CAP-1"
                )
                self.assertEqual(shown["status"], "OK")
                self.assertIn(
                    "exact supporting excerpt",
                    shown["text_rendition_view"]["content"],
                )
                exported = root / "imported-original.html"
                destination.export_external_material(
                    destination_run,
                    "CAP-1",
                    kind="original",
                    output_file=exported,
                )
                self.assertEqual(
                    exported.read_bytes(),
                    b"<html>original source A bytes</html>",
                )

                destination.complete_external_retrieval_attempt(
                    destination_run,
                    {
                        "attempt_id": "ATT-1",
                        "outcome": "source_captured",
                        "resulting_capture_id": "CAP-1",
                    },
                )
                destination.start_external_retrieval_attempt(
                    destination_run,
                    {
                        "attempt_id": "ATT-2",
                        "strategy": "counter search",
                        "coverage_dimension_ids": ["COV-COUNTER"],
                    },
                )
                destination.complete_external_retrieval_attempt(
                    destination_run,
                    {
                        "attempt_id": "ATT-2",
                        "outcome": "no_relevant_source",
                    },
                )
                handoff, extension = intake.golden_submission(
                    destination_app, destination_run, capture
                )
                result = destination.collect_external(
                    destination_run,
                    {"handoff": handoff, "extension": extension},
                )
                after = destination_app.state_repository.load_state_view(
                    "PRJ-1", "LIN-1"
                ).current_snapshot
                self.assertEqual(result["status"], "CAPABILITY_RESULT_COLLECTED")
                self.assertTrue(
                    result["execution_result"]["state_delta_proposal"][
                        "candidate_only"
                    ]
                )
                self.assertEqual(
                    (before["id"], before["content_digest"]),
                    (after["id"], after["content_digest"]),
                )
            finally:
                destination.close()
                destination_app.close()

    def test_corrupt_staged_backing_is_rejected_without_destination_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "previous-workspace"
            destination_root = root / "new-workspace"
            helper = intake.ExternalDesktopResearchIntakeTests()

            source_app, source = helper.make_facade(source_root)
            source_run = helper.prepare(source)["run_id"]
            _capture_source(source_root, source, source_run)
            source.close()
            source_app.close()

            destination_app, destination = helper.make_facade(destination_root)
            try:
                destination_run = helper.prepare(destination)["run_id"]
                staged = destination.stage_external_material_source(source_root)
                staged_root = destination_root / staged["staged_source"]["root"]
                with open_read_only_execution_store(
                    staged_root / "execution"
                ) as source_store:
                    original = next(
                        item
                        for item in source_store.artifacts_for(source_run)
                        if item.role == "desktop_research.original_capture"
                    )
                    backing = source_store.verified_artifact_path(
                        original.artifact_id
                    )
                backing.write_bytes(b"corrupt")
                with self.assertRaises(LocalApplicationError) as caught:
                    destination.import_staged_external_material(
                        staged["stage_id"],
                        source_run_id=source_run,
                        source_capture_id="CAP-1",
                        destination_run_id=destination_run,
                    )
                self.assertEqual(
                    caught.exception.code,
                    "APPLICATION-MATERIAL-IMPORT-VERIFY-001",
                )
                self.assertEqual(
                    destination_app.execution_store.artifacts_for(
                        destination_run
                    ),
                    (),
                )
            finally:
                destination.close()
                destination_app.close()


if __name__ == "__main__":
    unittest.main()
