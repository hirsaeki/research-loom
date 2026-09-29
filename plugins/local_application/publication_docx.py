"""Deterministic OOXML paragraphs, native tables and exact retained PNG parts.

This is structural/content verification, not a page-layout or visual-quality oracle.
"""
from __future__ import annotations

import hashlib
import io
import json
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
import zipfile

from .facade import LocalApplicationError

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _text(text: str) -> str:
    if any(not (ord(c) in {9, 10, 13} or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in text):
        raise LocalApplicationError("APPLICATION-PUBLICATION-RENDER-001", "publication text contains XML-incompatible characters")
    return escape(text.replace("\r\n", "\n").replace("\r", "\n"))


def _paragraph(
    text: str,
    role: str = "body",
    bookmark: tuple[int, str] | None = None,
    first_line_indent_twips: int = 0,
    reference_left_indent_twips: int = 0,
    reference_hanging_twips: int = 0,
) -> str:
    style = {
        "title": "Title",
        "heading": "Heading1",
        "heading2": "Heading2",
        "caption": "Caption",
        "source_caption": "SourceCaption",
        "reference_heading": "ReferenceHeading",
        "reference": "Reference",
        "cell": "TableText",
        "header": "TableHeader",
    }.get(role, "Normal")
    runs = "</w:t><w:br/><w:t xml:space=\"preserve\">".join(_text(text).split("\n"))
    runs = runs.replace("\t", '</w:t><w:tab/><w:t xml:space="preserve">')
    start = f'<w:bookmarkStart w:id="{bookmark[0]}" w:name="{bookmark[1]}"/>' if bookmark else ""
    end = f'<w:bookmarkEnd w:id="{bookmark[0]}"/>' if bookmark else ""
    indent = ''
    if role == 'body' and first_line_indent_twips:
        indent = f'<w:ind w:firstLine="{first_line_indent_twips}"/>'
    elif role == 'reference' and (reference_left_indent_twips or reference_hanging_twips):
        attrs = []
        if reference_left_indent_twips:
            attrs.append(f'w:left="{reference_left_indent_twips}"')
        if reference_hanging_twips:
            attrs.append(f'w:hanging="{reference_hanging_twips}"')
        indent = '<w:ind ' + ' '.join(attrs) + '/>'
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{indent}</w:pPr>{start}<w:r><w:t xml:space="preserve">{runs}</w:t></w:r>{end}</w:p>'


def _table(rows: list[list[str]], total_width_twips: int = 9360) -> str:
    width = max(1, total_width_twips // len(rows[0]))
    borders = ''.join(f'<w:{side} w:val="single" w:sz="4" w:color="auto"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    result = [f'<w:tbl><w:tblPr><w:tblW w:w="{total_width_twips}" w:type="dxa"/><w:tblLayout w:type="fixed"/>',
              f'<w:tblBorders>{borders}</w:tblBorders>',
              '<w:tblCellMar><w:top w:w="80" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>',
              '<w:tblGrid>' + ''.join(f'<w:gridCol w:w="{width}"/>' for _ in rows[0]) + '</w:tblGrid>']
    for index, row in enumerate(rows):
        result.append('<w:tr>' + ('<w:trPr><w:tblHeader/></w:trPr>' if index == 0 else ''))
        for cell in row:
            result.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>' + _paragraph(cell, 'header' if index == 0 else 'cell') + '</w:tc>')
        result.append('</w:tr>')
    return ''.join(result) + '</w:tbl>'


def _image(block: dict[str, Any], index: int, max_width_emu: int = 5943600) -> str:
    width, height = block["width"] * 9525, block["height"] * 9525  # 96dpi, preserve aspect ratio.
    scale = min(1, max_width_emu / width, 5029200 / height)
    width, height = max(1, int(width * scale)), max(1, int(height * scale))
    desc = quoteattr(block["caption"])
    return (f'<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{width}" cy="{height}"/><wp:docPr id="{index}" name="Image {index}" descr={desc}/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="{PIC}"><pic:pic>'
            f'<pic:nvPicPr><pic:cNvPr id="{index}" name="image-{index}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="rIdImage{index}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _bookmark(ref: str) -> str:
    return "EXH_" + hashlib.sha256(ref.encode()).hexdigest()[:24]


def _provenance(lines: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [{"ref": block["ref"], "caption": block["caption"], "kind": block["kind"],
             "provenance": block["provenance"], **({"asset_digest": block["asset_digest"]} if block["kind"] == "image" else {})}
            for role, block in lines if role == "exhibit"]


def docx_bytes(lines: list[tuple[str, Any]], layout: dict[str, Any] | None = None) -> bytes:
    layout = dict(layout or {})
    page_width = int(layout.get('page_width_twips', 12240))
    page_height = int(layout.get('page_height_twips', 15840))
    margin_top = int(layout.get('margin_top_twips', 1440))
    margin_right = int(layout.get('margin_right_twips', 1440))
    margin_bottom = int(layout.get('margin_bottom_twips', 1440))
    margin_left = int(layout.get('margin_left_twips', 1440))
    content_width_twips = max(1, page_width - margin_left - margin_right)
    content_width_emu = content_width_twips * 635
    body = []
    images = {}
    relationships = [f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>',
                     f'<Relationship Id="rIdProvenance" Type="{R}/customXml" Target="../customXml/item1.xml"/>']
    index = 0
    for role, block in lines:
        if role != "exhibit":
            body.append(_paragraph(
                block,
                role,
                first_line_indent_twips=int(layout.get('first_line_indent_twips', 0)),
                reference_left_indent_twips=int(layout.get('reference_left_indent_twips', 0)),
                reference_hanging_twips=int(layout.get('reference_hanging_twips', 0)),
            ))
            continue
        index += 1
        caption = _paragraph(block["caption"], "caption", (index, _bookmark(block["ref"])))
        if block["kind"] == "table":
            body.append(caption)
            body.append(_table(block["rows"], content_width_twips))
        elif block["kind"] == "image":
            body.append(_image(block, index, content_width_emu))
            body.append(caption)
            name = f'media/image-{index}.png'
            images['word/' + name] = block['data']
            relationships.append(f'<Relationship Id="rIdImage{index}" Type="{R}/image" Target="{name}"/>')
        else:
            body.append(_paragraph(f'[Unavailable exhibit: {block["code"]}. Preserve the source and supply a supported representation under a new identity.]'))
        if block.get("note"):
            body.append(_paragraph(block["note"], "source_caption"))
    header_margin = int(layout.get('header_margin_twips', 720))
    footer_margin = int(layout.get('footer_margin_twips', 720))
    grid = ''
    if layout.get('doc_grid_line_pitch_twips') is not None or layout.get('doc_grid_char_space') is not None:
        line_pitch = int(layout.get('doc_grid_line_pitch_twips', 360))
        char_space = int(layout.get('doc_grid_char_space', 0))
        grid = f'<w:docGrid w:type="linesAndChars" w:linePitch="{line_pitch}" w:charSpace="{char_space}"/>'
    document = (f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}" xmlns:wp="{WP}" xmlns:pic="{PIC}"><w:body>' + ''.join(body)
                + f'<w:sectPr><w:pgSz w:w="{page_width}" w:h="{page_height}"/><w:pgMar w:top="{margin_top}" w:right="{margin_right}" w:bottom="{margin_bottom}" w:left="{margin_left}" w:header="{header_margin}" w:footer="{footer_margin}"/>{grid}</w:sectPr></w:body></w:document>')
    body_font = str(layout.get('body_font', 'Arial'))
    body_latin_font = str(layout.get('body_latin_font', body_font))
    heading_font = str(layout.get('heading_font', body_font))
    heading_latin_font = str(layout.get('heading_latin_font', heading_font))
    title_font = str(layout.get('title_font', heading_font))
    title_latin_font = str(layout.get('title_latin_font', title_font))
    table_font = str(layout.get('table_font', body_font))
    table_latin_font = str(layout.get('table_latin_font', table_font))
    caption_font = str(layout.get('caption_font', heading_font))
    caption_latin_font = str(layout.get('caption_latin_font', heading_latin_font))
    body_size = int(layout.get('body_size_half_points', 22))
    styles = [f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{escape(body_latin_font)}" w:hAnsi="{escape(body_latin_font)}" w:eastAsia="{escape(body_font)}"/><w:sz w:val="{body_size}"/></w:rPr></w:rPrDefault></w:docDefaults>']
    style_rows = [
        ("Normal", body_size, False, body_font, body_latin_font, None),
        ("Title", int(layout.get('title_size_half_points', 34)), True, title_font, title_latin_font, "center"),
        ("Heading1", int(layout.get('heading1_size_half_points', 28)), True, heading_font, heading_latin_font, None),
        ("Heading2", int(layout.get('heading2_size_half_points', 22)), True, heading_font, heading_latin_font, None),
        ("Caption", int(layout.get('caption_size_half_points', 18)), True, caption_font, caption_latin_font, "center"),
        ("SourceCaption", int(layout.get('caption_size_half_points', 18)), False, caption_font, caption_latin_font, "center"),
        ("ReferenceHeading", body_size, False, body_font, body_latin_font, None),
        ("Reference", body_size, False, body_font, body_latin_font, None),
        ("TableText", int(layout.get('table_body_size_half_points', 18)), False, table_font, table_latin_font, None),
        ("TableHeader", int(layout.get('table_header_size_half_points', 18)), True, table_font, table_latin_font, None),
    ]
    for name, size, bold, font, latin_font, alignment in style_rows:
        keep = '<w:keepNext/>' if name in {"Title", "Heading1", "Heading2"} else ''
        jc = f'<w:jc w:val="{alignment}"/>' if alignment else ''
        styles.append(f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:pPr>{keep}{jc}<w:spacing w:after="0"/></w:pPr><w:rPr><w:rFonts w:ascii="{escape(latin_font)}" w:hAnsi="{escape(latin_font)}" w:eastAsia="{escape(font)}"/><w:sz w:val="{size}"/>' + ('<w:b/>' if bold else '') + '</w:rPr></w:style>')
    types = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    parts = {"[Content_Types].xml": types, "_rels/.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
             "word/document.xml": document, "word/styles.xml": ''.join(styles) + '</w:styles>',
             "word/_rels/document.xml.rels": f'<Relationships xmlns="{PKG}">' + ''.join(relationships) + '</Relationships>',
             "customXml/item1.xml": '<exhibits xmlns="urn:research-loom:publication-exhibits:0.2.0">' + _text(json.dumps(_provenance(lines), ensure_ascii=True, sort_keys=True)) + '</exhibits>'}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in {**parts, **images}.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            info.create_system = 3
            archive.writestr(info, data.encode('utf-8') if isinstance(data, str) else data)
    return output.getvalue()


def _paragraph_text(node: ET.Element) -> str:
    return ''.join(child.text or '' if child.tag == f'{{{W}}}t' else '\n' if child.tag == f'{{{W}}}br' else '\t' if child.tag == f'{{{W}}}tab' else '' for child in node.iter())


def verify_native_docx(data: bytes, lines: list[tuple[str, Any]], layout: dict[str, Any] | None = None) -> bool:
    """Inspect the generated archive independently of serialization logic."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            doc = ET.fromstring(archive.read('word/document.xml'))
            body = doc.find(f'{{{W}}}body')
            if body is None:
                return False
            layout = dict(layout or {})
            sect = body.find(f'{{{W}}}sectPr')
            if sect is None:
                return False
            pg_sz = sect.find(f'{{{W}}}pgSz')
            pg_mar = sect.find(f'{{{W}}}pgMar')
            if pg_sz is None or pg_mar is None:
                return False
            expected_page = {
                'w': int(layout.get('page_width_twips', 12240)),
                'h': int(layout.get('page_height_twips', 15840)),
            }
            expected_margins = {
                'top': int(layout.get('margin_top_twips', 1440)),
                'right': int(layout.get('margin_right_twips', 1440)),
                'bottom': int(layout.get('margin_bottom_twips', 1440)),
                'left': int(layout.get('margin_left_twips', 1440)),
                'header': int(layout.get('header_margin_twips', 720)),
                'footer': int(layout.get('footer_margin_twips', 720)),
            }
            if any(int(pg_sz.get(f'{{{W}}}{key}', '-1')) != value for key, value in expected_page.items()):
                return False
            if any(int(pg_mar.get(f'{{{W}}}{key}', '-1')) != value for key, value in expected_margins.items()):
                return False
            if layout.get('doc_grid_line_pitch_twips') is not None or layout.get('doc_grid_char_space') is not None:
                grid = sect.find(f'{{{W}}}docGrid')
                if grid is None:
                    return False
                if int(grid.get(f'{{{W}}}linePitch', '-1')) != int(layout.get('doc_grid_line_pitch_twips', 360)):
                    return False
                if int(grid.get(f'{{{W}}}charSpace', '-999999')) != int(layout.get('doc_grid_char_space', 0)):
                    return False
            children = [node for node in body if node.tag != f'{{{W}}}sectPr']
            relations = {r.attrib['Id']: r.attrib for r in ET.fromstring(archive.read('word/_rels/document.xml.rels'))}
            cursor = 0

            def normalized(value: str) -> str:
                return value.replace('\r\n', '\n').replace('\r', '\n')

            def take(tag: str) -> ET.Element:
                nonlocal cursor
                if cursor >= len(children) or children[cursor].tag != f'{{{W}}}{tag}':
                    raise ValueError('unexpected publication block order')
                node = children[cursor]
                cursor += 1
                return node

            for role, value in lines:
                if role != 'exhibit':
                    if _paragraph_text(take('p')) != normalized(value):
                        return False
                    continue

                block = value
                if block['kind'] == 'table':
                    caption = take('p')
                    if _paragraph_text(caption) != normalized(block['caption']):
                        return False
                    bookmarks = caption.findall(f'.//{{{W}}}bookmarkStart')
                    if len(bookmarks) != 1 or bookmarks[0].get(f'{{{W}}}name') != _bookmark(block['ref']):
                        return False
                    table = take('tbl')
                    rows = [[_paragraph_text(cell) for cell in row.findall(f'{{{W}}}tc')] for row in table.findall(f'{{{W}}}tr')]
                    expected = [[normalized(cell) for cell in row] for row in block['rows']]
                    if rows != expected:
                        return False
                elif block['kind'] == 'image':
                    image = take('p')
                    blips = image.findall(f'.//{{{A}}}blip')
                    doc_props = image.findall(f'.//{{{WP}}}docPr')
                    if len(blips) != 1 or len(doc_props) != 1 or doc_props[0].get('descr') != block['caption']:
                        return False
                    relation = relations[blips[0].attrib[f'{{{R}}}embed']]
                    if relation['Type'] != R + '/image' or relation.get('TargetMode') == 'External':
                        return False
                    payload = archive.read('word/' + relation['Target'])
                    if payload != block['data'] or 'sha256:' + hashlib.sha256(payload).hexdigest() != block['asset_digest']:
                        return False
                    caption = take('p')
                    if _paragraph_text(caption) != normalized(block['caption']):
                        return False
                    bookmarks = caption.findall(f'.//{{{W}}}bookmarkStart')
                    if len(bookmarks) != 1 or bookmarks[0].get(f'{{{W}}}name') != _bookmark(block['ref']):
                        return False
                else:
                    unavailable = take('p')
                    expected = f'[Unavailable exhibit: {block["code"]}. Preserve the source and supply a supported representation under a new identity.]'
                    if _paragraph_text(unavailable) != expected:
                        return False

                if block.get('note') and _paragraph_text(take('p')) != normalized(block['note']):
                    return False

            if cursor != len(children):
                return False
            if json.loads(ET.fromstring(archive.read('customXml/item1.xml')).text) != _provenance(lines):
                return False
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
        return False
    return True
