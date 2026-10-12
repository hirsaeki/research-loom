from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import unittest
import zipfile
from xml.etree import ElementTree as ET

from plugins.local_application.publication_docx import W
from plugins.local_application.publication_release_service import PublicationReleaseService
from plugins.local_application.research_chart import validate_chart_spec
from plugins.local_application.research_chart_png import render_chart
from test_issue456_formal_document import representative_report
import test_issue405_research_charts as chart_tests

ROOT = Path(__file__).resolve().parents[2]


def representative_inspection(group='G'):
    report = representative_report()
    report['footnotes'].append({'section_id': 's10', 'marker': '{{note-2}}', 'text': '別章の脚注番号を再開する。'})
    if group == 'M':
        report.pop('introduction')
    profile_root = ROOT / 'profiles/publication/misco-v1.4/resources'
    formal = json.loads((profile_root / 'publication-formal-spec.json').read_text(encoding='utf-8'))['formal_spec_profile']
    source = {'id': 'SRC-SYNTHETIC', 'kind': 'source', 'author': '検証太郎', 'title': '合成検証資料', 'publisher': '検証用発行元', 'publication_or_update_date': '2026', 'canonical_locator': 'https://example.test/full-long-source-url'}
    evidence = chart_tests.chart_evidence()
    png = render_chart(validate_chart_spec(chart_tests.chart_spec(evidence), evidence))
    exhibits = []
    blocks = {}
    for number in [1, 2]:
        table = {'exhibit_id': f'TABLE-{number}', 'kind': 'table', 'title': '検証値の対応'}
        image = {'exhibit_id': f'IMAGE-{number}', 'kind': 'figure', 'title': '値の比較', 'visual_target': {'capture_id': 'CAP-SYNTHETIC', 'locator': {'kind': 'page', 'page': 52, 'label': '52頁'}}, 'content': {'representation': 'text', 'value': '番号1は東京、2は大阪、3は名古屋を示す。'}}
        exhibits.extend([table, image])
        provenance = {'citation_sources': [source], 'source_capture': {'source_locators': [source['canonical_locator']]}}
        blocks[table['exhibit_id']] = {'kind': 'table', 'rows': [['地域', '件数'], ['東京', '30'], ['大阪', '20'], ['名古屋', '50']], 'provenance': deepcopy(provenance)}
        blocks[image['exhibit_id']] = {'kind': 'image', 'data': png, 'width': 800, 'height': 480, 'asset_digest': 'sha256:' + hashlib.sha256(png).hexdigest(), 'provenance': deepcopy(provenance)}
    sections = []
    for row in report['structure']:
        sid = row['section_id']
        marker = '{{note-1}}' if sid == 's2' else '{{note-2}}' if sid == 's10' else ''
        sections.append({'section_id': sid, 'content': '固定本文' + marker + '。数値123を保持する。', 'citations': [], 'exhibit_refs': []})
    for sid, page in [('s2', '51頁'), ('s3', '52頁'), ('s10', '61頁')]:
        section = next(s for s in sections if s['section_id'] == sid)
        section['citations'] = [{'source_ref': source['id'], 'locator_ref': page}]
        section['content'] += ' [[citation:SRC-SYNTHETIC]]'
    sections[1]['exhibit_refs'] = ['TABLE-1', 'IMAGE-1']
    sections[-1]['exhibit_refs'] = ['TABLE-2', 'IMAGE-2']
    return {'source_package_document': {'project': {'title': report['title']}, 'resolved_content': {'research_objects': [source], 'working_material': {'research_exhibits': exhibits}}}, 'revision': {'sections': sections}, 'composition': {'sections': [{'section_id': row['section_id'], 'heading': '検証事項'} for row in sections]}, 'publication_profile': {'profile_id': 'misco.publication'}, 'publication_policy': {'document_mode': 'formal_report', 'formal_report': report, 'formal_spec_profile': formal, 'research_group_type': group, 'missing_inputs': [], 'coverage': json.loads((profile_root / 'publication-coverage.json').read_text(encoding='utf-8'))}, 'exhibit_blocks': blocks}


class FormalRenderingTests(unittest.TestCase):
    def test_numbering_source_order_and_references_use_formal_section_scope(self):
        service = PublicationReleaseService.__new__(PublicationReleaseService)
        for group in ['G', 'M']:
            inspection = representative_inspection(group)
            markdown, docx, issues, checks = service._render(inspection)
            self.assertEqual(issues, [])
            self.assertEqual(checks['formal_specification'], 'warning')
            text = markdown.decode('utf-8')
            for caption in ['表1-1-1', '図1-1-1', '表2-1-1', '図2-1-1']:
                self.assertIn(caption, text)
            self.assertEqual(text.count('### ＜参考文献＞'), 2)
            self.assertIn('51頁；52頁', text)
            self.assertLess(text.index('１－１'), text.index('＜参考文献＞'))
            self.assertLess(text.index('＜参考文献＞'), text.index('１－２'))
            with zipfile.ZipFile(io.BytesIO(docx)) as archive:
                document = ET.fromstring(archive.read('word/document.xml'))
                paragraphs = [''.join(t.text or '' for t in p.iter(f'{{{W}}}t')) for p in document.findall('.//{%s}p' % W)]
                self.assertIn('（出典）検証太郎、合成検証資料、検証用発行元、2026、52頁、https://example.test/full-long-source-url', paragraphs)
                self.assertEqual(len([name for name in archive.namelist() if name.startswith('word/media/')]), 2)
