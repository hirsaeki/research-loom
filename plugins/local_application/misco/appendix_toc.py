"""Native scoped TOCs and appendix footer for the versioned Word workflow."""

from xml.etree import ElementTree as ET

from ..publication.publication_docx import W

NS = {"w": W}


def mark_range(nodes: list[ET.Element], name: str, bookmark_id: int) -> None:
    paragraphs = [node for node in nodes if node.tag == f"{{{W}}}p"]
    if not paragraphs:
        raise ValueError("A TOC scope requires a paragraph")
    start = ET.Element(
        f"{{{W}}}bookmarkStart", {f"{{{W}}}id": str(bookmark_id), f"{{{W}}}name": name}
    )
    paragraphs[0].insert(1 if paragraphs[0].find("w:pPr", NS) is not None else 0, start)
    ET.SubElement(paragraphs[-1], f"{{{W}}}bookmarkEnd", {f"{{{W}}}id": str(bookmark_id)})


def inspect(document: ET.Element, footer: ET.Element) -> list[str]:
    problems = []
    fields = document.findall(".//w:fldSimple", NS)
    codes = [field.get(f"{{{W}}}instr", "") for field in fields]
    for name in ["AUTO_BODY", "AUTO_APPENDIX"]:
        if sum(f"\\b {name} " in code for code in codes) != 1:
            problems.append("toc-scope:" + name)
        if len(document.findall(f'.//w:bookmarkStart[@w:name="{name}"]', NS)) != 1:
            problems.append("toc-bookmark:" + name)
    if "".join(footer.itertext()) != "付1":
        problems.append("appendix-page-prefix")
    return problems
