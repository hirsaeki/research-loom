from copy import deepcopy
import unittest
from plugins.local_application import LocalApplicationError
from plugins.local_application.publication_release_service import PublicationReleaseService
from plugins.local_application.research_package_builder import _bibliography_readiness
import test_issue426_source_bibliography as bibliography_tests


class BibliographyTests(unittest.TestCase):
    setUp = bibliography_tests.SourceBibliographyIngressTests.setUp
    current = bibliography_tests.SourceBibliographyIngressTests.current
    propose = bibliography_tests.SourceBibliographyIngressTests.propose
    apply_through_confirmation = bibliography_tests.SourceBibliographyIngressTests.apply_through_confirmation

    def test_public_candidate_preserves_separate_fields_and_source_binding(self):
        before = deepcopy(self.current())
        result = self.propose(title='原資料の題名', author='著者太郎', publisher='発行機関', publication_or_update_date='2026', bibliography_exceptions={'author': 'Recorded reviewer reason; explicit author is also retained.'})
        self.assertEqual(self.current(), before)
        self.apply_through_confirmation(result['data']['state_delta_proposal_id'])
        source = self.current()
        self.assertEqual(source['author'], '著者太郎')
        self.assertEqual(source['publisher'], '発行機関')
        for key in ['id', 'canonical_locator', 'content_digest', 'media_type']:
            self.assertEqual(source[key], before[key])
        self.assertTrue(_bibliography_readiness(source)[0])
        text = PublicationReleaseService._citation_label({**source, 'canonical_locator': 'https://example.test/full-long-url'}, '52頁', {'document_mode': 'formal_report'})
        self.assertEqual(text, '著者太郎、原資料の題名、発行機関、2026、52頁、https://example.test/full-long-url')
        incomplete = deepcopy(source)
        incomplete.pop('publisher')
        with self.assertRaises(LocalApplicationError):
            PublicationReleaseService._citation_label(incomplete, None, {'document_mode': 'formal_report'})
        incomplete['bibliography_exceptions']['publisher'] = 'This retained source has no separate publisher; verified by reviewer.'
        self.assertTrue(PublicationReleaseService._citation_label(incomplete, None, {'document_mode': 'formal_report'}))

    def test_exception_reason_is_required_and_cannot_change_source_identity(self):
        for exceptions in [{}, {'title': 'unknown'}, {'author': ''}, {'author': None}]:
            with self.assertRaises(Exception):
                self.propose(bibliography_exceptions=exceptions)
