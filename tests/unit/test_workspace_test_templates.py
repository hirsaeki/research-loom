"""Closed seed copies preserve case isolation, Config/EPS variants and fresh paths."""

from __future__ import annotations

import json
import re
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.runtime.test_external_desktop_research_intake as intake
import tests.runtime.test_misco_publication_profile_application as publication
import tests.runtime.test_misco_writer_profile_application as writer
from plugins.local_application import LocalWorkspace
from tests.runtime.research_package_acceptance_support import ResearchPackageAcceptanceSupport
from tests.runtime.workspace_test_templates import WorkspaceTemplateCache

CI_WINDOWS = True
ROOT = Path(__file__).resolve().parents[2]


class WorkspaceTemplateTests(unittest.TestCase):
    def setUp(self):
        self.templates = WorkspaceTemplateCache()
        self.addCleanup(self.templates.close)
        self.route = patch(
            "tests.runtime.research_package_acceptance_support.initialize_workspace_from_template",
            side_effect=self.templates.initialize,
        )
        self.route.start()
        self.addCleanup(self.route.stop)

    def fixture(self, fixture_class=None):
        fixture_class = fixture_class or type(
            "TemplateFixture",
            (ResearchPackageAcceptanceSupport,),
            {"REUSE_INITIAL_WORKSPACE": True},
        )
        case = fixture_class()
        self.addCleanup(case.doCleanups)
        case.setUp()
        return case

    def test_copies_do_not_share_db_files_artifacts_or_mutations(self):
        with patch.object(LocalWorkspace, "init", wraps=LocalWorkspace.init) as initialize:
            first, second = self.fixture(), self.fixture()
            self.assertEqual(1, initialize.call_count)
            relative = ".research-loom/research-state.sqlite3"
            first_db, second_db = first.workspace / relative, second.workspace / relative
            self.assertFalse(first_db.samefile(second_db))
            with sqlite3.connect(first_db) as connection:
                connection.execute("CREATE TABLE fixture_isolation_probe(value TEXT)")
                connection.execute("INSERT INTO fixture_isolation_probe VALUES ('first only')")
            connection.close()
            (first.workspace / "case-only.txt").write_text("first only", encoding="utf-8")
            first_db.unlink()
            third = self.fixture()
            self.assertEqual(1, initialize.call_count)
            for case in (second, third):
                self.assertFalse((case.workspace / "case-only.txt").exists())
                with sqlite3.connect(case.workspace / relative) as connection:
                    self.assertIsNone(
                        connection.execute(
                            "SELECT name FROM sqlite_master WHERE name='fixture_isolation_probe'"
                        ).fetchone()
                    )
                connection.close()
                with LocalWorkspace.open(case.workspace) as opened:
                    self.assertEqual("PRJ-1", opened.project_id)
            with self.assertRaises(FileExistsError):
                self.templates.initialize(
                    second.workspace,
                    second.root / "project-config-input.json",
                    second.root / "profiles-input.json",
                )

    def test_config_changes_and_real_profile_variants_have_distinct_seeds(self):
        with patch.object(LocalWorkspace, "init", wraps=LocalWorkspace.init) as initialize:
            generic = self.fixture()
            config = generic.root / "project-config-input.json"
            profiles = generic.root / "profiles-input.json"
            changed = json.loads(config.read_text(encoding="utf-8"))
            changed["project"]["title"] = "Different fixture title"
            config.write_text(
                json.dumps(intake.refresh(changed, "configuration_digest")), encoding="utf-8"
            )
            changed_workspace = generic.root / "changed-config"
            self.templates.initialize(changed_workspace, config, profiles)
            with LocalWorkspace.open(changed_workspace) as opened:
                self.assertEqual(
                    "Different fixture title", opened.project_config["project"]["title"]
                )
            narrative = self.fixture(writer.MiscoWriterProfileApplicationTests)
            formal = self.fixture(publication.MiscoPublicationProfileApplicationTests)
            profile_digests = set()
            for case in (generic, narrative, formal):
                with LocalWorkspace.open(case.workspace) as opened:
                    profile_digests.add(opened.binding["effective_profile_set"]["digest"])
                    expected = json.loads((case.root / "profiles-input.json").read_text("utf-8"))
                    self.assertEqual(expected, opened.effective_profile_set)
            self.assertEqual(3, len(profile_digests))
            self.assertEqual(4, initialize.call_count)

    def test_failed_seed_is_not_reused_and_existing_case_is_not_overwritten(self):
        with patch.object(LocalWorkspace, "init", side_effect=OSError("injected init failure")):
            with self.assertRaisesRegex(OSError, "injected init failure"):
                self.fixture()
        with patch.object(LocalWorkspace, "init", wraps=LocalWorkspace.init) as initialize:
            self.fixture()
            self.fixture()
            self.assertEqual(1, initialize.call_count)

    def test_opt_in_is_explicit_for_each_concrete_class(self):
        opted_in = type(
            "OptedIn", (ResearchPackageAcceptanceSupport,), {"REUSE_INITIAL_WORKSPACE": True}
        )
        inherited = type("NewScenario", (opted_in,), {})
        with patch.object(LocalWorkspace, "init") as initialize:
            self.fixture(ResearchPackageAcceptanceSupport)
            self.fixture(inherited)
            self.assertEqual(2, initialize.call_count)

    def test_initialization_migration_and_recovery_scenarios_keep_fresh_setup(self):
        def cases(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from cases(item)
                else:
                    yield item

        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT))
        self.assertEqual([], loader.errors)
        protected = re.compile(
            r"initializ|migrat|recover|restor|crash|interrupt|workspace_lock|profile_generation_advancement",
            re.IGNORECASE,
        )
        checked = 0
        for case in cases(suite):
            if isinstance(case, ResearchPackageAcceptanceSupport) and protected.search(case.id()):
                checked += 1
                self.assertFalse(
                    type(case).__dict__.get("REUSE_INITIAL_WORKSPACE", False), case.id()
                )
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
