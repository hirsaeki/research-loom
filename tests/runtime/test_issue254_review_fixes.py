from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
from plugins.local_application.item_listing import directory_page
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import issue80_writer_composition_suite as issue80


class Issue254InventoryRootTests(unittest.TestCase):
    def test_linked_root_or_ancestor_is_rejected_before_enumeration(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            outside = root / 'outside'
            (outside / 'RP-PRIVATE').mkdir(parents=True)
            alias = root / 'linked'
            if os.name == 'nt':
                completed = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(outside)],
                                           capture_output=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            else:
                alias.symlink_to(outside, target_is_directory=True)
            try:
                for path in [alias, alias / 'nested']:
                    for kind in ['research-package', 'writer-composition']:
                        with self.subTest(path=path, kind=kind), patch(
                            'plugins.local_application.item_listing.os.scandir',
                            side_effect=AssertionError('outside directory must not be scanned'),
                        ):
                            with self.assertRaises(LocalApplicationError) as raised:
                                directory_page(path, project_id='PRJ-A', kind=kind,
                                               limit=1, maximum=100, cursor=None)
                            self.assertEqual(raised.exception.code, 'APPLICATION-LIST-UNSAFE-PATH-001')
            finally:
                if os.name == 'nt':
                    alias.rmdir()
                else:
                    alias.unlink()


class Issue254SelectionEventTests(ResearchPackageAcceptanceSupport):
    _proposal = issue80.Issue80WriterCompositionTests._proposal

    def test_missing_event_is_local_missing_not_invalid_metadata(self):
        facade, case = self._build()
        self.addCleanup(facade.close)
        for name in ['COMP-A', 'COMP-B']:
            document = facade.capture_writer_composition(case['package_id'], self._proposal(case, composition_id=name))['composition']
            facade.select_writer_composition(name, 1, document['composition_digest'])
        service = facade._writer_composition_service()
        path = service._selection_event_path('COMP-B', 1)
        original = path.read_bytes()
        path.unlink()
        before = service._selection_state_path('COMP-B').read_bytes()
        rows = {row['composition_id']: row for row in facade.list_writer_compositions()['compositions']}
        self.assertEqual(rows['COMP-B']['availability'], 'UNAVAILABLE')
        self.assertEqual(rows['COMP-B']['diagnostic']['reason'], 'MISSING')
        self.assertEqual(rows['COMP-A']['availability'], 'AVAILABLE')
        self.assertEqual(service._selection_state_path('COMP-B').read_bytes(), before)
        self.assertFalse(path.exists())
        with self.assertRaises(LocalApplicationError):
            facade.show_writer_composition('COMP-B', 1)
        path.write_bytes(original)
        self.assertTrue(all(row['availability'] == 'AVAILABLE' for row in facade.list_writer_compositions()['compositions']))
