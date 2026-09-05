from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.execution import ExecutionIssue, RunLifecycleEvent, RunStatus
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_execution_store import LocalExecutionStoreConfig
from tests.runtime.test_research_question_review import _adopt_question, _workspace


ROOT = Path(__file__).resolve().parents[2]


def _cli(*args: str) -> tuple[subprocess.CompletedProcess[str], dict | None]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "research-loom"), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    value = None
    if completed.stdout.strip():
        value = json.loads(completed.stdout)
    return completed, value


def _prepare(facade: LocalApplicationFacade, question_id: str, *, policy: dict | None = None) -> str:
    payload = {"question_id": question_id, "purpose": "Issue 91 public material acceptance."}
    if policy is not None:
        payload["desktop_policy"] = policy
    return facade.submit_action({"action_type": "desktop_research.investigate", "payload": payload})["run_id"]


def _capture(
    facade: LocalApplicationFacade,
    workspace: Path,
    run_id: str,
    capture_id: str,
    original: bytes,
    rendition: bytes,
    *,
    name: str,
):
    raw = workspace / "captures" / "raw" / f"{name}.bin"
    text = workspace / "captures" / "text" / f"{name}.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    text.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(original)
    text.write_bytes(rendition)
    facade.start_external_retrieval_attempt(run_id, {
        "attempt_id": f"ATT-{capture_id}",
        "strategy": "local acceptance fixture",
        "coverage_dimension_ids": ["COV-SUPPORT"],
        "query_or_target": f"fixture:{capture_id}",
    })
    captured = facade.capture_external_source(run_id, {
        "capture_id": capture_id,
        "source_category": "other",
        "exact_locator": f"https://example.test/{capture_id.lower()}#source",
        "acquired_at": "2026-09-06T00:00:00Z",
        "original_file": str(raw.relative_to(workspace)),
        "original_media_type": "application/octet-stream",
        "text_rendition_file": str(text.relative_to(workspace)),
        "provenance": {"fixture": "issue-91"},
    })["capture"]
    facade.complete_external_retrieval_attempt(run_id, {
        "attempt_id": f"ATT-{capture_id}",
        "outcome": "source_captured",
        "resulting_capture_id": capture_id,
    })
    return captured, raw, text


class Issue91ExternalMaterialContentTests(unittest.TestCase):
    def test_c1_public_cli_round_trip_survives_source_removal_without_state_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = _workspace(root)
            original = b"\x00exact original\r\nbytes\xff"
            rendition = "exact UTF-8 rendition\nsecond line\n".encode("utf-8")
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 G1")
                snapshot_before = facade.resume_context()["research_state"]["snapshot"]
                run_id = _prepare(facade, question_id)
                captured, raw, text = _capture(
                    facade, workspace, run_id, "CAP-C1", original, rendition, name="c1"
                )
                before = facade.show_run(run_id)
                before_artifacts = len(before["artifacts"])
                before_attempts = before["desktop_research"]["retrieval_attempt_summary"]["total"]
                original_digest = captured["original_capture"]["content_digest"]
                rendition_digest = captured["text_rendition"]["content_digest"]
            raw.unlink(); text.unlink()

            listed_process, listed = _cli(
                "external", "materials", "list", "--workspace", str(workspace), "--json"
            )
            self.assertEqual(listed_process.returncode, 0, listed_process.stderr)
            capture = listed["materials"][0]["captures"][0]
            self.assertEqual((capture["run_id"], capture["capture_id"]), (run_id, "CAP-C1"))

            shown_process, shown = _cli(
                "external", "materials", "show", "--workspace", str(workspace),
                "--run-id", run_id, "--capture-id", "CAP-C1", "--json",
            )
            self.assertEqual(shown_process.returncode, 0, shown_process.stderr)
            self.assertEqual(shown["text_rendition_view"]["content"].encode("utf-8"), rendition)
            self.assertFalse(shown["text_rendition_view"]["truncated"])

            original_out = root / "export-original.bin"
            rendition_out = root / "export-rendition.txt"
            for kind, output, expected, digest in (
                ("original", original_out, original, original_digest),
                ("rendition", rendition_out, rendition, rendition_digest),
            ):
                process, exported = _cli(
                    "external", "materials", "export", "--workspace", str(workspace),
                    "--run-id", run_id, "--capture-id", "CAP-C1", "--kind", kind,
                    "--output", str(output), "--json",
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(output.read_bytes(), expected)
                self.assertEqual(exported["digest"], digest)
                self.assertEqual(exported["byte_length"], len(expected))

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                after = facade.show_run(run_id)
                self.assertEqual(facade.resume_context()["research_state"]["snapshot"], snapshot_before)
                self.assertEqual(after["run"]["status"], before["run"]["status"])
                self.assertEqual(len(after["artifacts"]), before_artifacts)
                self.assertEqual(
                    after["desktop_research"]["retrieval_attempt_summary"]["total"],
                    before_attempts,
                )

    def test_c2_large_original_exports_exact_bytes_and_show_marks_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = _workspace(root)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 C2")
                facade._application.execution_store.config = LocalExecutionStoreConfig(
                    max_artifact_bytes=32, max_run_output_bytes=64
                )
                policy = {
                    "max_acquired_source_captures": 1,
                    "max_capture_artifacts": 2,
                    "max_original_capture_bytes": 512,
                    "max_text_rendition_bytes": 64,
                }
                run_id = _prepare(facade, question_id, policy=policy)
                original = b"large-original-" * 8
                rendition = b"0123456789abcdefghijklmnop"
                _capture(facade, workspace, run_id, "CAP-C2", original, rendition, name="c2")
                shown = facade.show_external_material(run_id, "CAP-C2", max_text_bytes=7)
                self.assertTrue(shown["text_rendition_view"]["truncated"])
                self.assertEqual(shown["text_rendition_view"]["content"], "0123456")
                output = root / "large.bin"
                facade.export_external_material(run_id, "CAP-C2", kind="original", output_file=output)
                self.assertEqual(output.read_bytes(), original)

    def test_c3_explicit_capture_selects_version_and_cli_requires_capture_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = _workspace(root)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 C3")
                run_a = _prepare(facade, question_id)
                run_b = _prepare(facade, question_id)
                original = b"same-original"
                _capture(facade, workspace, run_a, "CAP-A", original, b"rendition-A", name="a")
                _capture(facade, workspace, run_b, "CAP-B", original, b"rendition-B", name="b")
                inventory = facade.list_external_materials()
                self.assertEqual(len(inventory["materials"]), 1)
                self.assertEqual(len(inventory["materials"][0]["captures"]), 2)
                self.assertEqual(
                    facade.show_external_material(run_a, "CAP-A")["text_rendition_view"]["content"],
                    "rendition-A",
                )
                self.assertEqual(
                    facade.show_external_material(run_b, "CAP-B")["text_rendition_view"]["content"],
                    "rendition-B",
                )
            process, result = _cli(
                "external", "materials", "show", "--workspace", str(workspace),
                "--run-id", run_a, "--json",
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("--capture-id", result["issues"][0]["message"])

    def test_c4_same_size_corruption_missing_pair_wrong_pair_and_foreign_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = _workspace(root)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 C4")
                run_id = _prepare(facade, question_id)
                _capture(facade, workspace, run_id, "CAP-C4", b"original-C4", b"rendition-C4", name="c4")
                store = facade._application.execution_store
                original = next(a for a in store.artifacts_for(run_id) if a.role.endswith("original_capture"))
                blob = store._locator_path(original.storage_locator, original.digest)
                saved = blob.read_bytes()
                blob.write_bytes(bytes([saved[0] ^ 1]) + saved[1:])
                with self.assertRaises(LocalApplicationError) as corrupt:
                    facade.export_external_material(
                        run_id, "CAP-C4", kind="original", output_file=root / "corrupt.bin"
                    )
                self.assertEqual(corrupt.exception.code, "APPLICATION-MATERIAL-INTEGRITY-001")
                self.assertFalse((root / "corrupt.bin").exists())
                blob.write_bytes(saved)

                with store._lock:
                    store._connection.execute(
                        "UPDATE execution_artifacts SET size=size+1 WHERE artifact_id=?",
                        (original.artifact_id,),
                    )
                    store._connection.commit()
                with self.assertRaises(LocalApplicationError) as size:
                    facade.export_external_material(
                        run_id, "CAP-C4", kind="original", output_file=root / "size.bin"
                    )
                self.assertEqual(size.exception.code, "APPLICATION-MATERIAL-INTEGRITY-001")
                with store._lock:
                    store._connection.execute(
                        "UPDATE execution_artifacts SET size=size-1 WHERE artifact_id=?",
                        (original.artifact_id,),
                    )
                    store._connection.commit()

                rendition = next(a for a in store.artifacts_for(run_id) if a.role.endswith("text_rendition"))
                good_prov = dict(rendition.provenance)
                bad_prov = dict(good_prov); bad_prov["parent_artifact_refs"] = ["ART-wrong"]
                with store._lock:
                    store._connection.execute(
                        "UPDATE execution_artifacts SET provenance_json=? WHERE artifact_id=?",
                        (json.dumps(bad_prov), rendition.artifact_id),
                    )
                    store._connection.commit()
                with self.assertRaises(LocalApplicationError) as wrong_pair:
                    facade.show_external_material(run_id, "CAP-C4")
                self.assertEqual(wrong_pair.exception.code, "APPLICATION-MATERIAL-INTEGRITY-001")
                with store._lock:
                    store._connection.execute(
                        "UPDATE execution_artifacts SET provenance_json=? WHERE artifact_id=?",
                        (json.dumps(good_prov), rendition.artifact_id),
                    )
                    store._connection.commit()

                with store._lock:
                    store._connection.execute(
                        "UPDATE runs SET project_ref=? WHERE run_id=?", ("PRJ-foreign", run_id)
                    )
                    store._connection.commit()
                with self.assertRaises(LocalApplicationError) as foreign:
                    facade.show_external_material(run_id, "CAP-C4")
                self.assertEqual(foreign.exception.code, "APPLICATION-MATERIAL-404")
                with store._lock:
                    store._connection.execute(
                        "UPDATE runs SET project_ref=? WHERE run_id=?", (facade.project_id, run_id)
                    )
                    store._connection.commit()

                blob.unlink()
                with self.assertRaises(LocalApplicationError) as missing_blob:
                    facade.export_external_material(
                        run_id, "CAP-C4", kind="original", output_file=root / "missing.bin"
                    )
                self.assertEqual(missing_blob.exception.code, "APPLICATION-MATERIAL-INTEGRITY-001")
                self.assertFalse((root / "missing.bin").exists())

                with self.assertRaises(LocalApplicationError) as unknown:
                    facade.show_external_material("RUN-missing", "CAP-C4")
                self.assertEqual(unknown.exception.code, "APPLICATION-MATERIAL-404")

    def test_c5_terminal_capture_remains_readable_but_attempt_only_has_no_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = _workspace(root)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 C5")
                run_id = _prepare(facade, question_id)
                _capture(facade, workspace, run_id, "CAP-C5", b"terminal", b"terminal text", name="c5")
                store = facade._application.execution_store
                running = store.load_run(run_id)
                failed = running.with_status(
                    RunStatus.FAILED,
                    completed_at="2026-09-06T00:02:00Z",
                    failure=ExecutionIssue("fixture", "terminal fixture"),
                )
                changed = store.transition_run(
                    RunStatus.RUNNING,
                    failed,
                    RunLifecycleEvent(
                        run_id, 3, RunStatus.RUNNING, RunStatus.FAILED,
                        "2026-09-06T00:02:00Z", "fixture terminal",
                    ),
                )
                self.assertTrue(changed)
                self.assertEqual(facade.show_external_material(run_id, "CAP-C5")["run"]["status"], "FAILED")

                attempt_only = _prepare(facade, question_id)
                facade.start_external_retrieval_attempt(attempt_only, {
                    "attempt_id": "ATT-ONLY", "strategy": "none", "coverage_dimension_ids": ["COV-SUPPORT"]
                })
                facade.complete_external_retrieval_attempt(attempt_only, {
                    "attempt_id": "ATT-ONLY", "outcome": "no_relevant_source"
                })
                with self.assertRaises(LocalApplicationError) as missing:
                    facade.show_external_material(attempt_only, "CAP-none")
                self.assertEqual(missing.exception.code, "APPLICATION-MATERIAL-404")

    def test_c6_export_never_overwrites_or_writes_managed_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = _workspace(root)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 C6")
                run_id = _prepare(facade, question_id)
                _capture(facade, workspace, run_id, "CAP-C6", b"original", b"text", name="c6")
                existing = root / "existing.bin"; existing.write_bytes(b"user data")
                with self.assertRaises(LocalApplicationError) as overwrite:
                    facade.export_external_material(run_id, "CAP-C6", kind="original", output_file=existing)
                self.assertEqual(overwrite.exception.code, "APPLICATION-MATERIAL-EXPORT-001")
                self.assertEqual(existing.read_bytes(), b"user data")

                managed = workspace / ".research-loom" / "do-not-write.bin"
                with self.assertRaises(LocalApplicationError) as internal:
                    facade.export_external_material(run_id, "CAP-C6", kind="original", output_file=managed)
                self.assertEqual(internal.exception.code, "APPLICATION-MATERIAL-EXPORT-001")
                self.assertFalse(managed.exists())

    def test_ablation_digest_guard_is_the_control_for_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = _workspace(root)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 91 ablation")
                run_id = _prepare(facade, question_id)
                _capture(facade, workspace, run_id, "CAP-ABL", b"original", b"text", name="abl")
                store = facade._application.execution_store
                original = next(a for a in store.artifacts_for(run_id) if a.role.endswith("original_capture"))
                blob = store._locator_path(original.storage_locator, original.digest)
                content = blob.read_bytes()
                corrupted = bytes([content[0] ^ 1]) + content[1:]
                blob.write_bytes(corrupted)
                with self.assertRaises(LocalApplicationError):
                    facade.export_external_material(
                        run_id, "CAP-ABL", kind="original", output_file=root / "guarded.bin"
                    )
                with patch.object(store, "_verify_blob_path", return_value=None):
                    bypass = root / "ablated.bin"
                    result = facade.export_external_material(
                        run_id, "CAP-ABL", kind="original", output_file=bypass
                    )
                self.assertEqual(result["status"], "EXPORTED")
                self.assertEqual(bypass.read_bytes(), corrupted)
                self.assertNotEqual(bypass.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
