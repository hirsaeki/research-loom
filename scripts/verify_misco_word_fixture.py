"""Generate isolated synthetic G/M DOCX fixtures or inspect their Word PDFs.

Run with uv from the repository. This does not initialize or approve a project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from test_issue456_formal_rendering import representative_inspection
from plugins.local_application.publication_release_service import PublicationReleaseService
from plugins.local_application.publication_pdf import inspect_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_directory', type=Path)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--grid-probe', action='store_true', help='Add 4000 fixed full-width Japanese glyphs to an isolated body section')
    parser.add_argument('--boundary-case', choices=['limits', 'over-limit'], help='Generate actual-pagination abstract/appendix boundary probes')
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for group in ['G', 'M']:
        if not args.inspect:
            service = PublicationReleaseService.__new__(PublicationReleaseService)
            fixture = representative_inspection(group)
            if args.grid_probe:
                fixture['revision']['sections'][7]['content'] += '\n\n' + 'あ' * 4000
            if args.boundary_case:
                report = fixture['publication_policy']['formal_report']
                report['abstract'] = '\n'.join(['経営への提言。境界検証用の合成要旨。'] * (60 if args.boundary_case == 'limits' else 100))
                report['appendices'][0]['content'] = '\n'.join(['境界検証用の合成付録。数値は変更しない。'] * (1960 if args.boundary_case == 'limits' else 2000))
            markdown, document, issues, _ = service._render(fixture)
            if issues:
                raise RuntimeError(issues)
            for extension, data in [('docx', document), ('md', markdown)]:
                path = args.output_directory / (group + '.' + extension)
                with path.open('xb') as stream:
                    stream.write(data)
        else:
            pdf = (args.output_directory / (group + '.pdf')).read_bytes()
            host = json.loads((args.output_directory / (group + '-host.json')).read_text(encoding='utf-8-sig'))
            source = (args.output_directory / (group + '.docx')).read_bytes()
            assert host['source_docx_digest'] == 'sha256:' + hashlib.sha256(source).hexdigest()
            assert host['pdf_digest'] == 'sha256:' + hashlib.sha256(pdf).hexdigest()
            parts = ['cover', 'cover_reverse', 'abstract', 'front_divider', 'front_divider_reverse', 'contents'] + (['introduction'] if group == 'G' else []) + ['body', 'back_divider', 'back_divider_reverse', 'appendix', 'back_cover', 'back_cover_reverse']
            inspection = inspect_pdf(pdf, page_ranges=host['page_ranges'], expected_parts=parts)
            print(json.dumps({'group': group, 'digest': host['pdf_digest'], 'host_receipt': host, 'inspection': {k: v for k, v in inspection.items() if k != 'page_text'}}, ensure_ascii=False))
            if inspection['problems']:
                raise RuntimeError(inspection['problems'])


if __name__ == '__main__':
    main()
