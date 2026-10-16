"""Bounded PDF inspection and exact-output MISCO review evaluation."""

from __future__ import annotations

import io
import re
from collections.abc import Mapping

from jsonschema import FormatChecker
from pypdf import PdfReader

from .facade import LocalApplicationError


def inspect_pdf(data: bytes, *, required_text=(), page_ranges=None, expected_parts=()):
    if len(data) > 16 * 1024 * 1024 or not data.startswith(b"%PDF-"):
        raise LocalApplicationError(
            "PUBLICATION-PDF-INVALID", "PDF must be bounded and carry a PDF header"
        )
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 256:
            raise ValueError("Encrypted or unsupported page count")
        texts = []
        footer_texts = []
        fonts = set()
        problems = []
        for index, page in enumerate(reader.pages, 1):
            if (
                abs(float(page.mediabox.width) - 595.276) > 2
                or abs(float(page.mediabox.height) - 841.89) > 2
                or page.rotation
            ):
                problems.append(f"page-size:{index}")
            footer = []

            def visit(text, cm, tm, font, size):
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                if y < 70 and text.strip():
                    footer.append(text.strip())
                if text.strip() and font is not None:
                    name = re.sub(r"^[A-Z]{6}\+", "", str(font.get("/BaseFont", "")).lstrip("/"))
                    fonts.add(name)
                    allowed = (
                        "MS-Mincho",
                        "MS-Gothic",
                        "MS-PGothic",
                        "MSMincho",
                        "MSGothic",
                        "MSPGothic",
                        "Century",
                    )
                    if not any(name.startswith(prefix) for prefix in allowed):
                        problems.append(f"font-substitution:{index}:{name}")

            texts.append(page.extract_text(visitor_text=visit) or "")
            footer_texts.append("".join(footer))

        def normalized(value):
            return re.sub(r"\s+", "", value)

        joined = normalized("\n".join(texts))
        for value in required_text:
            if normalized(value) and normalized(value) not in joined:
                problems.append("missing-text:" + value[:80])
        ranges = page_ranges or {}
        if not isinstance(ranges, Mapping):
            raise ValueError("Page ranges must be an object")
        if expected_parts:
            bookmarks = {}

            def collect(outlines):
                for destination in outlines:
                    if isinstance(destination, list):
                        collect(destination)
                    elif destination.title.startswith("RL_"):
                        bookmarks[destination.title[3:]] = (
                            reader.get_destination_page_number(destination) + 1
                        )

            collect(reader.outline)
            for part in expected_parts:
                span = ranges.get(part)
                if (
                    not isinstance(span, list)
                    or len(span) != 2
                    or any(type(n) is not int for n in span)
                    or not 1 <= span[0] <= span[1] <= len(texts)
                ):
                    problems.append("page-range:" + part)
                    continue
                if bookmarks.get(part) != span[0]:
                    problems.append("page-bookmark-binding:" + part)
                if part.endswith("_reverse") or part in {"front_divider", "back_divider"}:
                    if any(text.strip() for text in texts[span[0] - 1 : span[1]]):
                        problems.append("nonblank-part:" + part)
            starts = [ranges.get(part, [0])[0] for part in expected_parts]
            if starts != sorted(set(starts)):
                problems.append("formal-part-order")
            if "introduction" in bookmarks and bookmarks["introduction"] % 2 == 0:
                problems.append("introduction-not-right-page")
        for part in ["abstract", "body", "appendix"]:
            span = ranges.get(part)
            if (
                not isinstance(span, list)
                or len(span) != 2
                or any(isinstance(n, bool) or not isinstance(n, int) for n in span)
                or not 1 <= span[0] <= span[1] <= len(texts)
            ):
                problems.append("page-range:" + part)
        valid_ranges = all(
            "page-range:" + part not in problems for part in ["abstract", "body", "appendix"]
        )
        if valid_ranges:
            abstract, body, appendix = (ranges[part] for part in ["abstract", "body", "appendix"])
            if not abstract[1] < body[0] <= body[1] < appendix[0]:
                problems.append("page-range-order")
            if abstract[1] - abstract[0] + 1 > 2:
                problems.append("abstract-over-2-pages")
            if appendix[1] - appendix[0] + 1 > 50:
                problems.append("appendix-over-50-pages")
            if body[0] % 2:
                problems.append("body-not-left-page")
            for part, span in [("body", body), ("appendix", appendix)]:
                for ordinal, physical in enumerate(range(span[0], span[1] + 1), 1):
                    if footer_texts[physical - 1] != str(ordinal):
                        problems.append(f"page-number:{part}:{physical}")
            numbered_pages = set(range(body[0], body[1] + 1)) | set(
                range(appendix[0], appendix[1] + 1)
            )
            for physical, footer in enumerate(footer_texts, 1):
                if physical not in numbered_pages and footer:
                    problems.append(f"unexpected-footer:{physical}")
        return {
            "page_count": len(texts),
            "fonts": sorted(fonts),
            "problems": sorted(set(problems)),
            "page_text": texts,
        }
    except LocalApplicationError:
        raise
    except Exception as exc:
        raise LocalApplicationError(
            "PUBLICATION-PDF-INVALID", "PDF parsing failed: " + str(exc)
        ) from exc


def coverage_review(
    coverage: Mapping,
    policy: Mapping,
    review: Mapping,
    pdf_digest: str,
    page_count: int,
    *,
    page_ranges=None,
):
    problems = []
    required_keys = {"pdf_digest", "reviewer_id", "reviewed_at", "checks", "pages"}
    if (
        not isinstance(review, Mapping)
        or not required_keys <= set(review)
        or set(review) - required_keys - {"presentation_review"}
    ):
        raise LocalApplicationError(
            "PUBLICATION-PDF-INPUT",
            "Review requires exact PDF binding, reviewer, review time, checks and pages",
        )
    if (
        not isinstance(review["checks"], list)
        or len(review["checks"]) > 256
        or not isinstance(review["pages"], list)
        or len(review["pages"]) > 256
    ):
        raise LocalApplicationError(
            "PUBLICATION-PDF-INPUT", "Review checks and page evidence must be bounded arrays"
        )
    for row in review["checks"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"check_id", "status", "rationale"}
            or not isinstance(row["check_id"], str)
            or not isinstance(row["status"], str)
            or row["status"] not in {"passed", "warning", "failed", "unevaluated", "not_applicable"}
            or not isinstance(row["rationale"], str)
            or len(row["rationale"]) > 4000
        ):
            raise LocalApplicationError("PUBLICATION-PDF-INPUT", "Invalid clause review evidence")
    for row in review["pages"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"page", "status", "rationale"}
            or type(row["page"]) is not int
            or not isinstance(row["status"], str)
            or row["status"] not in {"passed", "failed", "unevaluated"}
            or not isinstance(row["rationale"], str)
            or len(row["rationale"]) > 4000
        ):
            raise LocalApplicationError("PUBLICATION-PDF-INPUT", "Invalid page review evidence")
    if (
        review.get("pdf_digest") != pdf_digest
        or not isinstance(review.get("reviewer_id"), str)
        or not review["reviewer_id"].strip()
        or not isinstance(review.get("reviewed_at"), str)
        or not FormatChecker().conforms(review["reviewed_at"], "date-time")
    ):
        problems.append("review-output-binding")
    report = policy.get("formal_report", {})
    sources = policy.get("review_conditions", {})
    flags = {
        "report": True,
        "research_theme": report.get("research_kind") == "research_theme",
        "commissioned": report.get("research_kind") == "commissioned",
        "presentation": report.get("presentation_required", False),
        "printing": report.get("printing_required", False),
        "submission": report.get("submission_requested", False),
        "color": report.get("color_used", False),
        "interview": sources.get("interview", False),
        "company_information": sources.get("company_information", False),
    }
    if flags["presentation"]:
        presentation = review.get("presentation_review")
        if (
            not isinstance(presentation, Mapping)
            or set(presentation)
            != {
                "artifact_digest",
                "artifact_reference",
                "software_version",
                "slide_count",
                "slides",
            }
            or not isinstance(presentation["artifact_digest"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", presentation["artifact_digest"])
            or any(
                not isinstance(presentation[key], str)
                or not presentation[key].strip()
                or len(presentation[key]) > 1024
                for key in ["artifact_reference", "software_version"]
            )
            or type(presentation["slide_count"]) is not int
            or not 1 <= presentation["slide_count"] <= 256
            or not isinstance(presentation["slides"], list)
        ):
            problems.append("presentation-review-binding")
        else:
            slides = presentation["slides"]
            valid = len(slides) == presentation["slide_count"] and len(slides) <= 256
            for index, slide in enumerate(slides if valid else (), 1):
                if (
                    not isinstance(slide, Mapping)
                    or set(slide)
                    != {"slide", "status", "citations_required", "citations", "rationale"}
                    or slide["slide"] != index
                    or type(slide["slide"]) is not int
                    or slide["status"] != "passed"
                    or type(slide["citations_required"]) is not bool
                    or not isinstance(slide["citations"], list)
                    or len(slide["citations"]) > 256
                    or any(
                        not isinstance(value, str) or not value.strip() or len(value) > 4000
                        for value in slide["citations"]
                    )
                    or not isinstance(slide["rationale"], str)
                    or not slide["rationale"].strip()
                    or len(slide["rationale"]) > 4000
                ):
                    valid = False
                elif slide["citations_required"] and not slide["citations"]:
                    valid = False
            if not valid:
                problems.append("presentation-per-slide-citations")
    rows = review.get("checks", [])
    by_id = {}
    known = {item["id"] for item in coverage["items"]} | {
        "misco-editorial-qa",
        "final-pdf-all-pages",
        "final-pdf-toc",
        "final-pdf-footnotes",
        "final-pdf-parity",
        "final-pdf-cover",
    }
    for row in rows:
        id_ = row.get("check_id")
        if id_ not in known or id_ in by_id:
            problems.append("unknown-or-duplicate-check:" + str(id_))
        by_id[id_] = row
        if not str(row.get("rationale", "")).strip():
            problems.append("missing-review-rationale:" + str(id_))
    applicability = []
    for item in coverage["items"]:
        applicable = item["force"] != "example" and bool(flags[item["when"]])
        row = by_id.get(item["id"])
        if applicable and (row is None or row.get("status") != "passed"):
            # should deviation is an evaluated warning with a rationale, not a
            # hard page-count prohibition or a fabricated conformance PASS.
            if not (
                item["force"] == "should"
                and row
                and row.get("status") == "warning"
                and row.get("rationale")
            ):
                problems.append("required-check:" + item["id"])
        elif not applicable and row and row.get("status") not in {"not_applicable", "passed"}:
            problems.append("invalid-inapplicable-check:" + item["id"])
        applicability.append(
            {
                "check_id": item["id"],
                "applicable": applicable,
                "force": item["force"],
                "when": item["when"],
                "review": row,
            }
        )
    for id_ in [
        "misco-editorial-qa",
        "final-pdf-all-pages",
        "final-pdf-toc",
        "final-pdf-footnotes",
        "final-pdf-parity",
        "final-pdf-cover",
    ]:
        if by_id.get(id_, {}).get("status") != "passed":
            problems.append("required-check:" + id_)
    body = page_ranges.get("body") if isinstance(page_ranges, Mapping) else None
    if (
        isinstance(body, list)
        and len(body) == 2
        and all(type(n) is int for n in body)
        and body[0] <= body[1]
    ):
        if (
            not 50 <= body[1] - body[0] + 1 <= 60
            and by_id.get("misco-body-length", {}).get("status") != "warning"
        ):
            problems.append("unrecorded-should-deviation:misco-body-length")
    pages = review.get("pages", [])
    if [row.get("page") for row in pages] != list(range(1, page_count + 1)) or any(
        row.get("status") != "passed" or not str(row.get("rationale", "")).strip() for row in pages
    ):
        problems.append("all-page-review-incomplete")
    return {
        "problems": sorted(set(problems)),
        "applicability": applicability,
        "review": dict(review),
    }
