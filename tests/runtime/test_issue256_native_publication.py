from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile
import zlib

from plugins.local_application import LocalApplicationError
from plugins.local_application import publication_release_service as publication
from plugins.local_application import publication_exhibits
from plugins.local_application.publication_docx import W, A, R, docx_bytes, verify_native_docx
from plugins.local_application.publication_exhibits import _asset, png_size, prepare_exhibits, table_rows
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue219_writer_round_trip as writer
import issue80_writer_composition_suite as composition_support
import test_research_exhibits as exhibits


def fixture_png(width=320, height=120, *, source_width=None):
    """Small synthetic grayscale bars, generated with stdlib only."""
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    rows = []
    for y in range(height):
        row = bytearray(b'\0')
        for x in range(width):
            level = 70 if 10 < y % 40 < 30 and 10 < x < (y // 40 + 1) * (source_width or width) // 4 else 245
            row.extend([level] * 3)
        rows.append(bytes(row))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')


class Issue256NativePublicationTests(ResearchPackageAcceptanceSupport):
    def _prepared(self, *, visual=False, derived=False, unsupported=False, region=False, original=None, matrix=False):
        image = original if original is not None else fixture_png()
        facade, case = self._prepare_case(**({'original_media_type': 'image/png', 'original_bytes': image} if visual else {}))
        self.addCleanup(facade.close)
        value = '| Item | Exact value | Unit |\n|---|---|---|\n| Alpha | 001.20 | percent |\n| Beta | -2.00 | points |'
        representation, kind = 'markdown', 'table'
        if matrix:
            representation, kind = 'json', 'matrix'
            value = {'columns': ['Item', 'Exact value', 'Unit'], 'rows': [['Alpha', '001.20', 'percent'], ['Beta', '-2.00', 'points']]}
        if unsupported:
            representation, kind, value = 'text', 'graph', 'A -> B (no retained image)'
        table = facade.capture_exhibit(exhibits.exhibit_payload(
            rq_id=case['rq_id'], title='Literal results', kind=kind, representation=representation, value=value,
            source_run_ids=[case['run_id']], source_artifact_refs=[f"{case['run_id']}.CAP-1.text"], source_object_ids=[]))['exhibit']
        selected = [table['exhibit_id']]
        case['table'] = table
        if visual:
            source_ref = f"{case['run_id']}.CAP-1.original"
            payload = exhibits.exhibit_payload(
                rq_id=case['rq_id'], title='Retained bars', kind='graph', representation='text', value='Synthetic fixture: not research evidence.',
                source_run_ids=[case['run_id']], source_artifact_refs=[source_ref], source_object_ids=[])
            target = {'source_run_id': case['run_id'], 'capture_id': 'CAP-1', 'source_artifact_ref': source_ref,
                      'locator': {'kind': 'figure', 'page': 1, 'label': 'Source Figure A'}}
            if region or derived:
                target['locator']['region'] = {'x': 0, 'y': 0, 'width': 0.5, 'height': 0.5, 'unit': 'normalized'}
            if derived:
                # Retained crop bytes are supplied by the operator, not fabricated by Publication.
                crop = fixture_png(160, 60, source_width=320)
                artifact = facade._application.execution_store.put_bytes(
                    facade._application.execution_store.load_run(case['run_id']), role='research_visual.crop', media_type='image/png',
                    content=crop, artifact_id='ART-CROP-256', provenance={'derivation_type': 'crop'}, parent_artifact_refs=(source_ref,))
                target.update({'derived_artifact_ref': artifact.artifact_id, 'derivation_type': 'crop'})
                payload['source_artifact_refs'].append(artifact.artifact_id)
                case['image'] = crop
            else:
                case['image'] = image
            payload['visual_target'] = target
            capture = facade.capture_exhibit(payload)['exhibit']
            selected.append(capture['exhibit_id'])
        case['build_input']['exhibit_ids'] = selected
        package = facade.build_research_package(case['build_input'])['package']
        case['package_id'] = package['package_id']
        case['package'] = facade.show_research_package(case['package_id'])['package']
        case['package_root'] = facade._research_package_service().root / case['package_id']
        case['exhibit_id'] = selected[0]
        proposal = composition_support.Issue80WriterCompositionTests._proposal(self, case)
        proposal['sections'][0]['exhibit_refs'] = selected
        proposal['sections'][1]['narrative_stage_refs'] = ['framing']
        proposal['sections'][1]['semantic_purpose_refs'] = ['frame_problem']
        composition = facade.capture_writer_composition(case['package_id'], proposal)['composition']
        facade.select_writer_composition(composition['composition_id'], 1, composition['composition_digest'])
        out = self.root / 'writer-input'
        facade.export_writer_round_trip_input(composition['composition_id'], ['SEC-FRAME', 'SEC-VALIDATE'], out)
        inputs = json.loads((out / 'writer-input.json').read_text())
        response = writer.Issue219WriterRoundTripTests._response(inputs)
        response['sections'][0]['content'] = 'Exact results: ' + ' and '.join(f'[[exhibit:{ref}]]' for ref in selected) + '. See [[section:SEC-VALIDATE]].'
        facade.import_writer_response(response)
        case['composition_id'] = composition['composition_id']
        return facade, case

    def _build(self, facade, case):
        built = facade.build_publication_preview(case['composition_id'])
        shown = facade.show_publication_preview(built['build']['build_id'])
        payload = (Path(shown['output_root']) / 'formal.docx').read_bytes()
        return built, shown, payload

    @staticmethod
    def _approval(request):
        return {'request_id': request['request_id'], 'request_digest': request['request_digest'], 'actor_id': request['human_actor_id'], 'disposition': 'approve_release'}

    def test_native_table_image_captions_crossrefs_exact_parts_and_provenance(self):
        facade, case = self._prepared(visual=True, derived=True)
        before = facade.status()['snapshot']
        built, shown, payload = self._build(facade, case)
        self.assertEqual(built['build']['verification']['render_verification'], 'passed')
        self.assertEqual(built['build']['verification']['layout_verification'], 'warning')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            document = ET.fromstring(archive.read('word/document.xml'))
            cells = [[node.text for node in row.findall(f'.//{{{W}}}t')] for row in document.findall(f'.//{{{W}}}tr')]
            self.assertEqual(cells, [['Item', 'Exact value', 'Unit'], ['Alpha', '001.20', 'percent'], ['Beta', '-2.00', 'points']])
            self.assertEqual(len(document.findall(f'.//{{{A}}}blip')), 1)
            images = [name for name in archive.namelist() if name.startswith('word/media/')]
            self.assertEqual(archive.read(images[0]), case['image'])
            provenance = json.loads(ET.fromstring(archive.read('customXml/item1.xml')).text)
            visual = case['package']['resolved_content']['working_material']['research_exhibits'][1]['visual_target']
            self.assertEqual(provenance[1]['provenance']['visual_target'], visual)
            self.assertEqual(provenance[1]['asset_digest'], 'sha256:' + hashlib.sha256(case['image']).hexdigest())
            text = '\n'.join(node.text or '' for node in document.findall(f'.//{{{W}}}t'))
            self.assertIn('Table 1. Literal results', text)
            self.assertIn('Figure 1. Retained bars', text)
            self.assertIn('Exact results: Table 1 and Figure 1.', text)
            self.assertNotIn('[[exhibit:', text)
        request = facade.request_publication_release(built['build']['build_id'], 'human-256')['decision_request']
        self.assertIn('every rendered page', request['required_human_review'])
        released = facade.release_publication(built['build']['build_id'], self._approval(request))
        self.assertEqual(released['status'], 'RELEASED')
        self.assertEqual(facade.status()['snapshot'], before)

    def test_json_matrix_preserves_literal_numeric_strings(self):
        facade, case = self._prepared(matrix=True)
        built, _, payload = self._build(facade, case)
        self.assertEqual(built['build']['verification']['render_verification'], 'passed')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            text = archive.read('word/document.xml').decode()
            self.assertIn('<w:tbl>', text)
            self.assertIn('001.20', text)
            self.assertIn('-2.00', text)

    def test_unsupported_exhibit_is_visible_but_not_eligible(self):
        facade, case = self._prepared(unsupported=True)
        built, shown, payload = self._build(facade, case)
        self.assertEqual(built['build']['verification']['render_verification'], 'failed')
        self.assertIn('UNSUPPORTED_EXHIBIT', shown['preview_markdown'])
        self.assertTrue(publication._verify_docx_bytes(payload))  # opens structurally, not a verified graph
        with self.assertRaises(LocalApplicationError):
            facade.request_publication_release(built['build']['build_id'], 'human-256')

    def test_missing_visual_preview_does_not_weaken_package_or_poison_rebuild(self):
        facade, case = self._prepared(visual=True, derived=True)
        healthy, _, _ = self._build(facade, case)
        visual = case['package']['resolved_content']['working_material']['research_exhibits'][1]['visual_target']
        path = case['package_root'] / visual['derived_artifact']['attachment_path']
        expected = path.read_bytes()
        path.unlink()
        with self.assertRaises(LocalApplicationError):
            facade.show_research_package(case['package_id'])
        broken, shown, payload = self._build(facade, case)
        self.assertNotEqual(broken['build']['build_id'], healthy['build']['build_id'])
        self.assertEqual(broken['build']['verification']['render_verification'], 'failed')
        self.assertIn('VISUAL_ASSET_UNAVAILABLE', shown['preview_markdown'])
        with self.assertRaises(LocalApplicationError):
            facade.request_publication_release(broken['build']['build_id'], 'human-256')
        path.write_bytes(expected)
        repaired, _, _ = self._build(facade, case)
        self.assertEqual(repaired['build']['build_id'], healthy['build']['build_id'])
        self.assertEqual(repaired['status'], 'VERIFIED_REUSE')
        self.assertEqual((Path(shown['output_root']) / 'formal.docx').read_bytes(), payload)

    def test_missing_original_and_source_text_have_different_preview_boundaries(self):
        facade, case = self._prepared(visual=True)
        visual = case['package']['resolved_content']['working_material']['research_exhibits'][1]['visual_target']
        path = case['package_root'] / visual['source_attachment_path']
        expected = path.read_bytes()
        path.write_bytes(b'corrupt')
        broken, _, _ = self._build(facade, case)
        self.assertEqual(broken['build']['verification']['render_verification'], 'failed')
        path.write_bytes(expected)
        material = case['package']['resolved_content']['materials'][0]['text_rendition']['attachment_path']
        (case['package_root'] / material).write_text('different source text')
        with self.assertRaises(LocalApplicationError):
            self._build(facade, case)

    def test_region_without_retained_crop_is_not_full_image_substitution(self):
        facade, case = self._prepared(visual=True, region=True)
        built, shown, payload = self._build(facade, case)
        self.assertEqual(built['build']['verification']['render_verification'], 'failed')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertFalse([name for name in archive.namelist() if name.startswith('word/media/')])
        self.assertIn('VISUAL_ASSET_UNAVAILABLE', shown['preview_markdown'])

    def test_asset_read_rejects_path_swap_between_check_and_open(self):
        root = self.root / 'asset-race'
        root.mkdir()
        expected = b'expected-image-bytes'
        decoy = b'unrelated-file-bytes'
        self.assertEqual(len(expected), len(decoy))
        (root / 'visual.png').write_bytes(expected)
        decoy_path = root / 'decoy.png'
        decoy_path.write_bytes(decoy)
        package = {'attachments': [{
            'path': 'visual.png',
            'content_digest': 'sha256:' + hashlib.sha256(expected).hexdigest(),
            'byte_length': len(expected),
            'media_type': 'image/png',
        }]}
        real_open = os.open
        with patch.object(publication_exhibits.os, 'open', side_effect=lambda _path, flags: real_open(decoy_path, flags)):
            with self.assertRaisesRegex(ValueError, 'changed during verification'):
                _asset(root, package, 'visual.png', package['attachments'][0]['content_digest'], len(expected), 'image/png')

    def test_reused_visual_attachment_is_verified_once_per_build(self):
        image = fixture_png(8, 8)
        digest = 'sha256:' + hashlib.sha256(image).hexdigest()
        visual = {
            'source_run_id': 'RUN-CACHE', 'capture_id': 'CAP-CACHE', 'source_artifact_ref': 'RUN-CACHE.CAP-CACHE.original',
            'source_attachment_path': 'attachments/shared.png', 'source_digest': digest,
            'source_byte_length': len(image), 'source_media_type': 'image/png', 'locator': {'page': 1},
        }
        def exhibit(ref):
            return {
                'exhibit_id': ref, 'content_digest': 'sha256:' + ref.lower().replace('-', '0').ljust(64, '0')[:64],
                'source_run_ids': ['RUN-CACHE'], 'source_artifact_refs': ['RUN-CACHE.CAP-CACHE.original'],
                'source_object_ids': [], 'derived_from_exhibit_ids': [], 'captured_against': {},
                'kind': 'graph', 'content': {'representation': 'text', 'value': ref}, 'visual_target': dict(visual),
            }
        inspection = {
            'revision': {'sections': [{'exhibit_refs': ['EX-CACHE-1', 'EX-CACHE-2']}]},
            'source_package_document': {
                'package_id': 'PKG-CACHE', 'attachments': [],
                'resolved_content': {
                    'materials': [{'run_id': 'RUN-CACHE', 'capture': {'capture_id': 'CAP-CACHE'}}],
                    'working_material': {'research_exhibits': [exhibit('EX-CACHE-1'), exhibit('EX-CACHE-2')]},
                },
            },
        }
        with patch.object(publication_exhibits, '_asset', return_value=image) as verified:
            result = prepare_exhibits(inspection, self.root)
        self.assertEqual(verified.call_count, 1)
        self.assertIs(result['EX-CACHE-1']['data'], result['EX-CACHE-2']['data'])

    def test_invalid_png_and_unsupported_tables_cannot_be_claimed_supported(self):
        for data in [b'\x89PNG\r\n\x1a\nlabel-only', fixture_png()[:-8], fixture_png() + b'extra']:
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                png_size(data)
        for content in [
            {'representation': 'json', 'value': {'columns': ['x'], 'rows': [[1.2]]}},
            {'representation': 'markdown', 'value': '| a |\n|:---|\n| b |'},
            {'representation': 'markdown', 'value': '| a |\n|---|\n| ![imaginary](x) |'},
        ]:
            with self.subTest(content=content), self.assertRaises(ValueError):
                table_rows(content)
        facade, case = self._prepared(visual=True, original=b'\x89PNG\r\n\x1a\nlabel-only')
        built, _, _ = self._build(facade, case)
        self.assertEqual(built['build']['verification']['render_verification'], 'failed')

    def test_ablation_structural_xml_alone_misses_flattening_and_wrong_image_relationship(self):
        png = fixture_png()
        table = {'ref': 'EX-T', 'caption': 'Table 1. Values', 'kind': 'table', 'rows': [['x'], ['001.2']], 'provenance': {}}
        image = {'ref': 'EX-I', 'caption': 'Figure 1. Bars', 'kind': 'image', 'data': png, 'width': 320, 'height': 120,
                 'asset_digest': 'sha256:' + hashlib.sha256(png).hexdigest(), 'provenance': {}}
        lines = [('body', 'See Table 1 and Figure 1.'), ('exhibit', table), ('exhibit', image)]
        data = docx_bytes(lines)
        self.assertTrue(verify_native_docx(data, lines))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        for change in ['flatten', 'wrong-image', 'caption', 'swapped-captions', 'swapped-blocks']:
            parts = dict(original)
            if change == 'flatten':
                doc = ET.fromstring(parts['word/document.xml'])
                body = doc.find(f'{{{W}}}body')
                body.remove(body.find(f'{{{W}}}tbl'))
                parts['word/document.xml'] = ET.tostring(doc)
            elif change == 'wrong-image':
                parts['word/_rels/document.xml.rels'] = parts['word/_rels/document.xml.rels'].replace(b'media/image-2.png', b'media/missing.png')
            elif change == 'caption':
                parts['word/document.xml'] = parts['word/document.xml'].replace(b'Table 1. Values', b'Table 2. Wrong')
            else:
                doc = ET.fromstring(parts['word/document.xml'])
                body = doc.find(f'{{{W}}}body')
                if change == 'swapped-captions':
                    captions = [node for node in body.findall(f'{{{W}}}p') if node.find(f'.//{{{W}}}bookmarkStart') is not None]
                    texts = [node.find(f'.//{{{W}}}t') for node in captions]
                    texts[0].text, texts[1].text = texts[1].text, texts[0].text
                else:
                    children = list(body)
                    table_index = next(i for i, node in enumerate(children) if node.tag == f'{{{W}}}tbl')
                    image_index = next(i for i, node in enumerate(children) if node.find(f'.//{{{A}}}blip') is not None)
                    children[table_index], children[image_index] = children[image_index], children[table_index]
                    body[:] = children
                parts['word/document.xml'] = ET.tostring(doc)
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as archive:
                for name, payload in parts.items():
                    archive.writestr(name, payload)
            self.assertTrue(publication._verify_docx_bytes(output.getvalue()))
            self.assertFalse(verify_native_docx(output.getvalue(), lines), change)

    def test_renderer_generation_rebuild_preserves_immutable_release_and_requires_new_approval(self):
        facade, case = self._prepared()
        built, shown, old_bytes = self._build(facade, case)
        request = facade.request_publication_release(built['build']['build_id'], 'human-256')['decision_request']
        approved = facade.release_publication(built['build']['build_id'], self._approval(request))
        with patch.dict(publication._RENDERER, {'renderer_version': '0.2.1', 'tool_digest': 'sha256:' + 'a' * 64}):
            changed, _, _ = self._build(facade, case)
            self.assertNotEqual(changed['build']['build_id'], built['build']['build_id'])
            with self.assertRaises(LocalApplicationError) as rejected:
                facade.request_publication_release(built['build']['build_id'], 'new-human')
            self.assertEqual(rejected.exception.code, 'APPLICATION-PUBLICATION-REBUILD-REQUIRED-001')
            reused = facade.release_publication(built['build']['build_id'], self._approval(request))
            self.assertEqual(reused['release'], approved['release'])
            self.assertEqual((Path(shown['output_root']) / 'formal.docx').read_bytes(), old_bytes)
