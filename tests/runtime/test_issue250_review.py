from __future__ import annotations

from contextlib import contextmanager
import errno
from pathlib import Path
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.material_reacquisition_facade import RetrievedMaterial
from plugins.local_execution_store import LocalExecutionStoreIntegrityError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_historical_material_recovery_reacquire import _submit_reacquire
import test_issue250_exact_payload_repair as support


class PayloadRepairReviewTests(ResearchPackageAcceptanceSupport):
    _ready = support.ExactPayloadRepairTests._ready

    @contextmanager
    def _failed_staging_cleanup(self, store):
        staged_paths = []
        stage = store._stage_controlled_original
        unlink = Path.unlink

        def tracked_stage(*args, **kwargs):
            result = stage(*args, **kwargs)
            staged_paths.append(result[0])
            return result

        def denied(path, *args, **kwargs):
            if path in staged_paths:
                raise PermissionError(errno.EACCES, "injected staging cleanup denial")
            return unlink(path, *args, **kwargs)

        with patch.object(store, "_stage_controlled_original", side_effect=tracked_stage):
            with patch.object(Path, "unlink", denied):
                yield staged_paths

    def test_staging_cleanup_does_not_mask_verified_repair(self):
        _, case, store, artifact, target, exact, source, service = self._ready()
        target.write_bytes(b"bad")
        with self.assertLogs("plugins.local_execution_store.verified_artifact_read", level="WARNING") as logs:
            with self._failed_staging_cleanup(store) as staged:
                result = service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertTrue(staged)
        self.assertIn(staged[0].name, logs.output[0])
        self.assertIn("PermissionError", logs.output[0])
        self.assertEqual(result["status"], "REPAIRED")
        self.assertEqual(result["artifact_id"], artifact.artifact_id)
        self.assertEqual(target.read_bytes(), exact)
        self.assertEqual(service.recover(case["run_id"], "CAP-1", kind="rendition",
                                         source_file=source)["status"], "ALREADY_VERIFIED")

    def test_staging_cleanup_does_not_mask_primary_identity_error(self):
        _, _, store, artifact, target, exact, source, _ = self._ready()
        target.write_bytes(b"bad")
        source.write_bytes(exact[:-1] + bytes([exact[-1] ^ 1]))
        with self.assertLogs("plugins.local_execution_store.verified_artifact_read", level="WARNING") as logs:
            with self._failed_staging_cleanup(store) as staged:
                with self.assertRaisesRegex(LocalExecutionStoreIntegrityError,
                                            "do not match persisted artifact digest/size"):
                    store.restore_missing_artifact_from_file(artifact.artifact_id, source)
        self.assertIn(staged[0].name, logs.output[0])
        self.assertEqual(target.read_bytes(), b"bad")

    def test_recorruption_retrieves_again_and_package_resumes(self):
        facade, case, _, _, target, exact, _, _ = self._ready(kind="original")
        facade.close()
        target.write_bytes(b"bad original")
        with patch("plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                   return_value=RetrievedMaterial(exact, "text/html",
                                                   "https://example.test/source-a#section-1", "test")) as retrieve:
            code, first = _submit_reacquire(self.workspace, run_id=case["run_id"], capture_id="CAP-1")
            self.assertEqual(code, 0)
            self.assertEqual(first["status"], "SUCCEEDED")
            self.assertEqual(first["data"]["historical_restore_status"], "REPAIRED")
            target.write_bytes(b"corrupted again")
            code, second = _submit_reacquire(self.workspace, run_id=case["run_id"], capture_id="CAP-1")
        self.assertEqual(code, 0)
        self.assertEqual(second["status"], "SUCCEEDED")
        self.assertEqual(second["data"]["status"], "IDENTICAL_REACQUISITION")
        self.assertEqual(second["data"]["historical_restore_status"], "REPAIRED")
        self.assertNotEqual(first["data"]["reacquisition_run_id"], second["data"]["reacquisition_run_id"])
        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(target.read_bytes(), exact)
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened.show_external_material(case["run_id"], "CAP-1")["status"], "OK")
            self.assertEqual(reopened.build_research_package(case["build_input"])["status"], "BUILT")
