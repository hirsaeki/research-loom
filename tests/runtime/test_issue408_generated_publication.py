from copy import deepcopy
import base64
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile
import unittest

from plugins.local_application import LocalApplicationError
from plugins.local_application.publication_exhibits import prepare_exhibits
from plugins.local_application.publication_docx import W, A, docx_bytes, verify_native_docx
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_issue256_native_publication import Issue256NativePublicationTests, fixture_png
from test_issue405_research_charts import ChartExhibitTests
import test_issue219_writer_round_trip as writer
import issue80_writer_composition_suite as compositions
from test_research_exhibits import state_signature


class GeneratedPublicationTests(ResearchPackageAcceptanceSupport):
    _prepared = Issue256NativePublicationTests._prepared

    def capture(self, facade, case, png):
        return facade.capture_explanation_exhibit({'package_id': case['package_id'], 'object_ids': [case['rq_id']], 'exhibit_ids': [], 'request': {'purpose': 'Existing question overview', 'allowed_labels': ['existing question'], 'allowed_relations': [], 'must_not_add': ['new research claims']}, 'generator': {'identity': 'synthetic test generator', 'version': '1', 'instruction': 'Use existing meaning only.'}, 'output_base64': base64.b64encode(png).decode(), 'semantic_changes': []})['exhibit']['exhibit_id']

    def review(self, facade, eid):
        return facade.capture_visual_review({'candidate_id': eid, 'disposition': 'existing_meaning_only', 'semantic_changes': [], 'reviewer': {'actor_type': 'host', 'actor_id': 'UNIT-REVIEW'}, 'rationale': 'Synthetic backend attestation, not live image QA.'})['exhibit']['exhibit_id']

    def preview(self, facade, case, selected, rendered):
        case['build_input']['exhibit_ids'] = selected
        package = facade.build_research_package(case['build_input'])['package']
        proposal = compositions.Issue80WriterCompositionTests._proposal(self, case)
        proposal['sections'][0]['exhibit_refs'] = rendered
        proposal['sections'][1]['narrative_stage_refs'] = ['framing']
        proposal['sections'][1]['semantic_purpose_refs'] = ['frame_problem']
        composition = facade.capture_writer_composition(package['package_id'], proposal)['composition']
        facade.select_writer_composition(composition['composition_id'], 1, composition['composition_digest'])
        out = self.root / composition['composition_id']
        facade.export_writer_round_trip_input(composition['composition_id'], ['SEC-FRAME','SEC-VALIDATE'], out)
        inputs = json.loads((out / 'writer-input.json').read_text())
        response = writer.Issue219WriterRoundTripTests._response(inputs)
        response['sections'][0]['content'] = 'See ' + ' and '.join('[[exhibit:'+ref+']]' for ref in rendered) + '.'
        facade.import_writer_response(response)
        built = facade.build_publication_preview(composition['composition_id'])
        shown = facade.show_publication_preview(built['build']['build_id'])
        return built, shown, (Path(shown['output_root']) / 'formal.docx').read_bytes(), package

    def test_pending_review_missing_asset_and_repaired_output_fail_closed(self):
        facade, case = self._prepared(matrix=True)
        before = state_signature(facade._application)
        eid = self.capture(facade, case, fixture_png(2,2))
        pending, shown, _, _ = self.preview(facade, case, [case['exhibit_id'], eid], [eid])
        self.assertIn('VISUAL_REVIEW_REQUIRED', shown['preview_markdown'])
        self.assertEqual(pending['build']['verification']['render_verification'], 'failed')
        with self.assertRaises(LocalApplicationError): facade.request_publication_release(pending['build']['build_id'], 'human')
        review = self.review(facade, eid)
        built, shown, payload, package = self.preview(facade, case, [case['exhibit_id'], eid, review], [case['exhibit_id'], eid])
        self.assertEqual(built['build']['verification']['render_verification'], 'passed')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            doc = ET.fromstring(archive.read('word/document.xml'))
            self.assertEqual(len(doc.findall('.//{'+A+'}blip')), 1)
            images = [name for name in archive.namelist() if name.startswith('word/media/')]
            self.assertEqual(archive.read(images[0]), fixture_png(2,2))
            text = '\n'.join(node.text or '' for node in doc.findall('.//{'+W+'}t'))
            self.assertIn('Table 1.', text); self.assertIn('Figure 1.', text)
            self.assertIn('See Table 1 and Figure 1.', text)
            trace = json.loads(ET.fromstring(archive.read('customXml/item1.xml')).text)
            self.assertEqual(trace[1]['provenance']['visual_semantics']['visual_class'], 'explanatory_visual')
            self.assertEqual(trace[1]['provenance']['visual_reviews'][0]['exhibit_id'], review)
        retained = facade.show_research_package(package['package_id'])['package']
        ex = next(e for e in retained['resolved_content']['working_material']['research_exhibits'] if e['exhibit_id'] == eid)
        root = facade._research_package_service().root / package['package_id']
        asset = root / ex['generated_visual']['attachment_path']; exact = asset.read_bytes(); asset.unlink()
        with self.assertRaises(LocalApplicationError): facade.show_research_package(package['package_id'])
        broken = facade.build_publication_preview(built['build']['source_manuscript']['composition_id'])
        self.assertEqual(broken['build']['verification']['render_verification'], 'failed')
        self.assertNotEqual(broken['build']['build_id'], built['build']['build_id'])
        self.assertIn('VISUAL_ASSET_UNAVAILABLE', facade.show_publication_preview(broken['build']['build_id'])['preview_markdown'])
        with self.assertRaises(LocalApplicationError): facade.request_publication_release(broken['build']['build_id'], 'human')
        asset.write_bytes(exact)
        repaired = facade.build_publication_preview(built['build']['source_manuscript']['composition_id'])
        self.assertEqual(repaired['build']['build_id'], built['build']['build_id'])
        replacement = self.capture(facade, case, fixture_png(3,2)); replacement_review = self.review(facade, replacement)
        changed, _, changed_payload, _ = self.preview(facade, case, [case['exhibit_id'], replacement, replacement_review], [case['exhibit_id'], replacement])
        self.assertNotEqual(changed['build']['build_id'], built['build']['build_id'])
        self.assertNotEqual(hashlib.sha256(changed_payload).hexdigest(), hashlib.sha256(payload).hexdigest())
        self.assertEqual(facade.show_publication_preview(built['build']['build_id'])['build'], built['build'])
        self.assertEqual(state_signature(facade._application), before)

    def test_consumer_removal_and_caption_missing_are_explicit_diagnostics(self):
        facade, case = self._prepared(matrix=True)
        eid = self.capture(facade, case, fixture_png(2,2)); review = self.review(facade, eid)
        built, _, _, _ = self.preview(facade, case, [case['exhibit_id'], eid, review], [eid])
        cid = built['build']['source_manuscript']['composition_id']
        inspected = facade.inspect_writer_round_trip(cid)
        original = prepare_exhibits(inspected, self.workspace)
        changed = deepcopy(inspected)
        target = next(e for e in changed['source_package_document']['resolved_content']['working_material']['research_exhibits'] if e['exhibit_id'] == eid)
        target['title'] = ''
        self.assertEqual(prepare_exhibits(changed, self.workspace)[eid]['code'], 'VISUAL_CAPTION_REQUIRED')
        target['title'] = 'Existing question overview'
        target['generated_visual']['generation_context']['content_digest'] = 'sha256:'+'0'*64
        self.assertEqual(prepare_exhibits(changed, self.workspace)[eid]['kind'], 'unavailable')
        removed = {eid: {'kind': 'unavailable', 'code': 'VISUAL_ASSET_UNAVAILABLE', 'provenance': original[eid]['provenance']}}
        with patch('plugins.local_application.publication_release_service.prepare_exhibits', return_value=removed):
            absent = facade.build_publication_preview(cid)
        self.assertEqual(absent['build']['verification']['render_verification'], 'failed')
        docx = (Path(facade.show_publication_preview(absent['build']['build_id'])['output_root']) / 'formal.docx').read_bytes()
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            self.assertFalse(any(n.startswith('word/media/') for n in archive.namelist()))
        self.assertNotEqual(absent['build']['build_id'], built['build']['build_id'])


class ChartNativeLegendTests(unittest.TestCase):
    setUp = ChartExhibitTests.setUp
    capture = ChartExhibitTests.capture
    # Consumer-level fixture uses the chart unit Package, not live Research/Host UAT.
    def test_chart_consumer_keeps_unicode_native_legend_and_detects_cell_tamper(self):
        chart = self.capture()
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp); package_root = workspace / '.research-loom/research-packages/RP-CONSUMER'
            package_root.mkdir(parents=True)
            png = base64.b64decode(chart['content']['value']['output']['bytes_base64'])
            import rfc8785
            origin = rfc8785.dumps(self.package)
            def pin(path, data, media):
                (package_root / path).write_bytes(data)
                return {'path': path, 'media_type': media, 'byte_length': len(data), 'content_digest': 'sha256:'+hashlib.sha256(data).hexdigest()}
            image_pin = pin('chart.png', png, 'image/png'); origin_pin = pin('origin.json', origin, 'application/json')
            chart['generated_visual'] = {'visual_class': 'data_visualization', 'attachment_path': 'chart.png', 'media_type': 'image/png', 'byte_length': len(png), 'digest': image_pin['content_digest'], 'generation_context': {'attachment_path': 'origin.json', 'byte_length': len(origin), 'content_digest': origin_pin['content_digest']}}
            package = {'package_id': 'RP-CONSUMER', 'attachments': [image_pin, origin_pin], 'resolved_content': {'research_objects': self.package['resolved_content']['research_objects'], 'working_material': {'research_exhibits': [chart]}}}
            inspection = {'source_package_document': package, 'revision': {'sections': [{'exhibit_refs': [chart['exhibit_id']]}]}}
            block = prepare_exhibits(inspection, workspace)[chart['exhibit_id']]
            self.assertEqual(block['kind'], 'image')
            self.assertEqual(block['legend_rows'][1], ['1','東京','30'])
            strict = deepcopy(inspection); strict['publication_profile'] = {'profile_id': 'misco.publication'}
            self.assertEqual(prepare_exhibits(strict, workspace)[chart['exhibit_id']]['code'], 'VISUAL_SOURCE_METADATA_REQUIRED')
            block.update(ref=chart['exhibit_id'], caption='Figure 1. 比較', note='Units: 件; period: 2026')
            lines = [('exhibit', block)]
            output = docx_bytes(lines); self.assertTrue(verify_native_docx(output, lines))
            with zipfile.ZipFile(io.BytesIO(output)) as archive:
                entries = {n: archive.read(n) for n in archive.namelist()}
            entries['word/document.xml'] = entries['word/document.xml'].replace('東京'.encode(), '京都'.encode())
            altered = io.BytesIO()
            with zipfile.ZipFile(altered, 'w') as archive:
                for name, data in entries.items(): archive.writestr(name, data)
            self.assertFalse(verify_native_docx(altered.getvalue(), lines))


class VisualPermissionTests(unittest.TestCase):
    def test_misco_interview_permission_requires_disclosure_and_original_review(self):
        from plugins.local_application.publication_release_service import _publication_policy
        package = {"resolved_content": {"research_objects": [{"id": "SRC-INTERNAL", "kind": "source", "source_type": "interview", "canonical_locator": "internal://interview"}]}}
        profile = {"profile_id": "misco.publication", "profile_version": "1.3.0"}
        inputs = {"formal_spec_profile": {"research_group_type_required": False}, "permissions": [{"source_ref": "SRC-INTERNAL", "publication_allowed": True, "company_disclosure": "allowed", "original_reviewed": True, "approval_ref": "Synthetic fixture"}]}
        self.assertNotIn('INPUT-PERMISSION', _publication_policy(package, profile, inputs)['missing_inputs'])
        for field, value in [('publication_allowed', False), ('original_reviewed', False), ('company_disclosure', 'prohibited')]:
            changed = deepcopy(inputs); changed['permissions'][0][field] = value
            self.assertIn('INPUT-PERMISSION', _publication_policy(package, profile, changed)['missing_inputs'])
        self.assertFalse(_publication_policy(package, {"profile_id": "generic", "profile_version": "1"}, {})['release_blocked'])
