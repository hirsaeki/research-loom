from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.writer_round_trip_service import WriterRoundTripService
from plugins.local_application.writer_composition_history_service import WriterCompositionHistoryService
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue219_writer_round_trip as round_trip
import issue80_writer_composition_suite as composition_support


class WriterRecoveryTests(ResearchPackageAcceptanceSupport):
    def _ready(self):
        result = round_trip.Issue219WriterRoundTripTests._build_round_trip(self)
        self.addCleanup(result[0].close)
        return result

    @staticmethod
    def _response(input_doc, **kwargs):
        return round_trip.Issue219WriterRoundTripTests._response(input_doc, **kwargs)

    @staticmethod
    def _base(revision):
        return {key: revision[key] for key in ('revision_id', 'revision_digest')}

    def test_interrupted_revision_is_finished_before_accepting_a_different_response(self):
        facade, _, composition, _, input_doc = self._ready()
        first = facade.import_writer_response(self._response(input_doc))
        b = self._response(input_doc, response_id='B', base=self._base(first))
        c = self._response(input_doc, response_id='C', base=self._base(first))
        with patch.object(WriterRoundTripService, '_write_head', side_effect=LocalApplicationError(
                'APPLICATION-WRITER-ROUND-TRIP-WRITE-001', 'injected head failure')):
            with self.assertRaises(LocalApplicationError):
                facade.import_writer_response(b)
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with self.assertRaises(LocalApplicationError) as error:
                reopened.import_writer_response(c)
            self.assertEqual(error.exception.code, 'APPLICATION-WRITER-ROUND-TRIP-STALE-001')
            replay = reopened.import_writer_response(b)
            self.assertEqual(replay['status'], 'VERIFIED_REUSE')
            self.assertEqual(replay['revision_number'], 2)
            shown = reopened.inspect_writer_round_trip(composition['composition_id'])
            self.assertEqual(shown['revision']['revision_id'], replay['revision_id'])
            c['base_revision_ref'] = self._base(replay)
            third = reopened.import_writer_response(c)
            self.assertEqual(third['revision_number'], 3)

    def test_revision_and_head_loss_restores_original_facts_not_a_later_clock(self):
        facade, _, composition, _, input_doc = self._ready()
        response = self._response(input_doc)
        first = facade.import_writer_response(response)
        service = facade._writer_round_trip_service()
        path = service._revision_path(composition['composition_id'], first['revision_id'])
        original = path.read_bytes()
        path.unlink()
        service._head_path(composition['composition_id']).unlink()
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with patch('plugins.local_application.writer_round_trip_service._now', return_value='2099-01-01T00:00:00Z'):
                retry = reopened.import_writer_response(response)
            self.assertEqual(retry['revision_id'], first['revision_id'])
            self.assertEqual(retry['revision_digest'], first['revision_digest'])
            self.assertEqual(path.read_bytes(), original)

    def test_composition_version_and_index_loss_preserves_exact_original_facts(self):
        facade, case = composition_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        self.addCleanup(facade.close)
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-RECOVER')
        first = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        service = facade._writer_composition_service()
        path = service._version_path(first['composition_id'], 1)
        original = path.read_bytes()
        path.unlink()
        service._series_index_path(first['composition_id']).unlink()
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with patch('plugins.local_application.writer_composition_history_service._now', return_value='2099-01-01T00:00:00Z'):
                retry = reopened.capture_writer_composition(case['package_id'], proposal)['composition']
            self.assertEqual(retry, first)
            self.assertEqual(path.read_bytes(), original)

    def test_pending_latest_inspection_is_read_only_and_healthy_replay_does_not_scan(self):
        facade, _, composition, _, input_doc = self._ready()
        first = facade.import_writer_response(self._response(input_doc))
        response = self._response(input_doc, response_id='B', base=self._base(first))
        with patch.object(WriterRoundTripService, '_write_head', side_effect=LocalApplicationError(
                'APPLICATION-WRITER-ROUND-TRIP-WRITE-001', 'injected')):
            with self.assertRaises(LocalApplicationError):
                facade.import_writer_response(response)
        service = facade._writer_round_trip_service()
        pointer = service._head_path(composition['composition_id'])
        original = pointer.read_bytes()
        with self.assertRaises(LocalApplicationError) as error:
            facade.inspect_writer_round_trip(composition['composition_id'])
        self.assertEqual(error.exception.code, 'APPLICATION-WRITER-ROUND-TRIP-RECOVERY-REQUIRED-001')
        self.assertEqual(pointer.read_bytes(), original)
        with patch.object(WriterRoundTripService, '_load_latest_revision', side_effect=AssertionError('history scan')):
            replay = facade.import_writer_response(response)
            self.assertEqual(replay['revision_number'], 2)
            self.assertEqual(facade.import_writer_response(response)['status'], 'VERIFIED_REUSE')
        self.assertFalse(replay['research_state_mutation_performed'])

    def test_bad_head_or_checkpoint_is_preserved_and_exact_backup_allows_retry(self):
        from plugins.local_application.writer_round_trip_service import _digest_document as _digest, _json_bytes
        facade, _, composition, _, input_doc = self._ready()
        response = self._response(input_doc)
        first = facade.import_writer_response(response)
        service = facade._writer_round_trip_service()
        cid = composition['composition_id']
        for target in (service._head_path(cid), service._checkpoint_path(cid), service._revision_path(cid, first['revision_id'])):
            original = target.read_bytes()
            for bad in (b'{', b'null', b'[]'):
                with self.subTest(path=target.name, bad=bad):
                    target.write_bytes(bad)
                    with self.assertRaises(LocalApplicationError):
                        facade.import_writer_response(response)
                    self.assertEqual(target.read_bytes(), bad)
            target.write_bytes(original)
        checkpoint = service._checkpoint_path(cid)
        original = checkpoint.read_bytes()
        for field, value in (('input_digest', 'sha256:' + '0' * 64), ('composition_id', 'COMP-OTHER')):
            forged = json.loads(original)
            forged['source'][field] = value
            forged['revision_digest'] = _digest(forged, 'revision_digest')
            checkpoint.write_bytes(_json_bytes(forged))
            with self.assertRaises(LocalApplicationError):
                facade.import_writer_response(response)
            self.assertEqual(checkpoint.read_bytes(), _json_bytes(forged))
        checkpoint.write_bytes(original)
        service._head_path(cid).unlink()  # An operator may remove only this derived pointer.
        retry = facade.import_writer_response(response)
        self.assertEqual(retry['revision_digest'], first['revision_digest'])

    def test_legacy_writer_history_recovers_unique_head_and_rejects_ambiguous_successors(self):
        from plugins.local_application.writer_round_trip_service import _digest_document as _digest, _json_bytes
        facade, _, composition, _, input_doc = self._ready()
        first_response = self._response(input_doc)
        first = facade.import_writer_response(first_response)
        second_response = self._response(input_doc, response_id='B', base=self._base(first))
        second = facade.import_writer_response(second_response)
        service = facade._writer_round_trip_service()
        cid = composition['composition_id']
        original = service._revision_path(cid, second['revision_id']).read_bytes()
        service._checkpoint_path(cid).unlink()
        service._head_path(cid).write_bytes(_json_bytes(service._revision_ref(first)))
        replay = facade.import_writer_response(second_response)
        self.assertEqual(replay['revision_digest'], second['revision_digest'])
        self.assertIn('continuity_record', replay['restored_components'])
        service._checkpoint_path(cid).unlink()
        fork = json.loads(original)
        fork['revision_id'] = 'WMR-' + 'f' * 24
        fork['revision_digest'] = _digest(fork, 'revision_digest')
        fork_path = service._revision_path(cid, fork['revision_id'])
        fork_path.write_bytes(_json_bytes(fork))
        with self.assertRaises(LocalApplicationError) as error:
            facade.import_writer_response(second_response)
        self.assertEqual(error.exception.code, 'APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001')
        self.assertFalse(service._checkpoint_path(cid).exists())
        self.assertEqual(service._revision_path(cid, second['revision_id']).read_bytes(), original)

    def test_writer_write_boundaries_preserve_pending_facts_and_retry_exactly(self):
        import os
        import tempfile
        from pathlib import Path
        facade, _, composition, _, input_doc = self._ready()
        service = facade._writer_round_trip_service()
        cid = composition['composition_id']
        prior = facade.import_writer_response(self._response(input_doc))
        for method in ('mkdir', 'mkstemp', 'link', 'replace'):
            response = self._response(input_doc, response_id='CUT-' + method, base=self._base(prior))
            target, name = (Path, 'mkdir') if method == 'mkdir' else ((tempfile, method) if method == 'mkstemp' else (os, method))
            original = getattr(target, name)
            def fail_at_record(*args, **kwargs):
                if method == 'mkdir':
                    hit = Path(args[0]) == service._revision_root(cid) / 'revisions'
                elif method == 'mkstemp':
                    hit = Path(kwargs.get('dir', '.')) == service._revision_root(cid) / 'revisions'
                elif method == 'link':
                    hit = Path(args[1]).parent == service._revision_root(cid) / 'revisions'
                else:
                    hit = Path(args[1]) == service._head_path(cid)
                if hit:
                    raise PermissionError('injected ' + method)
                return original(*args, **kwargs)
            with self.subTest(method=method), patch.object(target, name, fail_at_record):
                with self.assertRaises(LocalApplicationError) as error:
                    facade.import_writer_response(response)
                self.assertEqual(error.exception.code, 'APPLICATION-WRITER-ROUND-TRIP-WRITE-001')
            pending = json.loads(service._checkpoint_path(cid).read_bytes())
            with patch('plugins.local_application.writer_round_trip_service._now', return_value='2099-01-01T00:00:00Z'):
                retry = facade.import_writer_response(response)
            self.assertEqual(retry['revision_digest'], pending['revision_digest'])
            self.assertEqual(retry['revision_number'], prior['revision_number'] + 1)
            prior = retry

    def test_composition_pending_capture_precedes_other_proposals_and_legacy_replay(self):
        facade, case = composition_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        self.addCleanup(facade.close)
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-PENDING')
        first = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        revised = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-PENDING', base=first)
        with patch.object(WriterCompositionHistoryService, '_write_series_index', side_effect=LocalApplicationError(
                'APPLICATION-WRITER-COMPOSITION-WRITE-001', 'injected index failure')):
            with self.assertRaises(LocalApplicationError):
                facade.capture_writer_composition(case['package_id'], revised)
        other = deepcopy(revised)
        other['change_reason'] = 'A different successor'
        with self.assertRaises(LocalApplicationError) as error:
            facade.capture_writer_composition(case['package_id'], other)
        self.assertEqual(error.exception.code, 'APPLICATION-WRITER-COMPOSITION-STALE-001')
        service = facade._writer_composition_service()
        with patch.object(WriterCompositionHistoryService, '_legacy_latest_version_info', side_effect=AssertionError('healthy scan')):
            second = facade.capture_writer_composition(case['package_id'], revised)['composition']
        self.assertEqual(second['version'], 2)
        service._capture_operation_path('COMP-PENDING').unlink()
        service._series_index_path('COMP-PENDING').unlink()
        with patch('plugins.local_application.writer_composition_history_service._now', return_value='2099-01-01T00:00:00Z'):
            replay = facade.capture_writer_composition(case['package_id'], revised)
        self.assertEqual(replay['status'], 'RESTORED')
        self.assertEqual(replay['composition'], second)

    def test_composition_bad_pointer_and_continuity_binding_are_not_overwritten(self):
        from plugins.local_application.writer_composition_service import _digest_document
        facade, case = composition_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        self.addCleanup(facade.close)
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-CORRUPT')
        first = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        service = facade._writer_composition_service()
        operation_path = service._capture_operation_path(first['composition_id'])
        index_path = service._series_index_path(first['composition_id'])
        for target in (operation_path, index_path):
            original = target.read_bytes()
            for bad in (b'{', b'null'):
                target.write_bytes(bad)
                with self.assertRaises(LocalApplicationError):
                    facade.capture_writer_composition(case['package_id'], proposal)
                self.assertEqual(target.read_bytes(), bad)
            target.write_bytes(original)
        original = operation_path.read_bytes()
        for field, value in (('research_package_digest', 'sha256:' + '0' * 64), ('composition_id', 'COMP-OTHER')):
            forged = json.loads(original)
            if field == 'composition_id':
                forged['composition'][field] = value
            else:
                forged['composition']['source'][field] = value
            forged['composition']['composition_digest'] = _digest_document(forged['composition'], 'composition_digest')
            forged['operation_digest'] = _digest_document(forged, 'operation_digest')
            operation_path.write_text(json.dumps(forged), encoding='utf-8')
            with self.assertRaises(LocalApplicationError):
                facade.capture_writer_composition(case['package_id'], proposal)
            self.assertEqual(json.loads(operation_path.read_bytes()), forged)
        operation_path.write_bytes(original)
        index_path.unlink()
        self.assertEqual(facade.capture_writer_composition(case['package_id'], proposal)['composition'], first)

    def test_composition_staging_failure_has_public_diagnosis_and_retains_original_version(self):
        import os
        import tempfile
        from pathlib import Path
        facade, case = composition_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        self.addCleanup(facade.close)
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-CUT')
        first = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        service = facade._writer_composition_service()
        revised = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-CUT', base=first)
        original_mkstemp = tempfile.mkstemp
        def denied_staging(*args, **kwargs):
            if Path(kwargs.get('dir', '.')) == service._series_root('COMP-CUT') / 'versions':
                raise PermissionError('injected version staging failure')
            return original_mkstemp(*args, **kwargs)
        with patch.object(tempfile, 'mkstemp', side_effect=denied_staging):
            with self.assertRaises(LocalApplicationError) as error:
                facade.capture_writer_composition(case['package_id'], revised)
        self.assertEqual(error.exception.code, 'APPLICATION-WRITER-COMPOSITION-WRITE-001')
        pending = json.loads(service._capture_operation_path('COMP-CUT').read_bytes())['composition']
        with patch('plugins.local_application.writer_composition_history_service._now', return_value='2099-01-01T00:00:00Z'):
            retry = facade.capture_writer_composition(case['package_id'], revised)
        self.assertEqual(retry['status'], 'RESTORED')
        self.assertEqual(retry['composition'], pending)
        self.assertEqual(service._load_version('COMP-CUT', 1), first)
