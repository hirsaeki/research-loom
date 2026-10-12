"""MISCO-specific document assembly over the existing native Publication DOCX."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import re
import zipfile
from xml.etree import ElementTree as ET

from .facade import LocalApplicationError
from .publication_docx import W, R, PKG, _paragraph

NS = {'w': W}
V = 'urn:schemas-microsoft-com:vml'


def outline(structure, section_ids):
    if [row['section_id'] for row in structure] != list(section_ids):
        raise LocalApplicationError('PUBLICATION-FORMAL-STRUCTURE-001', 'Formal structure must map every Writer section exactly once in its pinned order')
    counters = [0] * 7
    result = {}
    for row in structure:
        level = row['level']
        if level > 1 and not counters[level - 2]:
            raise LocalApplicationError('PUBLICATION-FORMAL-STRUCTURE-001', 'Formal heading cannot skip an unset parent level')
        counters[level - 1] += 1
        counters[level:] = [0] * (7 - level)
        n = counters[level - 1]
        full = str.maketrans('0123456789', '０１２３４５６７８９')
        if level == 1:
            label = f'第{n}章'.translate(full)
        elif level == 2:
            label = f'{counters[0]}－{n}'.translate(full)
        elif level == 3:
            label = f'（{n}）'.translate(full)
        elif level == 4 and n <= 20:
            label = chr(0x2460 + n - 1)
        elif level == 5 and n <= 26:
            label = chr(0xff41 + n - 1) + '．'
        elif level == 6 and n <= 12:
            label = chr(0x2170 + n - 1) + '．'
        elif level == 7:
            label = '・'
        else:
            raise LocalApplicationError('PUBLICATION-FORMAL-STRUCTURE-001', 'Heading ordinal exceeds the original numeral repertoire')
        result[row['section_id']] = {'level': level, 'label': label, 'chapter': counters[0], 'section': counters[1]}
    return result


def _p(text, style='Normal'):
    node = ET.fromstring(f'<root xmlns:w="{W}">' + _paragraph(text, 'body') + '</root>')[0]
    node.find('w:pPr/w:pStyle', NS).set(f'{{{W}}}val', style)
    return node


def _front(text, style='FormalFrontBody'):
    return [_p(line, style) for line in text.splitlines() if line.strip()]


def _section(base, part, start='nextPage', numbered=False):
    section = deepcopy(base)
    for name in ('footerReference', 'headerReference', 'type', 'pgNumType'):
        for node in section.findall(f'w:{name}', NS):
            section.remove(node)
    ET.SubElement(section, f'{{{W}}}type', {f'{{{W}}}val': start})
    ET.SubElement(section, f'{{{W}}}footerReference', {f'{{{W}}}type': 'default', f'{{{R}}}id': 'rIdFormalFooter' if numbered else 'rIdFormalEmptyFooter'})
    if numbered:
        ET.SubElement(section, f'{{{W}}}pgNumType', {f'{{{W}}}start': '1'})
    # This marker is descriptive; pagination remains a final-output check.
    section.set('{urn:research-loom:publication}part', part)
    return section


def _end_section(nodes, section):
    p = _p('')
    p.find('w:pPr', NS).append(section)
    nodes.append(p)


def _field(instruction, style):
    p = _p('', style)
    field = ET.SubElement(p, f'{{{W}}}fldSimple', {f'{{{W}}}instr': instruction, f'{{{W}}}dirty': 'true'})
    run = ET.SubElement(field, f'{{{W}}}r')
    ET.SubElement(run, f'{{{W}}}t').text = '要更新'
    return p


def _cover_box(text, x, y, width, size, font, *, framed=False):
    p = _p('')
    run = ET.SubElement(p, f'{{{W}}}r')
    pict = ET.SubElement(run, f'{{{W}}}pict')
    shape = ET.SubElement(pict, f'{{{V}}}shape', {'type': '#_x0000_t202', 'style': f'position:absolute;margin-left:{x}mm;margin-top:{y}mm;width:{width}mm;height:40mm;z-index:1;mso-position-horizontal-relative:page;mso-position-vertical-relative:page', 'stroked': 't' if framed else 'f', 'strokeweight': '0.75pt', 'filled': 'f'})
    textbox = ET.SubElement(shape, f'{{{V}}}textbox', {'inset': '0,0,0,0', 'style': 'mso-fit-shape-to-text:t'})
    content = ET.SubElement(textbox, f'{{{W}}}txbxContent')
    for line in text.split('\n'):
        pp = ET.SubElement(content, f'{{{W}}}p')
        pr = ET.SubElement(pp, f'{{{W}}}pPr')
        ET.SubElement(pr, f'{{{W}}}jc', {f'{{{W}}}val': 'center'})
        rr = ET.SubElement(pp, f'{{{W}}}r')
        rp = ET.SubElement(rr, f'{{{W}}}rPr')
        ET.SubElement(rp, f'{{{W}}}rFonts', {f'{{{W}}}ascii': font, f'{{{W}}}hAnsi': font, f'{{{W}}}eastAsia': font})
        ET.SubElement(rp, f'{{{W}}}sz', {f'{{{W}}}val': str(size * 2)})
        ET.SubElement(rr, f'{{{W}}}t').text = line
    return p


def assemble(data: bytes, report: dict, group: str, layout: dict) -> bytes:
    """Build front/back matter and native notes; Word resolves fields/pagination."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(parts['word/document.xml'])
    body = document.find('w:body', NS)
    base = deepcopy(body.find('w:sectPr', NS))
    native = list(body)[:-1]
    if native and native[0].find('w:pPr/w:pStyle', NS).get(f'{{{W}}}val') == 'Title':
        native = native[1:]
    spaced = []
    for paragraph in native:
        style = paragraph.find('w:pPr/w:pStyle', NS)
        name = style.get(f'{{{W}}}val', '') if style is not None else ''
        previous = spaced[-1] if spaced else None
        previous_style = previous.find('w:pPr/w:pStyle', NS) if previous is not None else None
        previous_name = previous_style.get(f'{{{W}}}val', '') if previous_style is not None else ''
        has_text = previous is not None and bool(''.join(t.text or '' for t in previous.iter(f'{{{W}}}t')))
        if has_text and (name in {'Heading2', 'Heading3'} or (name == 'Heading4' and previous_name == 'Normal')):
            spaced.append(_p(''))
        spaced.append(paragraph)
    native = spaced
    # Circled/Roman heading labels are Japanese document symbols. Century does
    # not contain them; give only the label an explicit Japanese glyph font.
    for paragraph in native:
        style = paragraph.find('w:pPr/w:pStyle', NS)
        if style is None or style.get(f'{{{W}}}val') not in {'Heading4', 'Heading6'}:
            continue
        run = paragraph.find('w:r', NS)
        text = run.find('w:t', NS)
        if text is not None and '　' in (text.text or ''):
            label, remaining = text.text.split('　', 1)
            text.text = '　' + remaining
            symbol = ET.Element(f'{{{W}}}r')
            properties = ET.SubElement(symbol, f'{{{W}}}rPr')
            ET.SubElement(properties, f'{{{W}}}rFonts', {f'{{{W}}}{key}': 'ＭＳ 明朝' for key in ['ascii', 'hAnsi', 'eastAsia', 'cs']})
            ET.SubElement(symbol, f'{{{W}}}t').text = label
            paragraph.insert(list(paragraph).index(run), symbol)
    depth = 1
    for paragraph in native:
        style = paragraph.find('w:pPr/w:pStyle', NS)
        if style is None:
            continue
        name = style.get(f'{{{W}}}val', '')
        if re.fullmatch(r'Heading[1-7]', name):
            depth = int(name[-1])
        elif name == 'Normal' and ''.join(t.text or '' for t in paragraph.iter(f'{{{W}}}t')):
            style.set(f'{{{W}}}val', f'FormalBody{depth}')
            properties = paragraph.find('w:pPr', NS)
            for indent in properties.findall('w:ind', NS):
                properties.remove(indent)
    commissioned = report['research_kind'] == 'commissioned'
    introduction_required = group == 'G' or commissioned
    if introduction_required and not report.get('introduction'):
        raise LocalApplicationError('INPUT-FORMAL-INTRODUCTION', 'G formal report requires an explicit introduction')
    if group == 'M' and report.get('introduction') and report['research_kind'] == 'research_theme':
        raise LocalApplicationError('PUBLICATION-FORMAL-STRUCTURE-001', 'M research-theme report omits the introduction under MISCO 1.1/1.6')
    if commissioned and any(not str(report.get(key, '')).strip() for key in ['department', 'committee', 'chair', 'report_number']):
        raise LocalApplicationError('INPUT-COMMISSIONED-FRONT-MATTER', 'Commissioned report requires actual department, committee, chair and assigned report number')
    organization = '三井業際研究所' if commissioned else '三井情報システム協議会（ＭＩＳＣＯ）'
    # Neutral exact input values only: no sample year/theme or invented roster.
    nodes = []
    member = '会員会社限' + ('\n' + report['report_number'] if report.get('report_number') else '')
    nodes.append(_cover_box(member, 163, 20, 27, 12, 'ＭＳ ゴシック', framed=True))
    nodes.append(_cover_box(report['title'], 25, 70, 160, 24, 'ＭＳ ゴシック'))
    if report.get('subtitle'):
        nodes.append(_cover_box(report['subtitle'], 25, 100, 160, 18, 'ＭＳ ゴシック'))
    year, month = report['created_month'].split('-')
    nodes.append(_cover_box(f'{year}年{int(month)}月', 25, 200, 160, 18, 'ＭＳ Ｐゴシック'))
    cover_organization = organization + ('\n' + report['department'] + '\n' + report['committee'] if commissioned else '')
    nodes.append(_cover_box(cover_organization, 25, 230, 160, 20, 'ＭＳ ゴシック'))
    _end_section(nodes, _section(base, 'cover'))
    nodes.append(_p(''))
    _end_section(nodes, _section(base, 'cover_reverse'))
    nodes.append(_p('要約' if commissioned else '要旨', 'FormalFrontTitle'))
    if commissioned:
        nodes.append(_p(report['department'] + '　' + report['committee'] + '　主査 ' + report['chair'], 'FormalAuthor'))
    elif report.get('abstract_author'):
        nodes.append(_p(report['abstract_author'], 'FormalAuthor'))
    nodes.extend(_front(report['abstract']))
    _end_section(nodes, _section(base, 'abstract'))
    # evenPage makes the following two-page divider begin on a left page;
    # the Host validates the actual odd-page blank after field updates.
    nodes.append(_p(''))
    _end_section(nodes, _section(base, 'front_divider', 'oddPage'))
    nodes.append(_p(''))
    _end_section(nodes, _section(base, 'front_divider_reverse'))
    nodes.append(_p('目次', 'FormalFrontTitle'))
    nodes.append(_field('TOC \\o "1-3" \\h \\z \\u', 'TOC1'))
    _end_section(nodes, _section(base, 'contents'))
    if introduction_required:
        nodes.append(_p('はじめに', 'FormalFrontTitle'))
        nodes.extend(_front(report['introduction']))
        _end_section(nodes, _section(base, 'introduction', 'oddPage'))
    nodes.extend(native)
    # Word's evenPage break uses the logical page number and would change a
    # restarted page 1 to page 2. Physical parity is checked on the final PDF.
    _end_section(nodes, _section(base, 'body', 'nextPage', True))
    nodes.append(_p(''))
    _end_section(nodes, _section(base, 'back_divider'))
    nodes.append(_p(''))
    _end_section(nodes, _section(base, 'back_divider_reverse'))
    for appendix in report.get('appendices', []):
        nodes.append(_p(appendix['title'], 'FormalAppendixTitle'))
        nodes.extend(_front(appendix['content']))
    for title, field in [('委員会活動記録' if commissioned else '研究会活動記録', 'activity_record'), ('委員会名簿' if commissioned else '研究会名簿', 'roster')]:
        nodes.append(_p(title, 'FormalAppendixTitle'))
        nodes.extend(_front(report[field]))
    _end_section(nodes, _section(base, 'appendix', numbered=True))
    copyright_name = 'Mitsui Interbusiness Research Institute' if commissioned else 'Mitsui Information System Conference'
    nodes.append(_p(f'© {copyright_name} {year}'))
    nodes.append(_p('※本報告書記載事項の無断転載を禁じます。'))
    nodes.append(_p('※会員会社以外の第三者への本報告書の開示・提供はお控えくださいますようお願いいたします。'))
    _end_section(nodes, _section(base, 'back_cover'))
    nodes.append(_p(''))
    nodes.append(_section(base, 'back_cover_reverse'))
    body[:] = nodes
    notes = ET.Element(f'{{{W}}}footnotes')
    for id_, type_ in [(-1, 'separator'), (0, 'continuationSeparator')]:
        note = ET.SubElement(notes, f'{{{W}}}footnote', {f'{{{W}}}id': str(id_), f'{{{W}}}type': type_})
        p = ET.SubElement(note, f'{{{W}}}p')
        rr = ET.SubElement(p, f'{{{W}}}r')
        ET.SubElement(rr, f'{{{W}}}{type_}')
    for index, input_ in enumerate(report.get('footnotes', []), 1):
        marker = input_['marker']
        matches = []
        section_index = -1
        for node in native:
            style = node.find('w:pPr/w:pStyle', NS)
            if style is not None and re.fullmatch(r'Heading[1-7]', style.get(f'{{{W}}}val', '')):
                section_index += 1
            current_section = report['structure'][section_index]['section_id'] if 0 <= section_index < len(report['structure']) else None
            found = [t for t in node.findall('.//w:t', NS) if marker in (t.text or '')]
            if found and (style is None or not style.get(f'{{{W}}}val', '').startswith('FormalBody')):
                raise LocalApplicationError('PUBLICATION-FORMAL-FOOTNOTE-001', 'Native footnote marker must be in manuscript body text')
            if found and current_section != input_['section_id']:
                raise LocalApplicationError('PUBLICATION-FORMAL-FOOTNOTE-001', 'Footnote marker does not belong to its declared Writer section')
            matches.extend(found)
        if len(matches) != 1 or matches[0].text.count(marker) != 1:
            raise LocalApplicationError('PUBLICATION-FORMAL-FOOTNOTE-001', 'Each native footnote marker must occur exactly once in the pinned manuscript body')
        t = matches[0]
        rr = next(r for node in native for r in node.findall('.//w:r', NS) if t in list(r))
        pp = next(p for node in native for p in node.iter(f'{{{W}}}p') if rr in list(p))
        before, after = t.text.split(marker)
        t.text = before
        ref = ET.Element(f'{{{W}}}r')
        rp = ET.SubElement(ref, f'{{{W}}}rPr')
        ET.SubElement(rp, f'{{{W}}}vertAlign', {f'{{{W}}}val': 'superscript'})
        ET.SubElement(ref, f'{{{W}}}t').text = '*'
        ET.SubElement(ref, f'{{{W}}}footnoteReference', {f'{{{W}}}id': str(index)})
        tail = ET.Element(f'{{{W}}}r')
        ET.SubElement(tail, f'{{{W}}}t').text = after
        position = list(pp).index(rr)
        pp.insert(position + 1, ref)
        pp.insert(position + 2, tail)
        note = ET.SubElement(notes, f'{{{W}}}footnote', {f'{{{W}}}id': str(index)})
        np = _p(input_['text'], 'FormalFootnote')
        nr = ET.Element(f'{{{W}}}r')
        ET.SubElement(nr, f'{{{W}}}t').text = '*'
        ET.SubElement(nr, f'{{{W}}}footnoteRef')
        np.insert(1, nr)
        note.append(np)
    footpr = ET.SubElement(base, f'{{{W}}}footnotePr')
    ET.SubElement(footpr, f'{{{W}}}numFmt', {f'{{{W}}}val': 'decimal'})
    ET.SubElement(footpr, f'{{{W}}}numRestart', {f'{{{W}}}val': 'eachPage'})
    # Word supports a custom number symbol only via customMarkFollows;
    # Host checks the shoulder * prefix and per-page number in the final output.
    for section in body.findall('.//w:sectPr', NS):
        section.append(deepcopy(footpr))
    footer = ET.Element(f'{{{W}}}ftr')
    footer.append(_field('PAGE', 'FormalPageNumber'))
    footer.find('.//w:fldSimple/w:r/w:t', NS).text = '1'
    styles = ET.fromstring(parts['word/styles.xml'])
    for level, left in [(1, 0), (2, 0), (3, 227), (4, 453), (5, 680), (6, 907), (7, 1134)]:
        style = deepcopy(styles.find('w:style[@w:styleId="Normal"]', NS))
        style.set(f'{{{W}}}styleId', f'FormalBody{level}')
        style.find('w:name', NS).set(f'{{{W}}}val', f'FormalBody{level}')
        pr = style.find('w:pPr', NS)
        ET.SubElement(pr, f'{{{W}}}ind', {f'{{{W}}}left': str(left), f'{{{W}}}firstLine': '227'})
        ET.SubElement(pr, f'{{{W}}}jc', {f'{{{W}}}val': 'both'})
        styles.append(style)
    for name, size, bold, alignment in [('FormalFrontTitle', 24, True, 'center'), ('FormalAppendixTitle', 24, True, 'both'), ('FormalFrontBody', 21, False, 'both'), ('FormalAuthor', 21, False, 'right'), ('FormalFootnote', 18, False, 'both'), ('FormalPageNumber', 21, False, 'center'), ('TOC1', 21, False, 'left'), ('TOC2', 21, False, 'left'), ('TOC3', 21, False, 'left')]:
        style = ET.SubElement(styles, f'{{{W}}}style', {f'{{{W}}}type': 'paragraph', f'{{{W}}}styleId': name})
        ET.SubElement(style, f'{{{W}}}name', {f'{{{W}}}val': 'toc ' + name[3:] if name.startswith('TOC') else name})
        pr = ET.SubElement(style, f'{{{W}}}pPr')
        ET.SubElement(pr, f'{{{W}}}jc', {f'{{{W}}}val': alignment})
        if name == 'FormalAppendixTitle':
            ET.SubElement(pr, f'{{{W}}}keepNext')
        if name == 'FormalFrontBody':
            ET.SubElement(pr, f'{{{W}}}ind', {f'{{{W}}}firstLine': str(layout['first_line_indent_twips'])})
        if name.startswith('TOC'):
            ET.SubElement(pr, f'{{{W}}}ind', {f'{{{W}}}left': str((int(name[-1]) - 1) * 227)})
        rp = ET.SubElement(style, f'{{{W}}}rPr')
        font = 'ＭＳ ゴシック' if bold or name.startswith('TOC') else 'ＭＳ 明朝'
        latin = 'ＭＳ ゴシック' if name.startswith('TOC') else 'Century'
        ET.SubElement(rp, f'{{{W}}}rFonts', {f'{{{W}}}ascii': latin, f'{{{W}}}hAnsi': latin, f'{{{W}}}eastAsia': font})
        ET.SubElement(rp, f'{{{W}}}sz', {f'{{{W}}}val': str(size)})
        if bold:
            ET.SubElement(rp, f'{{{W}}}b')
    relations = ET.fromstring(parts['word/_rels/document.xml.rels'])
    types = ET.fromstring(parts['[Content_Types].xml'])
    for name, kind, id_ in [('footer1.xml', 'footer', 'rIdFormalFooter'), ('footer-empty.xml', 'footer', 'rIdFormalEmptyFooter'), ('footnotes.xml', 'footnotes', 'rIdFormalFootnotes')]:
        ET.SubElement(relations, f'{{{PKG}}}Relationship', {'Id': id_, 'Type': R + '/' + kind, 'Target': name})
        ET.SubElement(types, '{http://schemas.openxmlformats.org/package/2006/content-types}Override', {'PartName': '/word/' + name, 'ContentType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.' + kind + '+xml'})
    meta = ET.Element('formalReport', {'xmlns': 'urn:research-loom:publication-formal-report'})
    meta.text = json.dumps({'report': report, 'research_group_type': group}, ensure_ascii=False)
    parts.update({'word/document.xml': ET.tostring(document), 'word/styles.xml': ET.tostring(styles), 'word/footer1.xml': ET.tostring(footer), 'word/footer-empty.xml': ET.tostring(ET.Element(f'{{{W}}}ftr')), 'word/footnotes.xml': ET.tostring(notes), 'word/_rels/document.xml.rels': ET.tostring(relations), '[Content_Types].xml': ET.tostring(types), 'customXml/formal-report.xml': ET.tostring(meta)})
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, payload in parts.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return out.getvalue()


def inspect_formal(data: bytes, report: dict, group: str, layout: dict) -> list[str]:
    """Check native structure against original requirements, not serialized bytes."""
    problems = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            document = ET.fromstring(archive.read('word/document.xml'))
            styles = ET.fromstring(archive.read('word/styles.xml'))
            notes = ET.fromstring(archive.read('word/footnotes.xml'))
            relations = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
            footer = ET.fromstring(archive.read('word/footer1.xml'))
            if not any(row.get('Type') == R + '/footer' and row.get('Target') == 'footer1.xml' for row in relations):
                problems.append('footer-relationship')
            if not any('PAGE' in (node.get(f'{{{W}}}instr') or '') for node in footer.iter(f'{{{W}}}fldSimple')):
                problems.append('page-number-field')
            sections = document.findall('.//w:sectPr', NS)
            part_names = [node.get('{urn:research-loom:publication}part') for node in sections]
            expected = ['cover', 'cover_reverse', 'abstract', 'front_divider', 'front_divider_reverse', 'contents'] + (['introduction'] if group == 'G' or report['research_kind'] == 'commissioned' else []) + ['body', 'back_divider', 'back_divider_reverse', 'appendix', 'back_cover', 'back_cover_reverse']
            if part_names != expected:
                problems.append('formal-part-order')
            for section in sections:
                part = section.get('{urn:research-loom:publication}part')
                size = section.find('w:pgSz', NS)
                margins = section.find('w:pgMar', NS)
                if size is None or any(size.get(f'{{{W}}}{key}') != str(layout[field]) for key, field in [('w', 'page_width_twips'), ('h', 'page_height_twips')]):
                    problems.append('page-size:' + str(part))
                if margins is None or any(margins.get(f'{{{W}}}{key}') != str(layout[field]) for key, field in [('top', 'margin_top_twips'), ('bottom', 'margin_bottom_twips'), ('left', 'margin_left_twips'), ('right', 'margin_right_twips')]):
                    problems.append('margins:' + str(part))
                grid = section.find('w:docGrid', NS)
                if grid is None or any(grid.get(f'{{{W}}}{key}') != value for key, value in [('type', 'linesAndChars'), ('linePitch', str(layout['doc_grid_line_pitch_twips'])), ('charSpace', str(layout['doc_grid_char_space']))]):
                    problems.append('actual-40-grid:' + str(part))
                numbered = part in {'body', 'appendix'}
                footer_ref = section.find('w:footerReference', NS)
                if footer_ref is None or footer_ref.get(f'{{{R}}}id') != ('rIdFormalFooter' if numbered else 'rIdFormalEmptyFooter'):
                    problems.append('page-number-applicability:' + str(part))
                if numbered:
                    restart = section.find('w:pgNumType', NS)
                    if restart is None or restart.get(f'{{{W}}}start') != '1':
                        problems.append('page-number-restart:' + str(part))
                if section.find('w:footnotePr/w:numRestart[@w:val="eachPage"]', NS) is None:
                    problems.append('footnote-page-restart:' + str(part))
                if part in {'body', 'introduction'}:
                    opening = section.find('w:type', NS)
                    if opening is None or opening.get(f'{{{W}}}val') != ('nextPage' if part == 'body' else 'oddPage'):
                        problems.append('opening-page:' + str(part))
            text = ''.join(t.text or '' for t in document.iter(f'{{{W}}}t'))
            organization = '三井業際研究所' if report['research_kind'] == 'commissioned' else '三井情報システム協議会（ＭＩＳＣＯ）'
            for value in [report['title'], report['abstract'], report['activity_record'], report['roster'], '会員会社限', organization, '無断転載を禁じます']:
                if re.sub(r'\s+', '', value) not in re.sub(r'\s+', '', text):
                    problems.append('missing-content:' + value[:40])
            ref_ids = {node.get(f'{{{W}}}id') for node in document.iter(f'{{{W}}}footnoteReference')}
            note_ids = {node.get(f'{{{W}}}id') for node in notes if not node.get(f'{{{W}}}type')}
            if ref_ids != note_ids or len(ref_ids) != len(report.get('footnotes', [])):
                problems.append('native-footnote-binding')
            for name, size in [('FormalFrontTitle', '24'), ('FormalFrontBody', '21'), ('FormalFootnote', '18'), ('FormalPageNumber', '21')]:
                node = styles.find(f'w:style[@w:styleId="{name}"]/w:rPr/w:sz', NS)
                if node is None or node.get(f'{{{W}}}val') != size:
                    problems.append('style-size:' + name)
            for level, left in [(1, 0), (2, 0), (3, 227), (4, 453), (5, 680), (6, 907), (7, 1134)]:
                name = f'FormalBody{level}'
                style = styles.find(f'w:style[@w:styleId="{name}"]', NS)
                indent = style.find('w:pPr/w:ind', NS) if style is not None else None
                if indent is None or indent.attrib != {f'{{{W}}}left': str(left), f'{{{W}}}firstLine': '227'}:
                    problems.append('body-indent:' + name)
            expected_styles = [('FormalFrontTitle', 24, 'ＭＳ ゴシック', 'Century', True), ('FormalFrontBody', 21, 'ＭＳ 明朝', 'Century', False), ('FormalAuthor', 21, 'ＭＳ 明朝', 'Century', False), ('FormalFootnote', 18, 'ＭＳ 明朝', 'Century', False), ('FormalPageNumber', 21, 'ＭＳ 明朝', 'Century', False), ('Caption', 18, 'ＭＳ ゴシック', 'ＭＳ ゴシック', True), ('SourceCaption', 18, 'ＭＳ ゴシック', 'Century', True)]
            expected_styles += [(f'TOC{level}', 21, 'ＭＳ ゴシック', 'ＭＳ ゴシック', False) for level in range(1, 4)]
            expected_styles += [('FormalAppendixTitle', 24, 'ＭＳ ゴシック', 'Century', True)]
            expected_styles += [(f'FormalBody{level}', 21, 'ＭＳ 明朝', 'Century', False) for level in range(1, 8)]
            expected_styles += [(f'Heading{level}', {1: 28, 2: 24}.get(level, 21), 'ＭＳ ゴシック' if level <= 3 else 'ＭＳ 明朝', 'Century', level <= 3) for level in range(1, 8)]
            for name, size, font, latin, bold in expected_styles:
                style = styles.find(f'w:style[@w:styleId="{name}"]', NS)
                properties = style.find('w:rPr', NS) if style is not None else None
                fonts = properties.find('w:rFonts', NS) if properties is not None else None
                actual_size = properties.find('w:sz', NS) if properties is not None else None
                if fonts is None or any(fonts.get(f'{{{W}}}{key}') != value for key, value in [('ascii', latin), ('hAnsi', latin), ('eastAsia', font)]) or actual_size is None or actual_size.get(f'{{{W}}}val') != str(size) or (properties.find('w:b', NS) is not None) != bold:
                    problems.append('formal-style:' + name)
            for level in range(1, 4):
                indent = styles.find(f'w:style[@w:styleId="TOC{level}"]/w:pPr/w:ind', NS)
                if indent is None or indent.get(f'{{{W}}}left') != str((level - 1) * 227):
                    problems.append('toc-indent:' + str(level))
            for index, input_ in enumerate(report.get('footnotes', []), 1):
                note = notes.find(f'w:footnote[@w:id="{index}"]', NS)
                if note is None or input_['text'] not in ''.join(t.text or '' for t in note.iter(f'{{{W}}}t')):
                    problems.append('footnote-text:' + str(index))
            previous = None
            for paragraph in document.find('w:body', NS):
                style = paragraph.find('w:pPr/w:pStyle', NS)
                name = style.get(f'{{{W}}}val', '') if style is not None else ''
                if previous is not None:
                    previous_style = previous.find('w:pPr/w:pStyle', NS)
                    previous_name = previous_style.get(f'{{{W}}}val', '') if previous_style is not None else ''
                    has_text = bool(''.join(t.text or '' for t in previous.iter(f'{{{W}}}t')))
                    if has_text and (name in {'Heading2', 'Heading3'} or (name == 'Heading4' and previous_name.startswith('FormalBody'))):
                        problems.append('heading-before-blank:' + name)
                previous = paragraph
            cover_shapes = document.findall('.//{%s}shape' % V)
            expected_boxes = [(163, 20, '会員会社限'), (25, 70, report['title']), (25, 200, '年'), (25, 230, organization)]
            for x, y, value in expected_boxes:
                if not any(f'margin-left:{x}mm;' in node.get('style', '') and f'margin-top:{y}mm;' in node.get('style', '') and value in ''.join(t.text or '' for t in node.iter(f'{{{W}}}t')) for node in cover_shapes):
                    problems.append('cover-position:' + value[:40])
            # Fields are intentionally unmaterialized in a native draft. Final
            # conformance must additionally inspect the Host-produced PDF/TOC.
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
        problems.append('formal-docx-invalid')
    return sorted(set(problems))
