from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.material_recovery_facade import HistoricalMaterialRecoveryService
from plugins.local_application.material_reacquisition_facade import RetrievedMaterial
from plugins.local_execution_store import LocalExecutionStoreConfig, bind_controlled_import_root
from plugins import local_payload_repair as repair
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_historical_material_recovery import _run_cli, _submit_recovery
from test_historical_material_recovery_reacquire import _submit_reacquire
import test_external_desktop_research_intake_atomicity as intake_support


class ExactPayloadRepairTests(ResearchPackageAcceptanceSupport):
    def _ready(self, *, kind="rendition"):
        facade, case = self._prepare_case()
        self.addCleanup(facade.close)
        store = facade._application.execution_store
        artifact = next(a for a in store.artifacts_for(case["run_id"])
                        if a.provenance.get("capture_id") == "CAP-1"
                        and a.role.endswith("original_capture" if kind == "original" else "text_rendition"))
        path = store._locator_path(artifact.storage_locator, artifact.digest)
        original = path.read_bytes()
        source = self.workspace / "exact-replacement"
        source.write_bytes(original)
        service = HistoricalMaterialRecoveryService(store, facade.project_id, self.workspace)
        return facade, case, store, artifact, path, original, source, service

    def test_external_corruption_wrong_replacement_and_resume_public_cli(self):
        facade, case, store, artifact, target, exact, source, _ = self._ready()
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?", (case["proposal"]["proposal_id"],)
        )
        bad = b"x" * len(exact)
        target.write_bytes(bad)
        state = facade.resume_context()["research_state"]["snapshot"]
        facade.close()
        wrong = self.workspace / "wrong-bytes"
        wrong.write_bytes(exact[:-1] + bytes([exact[-1] ^ 1]))
        code, rejected = _submit_recovery(self.workspace, run_id=case["run_id"], capture_id="CAP-1",
                                         kind="rendition", source_file=str(wrong))
        self.assertEqual(code, 0)
        self.assertEqual(rejected["status"], "FAILED")
        self.assertEqual(target.read_bytes(), bad)
        code, recovered = _submit_recovery(self.workspace, run_id=case["run_id"], capture_id="CAP-1",
                                          kind="rendition", source_file=str(source))
        self.assertEqual(code, 0)
        data = recovered["data"]
        self.assertEqual(data["status"], "REPAIRED")
        self.assertEqual((store.root / data["quarantine_ref"]).read_bytes(), bad)
        self.assertEqual(target.read_bytes(), exact)
        self.assertTrue((store.root / data["recovery_record"]).is_file())
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened.resume_context()["research_state"]["snapshot"], state)
            self.assertEqual(reopened.show_external_material(case["run_id"], "CAP-1")["status"], "OK")
            self.assertEqual(reopened.show_run(case["run_id"])["finding_recovery"]["recovery_class"],
                             "proposal_rematerializable")
            self.assertEqual(next(a for a in reopened._application.execution_store.artifacts_for(case["run_id"])
                                  if a.artifact_id == artifact.artifact_id), artifact)
            self.assertEqual(reopened.build_research_package(case["build_input"])["status"], "BUILT")

    def test_verified_reuse_still_checks_actual_staging_bytes(self):
        _, case, store, _, target, exact, source, service = self._ready()
        stage = store._stage_controlled_original
        def altered_stage(*args, **kwargs):
            staged, digest, size = stage(*args, **kwargs)
            staged.write_bytes(b"x" * size)
            return staged, digest, size
        with patch.object(store, "_stage_controlled_original", side_effect=altered_stage):
            with self.assertRaises(LocalApplicationError):
                service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(target.read_bytes(), exact)
        self.assertFalse((store.root / "quarantine").exists())

    def test_failure_after_quarantine_preserves_bad_bytes_and_retry_repairs(self):
        _, case, store, _, target, exact, source, service = self._ready()
        target.write_bytes(b"damaged")
        replace = os.replace
        def denied(src, dst):
            if Path(dst) == target:
                raise PermissionError(errno.EACCES, "injected Windows-style replacement denial")
            return replace(src, dst)
        with patch.object(repair.os, "replace", side_effect=denied):
            with self.assertRaises(LocalApplicationError):
                service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(target.read_bytes(), b"damaged")
        self.assertEqual([p.read_bytes() for p in (store.root / "quarantine").iterdir()], [b"damaged"])
        result = service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(result["status"], "REPAIRED")
        self.assertEqual(target.read_bytes(), exact)
        self.assertEqual(service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)["status"],
                         "ALREADY_VERIFIED")

    def test_install_then_io_failure_reopens_and_reuses_verified_effect(self):
        facade, case, _, artifact, target, exact, source, service = self._ready()
        target.write_bytes(b"bad")
        fsync = repair._fsync_directory
        def fail_after_install(path):
            if path == target.parent:
                raise OSError(errno.EIO, "injected post-install sync failure")
            return fsync(path)
        with patch.object(repair, "_fsync_directory", side_effect=fail_after_install):
            with self.assertRaises(LocalApplicationError):
                service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(target.read_bytes(), exact)
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            svc = HistoricalMaterialRecoveryService(reopened._application.execution_store, reopened.project_id, self.workspace)
            result = svc.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
            self.assertEqual(result["status"], "ALREADY_VERIFIED")
            self.assertEqual(result["artifact_id"], artifact.artifact_id)

    def test_recovery_record_failure_does_not_hide_verified_effect(self):
        _, case, _, _, target, exact, source, service = self._ready()
        target.write_bytes(b"bad")
        replace = os.replace
        def fail_receipt(src, dst):
            if Path(dst).parent.name == "repairs":
                raise OSError(errno.EIO, "receipt failure")
            return replace(src, dst)
        with patch.object(repair.os, "replace", side_effect=fail_receipt):
            result = service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(result["status"], "REPAIRED")
        self.assertIn("recovery_record_warning", result)
        self.assertEqual(target.read_bytes(), exact)

    def test_permission_failure_is_not_classified_as_corruption(self):
        _, case, store, _, target, exact, source, service = self._ready()
        original_open = Path.open
        def denied(path, *args, **kwargs):
            if path == target:
                raise PermissionError("unreadable")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", denied):
            with self.assertRaises(LocalApplicationError):
                service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(target.read_bytes(), exact)
        self.assertFalse((store.root / "quarantine").exists())

    def test_invalid_binding_and_wrong_project_are_not_payload_repair(self):
        facade, case, store, artifact, target, exact, source, service = self._ready()
        target.write_bytes(b"bad")
        other = HistoricalMaterialRecoveryService(store, "PRJ-OTHER", self.workspace)
        with self.assertRaises(LocalApplicationError):
            other.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        store._connection.execute("UPDATE execution_artifacts SET role=? WHERE artifact_id=?",
                                  ("unrelated", artifact.artifact_id))
        with self.assertRaises(LocalApplicationError):
            service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(target.read_bytes(), b"bad")
        self.assertFalse((store.root / "quarantine").exists())

    def test_source_and_target_symlinks_and_oversize_are_rejected(self):
        _, case, store, _, target, exact, source, service = self._ready()
        target.write_bytes(b"bad")
        source.write_bytes(exact + b"x")
        with self.assertRaises(LocalApplicationError):
            service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertEqual(target.read_bytes(), b"bad")
        source.write_bytes(exact)
        alias = self.workspace / "linked-source"
        try:
            alias.symlink_to(source)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(LocalApplicationError):
            service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=alias)
        target.unlink()
        target.symlink_to(source)
        with self.assertRaises(LocalApplicationError):
            service.recover(case["run_id"], "CAP-1", kind="rendition", source_file=source)
        self.assertTrue(target.is_symlink())
        self.assertEqual(source.read_bytes(), exact)

    def test_project_input_public_repair_preserves_shared_roles_and_package_use(self):
        facade, case = self._prepare_case()
        self.addCleanup(facade.close)
        item = facade.show_project_input(case["project_input_id"])["project_input"]
        source = self.workspace / "rp1-input.txt"
        snap = facade.resume_context()["research_state"]["snapshot"]
        second = facade.register_project_input({
            "file": str(source), "role": "other", "expected_snapshot_id": snap["snapshot_id"],
            "expected_snapshot_digest": snap["content_digest"],
        })["project_input"]
        registry = facade._registry()
        target = registry._blob_path(item["content_digest"])
        target.write_bytes(b"bad input")
        health = facade.show_project_input(item["input_id"])["payload_health"]
        self.assertIn(health["status"], repair.REPAIRABLE)
        self.assertIn("research-input recover", health["next_action"])
        wrong = self.workspace / "wrong-input"; wrong.write_bytes(b"wrong input")
        with self.assertRaises(LocalApplicationError):
            facade.recover_project_input(item["input_id"], wrong)
        facade.close()
        code, result = _run_cli(["research-input", "recover", "--workspace", self.workspace,
                                 "--input-id", second["input_id"], "--source-file", source, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "REPAIRED")
        self.assertEqual((registry.root / result["quarantine_ref"]).read_bytes(), b"bad input")
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened.show_project_input(item["input_id"], format="text")["project_input"], item)
            self.assertEqual(reopened.show_project_input(second["input_id"])["project_input"], second)
            self.assertEqual(reopened.recover_project_input(item["input_id"], source)["status"], "ALREADY_VERIFIED")
            self.assertEqual(reopened.resume_context()["research_state"]["snapshot"], snap)
            self.assertEqual(reopened.build_research_package(case["build_input"])["status"], "BUILT")

    def test_project_input_missing_metadata_invalid_and_unreadable_are_distinct(self):
        facade, case = self._prepare_case(); self.addCleanup(facade.close)
        input_id = case["project_input_id"]; registry = facade._registry()
        item = registry.get(input_id, facade.project_id); target = registry._blob_path(item["content_digest"])
        exact = target.read_bytes(); target.unlink()
        self.assertEqual(facade.show_project_input(input_id)["payload_health"]["status"], "content_missing")
        self.assertEqual(facade.recover_project_input(input_id, "rp1-input.txt")["status"], "RESTORED")
        with self.assertRaises(LocalApplicationError):
            facade.recover_project_input("PIN-OTHER", "rp1-input.txt")
        original_open = Path.open
        def denied(path, *args, **kwargs):
            if path == target:
                raise PermissionError("access denied")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", denied):
            self.assertEqual(facade.show_project_input(input_id)["payload_health"]["status"], "content_unreadable")
            with self.assertRaises(LocalApplicationError):
                facade.recover_project_input(input_id, "rp1-input.txt")
        registry.db.execute("UPDATE project_inputs SET content_digest='invalid' WHERE input_id=?", (input_id,))
        self.assertEqual(registry.diagnose_content(input_id, facade.project_id)["status"], "metadata_invalid")
        with self.assertRaises(LocalApplicationError):
            facade.recover_project_input(input_id, "rp1-input.txt")
        self.assertEqual(target.read_bytes(), exact)

    def test_identical_locator_reacquisition_repairs_corrupt_original(self):
        facade, case, store, artifact, target, exact, _, _ = self._ready(kind="original")
        target.write_bytes(b"bad original")
        facade.close()
        with patch("plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                   return_value=RetrievedMaterial(exact, "text/html", "https://example.test/source-a#section-1", "test")):
            code, result = _submit_reacquire(self.workspace, run_id=case["run_id"], capture_id="CAP-1")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["data"]["status"], "IDENTICAL_REACQUISITION")
        self.assertEqual(result["data"]["historical_restore_status"], "REPAIRED")
        self.assertEqual(target.read_bytes(), exact)

    def test_changed_reacquisition_is_new_material_not_a_repair_of_old_identity(self):
        facade, case, _, _, target, _, _, _ = self._ready(kind="original")
        target.write_bytes(b"bad historical bytes")
        facade.close()
        with patch("plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                   return_value=RetrievedMaterial(b"<html>changed source</html>", "text/html",
                                                   "https://example.test/source-a#section-1", "test")):
            code, result = _submit_reacquire(self.workspace, run_id=case["run_id"], capture_id="CAP-1")
        self.assertEqual(code, 0)
        self.assertEqual(result["data"]["status"], "NEW_MATERIAL_VERSION")
        self.assertFalse(result["data"]["research_state_mutation_performed"])
        self.assertEqual(target.read_bytes(), b"bad historical bytes")



class SharedPayloadRepairTests(unittest.TestCase):
    def test_two_large_artifact_references_share_the_physical_repair_lock(self):
        helper = intake_support.ExternalDesktopResearchAtomicityTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app, facade = helper.make_facade(root)
            try:
                store = app.execution_store
                store.config = LocalExecutionStoreConfig(max_artifact_bytes=8, max_run_output_bytes=32)
                bind_controlled_import_root(store, root)
                policy = {"max_acquired_source_captures": 2, "max_capture_artifacts": 4,
                          "max_original_capture_bytes": 128, "max_text_rendition_bytes": 32}
                original_bytes = b"shared large original"
                runs = [helper.prepare(facade, policy), helper.prepare(facade, policy)]
                for index, run_id in enumerate(runs):
                    raw, text = helper.write_pair(root, str(index), original_bytes, b"quote")
                    facade.capture_external_source(run_id, helper.capture_input(f"CAP-{index}", raw, text))
                artifacts = [next(a for a in store.artifacts_for(run_id) if a.role.endswith("original_capture"))
                             for run_id in runs]
                self.assertEqual(artifacts[0].storage_locator, artifacts[1].storage_locator)
                target = store._locator_path(artifacts[0].storage_locator, artifacts[0].digest)
                target.write_bytes(b"damaged shared payload")
                source = root / "replacement"; source.write_bytes(original_bytes)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(store.restore_missing_artifact_from_file, a.artifact_id, source)
                               for a in artifacts]
                    results = [f.result(timeout=10) for f in futures]
                self.assertEqual(sorted(r["status"] for r in results), ["ALREADY_VERIFIED", "REPAIRED"])
                self.assertEqual(len(list((store.root / "quarantine").iterdir())), 1)
                self.assertEqual(len(list((store.root / "repair-locks").iterdir())), 1)
                for artifact in artifacts:
                    self.assertEqual(store.load_artifact(artifact.artifact_id).content, original_bytes)
            finally:
                facade.close()
                app.close()

    def test_bounded_lock_busy_and_io_are_distinct_and_lock_release_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); target = root / "blob"
            with repair.payload_lock(root, target):
                with self.assertRaisesRegex(repair.PayloadRepairError, "busy"):
                    with repair.payload_lock(root, target, timeout=0):
                        self.fail("second exclusive lock acquired")
            with repair.payload_lock(root, target, timeout=0):
                pass
            if os.name != "nt":
                import fcntl
                with patch.object(fcntl, "flock", side_effect=OSError(errno.EIO, "I/O")):
                    with self.assertRaises(OSError) as error:
                        with repair.payload_lock(root, target, timeout=0):
                            pass
                self.assertEqual(error.exception.errno, errno.EIO)

    def test_abrupt_process_exit_before_or_after_install_preserves_bytes_and_releases_lock(self):
        import subprocess
        import sys
        script = r"""
import hashlib, os, sys
from pathlib import Path
from plugins import local_payload_repair as repair
root = Path(sys.argv[1]); target = root / 'blob'; staged = root / 'stage'
def verify(path, digest, size):
    data = path.read_bytes()
    assert len(data) == size and 'sha256:' + hashlib.sha256(data).hexdigest() == digest
replace = os.replace
def crash(src, dst):
    if Path(dst) == target:
        if sys.argv[2] == 'after':
            replace(src, dst)
        os._exit(23)
    return replace(src, dst)
repair.os.replace = crash
repair.install_exact_payload(root, target, staged, 'sha256:' + hashlib.sha256(b'exact').hexdigest(), 5, verify=verify)
"""
        def verify(path, digest, size):
            data = path.read_bytes()
            self.assertEqual(len(data), size)
            self.assertEqual("sha256:" + hashlib.sha256(data).hexdigest(), digest)
        for boundary in ("before", "after"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); target = root / "blob"; staged = root / "stage"
                target.write_bytes(b"bad"); staged.write_bytes(b"exact")
                child = subprocess.run([sys.executable, "-c", script, str(root), boundary],
                                       capture_output=True, text=True, timeout=10)
                self.assertEqual(child.returncode, 23, child.stderr)
                self.assertEqual([p.read_bytes() for p in (root / "quarantine").iterdir()], [b"bad"])
                staged.write_bytes(b"exact")
                result = repair.install_exact_payload(
                    root, target, staged, "sha256:" + hashlib.sha256(b"exact").hexdigest(), 5, verify=verify,
                )
                self.assertEqual(result["status"], "REPAIRED" if boundary == "before" else "ALREADY_VERIFIED")
                self.assertEqual(target.read_bytes(), b"exact")
