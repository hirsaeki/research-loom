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
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for group in ['G', 'M']:
        if not args.inspect:
            service = PublicationReleaseService.__new__(PublicationReleaseService)
            markdown, document, issues, _ = service._render(representative_inspection(group))
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
