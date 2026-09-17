from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade, LocalWorkspace
from plugins.local_application.material_recovery_facade import HistoricalMaterialRecoveryService
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from tests.runtime.test_external_material_inventory import _capture, _create_running, _write_inputs


class ExternalMaterialHealthTests(unittest.TestCase):
    def _workspace(self, root: Path) -> LocalApplicationFacade:
        config, profiles = _write_inputs(root)
        opened = LocalWorkspace.init(root / "workspace", config, profiles)
        return LocalApplicationFacade.from_opened_workspace(opened)

    def test_shared_blob_loss_and_exact_recovery_keep_history_truthful(self):
        original_bytes = b"shared original"
        with tempfile.TemporaryDirectory() as temp:
            facade = self._workspace(Path(temp))
            try:
                store = facade._application.execution_store
                runs = [
                    _create_running(store, facade.project_id, "RUN-A", "2026-09-01T00:01:00Z"),
                    _create_running(store, facade.project_id, "RUN-B", "2026-09-01T00:02:00Z"),
                ]
                for index, run in enumerate(runs):
                    _capture(
                        store,
                        run,
                        f"CAP-{index}",
                        original_bytes,
                        f"https://example.test/{index}",
                        acquired_at=f"2026-09-01T00:0{index + 1}:20Z",
                    )

                with patch.object(store, "diagnose_artifact_content", wraps=store.diagnose_artifact_content) as diagnose:
                    healthy = facade.list_external_materials()["materials"][0]
                self.assertEqual(healthy["capture_count"], 2)
                self.assertEqual(healthy["backing_content_status"], "verified")
                self.assertEqual(healthy["verified_backing_copy_count"], 1)
                self.assertEqual(diagnose.call_count, 2)  # one original + one representative rendition
                self.assertEqual(healthy["captures"][0]["renditions"][0]["content_health"]["status"], "verified")
                self.assertFalse(healthy["captures"][1]["renditions"][0]["content_health"]["verification_performed"])

                originals = [
                    artifact
                    for run in runs
                    for artifact in store.artifacts_for(run.run_id)
                    if artifact.role == "desktop_research.original_capture"
                ]
                self.assertEqual(originals[0].storage_locator, originals[1].storage_locator)
                history = [(item["run_id"], item["capture_id"], item["captured_at"]) for item in healthy["captures"]]
                store._locator_path(originals[0].storage_locator, originals[0].digest).unlink()

                missing = facade.list_external_materials()["materials"][0]
                self.assertEqual(missing["capture_count"], 2)
                self.assertEqual(missing["backing_content_status"], "content_missing")
                self.assertEqual(missing["verified_backing_copy_count"], 0)
                self.assertFalse(missing["content_available"])
                self.assertTrue(all(item["capture_record_present"] for item in missing["captures"]))
                self.assertTrue(all(item["original"]["content_health"]["status"] == "content_missing" for item in missing["captures"]))
                self.assertEqual(missing["captures"][0]["renditions"][0]["content_health"]["status"], "verified")

                # Ablation: metadata grouping alone cannot observe the vanished shared CAS bytes.
                with patch.object(
                    store,
                    "diagnose_artifact_content",
                    return_value={
                        "status": "verified",
                        "expected_digest": originals[0].digest,
                        "expected_size": originals[0].size,
                        "actual_digest": originals[0].digest,
                        "actual_size": originals[0].size,
                    },
                ):
                    self.assertTrue(facade.list_external_materials()["materials"][0]["content_available"])

            finally:
                facade.close()

    def test_health_hashing_is_constant_per_material_with_many_captures(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self._workspace(Path(temp))
            try:
                store = facade._application.execution_store
                for index in range(12):
                    run = _create_running(store, facade.project_id, f"RUN-{index:02d}", f"2026-09-01T00:{index:02d}:00Z")
                    _capture(
                        store,
                        run,
                        f"CAP-{index:02d}",
                        b"shared bounded original",
                        f"https://example.test/{index}",
                        acquired_at=f"2026-09-01T00:{index:02d}:20Z",
                    )
                with patch.object(store, "diagnose_artifact_content", wraps=store.diagnose_artifact_content) as diagnose:
                    material = facade.list_external_materials(limit=1)["materials"][0]
                self.assertEqual(material["capture_count"], 12)
                self.assertEqual(diagnose.call_count, 2)
                health = [item["renditions"][0]["content_health"] for item in material["captures"]]
                self.assertEqual(sum(item["status"] == "verified" for item in health), 1)
                self.assertEqual(sum(item["verification_performed"] is False for item in health), 11)
            finally:
                facade.close()

    def test_corruption_reuses_integrity_states_without_exposing_storage_path(self):
        with tempfile.TemporaryDirectory() as temp:
            facade = self._workspace(Path(temp))
            try:
                store = facade._application.execution_store
                run = _create_running(store, facade.project_id, "RUN-CORRUPT", "2026-09-01T00:03:00Z")
                _capture(store, run, "CAP-CORRUPT", b"0123456789", "https://example.test/corrupt", acquired_at="2026-09-01T00:03:20Z")
                original = next(item for item in store.artifacts_for(run.run_id) if item.role == "desktop_research.original_capture")
                blob = store._locator_path(original.storage_locator, original.digest)
                saved = blob.read_bytes()

                blob.write_bytes(b"X" + saved[1:])
                health = facade.list_external_materials()["materials"][0]["original"]["content_health"]
                self.assertEqual(health["status"], "digest_mismatch")

                blob.write_bytes(saved + b"extra")
                listed = facade.list_external_materials()
                self.assertEqual(listed["materials"][0]["original"]["content_health"]["status"], "digest_and_size_mismatch")
                self.assertNotIn(str(blob), repr(listed))
            finally:
                facade.close()


class ExternalMaterialRecoveryHealthTests(ResearchPackageAcceptanceSupport):
    def test_exact_bytes_recovery_restores_health_without_rewriting_capture_history(self):
        facade, case = self._prepare_case()
        try:
            facade._application.conversation_store._db.execute(
                "DELETE FROM state_delta_proposals WHERE proposal_id=?",
                (case["proposal"]["proposal_id"],),
            )
            store = facade._application.execution_store
            original = next(
                item for item in store.artifacts_for(case["run_id"])
                if item.role == "desktop_research.original_capture"
                and item.provenance.get("capture_id") == "CAP-1"
            )
            store._locator_path(original.storage_locator, original.digest).unlink()
            missing = next(
                item for item in facade.list_external_materials()["materials"]
                if item["material_id"] == original.digest
            )
            history = [
                (item["run_id"], item["capture_id"], item["captured_at"])
                for item in missing["captures"]
            ]
            self.assertEqual(missing["backing_content_status"], "content_missing")
            self.assertEqual(missing["verified_backing_copy_count"], 0)

            recovered = HistoricalMaterialRecoveryService(
                store, facade.project_id, self.workspace
            ).recover(
                case["run_id"],
                "CAP-1",
                kind="original",
                source_file=self.workspace / "captures/raw/source-a.html",
            )
            self.assertEqual(recovered["status"], "RESTORED")
            self.assertFalse(recovered["research_state_mutation_performed"])
            self.assertFalse(recovered["historical_metadata_rewritten"])

            healthy = next(
                item for item in facade.list_external_materials()["materials"]
                if item["material_id"] == original.digest
            )
            self.assertEqual(healthy["backing_content_status"], "verified")
            self.assertEqual(healthy["verified_backing_copy_count"], 1)
            self.assertEqual(
                [(item["run_id"], item["capture_id"], item["captured_at"]) for item in healthy["captures"]],
                history,
            )
        finally:
            facade.close()


if __name__ == "__main__":
    unittest.main()
