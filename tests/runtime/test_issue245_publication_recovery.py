from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.cli import main
from plugins.local_application.publication_release_service import PublicationReleaseService, _json_bytes
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue220_publication_release as support


class PublicationRecoveryTests(ResearchPackageAcceptanceSupport):
    def _ready(self):
        helper = support.Issue220PublicationReleaseTests()
        helper.root, helper.workspace = self.root, self.workspace
        facade, _, composition, imported, _ = helper._prepared()
        self.addCleanup(facade.close)
        build = facade.build_publication_preview(composition['composition_id'], imported['revision_id'])['build']
        return facade, build['build_id']

    def _released(self):
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, 'H')['decision_request']
        response = support.Issue220PublicationReleaseTests._approval(request)
        manifest = facade.release_publication(build_id, response)['release']
        return facade, build_id, request, response, manifest

    def test_missing_request_manifest_artifact_and_directory_restore_exact_facts_after_reopen(self):
        facade, build_id, request, response, manifest = self._released()
        service = facade._publication_release_service()
        request_path = service._release_request_path(request['request_id'])
        target = service.root / 'releases' / manifest['release_id']
        original = (target / 'artifact.docx').read_bytes()
        before = facade.status()['snapshot']
        facade.close()
        for fault in ('request', 'manifest', 'artifact', 'directory', 'request_and_directory'):
            with self.subTest(fault=fault):
                if 'request' in fault:
                    request_path.unlink()
                if 'directory' in fault:
                    shutil.rmtree(target)
                elif fault == 'manifest':
                    (target / 'release-manifest.json').unlink()
                elif fault == 'artifact':
                    (target / 'artifact.docx').unlink()
                with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
                    with patch.object(reopened._application.clock, 'now', return_value='2099-01-01T00:00:00Z'):
                        result = reopened.release_publication(build_id, response)
                        retry = reopened.request_publication_release(build_id, 'H')
                    self.assertEqual(result['status'], 'RESTORED')
                    self.assertEqual(result['release'], manifest)
                    self.assertEqual(result['recovered_at'], '2099-01-01T00:00:00Z')
                    self.assertEqual(retry['decision_request'], request)
                    self.assertEqual(reopened.status()['snapshot'], before)
                self.assertEqual((target / 'artifact.docx').read_bytes(), original)
                self.assertEqual((target / 'release-manifest.json').read_bytes(), _json_bytes(manifest))
                self.assertEqual(request_path.read_bytes(), _json_bytes(request))

    def test_request_output_failure_reuses_write_ahead_request_without_another_timestamp(self):
        facade, build_id = self._ready()
        original = PublicationReleaseService._atomic_release_write
        def fail_replica(service, path, data, **kwargs):
            if path.parent.name == 'release-requests':
                raise OSError('injected response-copy write failure')
            return original(service, path, data, **kwargs)
        with patch.object(PublicationReleaseService, '_atomic_release_write', fail_replica):
            with self.assertRaises(OSError):
                facade.request_publication_release(build_id, 'H')
        record = json.loads(next((facade._publication_release_service().root / 'release-operations').glob('*.json')).read_text())
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with patch.object(reopened._application.clock, 'now', return_value='2099-01-01T00:00:00Z'):
                result = reopened.request_publication_release(build_id, 'H')
            self.assertEqual(result['status'], 'RESTORED')
            self.assertEqual(result['decision_request'], record['request'])
            self.assertEqual(reopened.request_publication_release(build_id, 'H')['status'], 'VERIFIED_REUSE')

    def test_release_interruption_replays_same_decision_before_and_after_artifact_install(self):
        facade, build_id = self._ready()
        original = PublicationReleaseService._atomic_release_write
        for failed_part in ('artifact.docx', 'release-manifest.json'):
            with self.subTest(failed_part=failed_part):
                request = facade.request_publication_release(build_id, failed_part)['decision_request']
                response = support.Issue220PublicationReleaseTests._approval(request)
                def fail_part(service, path, data, **kwargs):
                    if path.name == failed_part:
                        raise OSError('injected release copy failure')
                    return original(service, path, data, **kwargs)
                with patch.object(PublicationReleaseService, '_atomic_release_write', fail_part):
                    with self.assertRaises(OSError):
                        facade.release_publication(build_id, response)
                operation = facade._publication_release_service()._load_release_operation(request['request_id'])
                self.assertEqual(operation['phase'], 'DECIDED')
                with patch.object(facade._application.clock, 'now', return_value='2099-01-01T00:00:00Z'):
                    result = facade.release_publication(build_id, response)
                self.assertEqual(result['status'], 'RESTORED')
                self.assertEqual(result['release'], operation['release'])
                self.assertEqual(facade.release_publication(build_id, response)['status'], 'VERIFIED_REUSE')

    def test_failed_decision_record_commit_has_no_release_effect_and_can_retry(self):
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, 'H')['decision_request']
        response = support.Issue220PublicationReleaseTests._approval(request)
        root = facade._publication_release_service().root
        with patch('plugins.local_application.publication_release_service.os.replace', side_effect=PermissionError('denied')):
            with self.assertRaises(LocalApplicationError) as error:
                facade.release_publication(build_id, response)
        self.assertEqual(error.exception.code, 'APPLICATION-PUBLICATION-WRITE-001')
        self.assertFalse((root / 'releases').exists())
        self.assertEqual(facade._publication_release_service()._load_release_operation(request['request_id'])['phase'], 'PENDING')
        self.assertEqual(facade.release_publication(build_id, response)['status'], 'RELEASED')

    def test_lost_decision_facts_require_explicit_new_request_and_approval(self):
        facade, build_id, request, response, manifest = self._released()
        service = facade._publication_release_service()
        operation_path = service._operation_path(request['request_id'])
        saved_operation = operation_path.read_bytes()
        operation_path.unlink()
        # A complete, independently verified old manifest restores its original facts.
        self.assertEqual(facade.release_publication(build_id, response)['release'], manifest)
        self.assertEqual(operation_path.read_bytes(), saved_operation)
        operation_path.unlink()
        target = service.root / 'releases' / manifest['release_id']
        (target / 'release-manifest.json').unlink()
        artifact_before = (target / 'artifact.docx').read_bytes()
        for call in (lambda: facade.release_publication(build_id, response),
                     lambda: facade.request_publication_release(build_id, 'H')):
            with self.assertRaises(LocalApplicationError) as error:
                call()
            self.assertEqual(error.exception.code, 'APPLICATION-PUBLICATION-RECOVERY-REQUIRED-001')
        renewal = facade.request_publication_release(build_id, 'H', renewal_of=request['request_id'])['decision_request']
        self.assertNotEqual(renewal['request_id'], request['request_id'])
        self.assertEqual(facade.request_publication_release(build_id, 'H', renewal_of=request['request_id'])['decision_request'], renewal)
        wrong = {**response, 'request_id': renewal['request_id']}
        with self.assertRaises(LocalApplicationError):
            facade.release_publication(build_id, wrong)
        new = facade.release_publication(build_id, support.Issue220PublicationReleaseTests._approval(renewal))['release']
        self.assertNotEqual(new['release_id'], manifest['release_id'])
        self.assertEqual((target / 'artifact.docx').read_bytes(), artifact_before)
        self.assertFalse((target / 'release-manifest.json').exists())

    def test_total_request_fact_loss_allocates_new_identity_even_with_same_clock(self):
        facade, build_id, request, response, manifest = self._released()
        service = facade._publication_release_service()
        target = service.root / 'releases' / manifest['release_id'] / 'release-manifest.json'
        original = target.read_bytes()
        service._operation_path(request['request_id']).unlink()
        service._release_request_path(request['request_id']).unlink()
        with patch.object(facade._application.clock, 'now', return_value=request['issued_at']):
            fresh = facade.request_publication_release(build_id, 'H')['decision_request']
        self.assertNotEqual(fresh['request_id'], request['request_id'])
        self.assertNotEqual(fresh['request_digest'], request['request_digest'])
        with self.assertRaises(LocalApplicationError):
            facade.release_publication(build_id, response)
        self.assertEqual(target.read_bytes(), original)

    def test_cli_renewal_and_exact_restore(self):
        facade, build_id, request, response, manifest = self._released()
        service = facade._publication_release_service()
        service._release_request_path(request['request_id']).unlink()
        facade.close()
        output = io.StringIO()
        args = ['publication', 'release-request', '--workspace', str(self.workspace),
                '--build-id', build_id, '--actor-id', 'H', '--json']
        with patch('sys.stdout', output):
            code = main(args)
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['decision_request'], request)
        output = io.StringIO()
        with patch('sys.stdout', output):
            code = main(args + ['--renewal-of', request['request_id']])
        self.assertEqual(code, 0, output.getvalue())
        renewal = json.loads(output.getvalue())['decision_request']
        self.assertEqual(renewal['renewal_of'], request['request_id'])
        self.assertNotEqual(renewal['request_id'], request['request_id'])

    def test_corrupt_operation_and_unsafe_recovery_target_are_not_overwritten(self):
        facade, build_id, request, response, manifest = self._released()
        service = facade._publication_release_service()
        operation_path = service._operation_path(request['request_id'])
        original = operation_path.read_bytes()
        operation_path.write_bytes(b'{')
        with self.assertRaises(LocalApplicationError):
            facade.release_publication(build_id, response)
        self.assertEqual(operation_path.read_bytes(), b'{')
        operation_path.write_bytes(original)
        artifact = service.root / 'releases' / manifest['release_id'] / 'artifact.docx'
        outside = self.root / 'outside.docx'
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        try:
            artifact.symlink_to(outside)
        except OSError as exc:
            self.skipTest(str(exc))
        before = outside.read_bytes()
        with self.assertRaises(RuntimeError):
            facade.release_publication(build_id, response)
        self.assertEqual(outside.read_bytes(), before)

    def test_concurrent_identical_approval_records_one_decision(self):
        import threading
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, 'H')['decision_request']
        response = support.Issue220PublicationReleaseTests._approval(request)
        shown = facade.show_publication_preview(build_id)
        entered, proceed = threading.Event(), threading.Event()
        original = PublicationReleaseService._write_release_operation
        decisions = []
        def slow_commit(service, value, manifest=None):
            if manifest is not None:
                decisions.append(deepcopy(manifest))
                entered.set()
                self.assertTrue(proceed.wait(5))
            return original(service, value, manifest)
        results, errors = [], []
        def invoke():
            try:
                results.append(facade.release_publication(build_id, response))
            except Exception as exc:
                errors.append(exc)
        with patch.object(PublicationReleaseService, 'show_preview', return_value=shown), \
             patch.object(PublicationReleaseService, '_write_release_operation', slow_commit):
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke)
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            proceed.set()
            first.join(10)
            second.join(10)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual(len(decisions), 1)
        self.assertEqual({result['status'] for result in results}, {'RELEASED', 'VERIFIED_REUSE'})
        self.assertEqual(results[0]['release'], results[1]['release'])
