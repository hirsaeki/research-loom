"""Profile-driven MISCO research-theme covers; final PDF inspection stays required."""

from xml.etree import ElementTree as ET

from plugins.application_errors import LocalApplicationError

from ..publication.publication_docx import W

V = "urn:schemas-microsoft-com:vml"
NS = {"w": W}


def build_boxes(report: dict, spec: dict) -> list[ET.Element]:
    """Render only the new cover contract, without changing historical profiles."""
    try:
        if spec["schema_version"] != "1.0.0":
            raise ValueError("Unsupported cover schema")
        identification = spec["report_identification"]
        organization = spec["organization"]
        theme = report["title"]
        if report.get("subtitle"):
            theme += "\n" + report["subtitle"]
        year, month = map(int, report["created_month"].split("-"))
        date = (
            f"{year}年（令和{year - 2018}年）{month}月"
            if (year, month) >= (2019, 5)
            else f"{year}年{month}月"
        )
        date = date.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        member = "会員会社限"
        if report.get("report_number"):
            member += "\n" + report["report_number"]
        texts = {
            "membership": member,
            "identification": identification,
            "theme": theme,
            "issue_date": date,
            "organization": organization,
        }
        return [_box(texts[name], spec["boxes"][name], name) for name in texts]
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalApplicationError(
            "INPUT-MISCO-COVER-SPEC", "Invalid MISCO cover profile"
        ) from exc


def _box(text: str, config: dict, name: str) -> ET.Element:
    p = ET.Element(f"{{{W}}}p")
    run = ET.SubElement(p, f"{{{W}}}r")
    pict = ET.SubElement(run, f"{{{W}}}pict")
    shape = ET.SubElement(
        pict,
        f"{{{V}}}shape",
        {
            "id": "MiscoCover_" + name,
            "type": "#_x0000_t202",
            "style": f"position:absolute;margin-left:{config['left_mm']}mm;margin-top:{config['box_top_mm']}mm;width:{config['width_mm']}mm;height:{config['height_mm']}mm;z-index:1;mso-position-horizontal-relative:page;mso-position-vertical-relative:page",
            "stroked": "t" if config["framed"] else "f",
            "strokeweight": "0.75pt",
            "filled": "f",
        },
    )
    margins = config["inset_mm"]
    textbox = ET.SubElement(
        shape,
        f"{{{V}}}textbox",
        {
            "inset": ",".join(f"{n}mm" for n in margins),
            "style": "mso-fit-shape-to-text:t",
        },
    )
    content = ET.SubElement(textbox, f"{{{W}}}txbxContent")
    for line in text.split("\n"):
        pp = ET.SubElement(content, f"{{{W}}}p")
        pr = ET.SubElement(pp, f"{{{W}}}pPr")
        ET.SubElement(pr, f"{{{W}}}snapToGrid", {f"{{{W}}}val": "0"})
        ET.SubElement(
            pr,
            f"{{{W}}}spacing",
            {
                f"{{{W}}}before": "0",
                f"{{{W}}}after": "0",
                f"{{{W}}}beforeLines": str(config["space_before_hundredths_line"]),
                f"{{{W}}}line": "240",
                f"{{{W}}}lineRule": "auto",
            },
        )
        ET.SubElement(pr, f"{{{W}}}jc", {f"{{{W}}}val": "center"})
        rr = ET.SubElement(pp, f"{{{W}}}r")
        rp = ET.SubElement(rr, f"{{{W}}}rPr")
        ET.SubElement(
            rp,
            f"{{{W}}}rFonts",
            {f"{{{W}}}{key}": config["font"] for key in ["ascii", "hAnsi", "eastAsia"]},
        )
        ET.SubElement(rp, f"{{{W}}}sz", {f"{{{W}}}val": str(config["size_pt"] * 2)})
        ET.SubElement(rp, f"{{{W}}}spacing", {f"{{{W}}}val": "0"})
        ET.SubElement(rp, f"{{{W}}}snapToGrid", {f"{{{W}}}val": "0"})
        ET.SubElement(rr, f"{{{W}}}t").text = line
    return p


def inspect_boxes(document: ET.Element, report: dict, spec: dict) -> list[str]:
    """Check authored XML, never claim the final rendered text coordinates pass."""
    problems = []
    shapes = document.findall(f".//{{{V}}}shape")
    for expected in build_boxes(report, spec):
        shape = expected.find(f".//{{{V}}}shape")
        found = [node for node in shapes if node.get("id") == shape.get("id")]
        if len(found) != 1 or ET.tostring(found[0]) != ET.tostring(shape):
            problems.append("cover-profile:" + shape.get("id"))
    return problems
