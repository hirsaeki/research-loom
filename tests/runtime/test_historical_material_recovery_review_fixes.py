from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.cli import main as cli_main
from plugins.local_execution_store.verified_artifact_read import VerifiedArtifactReadMixin
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


def _run_cli(argv):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main([str(item) for item in argv])
    return code, json.loads(stream.getvalue())


def _submit_recovery(workspace, *, run_id: str, capture_id: str, kind: str, source_file: str):
    action_path = Path(workspace) / f"material-recovery-review-{kind}.json"
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


class HistoricalMaterialRecoveryReviewFixTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    def test_public_recovery_diagnosis_reuses_failed_verified_read(self):
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
            corrupt = b"corrupt retained bytes"
            managed.write_bytes(corrupt)
            facade.close()
            facade = None

            with patch.object(
                VerifiedArtifactReadMixin,
                "diagnose_artifact_content",
                side_effect=AssertionError("second content scan"),
            ):
                code, shown = _run_cli([
                    "run", "show", "--workspace", self.workspace,
                    "--run-id", case["run_id"], "--json",
                ])
            self.assertEqual(code, 0)
            failure = shown["finding_recovery"]["recovery_failure_details"]
            self.assertEqual(failure["artifact_id"], rendition.artifact_id)
            self.assertEqual(failure["actual_size"], len(corrupt))
            self.assertIsNotNone(failure["actual_digest"])
            self.assertIn(
                failure["verification_status"],
                {"digest_mismatch", "size_mismatch", "digest_and_size_mismatch"},
            )
        finally:
            if facade is not None:
                facade.close()

    def test_diagnostic_write_failure_does_not_turn_verified_restore_into_failure(self):
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
            facade.close()
            facade = None

            with patch(
                "plugins.local_execution_store.LocalExecutionStore.store_diagnostic",
                side_effect=OSError("diagnostic store unavailable"),
            ):
                code, action_result = _submit_recovery(
                    self.workspace,
                    run_id=case["run_id"],
                    capture_id="CAP-1",
                    kind="rendition",
                    source_file="captures/text/source-a.txt",
                )
            self.assertEqual(code, 0)
            self.assertEqual(action_result["status"], "SUCCEEDED")
            recovery = action_result["data"]
            self.assertEqual(recovery["status"], "RESTORED")
            self.assertFalse(recovery["diagnostic_recorded"])
            self.assertEqual(
                recovery["diagnostic_warning"]["code"],
                "APPLICATION-MATERIAL-RECOVERY-DIAGNOSTIC-001",
            )
            self.assertTrue(managed.exists())

            code, shown = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(
                shown["finding_recovery"]["recovery_class"],
                "proposal_rematerializable",
            )
        finally:
            if facade is not None:
                facade.close()
