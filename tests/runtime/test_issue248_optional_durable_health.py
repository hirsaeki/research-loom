from __future__ import annotations

import importlib
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalWorkspace
from plugins.local_application.cli import main
from plugins.local_durable_store import OPTIONAL_DURABLE_CHILDREN, register_optional_path
from tests.runtime.test_research_question_review import _workspace


class OptionalDurableHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = _workspace(self.root)
        self.internal = self.workspace / ".research-loom"
        self.binding_path = self.internal / "workspace-binding.json"

    def _binding(self):
        return json.loads(self.binding_path.read_text(encoding="utf-8"))

    def _input(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            source = self.workspace / "theme.md"
            source.write_text("retained input", encoding="utf-8")
            snap = facade.status()["snapshot"]
            value = {"file": str(source), "role": "theme",
                     "expected_snapshot_id": snap["snapshot_id"],
                     "expected_snapshot_digest": snap["content_digest"]}
            item = facade.register_project_input(value)["project_input"]
            # Registration must already exist while the facade is still open.
            self.assertIn("project_inputs", self._binding()["durable_children"])
            return item, value
        finally:
            facade.close()

    def _assert_unrelated_continuation(self, child_name):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            status = facade.status()
            self.assertEqual(status["status"], "DEGRADED")
            health = next(row for row in status["optional_children"] if row["name"] == child_name)
            self.assertEqual(health["status"], "UNAVAILABLE")
            before = status["snapshot"]
            proposed = facade.submit_action({"action_type": "research_question.propose",
                                             "payload": {"text": "An independent candidate"}})
            self.assertIn("state_delta_proposal_id", proposed["data"])
            self.assertEqual(facade.status()["snapshot"], before)
            return facade.resume_context()
        finally:
            facade.close()

    def test_never_initialized_input_list_is_read_only(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            before = self.binding_path.read_bytes()
            self.assertEqual(facade.list_project_inputs()["project_inputs"], [])
            with self.assertRaises(LocalApplicationError) as error:
                facade.show_project_input("PIN-absent")
            self.assertEqual(error.exception.code, "APPLICATION-PROJECT-INPUT-404")
            self.assertFalse((self.internal / "project-inputs").exists())
            self.assertEqual(self.binding_path.read_bytes(), before)
        finally:
            facade.close()
        row = next(x for x in LocalWorkspace.doctor(self.workspace)["checks"] if x.get("name") == "project_inputs")
        self.assertEqual(row["status"], "UNINITIALIZED")

    def test_project_input_missing_corrupt_schema_are_local_and_restorable(self):
        item, value = self._input()
        child = self.internal / "project-inputs"
        db = child / "project-inputs.sqlite3"
        saved = db.read_bytes()
        for fault, code in [
            ("root", "WORKSPACE-OPTIONAL-CHILD-MISSING-001"),
            ("database", "WORKSPACE-OPTIONAL-METADATA-MISSING-001"),
            ("corrupt", "WORKSPACE-OPTIONAL-DATABASE-001"),
            ("schema", "WORKSPACE-OPTIONAL-SCHEMA-001"),
        ]:
            with self.subTest(fault=fault):
                backup = self.root / "retained-child"
                if fault == "root":
                    child.rename(backup)
                elif fault == "database":
                    db.unlink()
                elif fault == "corrupt":
                    db.write_bytes(b"not a sqlite database")
                else:
                    with closing(sqlite3.connect(db)) as con:
                        con.execute("DROP TABLE project_inputs")
                        con.commit()
                report = LocalWorkspace.doctor(self.workspace)
                self.assertEqual(report["status"], "DEGRADED")
                self.assertEqual(report["issues"][0]["code"], code)
                self._assert_unrelated_continuation("project_inputs")
                facade = LocalApplicationFacade.open_workspace(self.workspace)
                try:
                    for operation in [facade.list_project_inputs,
                                      lambda: facade.show_project_input(item["input_id"]),
                                      lambda: facade.register_project_input(value)]:
                        with self.assertRaises(LocalApplicationError) as error:
                            operation()
                        self.assertEqual(error.exception.code, code)
                finally:
                    facade.close()
                if fault == "root":
                    self.assertFalse(child.exists())
                    backup.rename(child)
                else:
                    if fault == "database":
                        self.assertFalse(db.exists())
                    db.write_bytes(saved)
                self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")
                facade = LocalApplicationFacade.open_workspace(self.workspace)
                try:
                    restored = facade.show_project_input(item["input_id"], format="text")
                    self.assertEqual(restored["project_input"], item)
                finally:
                    facade.close()

    def test_all_optional_sqlite_stores_refuse_lost_db_and_missing_schema(self):
        for name, module, klass, writer, reader, table in [
            ("research_attention", "local_attention_store", "LocalAttentionStore", "_connect_write", "_connect_read", "attention_maps"),
            ("research_exhibits", "local_research_exhibit_store", "LocalResearchExhibitStore", "_connect_write", "_connect_read", "research_exhibits"),
            ("survey_registry", "local_survey_store", "LocalSurveyStore", "_write", "_read", "survey_instruments"),
            ("survey_response_registry", "local_survey_response_store", "LocalSurveyResponseStore", "_write", "_read", "survey_responses"),
            ("survey_analysis_registry", "local_survey_analysis_store", "LocalSurveyAnalysisStore", "_write", "_read", "survey_analysis_specs"),
            ("delphi_registry", "local_delphi_store", "LocalDelphiStore", "_write", "_read", "delphi_documents"),
        ]:
            with self.subTest(child=name):
                path = self.workspace / OPTIONAL_DURABLE_CHILDREN[name]["locator"]
                store = getattr(importlib.import_module(f"plugins.{module}"), klass)(path)
                getattr(store, writer)().close()
                self.assertIn(name, self._binding()["durable_children"])
                saved = path.read_bytes()
                path.unlink()
                for method in (reader, writer):
                    with self.assertRaises(RuntimeError) as error:
                        getattr(store, method)()
                    self.assertEqual(error.exception.code, "WORKSPACE-OPTIONAL-CHILD-MISSING-001")
                    self.assertFalse(path.exists())
                self._assert_unrelated_continuation(name)
                path.write_bytes(saved)
                with closing(sqlite3.connect(path)) as con:
                    con.execute(f'DROP TABLE "{table}"')
                    con.commit()
                before = path.read_bytes()
                for method in (reader, writer):
                    with self.assertRaises(RuntimeError) as error:
                        getattr(store, method)()
                    self.assertEqual(error.exception.code, "WORKSPACE-OPTIONAL-SCHEMA-001")
                self.assertEqual(path.read_bytes(), before)
                path.write_bytes(saved)
                con = getattr(store, reader)(); self.assertIsNotNone(con); con.close()
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "OK")

    def test_directory_child_loss_blocks_only_its_consumer(self):
        factories = {
            "research_packages": lambda f: f._research_package_service(),
            "writer_compositions": lambda f: f._writer_composition_service(),
            "writer_round_trips": lambda f: f._writer_round_trip_service(),
            "publication": lambda f: f._publication_release_service(),
        }
        for name, factory in factories.items():
            with self.subTest(child=name):
                child = self.workspace / OPTIONAL_DURABLE_CHILDREN[name]["locator"]
                child.mkdir()
                register_optional_path(child)
                child.rmdir()
                self._assert_unrelated_continuation(name)
                facade = LocalApplicationFacade.open_workspace(self.workspace)
                try:
                    with self.assertRaises(LocalApplicationError) as error:
                        factory(facade)
                    self.assertEqual(error.exception.code, "WORKSPACE-OPTIONAL-CHILD-MISSING-001")
                finally:
                    facade.close()
                child.mkdir()

    def test_readonly_doctor_does_not_claim_payload_hashes(self):
        item, _ = self._input()
        child = self.internal / "project-inputs"
        blob = next((child / "blobs").glob("*/*"))
        blob.unlink()
        def persistent_bytes():
            # SQLite mode=ro may create WAL coordination sidecars. They are not
            # canonical records, and their presence is not a recovery write.
            return {p.relative_to(self.internal): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.internal.rglob("*")
                    if p.is_file() and not p.name.endswith(("-shm", "-wal"))}

        before = persistent_bytes()
        report = LocalWorkspace.doctor(self.workspace)
        row = next(x for x in report["checks"] if x.get("name") == "project_inputs")
        self.assertEqual(row["status"], "OK")
        self.assertEqual(row["payload_integrity"], "UNCHECKED")
        self.assertEqual(row["validation_scope"], "sqlite_quick_check_and_schema")
        self.assertEqual(before, persistent_bytes())
        self.assertFalse(blob.exists())
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            self.assertEqual(facade.show_project_input(item["input_id"])["project_input"], item)
            with self.assertRaises(LocalApplicationError):
                facade.show_project_input(item["input_id"], format="text")
        finally:
            facade.close()

    def test_process_exit_after_capture_has_already_registered_child(self):
        script = '''
import json, os, sys
from pathlib import Path
from plugins.local_application import LocalApplicationFacade
w = Path(sys.argv[1]); f = LocalApplicationFacade.open_workspace(w)
p = w / 'input.txt'; p.write_text('test', encoding='utf-8')
s = f.status()['snapshot']
f.register_project_input({'file': str(p), 'role': 'theme',
 'expected_snapshot_id': s['snapshot_id'], 'expected_snapshot_digest': s['content_digest']})
os._exit(0)
'''
        result = subprocess.run([sys.executable, "-c", script, str(self.workspace)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project_inputs", self._binding()["durable_children"])
        db = self.internal / "project-inputs" / "project-inputs.sqlite3"
        db.unlink()
        self.assertEqual(LocalWorkspace.doctor(self.workspace)["status"], "DEGRADED")
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            with self.assertRaises(LocalApplicationError):
                facade.list_project_inputs()
        finally:
            facade.close()
        self.assertFalse(db.exists())

    def test_schema_ready_registration_failure_accepts_no_user_record(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            source = self.workspace / "input.txt"; source.write_text("input", encoding="utf-8")
            snap = facade.status()["snapshot"]
            value = {"file": str(source), "role": "theme", "expected_snapshot_id": snap["snapshot_id"],
                     "expected_snapshot_digest": snap["content_digest"]}
            with patch("plugins.local_project_input_store.register_optional_path", side_effect=OSError("injected inventory failure")):
                with self.assertRaises(OSError):
                    facade.register_project_input(value)
            db = self.internal / "project-inputs" / "project-inputs.sqlite3"
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM project_inputs").fetchone()[0], 0)
            item = facade.register_project_input(value)["project_input"]
            self.assertIn("project_inputs", self._binding()["durable_children"])
            self.assertEqual(facade.list_project_inputs()["project_inputs"], [item])
        finally:
            facade.close()

    def test_cli_missing_db_is_named_error_without_recreation(self):
        self._input()
        db = self.internal / "project-inputs" / "project-inputs.sqlite3"
        db.unlink()
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = main(["research-input", "list", "--workspace", str(self.workspace), "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["issues"][0]["code"], "WORKSPACE-OPTIONAL-METADATA-MISSING-001")
        self.assertFalse(db.exists())

    def test_publication_registration_and_missing_root_do_not_block_candidate_research(self):
        from test_issue220_publication_release import Issue220PublicationReleaseTests
        helper = Issue220PublicationReleaseTests()
        helper.setUp()
        try:
            facade, _case, composition, imported, _source = helper._prepared()
            try:
                built = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
                request = facade.request_publication_release(built["build"]["build_id"], "H")["decision_request"]
                response = helper._approval(request)
                released = facade.release_publication(built["build"]["build_id"], response)
                binding = helper.workspace / ".research-loom/workspace-binding.json"
                self.assertIn("publication", json.loads(binding.read_text())["durable_children"])
            finally:
                facade.close()
            child = helper.workspace / ".research-loom/publication"
            backup = helper.root / "retained-publication"
            child.rename(backup)
            self.assertEqual(LocalWorkspace.doctor(helper.workspace)["status"], "DEGRADED")
            facade = LocalApplicationFacade.open_workspace(helper.workspace)
            try:
                facade.submit_action({"action_type": "research_question.propose", "payload": {"text": "Still able to investigate"}})
                with self.assertRaises(LocalApplicationError) as error:
                    facade.show_publication_preview(built["build"]["build_id"])
                self.assertEqual(error.exception.code, "WORKSPACE-OPTIONAL-CHILD-MISSING-001")
                self.assertFalse(child.exists())
                backup.rename(child)
                self.assertEqual(facade.release_publication(built["build"]["build_id"], response)["release"], released["release"])
            finally:
                facade.close()
        finally:
            helper.tearDown()

    def test_directory_access_error_is_local_unreadable_diagnosis(self):
        child = self.internal / "publication"
        child.mkdir()
        register_optional_path(child)
        from plugins.local_durable_store import inspect_optional_child
        with patch("plugins.local_durable_store.os.scandir", side_effect=PermissionError("denied")):
            row = inspect_optional_child(self.workspace, "publication", self._binding())
        self.assertEqual(row["status"], "UNAVAILABLE")
        self.assertEqual(row["code"], "WORKSPACE-OPTIONAL-UNREADABLE-001")

    def test_unsafe_optional_path_does_not_poison_unrelated_open_or_follow_link(self):
        child = self.internal / "publication"
        child.mkdir(); register_optional_path(child); child.rmdir()
        outside = self.root / "outside"; outside.mkdir()
        try:
            child.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        report = LocalWorkspace.doctor(self.workspace)
        self.assertEqual(report["status"], "DEGRADED")
        self.assertEqual(report["issues"][0]["code"], "WORKSPACE-OPTIONAL-UNSAFE-PATH-001")
        self._assert_unrelated_continuation("publication")
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
