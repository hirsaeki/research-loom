from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue220_publication_release as support


class PublicationReviewTests(ResearchPackageAcceptanceSupport):
    def _ready(self):
        helper = support.Issue220PublicationReleaseTests()
        helper.root, helper.workspace = self.root, self.workspace
        facade, _, composition, imported, _ = helper._prepared()
        self.addCleanup(facade.close)
        build = facade.build_publication_preview(
            composition['composition_id'], imported['revision_id']
        )['build']
        return facade, build['build_id']

    def test_staging_initialization_errors_are_public_write_diagnostics_and_retryable(self):
        facade, build_id = self._ready()
        service = facade._publication_release_service()
        original_mkdir = Path.mkdir
        import tempfile
        original_mkstemp = tempfile.mkstemp
        operation_dir = service.root / 'release-operations'

        def denied_mkdir(path, *args, **kwargs):
            if path == operation_dir:
                raise PermissionError('injected operation directory failure')
            return original_mkdir(path, *args, **kwargs)

        def denied_mkstemp(*args, **kwargs):
            if Path(kwargs.get('dir', '.')) == operation_dir:
                raise PermissionError('injected operation staging failure')
            return original_mkstemp(*args, **kwargs)

        for target, method, replacement in (
            (Path, 'mkdir', denied_mkdir),
            (tempfile, 'mkstemp', denied_mkstemp),
        ):
            with self.subTest(method=method):
                with patch.object(target, method, replacement):
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.request_publication_release(build_id, method)
                self.assertEqual(error.exception.code, 'APPLICATION-PUBLICATION-WRITE-001')
                request = facade.request_publication_release(build_id, method)['decision_request']
                self.assertEqual(
                    facade.request_publication_release(build_id, method)['decision_request'], request
                )

    def test_operation_only_recovery_is_reported_without_changing_original_facts(self):
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, 'H')['decision_request']
        response = support.Issue220PublicationReleaseTests._approval(request)
        manifest = facade.release_publication(build_id, response)['release']
        service = facade._publication_release_service()
        operation = service._operation_path(request['request_id'])
        original = operation.read_bytes()
        operation.unlink()
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with patch.object(reopened._application.clock, 'now', return_value='2099-01-01T00:00:00Z'):
                result = reopened.release_publication(build_id, response)
            self.assertEqual(result['status'], 'RESTORED')
            self.assertEqual(result['restored_components'], ['release-operation'])
            self.assertEqual(result['recovered_at'], '2099-01-01T00:00:00Z')
            self.assertEqual(result['release'], manifest)
            self.assertEqual(operation.read_bytes(), original)
            self.assertEqual(reopened.release_publication(build_id, response)['status'], 'VERIFIED_REUSE')

    def test_missing_operation_does_not_scan_unrelated_request_history(self):
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, 'H')['decision_request']
        service = facade._publication_release_service()
        service._operation_path(request['request_id']).unlink()
        # Both retained facts and total request loss use direct operation paths.
        with patch.object(Path, 'glob', side_effect=AssertionError('history scan')), \
             patch.object(Path, 'iterdir', side_effect=AssertionError('history scan')):
            with self.assertRaises(LocalApplicationError) as error:
                facade.request_publication_release(build_id, 'H')
            self.assertEqual(error.exception.code, 'APPLICATION-PUBLICATION-RECOVERY-REQUIRED-001')
            service._release_request_path(request['request_id']).unlink()
            new = facade.request_publication_release(build_id, 'H')['decision_request']
        self.assertNotEqual(new['request_id'], request['request_id'])
