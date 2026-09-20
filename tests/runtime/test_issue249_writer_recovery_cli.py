from __future__ import annotations

import io
import json
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.cli import main
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue219_writer_round_trip as writer_support
import issue80_writer_composition_suite as composition_support


class WriterRecoveryCliTests(ResearchPackageAcceptanceSupport):
    def _cli(self, *args):
        output = io.StringIO()
        with patch('sys.stdout', output):
            code = main([*args, '--workspace', str(self.workspace)])
        self.assertEqual(code, 0, output.getvalue())
        return json.loads(output.getvalue())

    def test_cli_recovers_original_manuscript_then_inspects_it_without_state_mutation(self):
        facade, _, composition, _, input_doc = writer_support.Issue219WriterRoundTripTests._build_round_trip(self)
        self.addCleanup(facade.close)
        response = writer_support.Issue219WriterRoundTripTests._response(input_doc)
        first = facade.import_writer_response(response)
        service = facade._writer_round_trip_service()
        revision = service._revision_path(composition['composition_id'], first['revision_id'])
        original = revision.read_bytes()
        before = facade.status()['snapshot']
        revision.unlink()
        service._head_path(composition['composition_id']).unlink()
        response_file = self.root / 'response.json'
        response_file.write_text(json.dumps(response), encoding='utf-8')
        facade.close()

        with patch('plugins.local_application.writer_round_trip_service._now', return_value='2099-01-01T00:00:00Z'):
            recovered = self._cli('writer-round-trip', 'import-response', '--json', str(response_file))
        self.assertEqual(recovered['status'], 'RESTORED')
        self.assertEqual(recovered['revision_id'], first['revision_id'])
        self.assertEqual(recovered['recovered_at'], '2099-01-01T00:00:00Z')
        self.assertEqual(revision.read_bytes(), original)
        shown = self._cli('writer-round-trip', 'inspect', '--composition-id', composition['composition_id'], '--json')
        self.assertEqual(shown['revision']['revision_digest'], first['revision_digest'])
        replay = self._cli('writer-round-trip', 'import-response', '--json', str(response_file))
        self.assertEqual(replay['status'], 'VERIFIED_REUSE')
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened.status()['snapshot'], before)

    def test_cli_composition_recovery_keeps_selection_and_exact_historical_facts(self):
        facade, case = composition_support.Issue80WriterCompositionTests._build_complete_support_package(self)
        self.addCleanup(facade.close)
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case, composition_id='COMP-CLI-RECOVERY')
        composition = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        facade.select_writer_composition(composition['composition_id'], 1, composition['composition_digest'])
        service = facade._writer_composition_service()
        selection_before = service._selected(composition['composition_id'])
        version = service._version_path(composition['composition_id'], 1)
        original = version.read_bytes()
        version.unlink()
        service._series_index_path(composition['composition_id']).unlink()
        proposal_file = self.root / 'composition.json'
        proposal_file.write_text(json.dumps(proposal), encoding='utf-8')
        facade.close()

        with patch('plugins.local_application.writer_composition_history_service._now', return_value='2099-01-01T00:00:00Z'):
            result = self._cli('writer-composition', 'capture', '--package-id', case['package_id'], '--json', str(proposal_file))
        self.assertEqual(result['status'], 'RESTORED')
        self.assertEqual(result['composition'], composition)
        self.assertEqual(version.read_bytes(), original)
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            self.assertEqual(reopened._writer_composition_service()._selected(composition['composition_id']), selection_before)
