from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

from core.execution import CapabilityRunRecord, ExecutionIssue, RunLifecycleEvent, RunStatus
from plugins.desktop_research.attempts import ATTEMPT_COMPLETED, ATTEMPT_STARTED, OPERATIONAL_TERMINATION
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalWorkspace
from plugins.local_application.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


def _configuration_digest(config: dict) -> str:
    value = deepcopy(config)
    value.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _write_inputs(root: Path) -> tuple[Path, Path]:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = _configuration_digest(config)
    profiles = json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))
    config_path = root / "project-config.json"
    profile_path = root / "profiles.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    profile_path.write_text(json.dumps(profiles), encoding="utf-8")
    return config_path, profile_path


def _run_cli(argv):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main(argv)
    return code, json.loads(stream.getvalue())


def _prepared_run(project_id: str, run_id: str, *, capability_id: str = "desktop-research") -> CapabilityRunRecord:
    return CapabilityRunRecord(
        run_id=run_id,
        invocation_id=f"INV-{run_id}",
        invocation_digest="sha256:" + "1" * 64,
        capability_id=capability_id,
        capability_version="0.1.0",
        descriptor_digest="sha256:" + "2" * 64,
        implementation_id="desktop-research.external-first" if capability_id == "desktop-research" else "fixture.impl",
        implementation_version="0.1.0",
        function_id="investigate" if capability_id == "desktop-research" else "run",
        execution_mode="real",
        context_pack_id=f"CTX-{run_id}",
        context_pack_digest="sha256:" + "3" * 64,
        project_ref=project_id,
        lineage_ref="LIN-1",
        snapshot_ref="SNP-1",
        snapshot_digest="sha256:" + "4" * 64,
        attempt=1,
        parent_run_id=None,
        status=RunStatus.PREPARED,
        prepared_at="2026-08-31T00:00:00Z",
    )


def _create_running(store, project_id: str, run_id: str, *, capability_id: str = "desktop-research"):
    prepared = _prepared_run(project_id, run_id, capability_id=capability_id)
    store.create_run(prepared)
    store.append_run_event(RunLifecycleEvent(
        run_id, 1, None, RunStatus.PREPARED, "2026-08-31T00:00:00Z", "prepared"
    ))
    running = prepared.with_status(RunStatus.RUNNING, started_at="2026-08-31T00:01:00Z")
    changed = store.transition_run(
        RunStatus.PREPARED,
        running,
        RunLifecycleEvent(
            run_id, 2, RunStatus.PREPARED, RunStatus.RUNNING,
            "2026-08-31T00:01:00Z", "started",
        ),
    )
    assert changed
    return running


class RunInspectionTests(unittest.TestCase):
    def _workspace(self, root: Path):
        config, profiles = _write_inputs(root)
        return LocalWorkspace.init(root / "workspace", config, profiles)

    def test_running_desktop_run_projection_is_bounded_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                app = opened.application
                run = _create_running(app.execution_store, opened.project_id, "RUN-INSPECT")
                app.execution_store.store_diagnostic("RUN-INSPECT", "desktop_research.normalization", {"issues": [{"code": "D1"}]})
                app.execution_store.store_diagnostic("RUN-INSPECT", "desktop_research.validation", {"issues": [{"code": "D2"}]})
                app.execution_store.put_bytes(
                    run,
                    role="desktop_research.original_capture",
                    media_type="text/plain",
                    content=b"original",
                    artifact_id="ART-1",
                    provenance={
                        "capture_id": "CAP-1",
                        "exact_locator": "https://example.test/source#section",
                        "path": "/internal/should-not-leak",
                        "nested": {
                            "local_path": "C:/internal/should-not-leak",
                            "storage_locator": "artifact://internal/should-not-leak",
                            "note": "keep this provenance note",
                        },
                    },
                )
                app.execution_store.put_bytes(
                    run,
                    role="desktop_research.text_rendition",
                    media_type="text/plain",
                    content=b"rendition",
                    artifact_id="ART-2",
                    provenance={"capture_id": "CAP-1"},
                )
                for index, outcome in enumerate(("source_captured", "blocked", "out_of_scope", "no_relevant_source"), start=1):
                    attempt_id = f"ATT-{index}"
                    app.operational_store.append(
                        run.run_id,
                        ATTEMPT_STARTED,
                        f"2026-08-31T00:0{index}:10Z",
                        {
                            "attempt_id": attempt_id,
                            "strategy": "fixture",
                            "coverage_dimension_ids": ["G1"],
                            "query_or_target": attempt_id,
                            "provider_or_tool": "fixture",
                            "target_locator": f"https://example.test/{index}",
                            "provenance": {},
                        },
                    )
                    app.operational_store.append(
                        run.run_id,
                        ATTEMPT_COMPLETED,
                        f"2026-08-31T00:0{index}:20Z",
                        {
                            "attempt_id": attempt_id,
                            "outcome": outcome,
                            "failure_or_blocking_reason": "blocked" if outcome == "blocked" else None,
                            "target_locator": f"https://example.test/{index}",
                            "resulting_capture_id": "CAP-1" if outcome == "source_captured" else None,
                            "provenance": {},
                        },
                    )
                app.operational_store.append(
                    run.run_id,
                    OPERATIONAL_TERMINATION,
                    "2026-08-31T00:09:00Z",
                    {"reason": "budget", "detail": "fixture", "coverage_dimension_ids": ["G1"]},
                )

                state_repo = app.state_repository
                lineage = state_repo.load_active_lineage_ref(opened.project_id)
                state = state_repo.load_state_view(opened.project_id, lineage)
                before = (
                    state.current_snapshot["id"],
                    state.current_snapshot["content_digest"],
                    app.execution_store.load_run(run.run_id),
                    app.execution_store.events_for(run.run_id),
                    app.execution_store.artifacts_for(run.run_id),
                    app.operational_store.events_for(run.run_id),
                )
                facade = LocalApplicationFacade.from_opened_workspace(opened)
                opened = None
                with patch("plugins.local_application.run_inspection_facade._RUN_INSPECTION_ITEM_LIMIT", 1), patch.object(
                    facade._application.execution_store,
                    "diagnose_integrity",
                    side_effect=AssertionError("run show must not call diagnose_integrity"),
                ), patch.object(
                    facade._application.execution_store,
                    "artifacts_for",
                    side_effect=AssertionError("run show must use bounded artifact metadata read"),
                ):
                    result = facade.show_run(run.run_id)
                self.assertEqual(result["run"]["status"], "RUNNING")
                self.assertIsNone(result["run"]["failure"])
                self.assertEqual(result["run"]["bindings"]["project_ref"], facade.project_id)
                self.assertEqual(len(result["diagnostics"]), 1)
                self.assertEqual(len(result["artifacts"]), 1)
                self.assertTrue(result["truncated"]["diagnostics"])
                self.assertTrue(result["truncated"]["artifacts"])
                self.assertTrue(result["truncated"]["retrieval_attempts"])
                self.assertNotIn("storage_locator", result["artifacts"][0])
                self.assertNotIn("content", result["artifacts"][0])
                provenance = result["artifacts"][0]["provenance"]
                self.assertEqual(provenance["exact_locator"], "https://example.test/source#section")
                self.assertNotIn("path", provenance)
                self.assertNotIn("local_path", provenance["nested"])
                self.assertNotIn("storage_locator", provenance["nested"])
                self.assertEqual(provenance["nested"]["note"], "keep this provenance note")
                summary = result["desktop_research"]["retrieval_attempt_summary"]
                self.assertEqual(summary["total"], 4)
                for outcome in ("source_captured", "blocked", "out_of_scope", "no_relevant_source"):
                    self.assertEqual(summary[outcome], 1)
                app = facade._application
                state_after = app.state_repository.load_state_view(
                    facade.project_id,
                    app.state_repository.load_active_lineage_ref(facade.project_id),
                )
                after = (
                    state_after.current_snapshot["id"],
                    state_after.current_snapshot["content_digest"],
                    app.execution_store.load_run(run.run_id),
                    app.execution_store.events_for(run.run_id),
                    app.execution_store.artifacts_for(run.run_id),
                    app.operational_store.events_for(run.run_id),
                )
                self.assertEqual(before, after)
                facade.close()
            finally:
                if opened is not None:
                    opened.close()

    def test_failed_and_completed_runs_survive_restart_and_cli_show(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            opened = self._workspace(root)
            workspace = opened.root
            try:
                store = opened.application.execution_store
                failed_running = _create_running(store, opened.project_id, "RUN-FAILED", capability_id="fixture")
                failed = failed_running.with_status(
                    RunStatus.FAILED,
                    completed_at="2026-08-31T00:02:00Z",
                    failure=ExecutionIssue("HANDOFF_INVALID", "fixture handoff binding error", False),
                )
                self.assertTrue(store.transition_run(
                    RunStatus.RUNNING,
                    failed,
                    RunLifecycleEvent(
                        failed.run_id, 3, RunStatus.RUNNING, RunStatus.FAILED,
                        "2026-08-31T00:02:00Z", "handoff invalid",
                    ),
                ))

                completed_running = _create_running(store, opened.project_id, "RUN-COMPLETED", capability_id="fixture")
                store.store_diagnostic(completed_running.run_id, "fixture.normalization", {"issues": [{"code": "WARN"}]})
                completed = completed_running.with_status(
                    RunStatus.COMPLETED,
                    completed_at="2026-08-31T00:03:00Z",
                    handoff_ref="HND-1",
                    handoff_digest="sha256:" + "5" * 64,
                )
                self.assertTrue(store.transition_run(
                    RunStatus.RUNNING,
                    completed,
                    RunLifecycleEvent(
                        completed.run_id, 3, RunStatus.RUNNING, RunStatus.COMPLETED,
                        "2026-08-31T00:03:00Z", "completed",
                    ),
                ))
            finally:
                opened.close()

            code, failed_show = _run_cli([
                "run", "show", "--workspace", str(workspace), "--run-id", "RUN-FAILED", "--json"
            ])
            self.assertEqual(code, 0)
            self.assertEqual(failed_show["run"]["status"], "FAILED")
            self.assertEqual(failed_show["run"]["failure"]["code"], "HANDOFF_INVALID")
            self.assertEqual(failed_show["lifecycle"][-1]["to_status"], "FAILED")

            code, completed_show = _run_cli([
                "run", "show", "--workspace", str(workspace), "--run-id", "RUN-COMPLETED", "--json"
            ])
            self.assertEqual(code, 0)
            self.assertEqual(completed_show["run"]["status"], "COMPLETED")
            self.assertIsNone(completed_show["run"]["failure"])
            self.assertEqual(completed_show["run"]["handoff"]["ref"], "HND-1")
            self.assertEqual(completed_show["diagnostics"][0]["kind"], "fixture.normalization")

    def test_unknown_wrong_project_and_store_read_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                run = _create_running(opened.application.execution_store, opened.project_id, "RUN-BINDING", capability_id="fixture")
                facade = LocalApplicationFacade(opened.application, opened.project_id)
                with self.assertRaises(LocalApplicationError) as unknown:
                    facade.show_run("RUN-MISSING")
                self.assertEqual(unknown.exception.code, "APPLICATION-RUN-001")

                wrong = LocalApplicationFacade(opened.application, "PRJ-OTHER")
                with self.assertRaises(LocalApplicationError) as binding:
                    wrong.show_run(run.run_id)
                self.assertEqual(binding.exception.code, "APPLICATION-RUN-BINDING-001")

                with patch.object(opened.application.execution_store, "events_for", side_effect=RuntimeError("SELECT secret_table")):
                    with self.assertRaises(LocalApplicationError) as corrupt:
                        facade.show_run(run.run_id)
                self.assertEqual(corrupt.exception.code, "APPLICATION-RUN-READ-001")
                self.assertNotIn("secret_table", corrupt.exception.message)
            finally:
                opened.close()


if __name__ == "__main__":
    unittest.main()
