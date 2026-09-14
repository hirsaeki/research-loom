from __future__ import annotations

import json
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_service import verify_export_root
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


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

            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
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

            public = facade.diagnose_external_material(case["run_id"], "CAP-1")
            self.assertEqual(public["artifact_verification"]["original"]["status"], "content_missing")
            self.assertEqual(public["artifact_verification"]["rendition"]["status"], "verified")

            recovery = facade.recover_external_material(
                case["run_id"],
                "CAP-1",
                kind="original",
                source_file=self.workspace / "captures/raw/source-a.html",
            )
            self.assertEqual(recovery["status"], "RESTORED")
            self.assertFalse(recovery["historical_metadata_rewritten"])
            self.assertFalse(recovery["research_state_mutation_performed"])
            self.assertEqual(facade.show_external_material(case["run_id"], "CAP-1")["status"], "OK")
            after = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(after["recovery_class"], "proposal_rematerializable")
            self.assertEqual(after["recovery_route"], "canonical_result_rematerialization")
            original_after = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.artifact_id == original.artifact_id
            )
            self.assertEqual(original_after, original)
            state_after = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            ).current_snapshot
            self.assertEqual(state_after, state_before)
        finally:
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

            failure = facade.show_run(case["run_id"])["finding_recovery"]["recovery_failure_details"]
            self.assertEqual(failure["artifact_kind"], "rendition")
            self.assertEqual(failure["artifact_id"], rendition.artifact_id)
            self.assertEqual(failure["verification_status"], "content_missing")
            with self.assertRaisesRegex(LocalApplicationError, "could not be restored"):
                facade.recover_external_material(
                    case["run_id"], "CAP-1", kind="rendition", source_file=wrong
                )
            self.assertFalse(managed.exists())

            recovery = facade.recover_external_material(
                case["run_id"],
                "CAP-1",
                kind="rendition",
                source_file=self.workspace / "captures/text/source-a.txt",
            )
            self.assertEqual(recovery["status"], "RESTORED")
            self.assertEqual(
                facade.diagnose_external_material(case["run_id"], "CAP-1")["artifact_verification"]["rendition"]["status"],
                "verified",
            )

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

    def test_present_corrupt_artifact_is_diagnosed_and_not_overwritten(self):
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
            diagnosis = facade.diagnose_external_material(case["run_id"], "CAP-1")
            self.assertIn(
                diagnosis["artifact_verification"]["rendition"]["status"],
                {"digest_mismatch", "size_mismatch", "digest_and_size_mismatch"},
            )
            with self.assertRaisesRegex(LocalApplicationError, "could not be restored"):
                facade.recover_external_material(
                    case["run_id"],
                    "CAP-1",
                    kind="rendition",
                    source_file=self.workspace / "captures/text/source-a.txt",
                )
            self.assertEqual(managed.read_bytes(), before)
        finally:
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

            with patch.object(store, "_stage_controlled_original", side_effect=tampered_stage):
                with self.assertRaisesRegex(LocalApplicationError, "could not be restored"):
                    facade.recover_external_material(
                        case["run_id"],
                        "CAP-1",
                        kind="rendition",
                        source_file=self.workspace / "captures/text/source-a.txt",
                    )
            self.assertFalse(managed.exists())

            with patch.object(store, "_stage_controlled_original", side_effect=tampered_stage), patch.object(
                store, "_verify_blob_streaming", return_value=None
            ):
                ablated = facade.recover_external_material(
                    case["run_id"],
                    "CAP-1",
                    kind="rendition",
                    source_file=self.workspace / "captures/text/source-a.txt",
                )
            self.assertEqual(ablated["status"], "RESTORED")
            self.assertNotEqual(managed.read_bytes(), (self.workspace / "captures/text/source-a.txt").read_bytes())
        finally:
            facade.close()
