from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalWorkspace
from plugins.local_application.cli import main
from plugins.local_durable_store import register_optional_path, require_optional_available
from plugins.local_project_input_store import LocalProjectInputStore, LocalProjectInputStoreError
from tests.runtime.test_research_question_review import _workspace


class OptionalDurableReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = _workspace(self.root)

    def _input(self, facade):
        source = self.workspace / 'input.txt'
        source.write_text('exact retained input', encoding='utf-8')
        snapshot = facade.status()['snapshot']
        value = {'file': str(source), 'role': 'theme',
                 'expected_snapshot_id': snapshot['snapshot_id'],
                 'expected_snapshot_digest': snapshot['content_digest']}
        return facade.register_project_input(value)['project_input'], value

    def test_public_resume_reports_missing_child_and_exact_restoration(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            item, _ = self._input(facade)
        finally:
            facade.close()
        child = self.workspace / '.research-loom' / 'project-inputs'
        backup = self.root / 'retained-child'
        child.rename(backup)
        output = io.StringIO()
        with patch('sys.stdout', output):
            code = main(['resume', '--workspace', str(self.workspace), '--json'])
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'DEGRADED')
        row = next(r for r in result['optional_children'] if r['name'] == 'project_inputs')
        self.assertEqual(row['code'], 'WORKSPACE-OPTIONAL-CHILD-MISSING-001')
        self.assertFalse(child.exists())
        backup.rename(child)
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        try:
            self.assertEqual(facade.resume_context()['status'], 'OK')
            self.assertEqual(facade.show_project_input(item['input_id'])['project_input'], item)
        finally:
            facade.close()

    def test_same_facade_closes_failed_connection_before_exact_child_restore(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        self.addCleanup(facade.close)
        item, value = self._input(facade)
        db_path = self.workspace / '.research-loom/project-inputs/project-inputs.sqlite3'
        saved = db_path.read_bytes()
        for operation in (facade.list_project_inputs,
                          lambda: facade.show_project_input(item['input_id']),
                          lambda: facade.register_project_input(value)):
            with self.subTest(operation=operation):
                facade.list_project_inputs()
                store = facade._project_input_store
                previous = store.db
                # Windows cannot unlink an open database. Inject the same named
                # health failure, assert release, then replace the exact bytes.
                with patch('plugins.local_durable_store.require_optional_available',
                           side_effect=LocalProjectInputStoreError(
                               'WORKSPACE-OPTIONAL-METADATA-MISSING-001', 'injected missing database')):
                    with self.assertRaises(LocalApplicationError):
                        operation()
                self.assertIsNone(store.db)
                self.assertFalse(store._writable)
                with self.assertRaises(sqlite3.ProgrammingError):
                    previous.execute('SELECT 1')
                db_path.unlink()
                db_path.write_bytes(saved)
                self.assertEqual(facade.list_project_inputs()['project_inputs'], [item])
                self.assertIsNot(store.db, previous)
                self.assertEqual(facade.register_project_input(value)['project_input'], item)

    def test_direct_store_read_and_write_release_connection_on_health_failure(self):
        store = LocalProjectInputStore(self.workspace)
        self.addCleanup(store.close)
        for operation in (store._open_read, store._open_write):
            with self.subTest(operation=operation):
                store._open_write()
                previous = store.db
                with patch('plugins.local_project_input_store.require_optional_available',
                           side_effect=LocalProjectInputStoreError('WORKSPACE-OPTIONAL-METADATA-MISSING-001', 'missing')):
                    with self.assertRaises(LocalProjectInputStoreError):
                        operation()
                self.assertIsNone(store.db)
                self.assertFalse(store._writable)
                with self.assertRaises(sqlite3.ProgrammingError):
                    previous.execute('SELECT 1')
                self.assertTrue(store._open_read())

    def test_standalone_missing_path_closes_cached_connection(self):
        store = LocalProjectInputStore(self.root / 'standalone')
        self.addCleanup(store.close)
        previous = store.db
        original = Path.exists
        with patch.object(Path, 'exists', lambda path: False if path == store.path else original(path)):
            self.assertFalse(store._open_read())
        self.assertIsNone(store.db)
        self.assertFalse(store._writable)
        with self.assertRaises(sqlite3.ProgrammingError):
            previous.execute('SELECT 1')
        self.assertTrue(store._open_read())

    def test_noncanonical_parent_alias_preserves_child_registration_and_health(self):
        # LocalWorkspace normalizes these aliases, just as Windows resolve()
        # expands a short (8.3) ancestor name. Store entry points must do so too,
        # without resolving away a symlink at the child itself.
        (self.root / 'spare').mkdir()
        alias = self.root / 'spare' / '..' / self.workspace.name
        store = LocalProjectInputStore(alias)
        store.close()
        history = alias / '.research-loom' / 'profile-history'
        history.mkdir()
        register_optional_path(history)
        require_optional_available(history)
        binding = json.loads((self.workspace / '.research-loom/workspace-binding.json').read_text())
        self.assertIn('project_inputs', binding['durable_children'])
        self.assertIn('profile_history', binding['durable_children'])
        self.assertEqual(LocalWorkspace.doctor(self.workspace)['status'], 'OK')
        history.rmdir()
        with self.assertRaisesRegex(RuntimeError, 'registered child is missing'):
            require_optional_available(history)


if __name__ == '__main__':
    unittest.main()
