from __future__ import annotations

import ctypes
import os
from pathlib import Path
import unittest

from plugins.local_application.workspace import LocalWorkspaceError, _safe_locator
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import issue80_writer_composition_suite as composition_support
import test_issue219_writer_round_trip as round_trip


class WriterRecoveryReviewTests(ResearchPackageAcceptanceSupport):
    def test_legacy_writer_recovery_ignores_non_file_json_entries(self):
        facade, _, composition, _, input_doc = round_trip.Issue219WriterRoundTripTests._build_round_trip(self)
        self.addCleanup(facade.close)
        response = round_trip.Issue219WriterRoundTripTests._response(input_doc)
        original = facade.import_writer_response(response)
        cid = composition['composition_id']
        service = facade._writer_round_trip_service()
        (service._revision_root(cid) / 'revisions' / 'abandoned.json').mkdir()
        service._checkpoint_path(cid).unlink()
        service._head_path(cid).unlink()
        restored = facade.import_writer_response(response)
        self.assertEqual(restored['revision_id'], original['revision_id'])
        self.assertEqual(restored['revision_digest'], original['revision_digest'])
        self.assertEqual(restored['status'], 'VERIFIED_REUSE')
        self.assertEqual(restored['restored_components'], ['continuity_record', 'head'])
        self.assertEqual(facade.import_writer_response(response)['status'], 'VERIFIED_REUSE')

    def test_legacy_composition_recovery_ignores_non_file_json_entries(self):
        facade, case = composition_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        self.addCleanup(facade.close)
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-LEGACY-DIR')
        original = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        service = facade._writer_composition_service()
        cid = original['composition_id']
        (service._series_root(cid) / 'versions' / 'abandoned.json').mkdir()
        service._capture_operation_path(cid).unlink()
        service._series_index_path(cid).unlink()
        result = facade.capture_writer_composition(case['package_id'], proposal)
        self.assertEqual(result['status'], 'RESTORED')
        self.assertEqual(result['composition'], original)

    def test_locator_compares_resolved_root_and_target_without_weakening_escape_guard(self):
        root = self.root / 'locator-root'
        root.mkdir()
        (root / 'segment').mkdir()
        alternate = root / 'segment' / '..'
        result = _safe_locator(alternate, 'managed/output.json', require_exists=False)
        self.assertEqual(result.resolve(), (root / 'managed' / 'output.json').resolve())
        self.assertFalse(result.exists())
        with self.assertRaises(LocalWorkspaceError):
            _safe_locator(alternate, '../outside.json', require_exists=False)
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            (root / 'escape').symlink_to(outside, target_is_directory=True)
            (self.root / 'root-link').symlink_to(root, target_is_directory=True)
        except OSError:
            return  # The real Windows alias check below does not require symlink privilege.
        with self.assertRaises(LocalWorkspaceError):
            _safe_locator(alternate, 'escape/output.json', require_exists=False)
        with self.assertRaises(LocalWorkspaceError):
            _safe_locator(self.root / 'root-link', 'output.json', require_exists=False)

    @unittest.skipUnless(os.name == 'nt', 'requires Windows short-path aliases')
    def test_real_windows_short_root_and_long_target_are_the_same_directory(self):
        full = self.root.resolve()
        get_short_path = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        get_short_path.restype = ctypes.c_uint32
        size = get_short_path(str(full), None, 0)
        if not size:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(size)
        if not get_short_path(str(full), buffer, size):
            raise ctypes.WinError(ctypes.get_last_error())
        short = Path(buffer.value)
        if short == full:
            self.skipTest('volume has no distinct short-path alias')
        result = _safe_locator(short, 'managed/output.json', require_exists=False)
        self.assertEqual(result.resolve(), full / 'managed' / 'output.json')
