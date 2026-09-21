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


def _paragraph(text: str, role: str = "body", bookmark: tuple[int, str] | None = None) -> str:
    style = {"title": "Title", "heading": "Heading1", "heading2": "Heading2", "cell": "TableText", "header": "TableHeader"}.get(role, "Normal")
    runs = "</w:t><w:br/><w:t xml:space=\"preserve\">".join(_text(text).split("\n"))
    runs = runs.replace("\t", '</w:t><w:tab/><w:t xml:space="preserve">')
    start = f'<w:bookmarkStart w:id="{bookmark[0]}" w:name="{bookmark[1]}"/>' if bookmark else ""
    end = f'<w:bookmarkEnd w:id="{bookmark[0]}"/>' if bookmark else ""
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{start}<w:r><w:t xml:space="preserve">{runs}</w:t></w:r>{end}</w:p>'


def _table(rows: list[list[str]]) -> str:
    width = 9360 // len(rows[0])
    borders = ''.join(f'<w:{side} w:val="single" w:sz="4" w:color="auto"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    result = ['<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:tblLayout w:type="fixed"/>',
              f'<w:tblBorders>{borders}</w:tblBorders>',
              '<w:tblCellMar><w:top w:w="80" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>',
              '<w:tblGrid>' + ''.join(f'<w:gridCol w:w="{width}"/>' for _ in rows[0]) + '</w:tblGrid>']
    for index, row in enumerate(rows):
        result.append('<w:tr>' + ('<w:trPr><w:tblHeader/></w:trPr>' if index == 0 else ''))
        for cell in row:
            result.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>' + _paragraph(cell, 'header' if index == 0 else 'cell') + '</w:tc>')
        result.append('</w:tr>')
    return ''.join(result) + '</w:tbl>'


def _image(block: dict[str, Any], index: int) -> str:
    width, height = block["width"] * 9525, block["height"] * 9525  # 96dpi, preserve aspect ratio.
    scale = min(1, 5943600 / width, 5029200 / height)
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


def docx_bytes(lines: list[tuple[str, Any]]) -> bytes:
    body = []
    images = {}
    relationships = [f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>',
                     f'<Relationship Id="rIdProvenance" Type="{R}/customXml" Target="../customXml/item1.xml"/>']
    index = 0
    for role, block in lines:
        if role != "exhibit":
            body.append(_paragraph(block, role))
            continue
        index += 1
        body.append(_paragraph(block["caption"], "heading2", (index, _bookmark(block["ref"]))))
        if block["kind"] == "table":
            body.append(_table(block["rows"]))
        elif block["kind"] == "image":
            body.append(_image(block, index))
            name = f'media/image-{index}.png'
            images['word/' + name] = block['data']
            relationships.append(f'<Relationship Id="rIdImage{index}" Type="{R}/image" Target="{name}"/>')
        else:
            body.append(_paragraph(f'[Unavailable exhibit: {block["code"]}. Preserve the source and supply a supported representation under a new identity.]'))
        if block.get("note"):
            body.append(_paragraph(block["note"], "cell"))
    document = (f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}" xmlns:wp="{WP}" xmlns:pic="{PIC}"><w:body>' + ''.join(body)
                + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    styles = [f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>']
    for name, size, bold in [("Normal", 22, False), ("Title", 34, True), ("Heading1", 28, True), ("Heading2", 22, True), ("TableText", 18, False), ("TableHeader", 18, True)]:
        keep = '<w:keepNext/>' if name in {"Title", "Heading1", "Heading2"} else ''
        styles.append(f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:pPr>{keep}<w:spacing w:after="80"/></w:pPr><w:rPr><w:sz w:val="{size}"/>' + ('<w:b/>' if bold else '') + '</w:rPr></w:style>')
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


def verify_native_docx(data: bytes, lines: list[tuple[str, Any]]) -> bool:
    """Inspect the generated archive independently of serialization logic."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            doc = ET.fromstring(archive.read('word/document.xml'))
            blocks = [b for role, b in lines if role == 'exhibit']
            tables = doc.findall(f'.//{{{W}}}tbl')
            expected_tables = [b for b in blocks if b['kind'] == 'table']
            if len(tables) != len(expected_tables):
                return False
            for table, block in zip(tables, expected_tables):
                rows = [[_paragraph_text(cell) for cell in row.findall(f'{{{W}}}tc')] for row in table.findall(f'{{{W}}}tr')]
                if rows != [[cell.replace('\r\n', '\n').replace('\r', '\n') for cell in row] for row in block['rows']]:
                    return False
            paragraphs = [_paragraph_text(p) for p in doc.findall(f'.//{{{W}}}p')]
            bookmarks = {n.get(f'{{{W}}}name') for n in doc.findall(f'.//{{{W}}}bookmarkStart')}
            for block in blocks:
                if block['caption'].replace('\r\n', '\n').replace('\r', '\n') not in paragraphs or _bookmark(block['ref']) not in bookmarks:
                    return False
                if block.get('note') and block['note'].replace('\r\n', '\n').replace('\r', '\n') not in paragraphs:
                    return False
            # Body paragraphs include the already resolved section/citation/exhibit tokens.
            for role, text in lines:
                if role != 'exhibit' and text.replace('\r\n', '\n').replace('\r', '\n') not in paragraphs:
                    return False
            relations = {r.attrib['Id']: r.attrib for r in ET.fromstring(archive.read('word/_rels/document.xml.rels'))}
            images = [b for b in blocks if b['kind'] == 'image']
            blips = doc.findall(f'.//{{{A}}}blip')
            if len(blips) != len(images):
                return False
            for blip, block in zip(blips, images):
                relation = relations[blip.attrib[f'{{{R}}}embed']]
                if relation['Type'] != R + '/image' or relation.get('TargetMode') == 'External':
                    return False
                payload = archive.read('word/' + relation['Target'])
                if payload != block['data'] or 'sha256:' + hashlib.sha256(payload).hexdigest() != block['asset_digest']:
                    return False
            if json.loads(ET.fromstring(archive.read('customXml/item1.xml')).text) != _provenance(lines):
                return False
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
        return False
    return True
