"""Characterization tests for ``plugins/local_application/material/material_import_facade.py``.

Added for #507 (direct tests for modules that were only reached indirectly).
They pin the path helpers and ``MaterialImportMixin``: staging a portable
execution/material root into the workspace intake area, reopening a staged
root read-only, and importing one verified capture pair into a RUNNING
Desktop Research Run, including the destination budget checks and the stable
``LocalApplicationError`` codes. The workspaces come from the external Desktop
Research intake fixtures used by ``tests.runtime.test_issue165_staged_material_import``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tests.runtime.test_external_desktop_research_intake as intake
from plugins.local_application import LocalApplicationError
from plugins.local_application.material import material_import_facade
from plugins.local_application.material.material_import_facade import (
    MaterialImportMixin,
    _assert_link_free,
    _link_like,
    _resolve_source_execution_root,
    _source_filename,
    _stage_id,
)
from plugins.local_execution_store import LocalExecutionStoreIntegrityError
from plugins.local_execution_store.read_only import ReadOnlyLocalExecutionStore
from tests.runtime.test_issue165_staged_material_import import _capture_source

STAGE = "APPLICATION-MATERIAL-STAGE-001"
IMPORT = "APPLICATION-MATERIAL-IMPORT-001"
VERIFY = "APPLICATION-MATERIAL-IMPORT-VERIFY-001"
INTAKE = Path("intake") / "material-sources"


def _assert_code(case, code, call, *args, **kwargs):
    with case.assertRaises(LocalApplicationError) as caught:
        call(*args, **kwargs)
    case.assertEqual(caught.exception.code, code)
    return caught.exception


def _make_execution_root(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "execution.db").write_bytes(b"")
    return path


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_link_like_detects_symlinks_only(self) -> None:
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        os.symlink(target, link, target_is_directory=True)
        self.assertFalse(_link_like(target))
        self.assertTrue(_link_like(link))
        self.assertFalse(_link_like(self.root / "missing"))

    def test_source_root_resolves_each_supported_layout(self) -> None:
        direct = _make_execution_root(self.root / "direct")
        child = _make_execution_root(self.root / "child" / "execution")
        workspace = _make_execution_root(self.root / "ws" / ".research-loom" / "execution")
        self.assertEqual(_resolve_source_execution_root(direct), direct.resolve())
        self.assertEqual(_resolve_source_execution_root(self.root / "child"), child.resolve())
        self.assertEqual(_resolve_source_execution_root(str(self.root / "ws")), workspace.resolve())

    def test_source_root_rejections(self) -> None:
        ambiguous = _make_execution_root(self.root / "ambiguous")
        _make_execution_root(ambiguous / "execution")
        (self.root / "empty").mkdir()
        link = self.root / "linked"
        os.symlink(ambiguous, link, target_is_directory=True)
        cases = (
            ("", "material source path must be a non-empty path"),
            (1, "material source path must be a non-empty path"),
            (link, "material source root may not be a link or junction"),
            (self.root / "missing", "material source path does not exist"),
            (
                ambiguous,
                "material source must resolve unambiguously to one execution/material child root",
            ),
            (
                self.root / "empty",
                "material source must resolve unambiguously to one execution/material child root",
            ),
        )
        for source, message in cases:
            with self.subTest(source=source):
                error = _assert_code(self, STAGE, _resolve_source_execution_root, source)
                self.assertEqual(error.message, message)

    def test_assert_link_free(self) -> None:
        tree = self.root / "tree"
        (tree / "nested").mkdir(parents=True)
        (tree / "nested" / "file").write_text("x", encoding="utf-8")
        _assert_link_free(tree)
        os.symlink(tree / "nested" / "file", tree / "nested" / "alias")
        error = _assert_code(self, STAGE, _assert_link_free, tree)
        self.assertEqual(error.message, "staged material source contains a link or junction")
        os.symlink(tree, self.root / "tree-link", target_is_directory=True)
        error = _assert_code(self, STAGE, _assert_link_free, self.root / "tree-link")
        self.assertEqual(error.message, "staged material source may not be a link or junction")

    def test_stage_id_must_be_a_single_path_name(self) -> None:
        self.assertEqual(_stage_id("MSTG-1"), "MSTG-1")
        for value in ("", ".", "..", "a/b", "../x", 1, None):
            with self.subTest(value=value):
                error = _assert_code(self, IMPORT, _stage_id, value)
                self.assertEqual(error.message, "stage_id is invalid")

    def test_source_filename_keeps_only_the_basename(self) -> None:
        self.assertEqual(_source_filename({"k": "captures/raw/a.html"}, "k"), "a.html")
        for provenance in ({}, {"k": ""}, {"k": 3}):
            with self.subTest(provenance=provenance):
                self.assertIsNone(_source_filename(provenance, "k"))

    def test_intake_root_requires_a_workspace(self) -> None:
        fake = SimpleNamespace(_workspace_root=None)
        error = _assert_code(self, STAGE, MaterialImportMixin._material_intake_root, fake)
        self.assertEqual(
            error.message, "staged material import requires a workspace-backed application"
        )

    def test_intake_root_layout_and_link_guard(self) -> None:
        fake = SimpleNamespace(_workspace_root=self.root)
        self.assertEqual(
            MaterialImportMixin._material_intake_root(fake), self.root.resolve() / INTAKE
        )
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        os.symlink(elsewhere, self.root / "intake", target_is_directory=True)
        error = _assert_code(self, STAGE, MaterialImportMixin._material_intake_root, fake)
        self.assertEqual(error.message, "material intake path may not contain a link or junction")


class _MaterialBase(unittest.TestCase):
    """One captured source workspace per class; a fresh destination per test."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._source_temp = tempfile.TemporaryDirectory()
        cls.source_root = Path(cls._source_temp.name) / "source"
        helper = intake.ExternalDesktopResearchIntakeTests()
        app, facade = helper.make_facade(cls.source_root)
        try:
            cls.source_run = helper.prepare(facade)["run_id"]
            _capture_source(cls.source_root, facade, cls.source_run)
        finally:
            facade.close()
            app.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._source_temp.cleanup()

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / "destination"
        helper = intake.ExternalDesktopResearchIntakeTests()
        self.app, self.facade = helper.make_facade(self.workspace)
        self.addCleanup(self.app.close)
        self.addCleanup(self.facade.close)
        self.destination_run = helper.prepare(self.facade)["run_id"]

    def assertCode(self, code, call, *args, **kwargs):
        return _assert_code(self, code, call, *args, **kwargs)

    def _stage(self, source=None):
        return self.facade.stage_external_material_source(source or self.source_root)

    def _stage_root(self, staged) -> Path:
        return self.workspace / staged["staged_source"]["root"]

    def _import(self, stage_id, **overrides):
        kwargs = {
            "source_run_id": self.source_run,
            "source_capture_id": "CAP-1",
            "destination_run_id": self.destination_run,
            **overrides,
        }
        return self.facade.import_staged_external_material(stage_id, **kwargs)


class StageTests(_MaterialBase):
    def test_stage_copies_a_readable_portable_root(self) -> None:
        staged = self._stage()
        self.assertEqual(staged["status"], "MATERIAL_SOURCE_STAGED")
        self.assertTrue(staged["stage_id"].startswith("MSTG-"))
        self.assertFalse(staged["durable_state_registered"])
        stage_id = staged["stage_id"]
        self.assertEqual(
            staged["staged_source"],
            {
                "root": str(INTAKE / stage_id),
                "execution_root": str(INTAKE / stage_id / "execution"),
            },
        )
        stage_root = self._stage_root(staged)
        manifest = json.loads((stage_root / "stage.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {key: manifest[key] for key in ("schema_version", "stage_id", "source_kind")},
            {
                "schema_version": "0.1.0",
                "stage_id": stage_id,
                "source_kind": "portable_execution_material_root",
            },
        )
        self.assertEqual(manifest["execution_root"], "execution")
        self.assertIn("staged_at", manifest)
        self.assertTrue((stage_root / "execution" / "execution.db").is_file())
        self.assertFalse((stage_root / "execution" / "staging").exists())

    def test_lock_and_staging_entries_are_not_copied(self) -> None:
        source = self.root / "copy-of-source"
        shutil.copytree(self.source_root / ".research-loom" / "execution", source)
        (source / "staging" / "partial").mkdir(parents=True, exist_ok=True)
        (source / "large-original-locks").mkdir()
        (source / "writer.lock").write_text("", encoding="utf-8")
        execution = self._stage_root(self._stage(source)) / "execution"
        self.assertFalse((execution / "staging").exists())
        self.assertFalse((execution / "large-original-locks").exists())
        self.assertFalse((execution / "writer.lock").exists())

    def test_existing_stage_identity_is_refused(self) -> None:
        staged = self._stage()
        with patch.object(self.app.ids, "new", return_value=staged["stage_id"]):
            error = self.assertCode(STAGE, self._stage)
        self.assertEqual(error.message, "material stage identity already exists")
        self.assertTrue(self._stage_root(staged).is_dir())

    def test_unreadable_source_is_rolled_back(self) -> None:
        source = _make_execution_root(self.root / "garbage")
        (source / "execution.db").write_bytes(b"not a sqlite database")
        error = self.assertCode(STAGE, self._stage, source)
        self.assertEqual(
            error.message, "material source could not be staged as a readable portable root"
        )
        self.assertEqual(list((self.workspace / INTAKE).iterdir()), [])

    def test_source_containing_a_link_is_rolled_back(self) -> None:
        source = self.root / "linked-source"
        shutil.copytree(self.source_root / ".research-loom" / "execution", source)
        os.symlink(source / "execution.db", source / "alias.db")
        error = self.assertCode(STAGE, self._stage, source)
        self.assertEqual(error.message, "staged material source contains a link or junction")
        self.assertEqual(list((self.workspace / INTAKE).iterdir()), [])


class OpenStagedSourceTests(_MaterialBase):
    def test_open_returns_a_read_only_store(self) -> None:
        staged = self._stage()
        with self.facade._open_staged_material_source(staged["stage_id"]) as store:
            self.assertIsInstance(store, ReadOnlyLocalExecutionStore)
            self.assertIsNotNone(store.load_run(self.source_run))

    def test_missing_or_mismatched_manifest(self) -> None:
        staged = self._stage()
        manifest_path = self._stage_root(staged) / "stage.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        cases = (
            ("{not json", "staged material source manifest is missing or invalid"),
            ("[]", "staged material source manifest does not match the requested stage"),
            (
                json.dumps({**original, "stage_id": "MSTG-OTHER"}),
                "staged material source manifest does not match the requested stage",
            ),
            (
                json.dumps({**original, "source_kind": "other"}),
                "staged material source manifest does not match the requested stage",
            ),
            (
                json.dumps({**original, "execution_root": "elsewhere"}),
                "staged material source manifest does not match the requested stage",
            ),
        )
        for content, message in cases:
            with self.subTest(content=content[:20]):
                manifest_path.write_text(content, encoding="utf-8")
                error = self.assertCode(
                    IMPORT, self.facade._open_staged_material_source, staged["stage_id"]
                )
                self.assertEqual(error.message, message)
        error = self.assertCode(IMPORT, self.facade._open_staged_material_source, "MSTG-NONE")
        self.assertEqual(error.message, "staged material source manifest is missing or invalid")

    def test_linked_stage_root_is_refused(self) -> None:
        staged = self._stage()
        os.symlink(
            self._stage_root(staged),
            self.workspace / INTAKE / "MSTG-ALIAS",
            target_is_directory=True,
        )
        error = self.assertCode(IMPORT, self.facade._open_staged_material_source, "MSTG-ALIAS")
        self.assertEqual(error.message, "staged material source may not be a link or junction")

    def test_unreadable_staged_store(self) -> None:
        staged = self._stage()
        (self._stage_root(staged) / "execution" / "execution.db").write_bytes(b"corrupt")
        error = self.assertCode(
            IMPORT, self.facade._open_staged_material_source, staged["stage_id"]
        )
        self.assertEqual(error.message, "staged material source cannot be opened read-only")

    def test_invalid_stage_id(self) -> None:
        self.assertCode(IMPORT, self.facade._open_staged_material_source, "../escape")


class ImportTests(_MaterialBase):
    def setUp(self) -> None:
        super().setUp()
        self.staged = self._stage()
        self.stage_id = self.staged["stage_id"]

    def _with_extension(self, mutate):
        run, extension = self.facade._desktop_external_run(self.destination_run)
        extension = deepcopy(dict(extension))
        mutate(extension)
        return patch.object(self.facade, "_desktop_external_run", return_value=(run, extension))

    def test_import_copies_verified_pair_as_candidate_material(self) -> None:
        before = self.app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
        imported = self._import(self.stage_id)
        self.assertEqual(imported["status"], "MATERIAL_IMPORTED")
        self.assertEqual(imported["stage_id"], self.stage_id)
        self.assertFalse(imported["research_state_mutation_performed"])
        self.assertFalse(imported["source_authority_imported"])
        source = imported["source_material"]
        self.assertEqual((source["run_id"], source["capture_id"]), (self.source_run, "CAP-1"))
        destination = imported["destination"]
        self.assertEqual(destination["run_id"], self.destination_run)
        capture = destination["capture"]
        self.assertEqual(capture["capture_id"], "CAP-1")
        self.assertEqual(capture["source_category"], "other")
        self.assertEqual(capture["exact_locator"], "https://example.test/source-a#section-1")
        self.assertEqual(
            capture["original_capture"]["content_reference"],
            f"{self.destination_run}.CAP-1.original",
        )
        self.assertEqual(capture["original_capture"]["content_digest"], source["original_digest"])
        self.assertEqual(
            capture["text_rendition"]["content_reference"], f"{self.destination_run}.CAP-1.text"
        )
        self.assertEqual(
            capture["text_rendition"]["content_digest"], source["text_rendition_digest"]
        )

        artifacts = {
            item.artifact_id: item
            for item in self.app.execution_store.artifacts_for(self.destination_run)
        }
        original = artifacts[f"{self.destination_run}.CAP-1.original"]
        self.assertEqual(original.role, "desktop_research.original_capture")
        self.assertEqual(original.provenance["rendition_role"], "original")
        self.assertEqual(original.provenance["original_source_filename"], "source-a.html")
        self.assertEqual(original.provenance["text_rendition_source_filename"], "source-a.txt")
        material = original.provenance["material_import"]
        self.assertEqual(material["stage_id"], self.stage_id)
        self.assertEqual(material["historical_source_run_id"], self.source_run)
        self.assertEqual(material["historical_source_capture_id"], "CAP-1")
        self.assertEqual(material["historical_original_digest"], source["original_digest"])
        text = artifacts[f"{self.destination_run}.CAP-1.text"]
        self.assertEqual(text.provenance["rendition_role"], "text")
        after = self.app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
        self.assertEqual(before["content_digest"], after["content_digest"])

    def test_second_import_of_same_capture_cannot_be_copied(self) -> None:
        self._import(self.stage_id)
        error = self.assertCode(VERIFY, self._import, self.stage_id)
        self.assertEqual(
            error.message,
            "verified staged material could not be copied into destination durability",
        )

    def test_identifier_arguments_must_be_non_empty_strings(self) -> None:
        for name in ("source_run_id", "source_capture_id", "destination_run_id"):
            for value in ("", None):
                with self.subTest(name=name, value=value):
                    error = self.assertCode(IMPORT, self._import, self.stage_id, **{name: value})
                    self.assertEqual(error.message, f"{name} must be a non-empty string")

    def test_destination_must_be_a_running_external_run(self) -> None:
        self.assertCode(
            "APPLICATION-EXTERNAL-RUN-001", self._import, self.stage_id, destination_run_id="RUN-X"
        )

    def test_unknown_source_run_or_capture(self) -> None:
        error = self.assertCode(
            "APPLICATION-MATERIAL-IMPORT-404", self._import, self.stage_id, source_run_id="RUN-X"
        )
        self.assertEqual(error.message, "source Run is not a real Desktop Research investigate Run")
        self.assertCode(
            "APPLICATION-MATERIAL-404", self._import, self.stage_id, source_capture_id="CAP-NONE"
        )

    def test_integrity_failure_in_selected_pair_is_a_verify_error(self) -> None:
        with patch.object(
            material_import_facade,
            "_artifact_pair_for_capture",
            side_effect=LocalExecutionStoreIntegrityError("ambiguous pair"),
        ):
            error = self.assertCode(VERIFY, self._import, self.stage_id)
        self.assertEqual(
            error.message,
            "selected staged material is missing, corrupt, unreadable, or incorrectly bound",
        )

    def test_corrupt_staged_backing_is_a_verify_error(self) -> None:
        execution = self._stage_root(self.staged) / "execution"
        for blob in (execution / "blobs").rglob("*"):
            if blob.is_file():
                blob.write_bytes(b"corrupt")
        self.assertCode(VERIFY, self._import, self.stage_id)
        self.assertEqual(self.app.execution_store.artifacts_for(self.destination_run), ())

    def test_non_utf8_text_rendition_is_a_verify_error(self) -> None:
        with patch.object(
            ReadOnlyLocalExecutionStore,
            "load_artifact_verified_once",
            return_value=SimpleNamespace(content=b"\xff\xfe"),
        ):
            error = self.assertCode(VERIFY, self._import, self.stage_id)
        self.assertEqual(error.message, "selected text rendition is not valid UTF-8")

    def test_source_category_must_be_allowed(self) -> None:
        with self._with_extension(lambda ext: ext.update({"allowed_source_categories": []})):
            error = self.assertCode(IMPORT, self._import, self.stage_id)
        self.assertEqual(
            error.message,
            "source_category is not allowed by destination Desktop Research Run: other",
        )

    def test_budget_must_be_a_mapping(self) -> None:
        with self._with_extension(lambda ext: ext.update({"budget": None})):
            error = self.assertCode(IMPORT, self._import, self.stage_id)
        self.assertEqual(
            error.message, "destination Desktop Research Run has no valid capture budget"
        )

    def test_malformed_budget(self) -> None:
        mutations = (
            lambda budget: budget.pop("max_acquired_source_captures"),
            lambda budget: budget.update({"max_text_rendition_bytes": "many"}),
            lambda budget: budget.update({"max_original_capture_bytes": "x"}),
            lambda budget: budget.update({"max_capture_artifacts": -1}),
        )
        for mutate in mutations:
            with self.subTest():
                with self._with_extension(lambda ext, mutate=mutate: mutate(ext["budget"])):
                    error = self.assertCode(IMPORT, self._import, self.stage_id)
                self.assertEqual(
                    error.message, "destination Desktop Research capture budget is malformed"
                )

    def test_budget_limits_are_enforced(self) -> None:
        message = "selected material exceeds destination Desktop Research capture budget"
        mutations = (
            lambda budget: budget.update({"max_acquired_source_captures": 0}),
            lambda budget: budget.update({"max_capture_artifacts": 1}),
            lambda budget: budget.update({"max_text_rendition_bytes": 1}),
            lambda budget: budget.update({"max_original_capture_bytes": 1}),
        )
        for mutate in mutations:
            with self.subTest():
                with self._with_extension(lambda ext, mutate=mutate: mutate(ext["budget"])):
                    error = self.assertCode(IMPORT, self._import, self.stage_id)
                self.assertEqual(error.message, message)

    def test_undeclared_original_limit_uses_store_artifact_limit(self) -> None:
        def undeclared(ext):
            ext["budget"].pop("max_original_capture_bytes")
            ext["budget"].pop("max_capture_artifacts")

        with self._with_extension(undeclared):
            imported = self._import(self.stage_id)
        self.assertEqual(imported["status"], "MATERIAL_IMPORTED")

    def test_missing_source_filenames_are_omitted(self) -> None:
        with patch.object(material_import_facade, "_source_filename", return_value=None):
            self._import(self.stage_id)
        original = next(
            item
            for item in self.app.execution_store.artifacts_for(self.destination_run)
            if item.role == "desktop_research.original_capture"
        )
        self.assertNotIn("original_source_filename", original.provenance)
        self.assertNotIn("text_rendition_source_filename", original.provenance)


if __name__ == "__main__":
    unittest.main()
