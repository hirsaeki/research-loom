from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.cli import main
from plugins.local_application.item_listing import directory_page
from plugins.local_application.research_package_format import digest_json, without_digest
from plugins.local_application.writer_composition_service import _digest_document
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import issue80_writer_composition_suite as issue80


class Issue254ItemListingTests(ResearchPackageAcceptanceSupport):
    _proposal = issue80.Issue80WriterCompositionTests._proposal

    def _case(self):
        facade, case = self._build()
        self.addCleanup(facade.close)
        return facade, case

    def _package_copy(self, service, source_id, new_id, *, project_id=None):
        # Synthetic inventory fixture: only the listing's metadata contract is
        # changed. Content operations still perform independent full validation.
        path = service.root / new_id
        shutil.copytree(service.root / source_id, path)
        value = json.loads((path / 'research-package.json').read_text(encoding='utf-8'))
        value['package_id'] = new_id
        if project_id is not None:
            value['project']['project_id'] = project_id
        value['package_digest'] = digest_json(without_digest(value))
        (path / 'research-package.json').write_text(json.dumps(value), encoding='utf-8')
        return path

    @staticmethod
    def _bytes(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_package_faults_are_local_classified_and_exact_repair_restores_discovery(self):
        facade, case = self._case()
        service = facade._research_package_service()
        bad = self._package_copy(service, case['package_id'], 'RP-BAD')
        metadata = bad / 'research-package.json'
        original = metadata.read_bytes()
        for label, raw in [('MALFORMED_JSON', b'{'), ('MALFORMED_JSON', b'\xff'),
                           ('INVALID_METADATA_OR_BINDING', b'[]'), ('MISSING', None),
                           ('DIGEST_MISMATCH', original)]:
            with self.subTest(label=label, raw=raw and raw[:10]):
                if raw is None:
                    metadata.unlink(missing_ok=True)
                else:
                    # Use a schema-valid digest mismatch rather than a malformed digest.
                    if label == 'DIGEST_MISMATCH':
                        value = json.loads(original)
                        value['package_digest'] = 'sha256:' + '0' * 64
                        raw = json.dumps(value).encode()
                    metadata.write_bytes(raw)
                rows = {row['package_id']: row for row in facade.list_research_packages()['packages']}
                self.assertEqual(rows['RP-BAD']['diagnostic']['reason'], label)
                self.assertEqual(rows[case['package_id']]['availability'], 'AVAILABLE')
                self.assertIn('next_action', rows['RP-BAD']['diagnostic'])
                self.assertNotIn('package_digest', rows['RP-BAD'])
                with self.assertRaises(LocalApplicationError):
                    facade.show_research_package('RP-BAD')
                with self.assertRaises(LocalApplicationError):
                    facade.export_research_package('RP-BAD', self.root / 'bad-export')
                self.assertEqual(facade.show_research_package(case['package_id'])['status'], 'OK')
        metadata.write_bytes(original)
        self.assertTrue(all(row['availability'] == 'AVAILABLE' for row in facade.list_research_packages()['packages']))

    def test_permission_io_bounds_and_static_symlinks_do_not_read_unavailable_content(self):
        facade, case = self._case()
        service = facade._research_package_service()
        other = self._package_copy(service, case['package_id'], 'RP-BAD')
        path = other / 'research-package.json'
        real_open = Path.open
        for error, reason in [(PermissionError('private detail'), 'INACCESSIBLE'), (OSError('private detail'), 'IO_ERROR')]:
            def deny(item, *args, **kwargs):
                if item == path:
                    raise error
                return real_open(item, *args, **kwargs)
            with patch.object(Path, 'open', deny):
                rows = {row['package_id']: row for row in facade.list_research_packages()['packages']}
            self.assertEqual(rows['RP-BAD']['diagnostic']['reason'], reason)
            self.assertNotIn('private detail', json.dumps(rows))
            self.assertEqual(rows[case['package_id']]['availability'], 'AVAILABLE')
        original = path.read_bytes()
        path.write_bytes(b' ' * (16 * 1024 * 1024 + 1))
        rows = {row['package_id']: row for row in facade.list_research_packages()['packages']}
        self.assertEqual(rows['RP-BAD']['diagnostic']['reason'], 'READ_BOUND_EXCEEDED')
        path.write_bytes(original)
        link = service.root / 'RP-LINK'
        try:
            link.symlink_to(service.root / case['package_id'], target_is_directory=True)
        except OSError:
            pass  # Windows hosts without symlink privilege still run all fault cases.
        else:
            rows = {row['package_id']: row for row in facade.list_research_packages()['packages']}
            self.assertEqual(rows['RP-LINK']['diagnostic']['reason'], 'UNSAFE_PATH')

    def test_keyset_pages_cover_large_inventory_skip_staging_and_bind_scope(self):
        facade, case = self._case()
        service = facade._research_package_service()
        for n in reversed(range(102)):
            self._package_copy(service, case['package_id'], f'RP-ITEM-{n:03d}')
        (service.root / '.rp-staging').mkdir()
        self._package_copy(service, case['package_id'], 'RP-FOREIGN', project_id='PRJ-FOREIGN')
        seen, cursor, pages = [], None, 0
        while True:
            page = facade.list_research_packages(limit=17, cursor=cursor)
            self.assertLessEqual(page['scanned_items'], 17)
            self.assertEqual(page['truncated'], page['next_cursor'] is not None)
            seen.extend(row['package_id'] for row in page['packages'])
            pages += 1
            cursor = page['next_cursor']
            if not cursor:
                break
            self.assertLess(pages, 10)
        self.assertEqual(seen, sorted([case['package_id']] + [f'RP-ITEM-{n:03d}' for n in range(102)]))
        first = facade.list_research_packages(limit=1)
        cursor = first['next_cursor']
        self._package_copy(service, case['package_id'], 'RP-ZZZ-LATER')
        remaining = facade.list_research_packages(limit=100, cursor=cursor)
        self.assertTrue(remaining['truncated'])
        for invalid in ['', 'not base64', 'A' * 2049]:
            with self.assertRaises(LocalApplicationError):
                facade.list_research_packages(cursor=invalid)
        for limit in [0, -1, 101, True, 1.5]:
            with self.assertRaises(LocalApplicationError):
                facade.list_research_packages(limit=limit)
        with self.assertRaises(LocalApplicationError):
            facade.list_writer_compositions(cursor=cursor)
        with self.assertRaises(LocalApplicationError):
            directory_page(service.root, project_id='PRJ-OTHER', kind='research-package', limit=1, maximum=100, cursor=cursor)

    def test_writer_faults_paging_repair_and_selection_use_bounded_metadata(self):
        facade, case = self._case()
        service = facade._writer_composition_service()
        for name in ['COMP-A', 'COMP-B', 'COMP-C']:
            item = facade.capture_writer_composition(case['package_id'], self._proposal(case, composition_id=name))['composition']
            facade.select_writer_composition(name, 1, item['composition_digest'])
        page = facade.list_writer_compositions(limit=2)
        self.assertEqual([x['composition_id'] for x in page['compositions']], ['COMP-A', 'COMP-B'])
        tail = facade.list_writer_compositions(limit=2, cursor=page['next_cursor'])
        self.assertEqual([x['composition_id'] for x in tail['compositions']], ['COMP-C'])
        self.assertFalse(tail['truncated'])
        broken_paths = [service._series_index_path('COMP-B'), service._version_path('COMP-B', 1),
                        service._selection_state_path('COMP-B'), service._selection_event_path('COMP-B', 1)]
        for path in broken_paths:
            original = path.read_bytes()
            for raw in [b'{', b' ' * (4 * 1024 * 1024 + 1)]:
                path.write_bytes(raw)
                rows = {row['composition_id']: row for row in facade.list_writer_compositions()['compositions']}
                self.assertEqual(rows['COMP-B']['availability'], 'UNAVAILABLE')
                self.assertIn(rows['COMP-B']['diagnostic']['reason'], {'MALFORMED_JSON', 'READ_BOUND_EXCEEDED'})
                self.assertEqual(rows['COMP-A']['availability'], 'AVAILABLE')
                self.assertEqual(facade.show_writer_composition('COMP-A', 1)['status'], 'OK')
            path.write_bytes(original)
        # A missing derived latest pointer may be inspected, but list must not repair it.
        service._series_index_path('COMP-B').unlink()
        before = self._bytes(service.root)
        rows = facade.list_writer_compositions()['compositions']
        self.assertTrue(all(row['availability'] == 'AVAILABLE' for row in rows))
        self.assertEqual(self._bytes(service.root), before)
        self.assertTrue(all(row['verification_scope'] == 'METADATA_ONLY' for row in rows))
        # Losing the immutable version is local and cannot silently produce a healthy row.
        service._version_path('COMP-B', 1).unlink()
        rows = {row['composition_id']: row for row in facade.list_writer_compositions()['compositions']}
        self.assertEqual(rows['COMP-B']['diagnostic']['reason'], 'MISSING')
        with self.assertRaises(LocalApplicationError):
            facade.show_writer_composition('COMP-B', 1)
        with self.assertRaises(LocalApplicationError):
            facade.export_writer_composition('COMP-B', 1, self.root / 'bad-composition.json')

    def test_list_does_not_read_attachments_or_write_and_cli_continues(self):
        facade, case = self._case()
        package_service = facade._research_package_service()
        facade.capture_writer_composition(case['package_id'], self._proposal(case, composition_id='COMP-A'))
        self._package_copy(package_service, case['package_id'], 'RP-OTHER')
        before = self._bytes(package_service.root)
        real_open = Path.open
        def no_attachment(path, *args, **kwargs):
            if 'attachments' in path.parts:
                raise AssertionError('inventory must not read payloads')
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', no_attachment):
            self.assertTrue(all(x['availability'] == 'AVAILABLE' for x in facade.list_research_packages()['packages']))
            self.assertEqual(facade.list_writer_compositions()['compositions'][0]['availability'], 'AVAILABLE')
        self.assertEqual(self._bytes(package_service.root), before)
        facade.close()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['research-package', 'list', '--workspace', str(self.workspace), '--limit', '1', '--json']), 0)
        first = json.loads(output.getvalue())
        self.assertTrue(first['truncated'])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['research-package', 'list', '--workspace', str(self.workspace), '--limit', '1', '--cursor', first['next_cursor'], '--json']), 0)
        self.assertFalse(json.loads(output.getvalue())['truncated'])

    def test_empty_inventory_and_unsafe_identity_are_non_creating(self):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            roots = [facade._research_package_service().root, facade._writer_composition_service().root]
            self.assertTrue(all(not root.exists() for root in roots))
            self.assertEqual(facade.list_research_packages()['packages'], [])
            self.assertEqual(facade.list_writer_compositions()['compositions'], [])
            self.assertTrue(all(not root.exists() for root in roots))
        facade, case = self._case()
        service = facade._research_package_service()
        # Newline is legal on POSIX, rejected by Windows filename rules.
        try:
            (service.root / 'RP-unsafe\nname').mkdir()
        except OSError:
            return
        rows = facade.list_research_packages()['packages']
        bad = next(row for row in rows if row['availability'] == 'UNAVAILABLE')
        self.assertNotIn('package_id', bad)
        self.assertIn('entry_fingerprint', bad)
        first = facade.list_research_packages(limit=1)
        tail = facade.list_research_packages(limit=1, cursor=first['next_cursor'])
        self.assertFalse(tail['truncated'])

    def test_ablation_isolation_and_digest_guards_have_distinct_effects(self):
        facade, case = self._case()
        service = facade._research_package_service()
        broken = self._package_copy(service, case['package_id'], 'RP-BAD') / 'research-package.json'
        value = json.loads(broken.read_text(encoding='utf-8'))
        value['package_digest'] = 'sha256:' + '0' * 64
        broken.write_text(json.dumps(value), encoding='utf-8')
        rows = {r['package_id']: r for r in facade.list_research_packages()['packages']}
        self.assertEqual(rows['RP-BAD']['diagnostic']['reason'], 'DIGEST_MISMATCH')
        # Removing only isolation makes one broken item abort discovery.
        def fail_again(_field, _identity, error):
            raise error
        with patch('plugins.local_application.research_package_service.unavailable', fail_again):
            with self.assertRaises(LocalApplicationError):
                facade.list_research_packages()
        # Removing only digest validation admits a metadata record whose digest is false.
        with patch('plugins.local_application.research_package_service.digest_json', return_value=value['package_digest']):
            item = service._load_metadata('RP-BAD')
        self.assertNotEqual(item['package_digest'], digest_json(without_digest(item)))
        with self.assertRaises(LocalApplicationError):
            facade.show_research_package('RP-BAD')

    def test_writer_identity_digest_and_foreign_project_are_not_healthy_local_records(self):
        facade, case = self._case()
        service = facade._writer_composition_service()
        value = facade.capture_writer_composition(case['package_id'], self._proposal(case, composition_id='COMP-A'))['composition']
        facade.capture_writer_composition(case['package_id'], self._proposal(case, composition_id='COMP-B'))
        path = service._version_path('COMP-B', 1)
        original = path.read_bytes()
        # Exact copied bytes with the wrong identity must also fail known-ID show/export.
        path.write_text(json.dumps(value), encoding='utf-8')
        rows = {row['composition_id']: row for row in facade.list_writer_compositions()['compositions']}
        self.assertEqual(rows['COMP-B']['diagnostic']['reason'], 'INVALID_METADATA_OR_BINDING')
        with self.assertRaises(LocalApplicationError):
            facade.show_writer_composition('COMP-B', 1)
        path.write_bytes(original)
        changed = json.loads(original)
        changed['purpose'] = 'Different unverified facts'
        path.write_text(json.dumps(changed), encoding='utf-8')
        rows = {row['composition_id']: row for row in facade.list_writer_compositions()['compositions']}
        self.assertEqual(rows['COMP-B']['diagnostic']['reason'], 'DIGEST_MISMATCH')
        path.write_bytes(original)
        # Scope is assessed from independently digest-checked metadata. A valid
        # foreign record consumes a scan slot, not a local inventory row.
        package_service = facade._research_package_service()
        foreign = self._package_copy(package_service, case['package_id'], 'RP-FOREIGN', project_id='PRJ-FOREIGN')
        package = json.loads((foreign / 'research-package.json').read_text(encoding='utf-8'))
        changed = json.loads(original)
        changed['source'] = service._source_pin(package, lineage_ref=changed['source']['lineage_ref'])
        changed['composition_digest'] = _digest_document(changed, 'composition_digest')
        path.write_text(json.dumps(changed), encoding='utf-8')
        index = json.loads(service._series_index_path('COMP-B').read_text(encoding='utf-8'))
        index['latest_digest'] = changed['composition_digest']
        service._series_index_path('COMP-B').write_text(json.dumps(index), encoding='utf-8')
        rows = facade.list_writer_compositions()['compositions']
        self.assertEqual([row['composition_id'] for row in rows], ['COMP-A'])
