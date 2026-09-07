from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from core.execution import RunStatus
from plugins.local_application.cli import main as cli_main
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
import test_external_desktop_research_intake as intake


class Issue92ExternalSubmissionPreflightTests(intake.ExternalDesktopResearchIntakeTests):
    """Issue #92 D1-D6 acceptance over the public Application Facade."""

    @staticmethod
    def research_result(handoff: dict, extension: dict) -> dict:
        outputs = deepcopy(handoff["outputs"])
        capture_ids = [item["capture_id"] for item in outputs.pop("source_captures")]
        citations = [
            {key: item[key] for key in (
                "citation_id", "handoff_output_kind", "handoff_output_id",
                "capture_id", "excerpt", "excerpt_locator",
            )}
            for item in extension["citation_details"]
        ]
        links = []
        for item in extension["search_trace"]["entries"]:
            link = {
                "attempt_id": item["trace_entry_id"],
                "related_handoff_output_ids": deepcopy(item["related_handoff_output_ids"]),
            }
            if "notes" in item:
                link["notes"] = item["notes"]
            links.append(link)
        return {
            "validation": deepcopy(handoff["validation"]),
            "outputs": outputs,
            "capture_ids": capture_ids,
            "citation_details": citations,
            "search_trace": {"entries": links},
            "null_results": deepcopy(extension["null_results"]),
            "evidence_gap_assessments": deepcopy(extension["evidence_gap_assessments"]),
            "coverage_assessment": deepcopy(extension["coverage_assessment"]),
            "candidate_next_method_ids": deepcopy(extension["candidate_next_method_ids"]),
        }

    def prepared(self, root: Path, facade: LocalApplicationFacade):
        run_id = self.prepare(facade)["run_id"]
        facade.start_external_retrieval_attempt(run_id, {
            "attempt_id": "ATT-1", "strategy": "support search",
            "coverage_dimension_ids": ["COV-SUPPORT"],
            "target_locator": "https://example.test/source-a",
        })
        self.write_capture_files(root)
        capture = facade.capture_external_source(run_id, {
            "capture_id": "CAP-1", "source_category": "other",
            "exact_locator": "https://example.test/source-a#section-1",
            "acquired_at": "2026-08-31T00:00:00Z",
            "original_file": "captures/raw/source-a.html",
            "original_media_type": "text/html",
            "text_rendition_file": "captures/text/source-a.txt",
        })["capture"]
        facade.complete_external_retrieval_attempt(run_id, {
            "attempt_id": "ATT-1", "outcome": "source_captured",
            "resulting_capture_id": "CAP-1",
        })
        facade.start_external_retrieval_attempt(run_id, {
            "attempt_id": "ATT-2", "strategy": "counter search",
            "coverage_dimension_ids": ["COV-COUNTER"],
        })
        facade.complete_external_retrieval_attempt(run_id, {
            "attempt_id": "ATT-2", "outcome": "no_relevant_source",
        })
        handoff, extension = intake.golden_submission(facade._application, run_id, capture)
        return run_id, self.research_result(handoff, extension), capture

    def assert_running(self, app, run_id: str):
        run = app.execution_store.load_run(run_id)
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertIsNone(run.handoff_ref)
        self.assertEqual(len(app.execution_store.artifacts_for(run_id)), 2)
        self.assertEqual(len(app.operational_store.events_for(run_id)), 4)

    def test_d1_assembled_collect_uses_persisted_bindings_and_is_candidate_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, result_input, _ = self.prepared(root, facade)
                before = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                preflight = facade.preflight_external(run_id, {"research_result": result_input})
                self.assertEqual((preflight["status"], preflight["run_status"]), ("PREFLIGHT_OK", "RUNNING"))
                self.assertNotIn("input_pins", result_input)
                collected = facade.collect_external(run_id, {"research_result": result_input})
                after = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                self.assertEqual(collected["execution_result"]["run"]["status"], "COMPLETED")
                self.assertTrue(collected["execution_result"]["state_delta_proposal"]["candidate_only"])
                self.assertEqual((before["id"], before["content_digest"]), (after["id"], after["content_digest"]))
            finally: facade.close()

    def test_d2_preflight_survives_process_style_reopen_without_committing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            run_id, result_input, _ = self.prepared(root, facade)
            facade.close()
            reopened_app = LocalResearchApplication(
                root / ".research-loom", resolver=intake.NullResolver(),
                effective_profile_set_provider=intake.profile_provider,
            )
            reopened = LocalApplicationFacade(reopened_app, "PRJ-1", workspace_root=root)
            try:
                result = reopened.preflight_external(run_id, {"research_result": result_input})
                self.assertEqual((result["status"], result["run_status"]), ("PREFLIGHT_OK", "RUNNING"))
                self.assert_running(reopened_app, run_id)
            finally: reopened.close()

    def test_d3_reference_citation_and_coverage_errors_are_correctable_on_same_run(self):
        mutators = (
            lambda value: value["outputs"]["evidence_candidates"][0]["source_basis"].update(capture_id="CAP-MISSING"),
            lambda value: value["citation_details"][0].update(excerpt="not present in captured text"),
            lambda value: value["coverage_assessment"]["dimensions"][0].update(dimension_id="COV-UNKNOWN"),
        )
        for mutate in mutators:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); app, facade = self.make_facade(root)
                try:
                    run_id, valid, _ = self.prepared(root, facade)
                    broken = deepcopy(valid); mutate(broken)
                    rejected = facade.collect_external(run_id, {"research_result": broken})
                    self.assertTrue(rejected["execution_result"]["issues"])
                    self.assert_running(app, run_id)
                    accepted = facade.collect_external(run_id, {"research_result": valid})
                    self.assertEqual(accepted["execution_result"]["run"]["status"], "COMPLETED")
                finally: facade.close()

    def test_d4_internal_fields_and_persisted_blob_damage_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                for field in ("run_id", "project_id", "input_pins", "execution_mode"):
                    broken = deepcopy(valid); broken[field] = {} if field == "input_pins" else "wrong"
                    with self.subTest(field=field), self.assertRaises(LocalApplicationError) as caught:
                        facade.preflight_external(run_id, {"research_result": broken})
                    self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-SUBMISSION-001")
                original = next(x for x in app.execution_store.artifacts_for(run_id) if x.role.endswith("original_capture"))
                blob = app.execution_store._locator_path(original.storage_locator, original.digest)
                data = blob.read_bytes(); blob.write_bytes(bytes([data[0] ^ 1]) + data[1:])
                with self.assertRaises(LocalApplicationError) as corrupt:
                    facade.collect_external(run_id, {"research_result": valid})
                self.assertEqual(corrupt.exception.code, "APPLICATION-EXTERNAL-INTEGRITY-001")
                self.assert_running(app, run_id)
                blob.unlink()
                with self.assertRaises(LocalApplicationError) as missing:
                    facade.preflight_external(run_id, {"research_result": valid})
                self.assertEqual(missing.exception.code, "APPLICATION-EXTERNAL-INTEGRITY-001")
            finally: facade.close()

    def test_d5_final_collect_revalidates_changed_input_bytes_and_run_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                self.assertEqual(facade.preflight_external(run_id, {"research_result": valid})["status"], "PREFLIGHT_OK")
                changed = deepcopy(valid); changed["citation_details"][0]["excerpt"] = "not captured"
                self.assertTrue(facade.collect_external(run_id, {"research_result": changed})["execution_result"]["issues"])
                self.assert_running(app, run_id)
                original = next(x for x in app.execution_store.artifacts_for(run_id) if x.role.endswith("original_capture"))
                blob = app.execution_store._locator_path(original.storage_locator, original.digest)
                data = blob.read_bytes(); blob.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
                with self.assertRaises(LocalApplicationError) as corrupt:
                    facade.collect_external(run_id, {"research_result": valid})
                self.assertEqual(corrupt.exception.code, "APPLICATION-EXTERNAL-INTEGRITY-001")
            finally: facade.close()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                self.assertEqual(facade.preflight_external(run_id, {"research_result": valid})["status"], "PREFLIGHT_OK")
                app.capability_execution_service.abort(run_id, reason="D5 concurrent terminalization")
                with self.assertRaises(LocalApplicationError) as terminal:
                    facade.collect_external(run_id, {"research_result": valid})
                self.assertEqual(terminal.exception.code, "APPLICATION-EXTERNAL-RUN-STATE-001")
            finally: facade.close()

    def test_d6_legacy_collect_and_formal_rejected_result_remain_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, _, capture = self.prepared(root, facade)
                handoff, extension = intake.golden_submission(app, run_id, capture)
                accepted = facade.collect_external(run_id, {"handoff": handoff, "extension": extension})
                self.assertEqual(accepted["execution_result"]["run"]["status"], "COMPLETED")
            finally: facade.close()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                rejected = deepcopy(valid)
                rejected["validation"] = {"status": "rejected", "issues": [{
                    "code": "SOURCE-QUALITY", "severity": "error", "message": "Formal research rejection."
                }]}
                result = facade.collect_external(run_id, {"research_result": rejected})
                self.assertEqual(result["execution_result"]["run"]["status"], "COMPLETED")
                self.assertEqual(result["execution_result"]["handoff_status"], "rejected")
                self.assertIsNone(result["execution_result"]["state_delta_proposal"])
            finally: facade.close()

    def test_review_fix_operator_shape_errors_are_correctable_but_internal_fields_are_hard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                broken = deepcopy(valid); broken["outputs"] = []
                preflight = facade.preflight_external(run_id, {"research_result": broken})
                self.assertEqual(preflight["status"], "PREFLIGHT_REJECTED")
                self.assertEqual(preflight["issues"][0]["code"], "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001")
                collected = facade.collect_external(run_id, {"research_result": broken})
                self.assertEqual(collected["execution_result"]["run"]["status"], "RUNNING")
                self.assertEqual(collected["execution_result"]["issues"][0]["code"], "APPLICATION-EXTERNAL-SUBMISSION-CONTENT-001")
                self.assert_running(app, run_id)

                missing = deepcopy(valid); missing["outputs"].pop("unknowns")
                missing_result = facade.collect_external(run_id, {"research_result": missing})
                self.assertEqual(missing_result["execution_result"]["run"]["status"], "RUNNING")
                self.assert_running(app, run_id)

                forbidden = deepcopy(valid); forbidden["outputs"]["source_captures"] = []
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.preflight_external(run_id, {"research_result": forbidden})
                self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-SUBMISSION-001")

                accepted = facade.collect_external(run_id, {"research_result": valid})
                self.assertEqual(accepted["execution_result"]["run"]["status"], "COMPLETED")
            finally:
                facade.close()

    def test_review_fix_authorization_denial_is_not_a_correctable_submission(self):
        from core.execution.testing import AllowListedAuthorizationProvider

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                app.authorization = AllowListedAuthorizationProvider(denied=True)
                with self.assertRaises(LocalApplicationError) as preflight:
                    facade.preflight_external(run_id, {"research_result": valid})
                self.assertEqual(preflight.exception.code, "APPLICATION-EXTERNAL-BINDING-001")
                with self.assertRaises(LocalApplicationError) as collect:
                    facade.collect_external(run_id, {"research_result": valid})
                self.assertEqual(collect.exception.code, "APPLICATION-EXTERNAL-BINDING-001")
                self.assert_running(app, run_id)
            finally:
                facade.close()

    def test_review_fix_rejected_handoff_requires_valid_desktop_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                rejected = deepcopy(valid)
                rejected["validation"] = {"status": "rejected", "issues": [{
                    "code": "SOURCE-QUALITY", "severity": "error", "message": "Formal research rejection."
                }]}
                rejected["citation_details"][0]["excerpt"] = "not present in captured text"
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.collect_external(run_id, {"research_result": rejected})
                self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-INTEGRITY-001")
                self.assert_running(app, run_id)
            finally:
                facade.close()

    def test_review_round2_capture_pair_parent_provenance_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id, valid, _ = self.prepared(root, facade)
                rendition = next(
                    item for item in app.execution_store.artifacts_for(run_id)
                    if item.role.endswith("text_rendition")
                )
                provenance = dict(rendition.provenance)
                provenance["parent_artifact_refs"] = ["ART-forged-parent"]
                with app.execution_store._lock:
                    app.execution_store._connection.execute(
                        "UPDATE execution_artifacts SET provenance_json=? WHERE artifact_id=?",
                        (json.dumps(provenance), rendition.artifact_id),
                    )
                    app.execution_store._connection.commit()
                for call in (facade.preflight_external, facade.collect_external):
                    with self.subTest(call=call.__name__), self.assertRaises(LocalApplicationError) as caught:
                        call(run_id, {"research_result": valid})
                    self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-INTEGRITY-001")
                    self.assert_running(app, run_id)
            finally:
                facade.close()

    def test_review_round2_whitespace_equivalent_citation_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = self.make_facade(root)
            try:
                run_id = self.prepare(facade)["run_id"]
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "target_locator": "https://example.test/source-a",
                })
                raw = root / "captures/raw/source-a.html"
                text = root / "captures/text/source-a.txt"
                raw.parent.mkdir(parents=True, exist_ok=True); text.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(b"<html>original source A bytes</html>")
                text.write_text("Source A contains the exact supporting\nexcerpt used here.", encoding="utf-8")
                capture = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1", "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                })["capture"]
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "outcome": "source_captured", "resulting_capture_id": "CAP-1",
                })
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2", "strategy": "counter search", "coverage_dimension_ids": ["COV-COUNTER"],
                })
                facade.complete_external_retrieval_attempt(run_id, {"attempt_id": "ATT-2", "outcome": "no_relevant_source"})
                handoff, extension = intake.golden_submission(app, run_id, capture)
                valid = self.research_result(handoff, extension)
                self.assertEqual(facade.preflight_external(run_id, {"research_result": valid})["status"], "PREFLIGHT_OK")
                accepted = facade.collect_external(run_id, {"research_result": valid})
                self.assertEqual(accepted["execution_result"]["run"]["status"], "COMPLETED")
            finally:
                facade.close()

    def test_review_round2_nested_schema_errors_are_correctable(self):
        mutators = (
            lambda value: value.__setitem__("coverage_assessment", {}),
            lambda value: value.__setitem__("null_results", [None]),
        )
        for mutate in mutators:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); app, facade = self.make_facade(root)
                try:
                    run_id, valid, _ = self.prepared(root, facade)
                    broken = deepcopy(valid); mutate(broken)
                    preflight = facade.preflight_external(run_id, {"research_result": broken})
                    self.assertEqual(preflight["status"], "PREFLIGHT_REJECTED")
                    collected = facade.collect_external(run_id, {"research_result": broken})
                    self.assertEqual(collected["execution_result"]["run"]["status"], "RUNNING")
                    self.assert_running(app, run_id)
                    fixed = facade.collect_external(run_id, {"research_result": valid})
                    self.assertEqual(fixed["execution_result"]["run"]["status"], "COMPLETED")
                finally:
                    facade.close()

    def test_review_round2_resource_basis_is_verified_before_terminal_intake(self):
        from runtime_fixtures import project, rq, seed_state
        catalog = {
            "REF-SOURCE-1": {
                "reference_type": "source", "object_id": "SRC-1",
                "access_mode": "read", "evidentiary_use": "candidate_source",
            }
        }
        for mode in ("tampered", "missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                seed = seed_state(objects=[project(), rq(state="approved")], mode="real", snapshot_id="SNP-R2-RESOURCE")
                app = LocalResearchApplication(
                    root / ".research-loom", resolver=intake.NullResolver(),
                    effective_profile_set_provider=intake.profile_provider, seed_state=seed,
                    resource_catalog=catalog, resource_roles={"REF-SOURCE-1": "candidate_source"},
                    resource_bytes={"REF-SOURCE-1": b"registered source resource bytes"},
                )
                facade = LocalApplicationFacade(app, "PRJ-1", workspace_root=root)
                try:
                    prepared = facade.submit_action({
                        "action_type": "desktop_research.investigate",
                        "payload": {
                            "question_id": "RQ-1", "purpose": "resource preflight",
                            "resource_reference_ids": ["REF-SOURCE-1"],
                        },
                    })
                    run_id = prepared["run_id"]
                    facade.start_external_retrieval_attempt(run_id, {
                        "attempt_id": "ATT-1", "strategy": "support search", "coverage_dimension_ids": ["COV-SUPPORT"],
                        "target_locator": "https://example.test/source-a",
                    })
                    self.write_capture_files(root)
                    capture = facade.capture_external_source(run_id, {
                        "capture_id": "CAP-1", "source_category": "other",
                        "exact_locator": "https://example.test/source-a#section-1",
                        "acquired_at": "2026-08-31T00:00:00Z",
                        "original_file": "captures/raw/source-a.html", "original_media_type": "text/html",
                        "text_rendition_file": "captures/text/source-a.txt",
                    })["capture"]
                    facade.complete_external_retrieval_attempt(run_id, {
                        "attempt_id": "ATT-1", "outcome": "source_captured", "resulting_capture_id": "CAP-1",
                    })
                    facade.start_external_retrieval_attempt(run_id, {
                        "attempt_id": "ATT-2", "strategy": "counter search", "coverage_dimension_ids": ["COV-COUNTER"],
                    })
                    facade.complete_external_retrieval_attempt(run_id, {"attempt_id": "ATT-2", "outcome": "no_relevant_source"})
                    handoff, extension = intake.golden_submission(app, run_id, capture)
                    valid = self.research_result(handoff, extension)
                    valid["outputs"]["evidence_candidates"][0]["source_basis"] = {
                        "basis_type": "resource_reference", "resource_reference_id": "REF-SOURCE-1"
                    }
                    valid["citation_details"] = []
                    context = app.execution_store.load_context_pack(app.execution_store.load_run(run_id).context_pack_id)
                    resource = next(item for item in context["resources"] if item["reference_id"] == "REF-SOURCE-1")
                    hex_digest = resource["digest"].split(":", 1)[1]
                    blob = app.execution_store.blob_root / hex_digest[:2] / hex_digest
                    if mode == "tampered":
                        data = blob.read_bytes(); blob.write_bytes(bytes([data[0] ^ 1]) + data[1:])
                    else:
                        blob.unlink()
                    for call in (facade.preflight_external, facade.collect_external):
                        with self.subTest(call=call.__name__), self.assertRaises(LocalApplicationError) as caught:
                            call(run_id, {"research_result": valid})
                        self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-INTEGRITY-001")
                        self.assert_running(app, run_id)
                finally:
                    facade.close()

    def test_review_round2_real_profile_public_cli_connects_a_through_d(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = intake.write_workspace_inputs(root)
            workspace = root / "workspace"
            LocalApplicationFacade.initialize_workspace(workspace, config_path, profile_path)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq1 = intake.adopt_rq(facade)
                source = workspace / "theme.md"; source.write_text("Theme input\n", encoding="utf-8")
                snap0 = facade.resume_context()["research_state"]["snapshot"]
                registered = facade.register_project_input({
                    "file": str(source), "role": "theme",
                    "expected_snapshot_id": snap0["snapshot_id"],
                    "expected_snapshot_digest": snap0["content_digest"],
                    "provenance": {"supplied_by": "issue-92-review"},
                })["project_input"]
                rq2 = intake.adopt_rq(facade)
                self.assertNotEqual(rq1, rq2)
                snap1 = facade.resume_context()["research_state"]["snapshot"]
                self.assertNotEqual(snap0["snapshot_id"], snap1["snapshot_id"])
                stored = facade.show_project_input(registered["input_id"])["project_input"]
                self.assertEqual(stored["content_digest"], registered["content_digest"])
                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": rq1, "purpose": "Issue 92 A-D connected acceptance."},
                })
                run_id = prepared["run_id"]
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "strategy": "support search", "coverage_dimension_ids": ["COV-SUPPORT"],
                    "target_locator": "https://example.test/source-a",
                })
                raw = workspace / "captures/raw/source-a.html"; text = workspace / "captures/text/source-a.txt"
                raw.parent.mkdir(parents=True, exist_ok=True); text.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(b"<html>original source A bytes</html>")
                text.write_text("Source A contains the exact supporting excerpt used here.", encoding="utf-8")
                capture = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1", "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1", "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html", "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                })["capture"]
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "outcome": "source_captured", "resulting_capture_id": "CAP-1",
                })
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2", "strategy": "counter search", "coverage_dimension_ids": ["COV-COUNTER"],
                })
                facade.complete_external_retrieval_attempt(run_id, {"attempt_id": "ATT-2", "outcome": "no_relevant_source"})
                handoff, extension = intake.golden_submission(facade._application, run_id, capture)
                valid = self.research_result(handoff, extension)
                before = facade.resume_context()["research_state"]["snapshot"]
                preflight = facade.preflight_external(run_id, {"research_result": valid})
                assembled = preflight["assembled_submission"]["handoff"]
                self.assertTrue(assembled["preserved_context"]["research_attention_ids"])
                self.assertTrue(assembled["preserved_context"]["project_guard_ids"])
                self.assertTrue(assembled["preserved_context"]["effective_constraint_paths"])
            raw.unlink(); text.unlink()
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli_main(["external", "materials", "show", "--workspace", str(workspace), "--run-id", run_id, "--capture-id", "CAP-1", "--json"])
            self.assertEqual(code, 0); shown = json.loads(out.getvalue()); self.assertEqual(shown["capture"]["capture_id"], "CAP-1")
            export_path = root / "exported-source.bin"
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli_main(["external", "materials", "export", "--workspace", str(workspace), "--run-id", run_id, "--capture-id", "CAP-1", "--kind", "original", "--output", str(export_path), "--json"])
            self.assertEqual(code, 0); self.assertEqual(export_path.read_bytes(), b"<html>original source A bytes</html>")
            bad = deepcopy(valid); bad["coverage_assessment"] = {}
            bad_path = root / "bad.json"; bad_path.write_text(json.dumps({"research_result": bad}), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli_main(["external", "collect", "--workspace", str(workspace), "--run-id", run_id, "--json", str(bad_path)])
            self.assertEqual(code, 0); rejected = json.loads(out.getvalue()); self.assertEqual(rejected["execution_result"]["run"]["status"], "RUNNING")
            valid_path = root / "valid.json"; valid_path.write_text(json.dumps({"research_result": valid}), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli_main(["external", "collect", "--workspace", str(workspace), "--run-id", run_id, "--json", str(valid_path)])
            self.assertEqual(code, 0); accepted = json.loads(out.getvalue())
            self.assertEqual(accepted["execution_result"]["run"]["status"], "COMPLETED")
            proposal = accepted["execution_result"]["state_delta_proposal"]
            self.assertTrue(proposal["candidate_only"])
            normalized = [action["payload"]["object"] for action in proposal["proposed_actions"]]
            evidence = next(item for item in normalized if item.get("kind") == "evidence")
            finding = next(item for item in normalized if item.get("kind") == "finding")
            self.assertEqual(evidence["capture_digest"], capture["original_capture"]["content_digest"])
            self.assertEqual(evidence["verification_status"], "unverified")
            self.assertEqual(finding["adoption_state"], "candidate")
            with LocalApplicationFacade.open_workspace(workspace) as reopened:
                after = reopened.resume_context()["research_state"]["snapshot"]
                self.assertEqual(before, after)
                self.assertEqual(reopened.show_project_input(registered["input_id"])["project_input"], stored)


if __name__ == "__main__":
    unittest.main()
