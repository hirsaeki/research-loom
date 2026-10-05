from copy import deepcopy
from plugins.local_application import LocalApplicationFacade, LocalApplicationError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue256_native_publication as native
from test_research_exhibits import exhibit_payload, state_signature


class VisualNeedTests(ResearchPackageAcceptanceSupport):
    _prepared = native.Issue256NativePublicationTests._prepared

    def test_three_origins_resume_after_reopen_preserving_history_and_authority(self):
        facade, case = self._prepared(matrix=True)
        composition = facade.show_writer_composition(case['composition_id'], 1)['composition']
        revision = facade.inspect_writer_round_trip(case['composition_id'])['revision']
        preview = facade.build_publication_preview(case['composition_id'])['build']
        original_package = facade.show_research_package(case['package_id'])['package']
        before = state_signature(facade._application)
        origins = [
            {'stage': 'narrative', 'composition_id': case['composition_id'], 'composition_version': composition['version']},
            {'stage': 'writer', 'composition_id': case['composition_id'], 'revision_id': revision['revision_id']},
            {'stage': 'publication', 'build_id': preview['build_id']},
        ]
        needs = [facade.capture_visual_need({'origin': o, 'purpose': 'Clarify the existing comparison', 'semantic_changes': [], 'affected_section_ids': ['SEC-FRAME']})['exhibit']['exhibit_id'] for o in origins]
        added = facade.capture_exhibit(exhibit_payload(rq_id=case['rq_id'], title='Existing comparison', kind='matrix', representation='json', value={'columns': ['Item', 'Value'], 'rows': [['Alpha', '001.20']]}, source_object_ids=[]))['exhibit']['exhibit_id']
        facade.close()
        facade = LocalApplicationFacade.open_workspace(self.workspace); self.addCleanup(facade.close)
        for need in needs:
            resumed = facade.resume_visual_need({'need_id': need, 'exhibit_ids': [case['exhibit_id'], added], 'section_exhibit_refs': {'SEC-FRAME': [case['exhibit_id'], added]}})
            self.assertEqual(resumed['status'], 'RESUMABLE')
            self.assertNotEqual(resumed['package']['package_id'], case['package_id'])
            self.assertNotEqual(resumed['composition']['composition_id'], case['composition_id'])
            new = facade.show_writer_composition(resumed['composition']['composition_id'], 1)['composition']
            self.assertEqual(new['sections'][1], composition['sections'][1])
            self.assertFalse(resumed['release_approval_performed'])
        self.assertEqual(state_signature(facade._application), before)
        self.assertEqual(facade.show_research_package(case['package_id'])['package'], original_package)
        self.assertEqual(facade.show_writer_composition(case['composition_id'], 1)['composition'], composition)
        self.assertEqual(facade.inspect_writer_round_trip(case['composition_id'])['revision'], revision)
        self.assertEqual(facade.show_publication_preview(preview['build_id'])['build'], preview)

    def test_new_semantics_and_undeclared_section_changes_do_not_rebuild(self):
        facade, case = self._prepared(matrix=True)
        origin = {'stage': 'narrative', 'composition_id': case['composition_id'], 'composition_version': 1}
        before = state_signature(facade._application)
        need = facade.capture_visual_need({'origin': origin, 'purpose': 'Infer a new cause', 'semantic_changes': ['causality'], 'affected_section_ids': ['SEC-FRAME']})
        self.assertEqual(need['return_depth'], 'research')
        with self.assertRaises(LocalApplicationError) as raised:
            facade.resume_visual_need({'need_id': need['exhibit']['exhibit_id'], 'exhibit_ids': [case['exhibit_id']], 'section_exhibit_refs': {}})
        self.assertEqual(raised.exception.code, 'APPLICATION-VISUAL-RESEARCH-REQUIRED')
        plain = facade.capture_visual_need({'origin': origin, 'purpose': 'Clarify existing meaning', 'semantic_changes': [], 'affected_section_ids': ['SEC-FRAME']})
        with self.assertRaises(LocalApplicationError):
            facade.resume_visual_need({'need_id': plain['exhibit']['exhibit_id'], 'exhibit_ids': [case['exhibit_id']], 'section_exhibit_refs': {'SEC-VALIDATE': []}})
        # Omitting rebuild cannot insert an Exhibit absent from the old Package.
        proposal = deepcopy(facade.show_writer_composition(case['composition_id'], 1)['composition'])
        proposal['sections'][0]['exhibit_refs'].append(plain['exhibit']['exhibit_id'])
        proposal = {k: proposal[k] for k in ('purpose', 'audience', 'sections')}
        proposal['created_by'] = {'type': 'unit'}; proposal['change_reason'] = 'Attempt stale binding'
        with self.assertRaises(LocalApplicationError): facade.capture_writer_composition(case['package_id'], proposal)
        self.assertEqual(state_signature(facade._application), before)

    def test_remove_visual_creates_new_identity_and_keeps_old_revision(self):
        facade, case = self._prepared(matrix=True)
        composition = facade.show_writer_composition(case['composition_id'], 1)['composition']
        need = facade.capture_visual_need({'origin': {'stage': 'narrative', 'composition_id': case['composition_id'], 'composition_version': 1}, 'purpose': 'Use prose instead', 'semantic_changes': [], 'affected_section_ids': ['SEC-FRAME']})
        resumed = facade.resume_visual_need({'need_id': need['exhibit']['exhibit_id'], 'exhibit_ids': [], 'section_exhibit_refs': {'SEC-FRAME': []}})
        current = facade.show_writer_composition(resumed['composition']['composition_id'], 1)['composition']
        self.assertEqual(current['sections'][0]['exhibit_refs'], [])
        self.assertEqual(facade.show_writer_composition(case['composition_id'], 1)['composition'], composition)

    def test_pending_explanation_cannot_resume_until_exact_review_is_selected(self):
        import base64
        from unittest.mock import patch
        from test_issue256_native_publication import fixture_png
        facade, case = self._prepared(matrix=True)
        need = facade.capture_visual_need({'origin': {'stage': 'narrative', 'composition_id': case['composition_id'], 'composition_version': 1}, 'purpose': 'Explain existing meaning', 'semantic_changes': [], 'affected_section_ids': ['SEC-FRAME']})
        candidate = facade.capture_explanation_exhibit({'package_id': case['package_id'], 'object_ids': [case['rq_id']], 'exhibit_ids': [], 'request': {'purpose': 'Existing question', 'allowed_labels': ['existing question'], 'allowed_relations': [], 'must_not_add': ['new research meaning']}, 'generator': {'identity': 'unit generator', 'version': '1', 'instruction': 'Use existing meaning only.'}, 'output_base64': base64.b64encode(fixture_png(2,2)).decode(), 'semantic_changes': []})['exhibit']['exhibit_id']
        request = {'need_id': need['exhibit']['exhibit_id'], 'exhibit_ids': [case['exhibit_id'], candidate], 'section_exhibit_refs': {'SEC-FRAME': [candidate]}}
        with patch.object(facade, 'build_research_package') as rebuild:
            with self.assertRaises(LocalApplicationError) as raised: facade.resume_visual_need(request)
            self.assertEqual(raised.exception.code, 'APPLICATION-VISUAL-REVIEW-REQUIRED')
            rebuild.assert_not_called()
        review = facade.capture_visual_review({'candidate_id': candidate, 'disposition': 'existing_meaning_only', 'semantic_changes': [], 'reviewer': {'actor_type': 'host', 'actor_id': 'UNIT-HOST'}, 'rationale': 'Synthetic backend review fixture, not live UAT.'})['exhibit']['exhibit_id']
        request['exhibit_ids'].append(review)
        resumed = facade.resume_visual_need(request)
        self.assertEqual(resumed['status'], 'RESUMABLE')
