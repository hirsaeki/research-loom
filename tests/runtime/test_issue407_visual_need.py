from copy import deepcopy
from plugins.local_application import LocalApplicationFacade, LocalApplicationError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_issue256_native_publication import Issue256NativePublicationTests
from test_research_exhibits import exhibit_payload, state_signature


class VisualNeedTests(ResearchPackageAcceptanceSupport):
    _prepared = Issue256NativePublicationTests._prepared

    def test_three_origins_resume_after_reopen_preserving_history_and_authority(self):
        facade, case = self._prepared(matrix=True)
        composition = facade.show_writer_composition(case['composition_id'])['composition']
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
            new = facade.show_writer_composition(resumed['composition']['composition_id'])['composition']
            for field in ('title', 'purpose', 'exhibit_refs', 'research_object_refs'):
                self.assertEqual(new['sections'][1].get(field), composition['sections'][1].get(field))
            self.assertFalse(resumed['release_approval_performed'])
        self.assertEqual(state_signature(facade._application), before)
        self.assertEqual(facade.show_research_package(case['package_id'])['package'], original_package)
        self.assertEqual(facade.show_writer_composition(case['composition_id'])['composition'], composition)
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
        proposal = deepcopy(facade.show_writer_composition(case['composition_id'])['composition'])
        proposal['sections'][0]['exhibit_refs'].append(plain['exhibit']['exhibit_id'])
        proposal = {k: proposal[k] for k in ('purpose', 'audience', 'sections')}
        proposal['created_by'] = {'type': 'unit'}; proposal['change_reason'] = 'Attempt stale binding'
        with self.assertRaises(LocalApplicationError): facade.capture_writer_composition(case['package_id'], proposal)
        self.assertEqual(state_signature(facade._application), before)

    def test_remove_visual_creates_new_identity_and_keeps_old_revision(self):
        facade, case = self._prepared(matrix=True)
        composition = facade.show_writer_composition(case['composition_id'])['composition']
        need = facade.capture_visual_need({'origin': {'stage': 'narrative', 'composition_id': case['composition_id'], 'composition_version': 1}, 'purpose': 'Use prose instead', 'semantic_changes': [], 'affected_section_ids': ['SEC-FRAME']})
        resumed = facade.resume_visual_need({'need_id': need['exhibit']['exhibit_id'], 'exhibit_ids': [], 'section_exhibit_refs': {'SEC-FRAME': []}})
        current = facade.show_writer_composition(resumed['composition']['composition_id'])['composition']
        self.assertEqual(current['sections'][0]['exhibit_refs'], [])
        self.assertEqual(facade.show_writer_composition(case['composition_id'])['composition'], composition)
