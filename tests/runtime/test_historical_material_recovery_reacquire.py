from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import subprocess
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.material_reacquisition_facade import (
    MaterialReacquisitionRetrievalError,
    RetrievedMaterial,
    _regenerate_text_rendition,
    material_reacquisition_payload,
)
from plugins.local_application.cli import main as cli_main
from plugins.local_execution_store import child_runs_for_parent
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


def _run_cli(argv):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = cli_main([str(item) for item in argv])
    return code, json.loads(stream.getvalue())


def _submit_reacquire(workspace, *, run_id: str, capture_id: str, kind: str = "original"):
    action_path = workspace / "material-reacquire.json"
    action_path.write_text(
        json.dumps(
            {
                "action_type": "desktop_research.material.reacquire",
                "payload": {
                    "historical_run_id": run_id,
                    "capture_id": capture_id,
                    "kind": kind,
                },
            }
        ),
        encoding="utf-8",
    )
    try:
        return _run_cli(
            ["action", "submit", "--workspace", workspace, "--json", action_path]
        )
    finally:
        action_path.unlink(missing_ok=True)


class HistoricalMaterialReacquisitionTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _remove_producer_candidate(facade, case):
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?",
            (case["proposal"]["proposal_id"],),
        )

    @staticmethod
    def _missing_original(facade, case):
        store = facade._application.execution_store
        original = next(
            artifact
            for artifact in store.artifacts_for(case["run_id"])
            if artifact.role == "desktop_research.original_capture"
            and artifact.provenance.get("capture_id") == "CAP-1"
        )
        store._locator_path(original.storage_locator, original.digest).unlink()
        return original

    @staticmethod
    def _missing_rendition(facade, case):
        store = facade._application.execution_store
        rendition = next(
            artifact
            for artifact in store.artifacts_for(case["run_id"])
            if artifact.role == "desktop_research.text_rendition"
            and artifact.provenance.get("capture_id") == "CAP-1"
        )
        content = store.load_artifact(rendition.artifact_id).content
        store._locator_path(rendition.storage_locator, rendition.digest).unlink()
        return rendition, content

    @staticmethod
    def _snapshot(facade):
        repo = facade._application.state_repository
        return repo.load_state_view(
            facade.project_id, repo.load_active_lineage_ref(facade.project_id)
        ).current_snapshot

    def test_public_payload_is_authority_safe_for_original_and_rendition(self):
        self.assertEqual(
            material_reacquisition_payload(
                {
                    "historical_run_id": "RUN-1",
                    "capture_id": "CAP-1",
                    "kind": "original",
                }
            ),
            {
                "historical_run_id": "RUN-1",
                "capture_id": "CAP-1",
                "kind": "original",
            },
        )
        for extra in ("exact_locator", "expected_digest", "expected_size", "artifact_id"):
            with self.assertRaises(ValueError):
                material_reacquisition_payload(
                    {
                        "historical_run_id": "RUN-1",
                        "capture_id": "CAP-1",
                        "kind": "original",
                        extra: "caller-controlled",
                    }
                )
        self.assertEqual(
            material_reacquisition_payload(
                {
                    "historical_run_id": "RUN-1",
                    "capture_id": "CAP-1",
                    "kind": "rendition",
                }
            )["kind"],
            "rendition",
        )
        with self.assertRaises(ValueError):
            material_reacquisition_payload(
                {
                    "historical_run_id": "RUN-1",
                    "capture_id": "CAP-1",
                    "kind": "unsupported",
                }
            )

    def test_identical_reacquisition_restores_without_rewriting_history_and_is_idempotent(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            state_before = self._snapshot(facade)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            seen = []

            def retrieve(locator, *, max_bytes):
                seen.append((locator, max_bytes))
                return RetrievedMaterial(
                    b"<html>fixed source body</html>",
                    "text/html",
                    "https://example.test/source-a#section-1",
                    "fake-http",
                    200,
                )

            facade.close(); facade = None
            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                side_effect=retrieve,
            ):
                code, result = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1"
                )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "SUCCEEDED")
            data = result["data"]
            self.assertEqual(data["status"], "IDENTICAL_REACQUISITION")
            self.assertEqual(seen[0][0], "https://example.test/source-a#section-1")
            self.assertFalse(data["historical_metadata_rewritten"])
            self.assertFalse(data["research_state_mutation_performed"])
            child_id = data["reacquisition_run_id"]

            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                self.assertEqual(
                    reopened._application.execution_store.diagnose_artifact_content(original.artifact_id)["status"],
                    "verified",
                )
                self.assertEqual(
                    reopened._application.execution_store.load_run(case["run_id"]), historical_before
                )
                self.assertEqual(self._snapshot(reopened), state_before)
                children_before = child_runs_for_parent(
                    reopened._application.execution_store, case["run_id"], limit=100
                )
                child = reopened._application.execution_store.load_run(child_id)
                self.assertEqual(child.status.value, "COMPLETED")
                self.assertEqual(child.parent_run_id, case["run_id"])

            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                side_effect=AssertionError("idempotent repeat must not fetch"),
            ):
                code, repeated = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1"
                )
            self.assertEqual(code, 0)
            self.assertEqual(repeated["data"]["status"], "ALREADY_VERIFIED")
            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                self.assertEqual(
                    child_runs_for_parent(reopened._application.execution_store, case["run_id"], limit=100),
                    children_before,
                )
        finally:
            if facade is not None:
                facade.close()

    def test_changed_bytes_become_new_material_and_do_not_unblock_historical_recovery(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            state_before = self._snapshot(facade)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            facade.close(); facade = None

            changed = b"<html>changed source body</html>"
            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                return_value=RetrievedMaterial(
                    changed,
                    "text/html",
                    "https://cdn.example.test/source-a-v2",
                    "fake-http",
                    200,
                ),
            ):
                code, result = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1"
                )
            self.assertEqual(code, 0)
            data = result["data"]
            self.assertEqual(data["status"], "NEW_MATERIAL_VERSION")
            self.assertFalse(data["old_material_restored"])
            self.assertTrue(data["requires_new_canonical_research_result"])

            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(store.diagnose_artifact_content(original.artifact_id)["status"], "content_missing")
                self.assertEqual(store.load_run(case["run_id"]), historical_before)
                self.assertEqual(self._snapshot(reopened), state_before)
                new_artifact = store.load_artifact(data["new_artifact_id"])
                self.assertEqual(new_artifact.content, changed)

            code, old_run = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", case["run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(old_run["finding_recovery"]["recovery_class"], "material_recovery_required")
            code, child_run = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", data["reacquisition_run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(child_run["run"]["status"], "COMPLETED")
            self.assertEqual(child_run["artifacts"][0]["digest"], data["actual_digest"])
            self.assertEqual(
                child_run["artifacts"][0]["provenance"]["historical_artifact_id"], original.artifact_id
            )
        finally:
            if facade is not None:
                facade.close()

    def test_retrieval_failure_is_retained_as_failed_child_execution(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            facade.close(); facade = None
            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                side_effect=MaterialReacquisitionRetrievalError("HTTP 403 blocked"),
            ):
                code, result = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1"
                )
            self.assertEqual(code, 0)
            data = result["data"]
            self.assertEqual(data["status"], "REACQUISITION_FAILED")
            self.assertIn("403", data["failure_reason"])
            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(store.load_run(case["run_id"]), historical_before)
                self.assertEqual(store.diagnose_artifact_content(original.artifact_id)["status"], "content_missing")
            code, child_run = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", data["reacquisition_run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(child_run["run"]["status"], "FAILED")
            self.assertEqual(child_run["diagnostics"][0]["payload"]["status"], "REACQUISITION_FAILED")
        finally:
            if facade is not None:
                facade.close()

    def test_mra5_original_then_rendition_exact_reacquisition_reaches_proposal_rematerializable(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            rendition, exact_rendition = self._missing_rendition(facade, case)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            state_before = self._snapshot(facade)
            facade.close(); facade = None

            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                return_value=RetrievedMaterial(
                    b"<html>fixed source body</html>",
                    "text/html",
                    "https://example.test/source-a#section-1",
                    "fixture-http",
                    200,
                ),
            ):
                code, original_result = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1", kind="original"
                )
            self.assertEqual(code, 0)
            self.assertEqual(original_result["data"]["status"], "IDENTICAL_REACQUISITION")

            code, after_original = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", case["run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                after_original["finding_recovery"]["recovery_class"],
                "material_recovery_required",
            )
            self.assertEqual(
                after_original["finding_recovery"]["recovery_failure_details"]["artifact_kind"],
                "rendition",
            )

            with patch(
                "plugins.local_application.material_reacquisition_facade._regenerate_text_rendition",
                return_value=RetrievedMaterial(
                    exact_rendition,
                    "text/plain",
                    "https://example.test/source-a#section-1",
                    "fixture-rendition-generator",
                    None,
                ),
            ):
                code, rendition_result = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1", kind="rendition"
                )
            self.assertEqual(code, 0)
            self.assertEqual(rendition_result["data"]["status"], "IDENTICAL_REACQUISITION")

            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(store.diagnose_artifact_content(original.artifact_id)["status"], "verified")
                self.assertEqual(store.diagnose_artifact_content(rendition.artifact_id)["status"], "verified")
                self.assertEqual(store.load_run(case["run_id"]), historical_before)
                self.assertEqual(self._snapshot(reopened), state_before)

            code, shown = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", case["run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                shown["finding_recovery"]["recovery_class"],
                "proposal_rematerializable",
            )
        finally:
            if facade is not None:
                facade.close()

    def test_exact_rendition_regeneration_restores_and_unblocks_result_rematerialization(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            rendition, exact_rendition = self._missing_rendition(facade, case)
            state_before = self._snapshot(facade)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            facade.close(); facade = None

            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                side_effect=AssertionError("rendition regeneration must reuse the verified historical original"),
            ), patch(
                "plugins.local_application.material_reacquisition_facade._regenerate_text_rendition",
                return_value=RetrievedMaterial(
                    exact_rendition,
                    "text/plain",
                    "https://example.test/source-a#section-1",
                    "fixture-rendition-generator",
                    None,
                ),
            ):
                code, result = _submit_reacquire(
                    self.workspace,
                    run_id=case["run_id"],
                    capture_id="CAP-1",
                    kind="rendition",
                )
            self.assertEqual(code, 0)
            data = result["data"]
            self.assertEqual(data["status"], "IDENTICAL_REACQUISITION")
            self.assertEqual(
                data["reacquisition_mode"],
                "regenerated_from_verified_historical_original",
            )
            self.assertEqual(data["kind"], "rendition")
            self.assertEqual(data["actual_digest"], rendition.digest)
            self.assertEqual(data["actual_size"], rendition.size)
            self.assertEqual(
                data["derivation_source"]["artifact_id"],
                f"{case['run_id']}.CAP-1.original",
            )

            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(
                    store.diagnose_artifact_content(rendition.artifact_id)["status"],
                    "verified",
                )
                self.assertEqual(store.load_run(case["run_id"]), historical_before)
                self.assertEqual(self._snapshot(reopened), state_before)

            code, shown = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", case["run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                shown["finding_recovery"]["recovery_class"],
                "proposal_rematerializable",
            )
        finally:
            if facade is not None:
                facade.close()

    def test_changed_rendition_becomes_new_version_and_old_rendition_stays_missing(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            rendition, _exact_rendition = self._missing_rendition(facade, case)
            state_before = self._snapshot(facade)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            changed = b"Current regenerated rendition differs from historical bytes.\n"
            facade.close(); facade = None

            with patch(
                "plugins.local_application.material_reacquisition_facade._regenerate_text_rendition",
                return_value=RetrievedMaterial(
                    changed,
                    "text/plain",
                    "https://example.test/source-a#section-1",
                    "fixture-rendition-generator",
                    None,
                ),
            ):
                code, result = _submit_reacquire(
                    self.workspace,
                    run_id=case["run_id"],
                    capture_id="CAP-1",
                    kind="rendition",
                )
            self.assertEqual(code, 0)
            data = result["data"]
            self.assertEqual(data["status"], "NEW_MATERIAL_VERSION")
            self.assertEqual(data["new_material_kind"], "rendition")
            self.assertIn("new_rendition_version_id", data)
            self.assertFalse(data["old_material_restored"])
            self.assertTrue(data["requires_new_canonical_research_result"])

            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(
                    store.diagnose_artifact_content(rendition.artifact_id)["status"],
                    "content_missing",
                )
                self.assertEqual(store.load_run(case["run_id"]), historical_before)
                self.assertEqual(self._snapshot(reopened), state_before)
                new_meta = next(
                    artifact
                    for artifact in store.artifacts_for(data["reacquisition_run_id"])
                    if artifact.artifact_id == data["new_artifact_id"]
                )
                self.assertEqual(new_meta.role, "desktop_research.reacquired_rendition")
                self.assertEqual(store.load_artifact(new_meta.artifact_id).content, changed)
                self.assertEqual(
                    new_meta.provenance["relation"],
                    "regenerated_version_of_historical_rendition",
                )

            code, shown = _run_cli(
                ["run", "show", "--workspace", self.workspace, "--run-id", case["run_id"], "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                shown["finding_recovery"]["recovery_class"],
                "material_recovery_required",
            )
        finally:
            if facade is not None:
                facade.close()

    def test_rendition_regeneration_failure_is_recorded_without_history_mutation(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            rendition, _exact_rendition = self._missing_rendition(facade, case)
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            state_before = self._snapshot(facade)
            facade.close(); facade = None

            with patch(
                "plugins.local_application.material_reacquisition_facade._regenerate_text_rendition",
                side_effect=MaterialReacquisitionRetrievalError("no exact-safe rendition provider"),
            ):
                code, result = _submit_reacquire(
                    self.workspace,
                    run_id=case["run_id"],
                    capture_id="CAP-1",
                    kind="rendition",
                )
            self.assertEqual(code, 0)
            data = result["data"]
            self.assertEqual(data["status"], "REACQUISITION_FAILED")
            self.assertIn("rendition provider", data["failure_reason"])
            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(
                    store.diagnose_artifact_content(rendition.artifact_id)["status"],
                    "content_missing",
                )
                self.assertEqual(store.load_run(case["run_id"]), historical_before)
                self.assertEqual(self._snapshot(reopened), state_before)
                child = store.load_run(data["reacquisition_run_id"])
                self.assertEqual(child.status.value, "FAILED")
        finally:
            if facade is not None:
                facade.close()

    def test_rendition_regeneration_requires_verified_historical_original(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            rendition, _exact_rendition = self._missing_rendition(facade, case)
            facade.close(); facade = None
            with patch(
                "plugins.local_application.material_reacquisition_facade._regenerate_text_rendition",
                side_effect=AssertionError("must fail before generation"),
            ):
                code, result = _submit_reacquire(
                    self.workspace,
                    run_id=case["run_id"],
                    capture_id="CAP-1",
                    kind="rendition",
                )
            self.assertEqual(code, 0)
            data = result["data"]
            self.assertEqual(data["status"], "REACQUISITION_FAILED")
            self.assertIn("historical original", data["failure_reason"])
            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                store = reopened._application.execution_store
                self.assertEqual(store.diagnose_artifact_content(original.artifact_id)["status"], "content_missing")
                self.assertEqual(store.diagnose_artifact_content(rendition.artifact_id)["status"], "content_missing")
        finally:
            if facade is not None:
                facade.close()

    def test_pdf_rendition_generator_is_bounded_and_does_not_use_shell(self):
        rendered = b"deterministic utf-8 rendition\n"

        class FakeProcess:
            def __init__(self, content):
                self.stdout = io.BytesIO(content)
                self.killed = False
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

        created = []

        def fake_popen(command, **kwargs):
            self.assertEqual(command[1:3], ["-enc", "UTF-8"])
            self.assertEqual(command[-1], "-")
            self.assertNotIn("shell", kwargs)
            self.assertIs(kwargs["stdout"], subprocess.PIPE)
            self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
            process = FakeProcess(rendered)
            created.append(process)
            return process

        with patch(
            "plugins.local_application.material_reacquisition_facade.shutil.which",
            return_value="pdftotext",
        ), patch(
            "plugins.local_application.material_reacquisition_facade.subprocess.Popen",
            side_effect=fake_popen,
        ):
            result = _regenerate_text_rendition(
                b"%PDF-1.7 fixture",
                "application/pdf",
                "https://example.test/source.pdf",
                max_bytes=1024,
            )
        self.assertEqual(result.content, rendered)
        self.assertEqual(result.media_type, "text/plain")
        self.assertEqual(result.provider, "pdftotext")
        self.assertFalse(created[0].killed)

    def test_read_diagnosis_guides_recover_or_reacquire_without_network(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            self._missing_original(facade, case)
            facade.close(); facade = None
            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                side_effect=AssertionError("run show must never retrieve"),
            ):
                code, shown = _run_cli(
                    ["run", "show", "--workspace", self.workspace, "--run-id", case["run_id"], "--json"]
                )
            self.assertEqual(code, 0)
            actions = shown["finding_recovery"]["recovery_failure_details"]["available_actions"]
            self.assertEqual(
                [item["action_type"] for item in actions],
                ["desktop_research.material.recover", "desktop_research.material.reacquire"],
            )
        finally:
            if facade is not None:
                facade.close()

    def test_ablation_equivalence_guard_removal_breaks_changed_byte_acceptance(self):
        facade, case = self._prepare_case()
        try:
            self._remove_producer_candidate(facade, case)
            original = self._missing_original(facade, case)
            facade.close(); facade = None
            with patch(
                "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
                return_value=RetrievedMaterial(
                    b"changed bytes",
                    "text/html",
                    "https://example.test/source-a#section-1",
                    "fake-http",
                    200,
                ),
            ), patch(
                "plugins.local_application.material_reacquisition_facade._historical_equivalent",
                return_value=True,
            ):
                code, result = _submit_reacquire(
                    self.workspace, run_id=case["run_id"], capture_id="CAP-1"
                )
            self.assertEqual(code, 0)
            # With only the classification guard ablated, the MRA5 changed-byte
            # acceptance no longer succeeds: the independent #156 exact-byte
            # installer fails closed instead of allowing history corruption.
            self.assertEqual(result["data"]["status"], "REACQUISITION_FAILED")
            with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                self.assertEqual(
                    reopened._application.execution_store.diagnose_artifact_content(original.artifact_id)["status"],
                    "content_missing",
                )
        finally:
            if facade is not None:
                facade.close()
