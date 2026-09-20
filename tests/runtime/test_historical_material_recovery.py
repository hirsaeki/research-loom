from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.material_recovery_facade import HistoricalMaterialRecoveryService
from plugins.local_application.cli import main as cli_main
from plugins.local_application.research_package_service import verify_export_root
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


def _run_cli(argv):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main([str(item) for item in argv])
    return code, json.loads(stream.getvalue())


def _submit_recovery(workspace, *, run_id: str, capture_id: str, kind: str, source_file: str):
    action_path = Path(workspace) / f"material-recovery-{kind}.json"
    action_path.write_text(
        json.dumps({
            "action_type": "desktop_research.material.recover",
            "payload": {
                "run_id": run_id,
                "capture_id": capture_id,
                "kind": kind,
                "source_file": source_file,
            },
        }),
        encoding="utf-8",
    )
    return _run_cli([
        "action", "submit", "--workspace", workspace, "--json", action_path,
    ])


class HistoricalMaterialRecoveryTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    def test_missing_original_is_publicly_diagnosed_restored_and_rematerializable(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            state_before = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot
            original = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.role == "desktop_research.original_capture"
                and artifact.provenance.get("capture_id") == "CAP-1"
            )
            managed = store._locator_path(original.storage_locator, original.digest)
            managed.unlink()
            facade.close()
            facade = None

            code, shown_run = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            diagnosis = shown_run["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "material_recovery_required")
            failure = diagnosis["recovery_failure_details"]
            self.assertEqual(failure["capture_id"], "CAP-1")
            self.assertEqual(failure["artifact_kind"], "original")
            self.assertEqual(failure["artifact_id"], original.artifact_id)
            self.assertEqual(failure["verification_status"], "content_missing")
            self.assertEqual(failure["expected_digest"], original.digest)
            self.assertEqual(failure["expected_size"], original.size)
            self.assertIsNone(failure["actual_digest"])
            self.assertIsNone(failure["actual_size"])

            code, action_result = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="original",
                source_file="captures/raw/source-a.html",
            )
            self.assertEqual(code, 0)
            self.assertEqual(action_result["status"], "SUCCEEDED")
            recovery = action_result["data"]
            self.assertEqual(recovery["status"], "RESTORED")
            self.assertFalse(recovery["historical_metadata_rewritten"])
            self.assertFalse(recovery["research_state_mutation_performed"])
            code, repeated_result = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="original",
                source_file="captures/raw/source-a.html",
            )
            self.assertEqual(code, 0)
            self.assertEqual(repeated_result["status"], "SUCCEEDED")
            self.assertEqual(repeated_result["data"]["status"], "ALREADY_VERIFIED")

            code, shown = _run_cli([
                "external", "materials", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--capture-id", "CAP-1", "--json",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(shown["status"], "OK")
            code, after_run = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            after = after_run["finding_recovery"]
            self.assertEqual(after["recovery_class"], "proposal_rematerializable")
            self.assertEqual(after["recovery_route"], "canonical_result_rematerialization")
            self.assertTrue(any(
                item.get("kind") == "historical_material_recovery"
                and item.get("payload", {}).get("artifact_id") == original.artifact_id
                for item in after_run["diagnostics"]
            ))

            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                original_after = next(
                    artifact
                    for artifact in reopened._application.execution_store.artifacts_for(case["run_id"])
                    if artifact.artifact_id == original.artifact_id
                )
                self.assertEqual(original_after, original)
                state_after = reopened._application.state_repository.load_state_view(
                    reopened.project_id,
                    reopened._application.state_repository.load_active_lineage_ref(reopened.project_id),
                ).current_snapshot
                self.assertEqual(state_after, state_before)
        finally:
            if facade is not None:
                facade.close()

    def test_missing_rendition_rejects_wrong_bytes_then_restores_exact_bytes(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            rendition = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.role == "desktop_research.text_rendition"
                and artifact.provenance.get("capture_id") == "CAP-1"
            )
            managed = store._locator_path(rendition.storage_locator, rendition.digest)
            managed.unlink()
            wrong = self.workspace / "wrong-rendition.txt"
            wrong.write_text("wrong bytes", encoding="utf-8")

            facade.close()
            facade = None
            code, shown_run = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            failure = shown_run["finding_recovery"]["recovery_failure_details"]
            self.assertEqual(failure["artifact_kind"], "rendition")
            self.assertEqual(failure["artifact_id"], rendition.artifact_id)
            self.assertEqual(failure["verification_status"], "content_missing")
            code, wrong_result = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="rendition",
                source_file="wrong-rendition.txt",
            )
            self.assertEqual(code, 0)
            self.assertEqual(wrong_result["status"], "FAILED")
            self.assertEqual(wrong_result["issues"][0]["code"], "CONV-AUDIT-001")
            self.assertFalse(managed.exists())

            code, recovery_result = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="rendition",
                source_file="captures/text/source-a.txt",
            )
            self.assertEqual(code, 0)
            self.assertEqual(recovery_result["status"], "SUCCEEDED")
            self.assertEqual(recovery_result["data"]["status"], "RESTORED")
            code, recovered_run = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(
                recovered_run["finding_recovery"]["recovery_class"],
                "proposal_rematerializable",
            )

            facade = LocalApplicationFacade.open_workspace(self.workspace)

            package = facade.build_research_package(case["build_input"])["package"]
            output = self.root / "material-recovery-detached"
            facade.export_research_package(package["package_id"], output)
            facade.close()
            facade = None
            unavailable = self.root / "workspace-unavailable-after-material-recovery"
            self.workspace.rename(unavailable)
            self.assertEqual(verify_export_root(output)["status"], "VERIFIED")
            detached = json.loads(
                (output / "research-package.json").read_text(encoding="utf-8")
            )
            material = detached["resolved_content"]["materials"][0]
            attachment = output / material["text_rendition"]["attachment_path"]
            self.assertEqual(attachment.read_text(encoding="utf-8"), case["source_text"])
        finally:
            if facade is not None:
                facade.close()

    def test_present_corrupt_artifact_is_diagnosed_and_exactly_repaired(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            rendition = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.role == "desktop_research.text_rendition"
                and artifact.provenance.get("capture_id") == "CAP-1"
            )
            managed = store._locator_path(rendition.storage_locator, rendition.digest)
            managed.write_bytes(b"corrupt retained bytes")
            before = managed.read_bytes()
            facade.close()
            facade = None
            code, shown_run = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            failure = shown_run["finding_recovery"]["recovery_failure_details"]
            self.assertEqual(failure["artifact_kind"], "rendition")
            self.assertIn(
                failure["verification_status"],
                {"digest_mismatch", "size_mismatch", "digest_and_size_mismatch"},
            )
            code, recovery_result = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="rendition",
                source_file="captures/text/source-a.txt",
            )
            self.assertEqual(code, 0)
            self.assertEqual(recovery_result["status"], "SUCCEEDED")
            self.assertEqual(recovery_result["data"]["status"], "REPAIRED")
            self.assertEqual(managed.read_bytes(), (self.workspace / "captures/text/source-a.txt").read_bytes())
            quarantine = store.root / recovery_result["data"]["quarantine_ref"]
            self.assertEqual(quarantine.read_bytes(), before)
        finally:
            if facade is not None:
                facade.close()

    def test_ablation_post_install_verifier_blocks_staged_byte_tampering(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            rendition = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.role == "desktop_research.text_rendition"
                and artifact.provenance.get("capture_id") == "CAP-1"
            )
            managed = store._locator_path(rendition.storage_locator, rendition.digest)
            managed.unlink()
            original_stage = store._stage_controlled_original

            def tampered_stage(*args, **kwargs):
                temporary, digest, size = original_stage(*args, **kwargs)
                temporary.write_bytes(b"x" * size)
                return temporary, digest, size

            service = HistoricalMaterialRecoveryService(
                store, facade.project_id, self.workspace
            )
            with patch.object(store, "_stage_controlled_original", side_effect=tampered_stage):
                with self.assertRaisesRegex(LocalApplicationError, "could not be restored"):
                    service.recover(
                        case["run_id"],
                        "CAP-1",
                        kind="rendition",
                        source_file=self.workspace / "captures/text/source-a.txt",
                    )
            self.assertFalse(managed.exists())

            with patch.object(store, "_stage_controlled_original", side_effect=tampered_stage), patch.object(
                store, "_verify_blob_streaming", return_value=None
            ):
                ablated = service.recover(
                    case["run_id"],
                    "CAP-1",
                    kind="rendition",
                    source_file=self.workspace / "captures/text/source-a.txt",
                )
            self.assertEqual(ablated["status"], "RESTORED")
            self.assertNotEqual(managed.read_bytes(), (self.workspace / "captures/text/source-a.txt").read_bytes())
        finally:
            facade.close()
