from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.execution import CapabilityRunRecord, RunLifecycleEvent, RunStatus
from plugins.desktop_research import DesktopResearchCaptureService, DesktopResearchExternalAdapter
from plugins.desktop_research.attempts import ATTEMPT_COMPLETED, ATTEMPT_STARTED
from plugins.local_application import LocalApplicationFacade, LocalWorkspace
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


def _run_cli(argv: list[str]) -> tuple[int, str]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main(argv)
    return code, stream.getvalue()


def _create_running(store, project_id: str, run_id: str, prepared_at: str) -> CapabilityRunRecord:
    prepared = CapabilityRunRecord(
        run_id=run_id,
        invocation_id=f"INV-{run_id}",
        invocation_digest="sha256:" + "1" * 64,
        capability_id=DesktopResearchExternalAdapter.capability_id,
        capability_version=DesktopResearchExternalAdapter.capability_version,
        descriptor_digest="sha256:" + "2" * 64,
        implementation_id=DesktopResearchExternalAdapter.implementation_id,
        implementation_version=DesktopResearchExternalAdapter.implementation_version,
        function_id="investigate",
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
        prepared_at=prepared_at,
    )
    store.create_run(prepared)
    store.append_run_event(RunLifecycleEvent(
        run_id,
        1,
        None,
        RunStatus.PREPARED,
        prepared_at,
        "prepared",
    ))
    started_at = prepared_at.replace("00Z", "10Z")
    running = prepared.with_status(RunStatus.RUNNING, started_at=started_at)
    changed = store.transition_run(
        RunStatus.PREPARED,
        running,
        RunLifecycleEvent(
            run_id,
            2,
            RunStatus.PREPARED,
            RunStatus.RUNNING,
            started_at,
            "started",
        ),
    )
    assert changed
    return running


def _capture(
    store,
    run: CapabilityRunRecord,
    capture_id: str,
    original: bytes,
    locator: str,
    *,
    acquired_at: str,
):
    return DesktopResearchCaptureService(store).capture(
        run,
        capture_id=capture_id,
        source_category="public_web",
        exact_locator=locator,
        acquired_at=acquired_at,
        original_bytes=original,
        original_media_type="application/pdf",
        text_rendition=f"UTF-8 rendition for {capture_id}",
        provenance={"fixture": "external-material-inventory"},
    )


def _failed_attempt(operational_store, run_id: str, attempt_id: str) -> None:
    operational_store.append(
        run_id,
        ATTEMPT_STARTED,
        "2026-09-01T00:00:20Z",
        {
            "attempt_id": attempt_id,
            "strategy": "fixture failure",
            "coverage_dimension_ids": ["G1"],
            "query_or_target": "no material",
            "provider_or_tool": "fixture",
            "target_locator": "https://example.test/unavailable",
            "provenance": {},
        },
    )
    operational_store.append(
        run_id,
        ATTEMPT_COMPLETED,
        "2026-09-01T00:00:30Z",
        {
            "attempt_id": attempt_id,
            "outcome": "failed",
            "failure_or_blocking_reason": "fixture failure",
            "target_locator": "https://example.test/unavailable",
            "resulting_capture_id": None,
            "provenance": {},
        },
    )


class ExternalMaterialInventoryTests(unittest.TestCase):
    def _workspace(self, root: Path):
        config, profiles = _write_inputs(root)
        return LocalWorkspace.init(root / "workspace", config, profiles)

    def test_empty_workspace_and_attempt_only_are_normal_empty_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                facade = LocalApplicationFacade(opened.application, opened.project_id)
                self.assertEqual(facade.list_external_materials()["materials"], [])

                run = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-ATTEMPT-ONLY",
                    "2026-09-01T00:00:00Z",
                )
                _failed_attempt(opened.application.operational_store, run.run_id, "ATT-FAILED")
                result = facade.list_external_materials()
                self.assertEqual(result["status"], "OK")
                self.assertEqual(result["materials"], [])
            finally:
                opened.close()

    def test_one_capture_projects_original_rendition_locator_and_run(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                run = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-ONE",
                    "2026-09-01T00:01:00Z",
                )
                capture = _capture(
                    opened.application.execution_store,
                    run,
                    "CAP-ONE",
                    b"same original bytes",
                    "https://example.test/source-one",
                    acquired_at="2026-09-01T00:01:20Z",
                )
                result = LocalApplicationFacade(
                    opened.application, opened.project_id
                ).list_external_materials()
                self.assertEqual(len(result["materials"]), 1)
                material = result["materials"][0]
                self.assertEqual(material["material_id"], capture["original_capture"]["content_digest"])
                self.assertEqual(material["original_digest"], capture["original_capture"]["content_digest"])
                self.assertEqual(material["run_ids"], [run.run_id])
                self.assertEqual(material["source_locators"], ["https://example.test/source-one"])
                self.assertEqual(material["original"]["artifact_id"], capture["original_capture"]["content_reference"])
                self.assertEqual(material["renditions"][0]["artifact_id"], capture["text_rendition"]["content_reference"])
                self.assertEqual(material["renditions"][0]["kind"], "utf8_text")
                self.assertEqual(material["renditions"][0]["encoding"], "UTF-8")
                self.assertEqual(material["captures"][0]["capture_id"], "CAP-ONE")
                self.assertEqual(material["captures"][0]["source_locator"], "https://example.test/source-one")
            finally:
                opened.close()

    def test_same_original_bytes_across_runs_deduplicates_by_digest_only(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                first = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-A",
                    "2026-09-01T00:01:00Z",
                )
                second = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-B",
                    "2026-09-01T00:02:00Z",
                )
                first_capture = _capture(
                    opened.application.execution_store,
                    first,
                    "CAP-A",
                    b"identical original",
                    "https://example.test/one",
                    acquired_at="2026-09-01T00:01:20Z",
                )
                second_capture = _capture(
                    opened.application.execution_store,
                    second,
                    "CAP-B",
                    b"identical original",
                    "https://mirror.test/two",
                    acquired_at="2026-09-01T00:02:20Z",
                )
                self.assertEqual(
                    first_capture["original_capture"]["content_digest"],
                    second_capture["original_capture"]["content_digest"],
                )

                result = LocalApplicationFacade(
                    opened.application, opened.project_id
                ).list_external_materials()
                self.assertEqual(len(result["materials"]), 1)
                material = result["materials"][0]
                self.assertEqual(material["run_ids"], ["RUN-A", "RUN-B"])
                self.assertEqual(
                    material["source_locators"],
                    ["https://example.test/one", "https://mirror.test/two"],
                )
                self.assertEqual(len(material["captures"]), 2)
            finally:
                opened.close()

    def test_same_locator_with_different_original_bytes_remains_two_materials(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                first = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-A",
                    "2026-09-01T00:01:00Z",
                )
                second = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-B",
                    "2026-09-01T00:02:00Z",
                )
                locator = "https://example.test/changing-source"
                _capture(
                    opened.application.execution_store,
                    first,
                    "CAP-A",
                    b"version A",
                    locator,
                    acquired_at="2026-09-01T00:01:20Z",
                )
                _capture(
                    opened.application.execution_store,
                    second,
                    "CAP-B",
                    b"version B",
                    locator,
                    acquired_at="2026-09-01T00:02:20Z",
                )
                materials = LocalApplicationFacade(
                    opened.application, opened.project_id
                ).list_external_materials()["materials"]
                self.assertEqual(len(materials), 2)
                self.assertNotEqual(materials[0]["material_id"], materials[1]["material_id"])
                self.assertTrue(all(item["source_locators"] == [locator] for item in materials))
            finally:
                opened.close()

    def test_captured_material_excludes_failed_attempt_and_read_is_deterministic_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            opened = self._workspace(Path(temp))
            try:
                captured_run = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-CAPTURED",
                    "2026-09-01T00:01:00Z",
                )
                failed_run = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-FAILED-ATTEMPT",
                    "2026-09-01T00:02:00Z",
                )
                _capture(
                    opened.application.execution_store,
                    captured_run,
                    "CAP-X",
                    b"captured X",
                    "https://example.test/x",
                    acquired_at="2026-09-01T00:01:20Z",
                )
                _failed_attempt(
                    opened.application.operational_store,
                    failed_run.run_id,
                    "ATT-NO-CAPTURE",
                )

                state_repo = opened.application.state_repository
                lineage = state_repo.load_active_lineage_ref(opened.project_id)
                state = state_repo.load_state_view(opened.project_id, lineage)
                before = (
                    state.current_snapshot["id"],
                    state.current_snapshot["content_digest"],
                    opened.application.execution_store.load_run(captured_run.run_id),
                    opened.application.execution_store.load_run(failed_run.run_id),
                    opened.application.execution_store.events_for(captured_run.run_id),
                    opened.application.execution_store.events_for(failed_run.run_id),
                    opened.application.execution_store.artifacts_for(captured_run.run_id),
                    opened.application.execution_store.artifacts_for(failed_run.run_id),
                    opened.application.operational_store.events_for(failed_run.run_id),
                )

                facade = LocalApplicationFacade(opened.application, opened.project_id)
                first = facade.list_external_materials()
                second = facade.list_external_materials()
                self.assertEqual(first, second)
                self.assertEqual(len(first["materials"]), 1)
                self.assertEqual(first["materials"][0]["run_ids"], [captured_run.run_id])

                state_after = state_repo.load_state_view(opened.project_id, lineage)
                after = (
                    state_after.current_snapshot["id"],
                    state_after.current_snapshot["content_digest"],
                    opened.application.execution_store.load_run(captured_run.run_id),
                    opened.application.execution_store.load_run(failed_run.run_id),
                    opened.application.execution_store.events_for(captured_run.run_id),
                    opened.application.execution_store.events_for(failed_run.run_id),
                    opened.application.execution_store.artifacts_for(captured_run.run_id),
                    opened.application.execution_store.artifacts_for(failed_run.run_id),
                    opened.application.operational_store.events_for(failed_run.run_id),
                )
                self.assertEqual(before, after)
            finally:
                opened.close()

    def test_cli_human_and_json_survive_workspace_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            opened = self._workspace(root)
            workspace = opened.root
            try:
                run = _create_running(
                    opened.application.execution_store,
                    opened.project_id,
                    "RUN-CLI",
                    "2026-09-01T00:01:00Z",
                )
                capture = _capture(
                    opened.application.execution_store,
                    run,
                    "CAP-CLI",
                    b"cli source",
                    "https://example.test/cli-source",
                    acquired_at="2026-09-01T00:01:20Z",
                )
            finally:
                opened.close()

            code, human = _run_cli([
                "external", "materials", "list", "--workspace", str(workspace)
            ])
            self.assertEqual(code, 0)
            self.assertIn("Captured external materials: 1", human)
            self.assertIn("https://example.test/cli-source", human)
            self.assertIn("RUN-CLI", human)
            self.assertIn(capture["original_capture"]["content_digest"], human)

            code, raw_json = _run_cli([
                "external", "materials", "list", "--workspace", str(workspace), "--json"
            ])
            self.assertEqual(code, 0)
            payload = json.loads(raw_json)
            self.assertEqual(payload["status"], "OK")
            self.assertEqual(len(payload["materials"]), 1)
            self.assertEqual(payload["materials"][0]["run_ids"], ["RUN-CLI"])


if __name__ == "__main__":
    unittest.main()
