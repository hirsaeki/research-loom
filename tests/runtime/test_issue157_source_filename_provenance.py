from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.cli import main as cli_main
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


def _run_cli(argv):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main([str(item) for item in argv])
    return code, json.loads(stream.getvalue())


def _submit_recovery(workspace, *, run_id: str, capture_id: str, kind: str, source_file: str):
    action_path = Path(workspace) / f"issue157-recover-{kind}.json"
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


class Issue157SourceFilenameProvenanceTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    def test_public_capture_persists_basename_only_and_inventory_exposes_it(self):
        facade, case = self._prepare_case()
        try:
            artifacts = facade._application.execution_store.artifacts_for(case["run_id"])
            original = next(item for item in artifacts if item.role == "desktop_research.original_capture")
            rendition = next(item for item in artifacts if item.role == "desktop_research.text_rendition")
            self.assertEqual(original.provenance["original_source_filename"], "source-a.html")
            self.assertEqual(original.provenance["text_rendition_source_filename"], "source-a.txt")
            self.assertEqual(rendition.provenance["original_source_filename"], "source-a.html")
            self.assertEqual(rendition.provenance["text_rendition_source_filename"], "source-a.txt")
            serialized = json.dumps([original.provenance, rendition.provenance])
            self.assertNotIn("captures/raw", serialized)
            self.assertNotIn("captures/text", serialized)
            self.assertNotIn(str(self.workspace), serialized)

            materials = facade.list_external_materials()["materials"]
            capture = materials[0]["captures"][0]
            self.assertEqual(capture["original_source_filename"], "source-a.html")
            self.assertEqual(capture["text_rendition_source_filename"], "source-a.txt")
            self.assertNotIn(str(self.workspace), json.dumps(materials))
        finally:
            facade.close()

    def test_recovery_diagnosis_is_self_contained_and_filename_is_not_authority(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            original = next(
                artifact
                for artifact in store.artifacts_for(case["run_id"])
                if artifact.role == "desktop_research.original_capture"
            )
            source = self.workspace / "captures/raw/source-a.html"
            exact_bytes = source.read_bytes()
            renamed = self.workspace / "renamed-exact-copy.bin"
            renamed.write_bytes(exact_bytes)
            source.write_bytes(b"wrong bytes under the same filename")
            store._locator_path(original.storage_locator, original.digest).unlink()
            facade.close()
            facade = None

            code, shown = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            failure = shown["finding_recovery"]["recovery_failure_details"]
            self.assertEqual(failure["source_filename"], "source-a.html")
            self.assertEqual(failure["exact_locator"], "https://example.test/source-a#section-1")
            self.assertEqual(failure["media_type"], "text/html")
            self.assertEqual(failure["expected_digest"], original.digest)
            self.assertEqual(failure["expected_size"], original.size)

            code, wrong = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="original",
                source_file="captures/raw/source-a.html",
            )
            self.assertEqual(code, 0)
            self.assertEqual(wrong["status"], "FAILED")

            code, exact = _submit_recovery(
                self.workspace,
                run_id=case["run_id"],
                capture_id="CAP-1",
                kind="original",
                source_file="renamed-exact-copy.bin",
            )
            self.assertEqual(code, 0)
            self.assertEqual(exact["status"], "SUCCEEDED")
            self.assertEqual(exact["data"]["status"], "RESTORED")
        finally:
            if facade is not None:
                facade.close()

    def test_legacy_capture_without_filename_hint_reports_unavailable_but_keeps_locator(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            store = facade._application.execution_store
            artifacts = store.artifacts_for(case["run_id"])
            original = next(item for item in artifacts if item.role == "desktop_research.original_capture")
            with store._lock:
                for artifact in artifacts:
                    provenance = dict(artifact.provenance)
                    provenance.pop("original_source_filename", None)
                    provenance.pop("text_rendition_source_filename", None)
                    store._connection.execute(
                        "UPDATE execution_artifacts SET provenance_json=? WHERE artifact_id=?",
                        (
                            json.dumps(provenance, sort_keys=True, separators=(",", ":")),
                            artifact.artifact_id,
                        ),
                    )
                store._connection.commit()
            store._locator_path(original.storage_locator, original.digest).unlink()
            facade.close()
            facade = None

            code, shown = _run_cli([
                "run", "show", "--workspace", self.workspace,
                "--run-id", case["run_id"], "--json",
            ])
            self.assertEqual(code, 0)
            failure = shown["finding_recovery"]["recovery_failure_details"]
            self.assertIsNone(failure["source_filename"])
            self.assertEqual(failure["exact_locator"], "https://example.test/source-a#section-1")
            self.assertEqual(failure["media_type"], "text/html")
        finally:
            if facade is not None:
                facade.close()
