from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade, LocalResearchApplication
from plugins.local_execution_store import LocalExecutionStoreConfig
from test_external_desktop_research_intake import NullResolver, profile_provider
from test_external_desktop_research_intake_atomicity import (
    ExternalDesktopResearchAtomicityTests,
)


class DesktopResearchRetentionReopenTests(unittest.TestCase):
    def test_large_capture_survives_process_style_reopen(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            reopened = None
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
                        "max_original_capture_bytes": 128,
                        "max_text_rendition_bytes": 32,
                    },
                )
                raw, text = helper.write_pair(
                    root,
                    "reopen",
                    b"large-original-survives-reopen",
                    b"text",
                )
                captured = facade.capture_external_source(
                    run_id,
                    helper.capture_input("CAP-REOPEN", raw, text),
                )["capture"]
                digest = captured["original_capture"]["content_digest"]
                facade.close()
                facade = None

                reopened_app = LocalResearchApplication(
                    root / ".research-loom",
                    resolver=NullResolver(),
                    effective_profile_set_provider=profile_provider,
                )
                reopened = LocalApplicationFacade(
                    reopened_app,
                    "PRJ-1",
                    workspace_root=root,
                )
                shown = reopened.show_run(run_id)
                original = next(
                    item
                    for item in shown["artifacts"]
                    if item["role"] == "desktop_research.original_capture"
                )
                self.assertEqual(original["digest"], digest)
                self.assertNotIn("storage_locator", str(shown))

                inventory = reopened.list_external_materials(limit=10)
                self.assertEqual(inventory["materials"][0]["original_digest"], digest)
                self.assertNotIn("storage_locator", str(inventory))
            finally:
                if reopened is not None:
                    reopened.close()
                if facade is not None:
                    facade.close()

    def test_small_capture_after_large_does_not_charge_large_bytes_to_generic_run_budget(self):
        helper = ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = helper.make_facade(root)
            try:
                app.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=8,
                    max_run_output_bytes=12,
                )
                run_id = helper.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 2,
                        "max_capture_artifacts": 4,
                        "max_original_capture_bytes": 128,
                        "max_text_rendition_bytes": 32,
                    },
                )
                raw_large, text_large = helper.write_pair(
                    root,
                    "mixed-large",
                    b"large-original-does-not-count",
                    b"aa",
                )
                facade.capture_external_source(
                    run_id,
                    helper.capture_input("CAP-LARGE", raw_large, text_large),
                )

                raw_small, text_small = helper.write_pair(
                    root,
                    "mixed-small",
                    b"tiny",
                    b"bb",
                )
                result = facade.capture_external_source(
                    run_id,
                    helper.capture_input("CAP-SMALL", raw_small, text_small),
                )
                self.assertEqual(result["status"], "EXTERNAL_SOURCE_CAPTURED")
                self.assertEqual(len(app.execution_store.artifacts_for(run_id)), 4)
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
