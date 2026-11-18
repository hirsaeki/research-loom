"""Optional bibliography selection without changing citation provenance (#619)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from plugins.application_errors import LocalApplicationError

TOKEN = re.compile(r"\[\[citation:([^\]]+)\]\]")


def review_digest(section, source, display, note, policy):
    """Bind manual review to exact text, citation registrations, source and layout scope."""
    payload = {
        "version": 1,
        "section": section,
        "source": source,
        "display": {k: v for k, v in display.items() if k != "review"},
        "note": note,
        "structure": policy.get("formal_report", {}).get("structure"),
        "formal_spec": policy.get("formal_spec_profile"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def select_references(inspection, dialect, label):
    """Return an auditable section/source plan; never mutate supplied inputs."""
    policy = inspection.get("publication_policy", {})
    config = policy.get("bibliography")
    if config is None:
        return []
    if not dialect.formal_report_requested(policy) or not dialect.supports_local_references:
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-INPUT-001",
            "Local bibliography selection requires a supported formal report dialect",
        )
    sections = inspection["revision"]["sections"]
    sources = {
        o["id"]: o
        for o in inspection["source_package_document"]["resolved_content"]["research_objects"]
        if o.get("kind") == "source"
    }
    displays = config.get("displays", [])
    ids = [d["display_id"] for d in displays]
    if len(ids) != len(set(ids)):
        raise LocalApplicationError("APPLICATION-PUBLICATION-INPUT-001", "Duplicate display_id")
    known = {s["section_id"]: s for s in sections}
    for display in displays:
        section = known.get(display["section_id"])
        if section is None or not any(
            c["source_ref"] == display["source_ref"]
            and c.get("locator_ref") == display.get("locator_ref")
            for c in section.get("citations", [])
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INPUT-001", "Display must bind a registered citation"
            )
    result = []
    notes = policy["formal_report"].get("footnotes", [])
    for section in sections:
        sid = section["section_id"]
        content = section["content"]
        tokens = Counter(TOKEN.findall(content))
        refs = list(dict.fromkeys(c["source_ref"] for c in section.get("citations", [])))
        for ref in refs:
            if ref not in sources:
                continue  # Existing unresolved-citation validation remains authoritative.
            source = sources[ref]
            citations = [c for c in section["citations"] if c["source_ref"] == ref]
            local = [d for d in displays if d["section_id"] == sid and d["source_ref"] == ref]
            evaluated = []
            covered = []
            # Every inline token renders the complete set of registered locators.
            locators = list(dict.fromkeys(c.get("locator_ref") for c in citations))
            if tokens[ref]:
                ok = all(dialect.local_reference_sufficient(source, loc, "") for loc in locators)
                evaluated.append({"kind": "inline_tokens", "count": tokens[ref], "sufficient": ok})
                if ok:
                    covered.extend(locators * tokens[ref])
            for display in local:
                marker = display["marker"]
                note = None
                if display["placement"] == "footnote":
                    matches = [n for n in notes if n["section_id"] == sid and n["marker"] == marker]
                    note = matches[0] if len(matches) == 1 else None
                    text = note["text"] if note else ""
                else:
                    text = marker
                # A marker is an exact occurrence anchor, never an approximate text search.
                unique = content.count(marker) == 1 and (
                    display["placement"] == "inline"
                    or sum(s["content"].count(marker) for s in sections) == 1
                )
                overlaps = any(
                    d["display_id"] != display["display_id"]
                    and d["section_id"] == sid
                    and (marker in d["marker"] or d["marker"] in marker)
                    for d in displays
                )
                digest = review_digest(section, source, display, note, policy)
                review = display.get("review", {})
                reviewed = (
                    review.get("content_digest") == digest and review.get("status") == "sufficient"
                )
                locator = display.get("locator_ref")
                structural = (
                    unique and not overlaps and bool(text.strip()) and not TOKEN.search(marker)
                )
                if display["placement"] == "footnote":
                    structural = structural and note is not None
                eligible = dialect.local_reference_sufficient(
                    source,
                    locator,
                    display.get("locator_exception", "") if reviewed else "",
                    reviewed=reviewed,
                )
                canonical = str(source.get("canonical_locator") or "")
                if canonical.startswith(("https://", "http://")) and canonical not in text:
                    eligible = False
                expected = label(source, locator, policy)
                generated = display["method"] == "generated" and text == expected and not review
                sufficient = structural and eligible and (generated or reviewed)
                reason = (
                    "complete_local_display"
                    if sufficient
                    else "invalid_anchor"
                    if not structural
                    else "incomplete_metadata_or_locator"
                    if not eligible
                    else "stale_review"
                    if review and review.get("content_digest") != digest
                    else "unconfirmed_display"
                )
                evaluated.append(
                    {
                        "display_id": display["display_id"],
                        "sufficient": sufficient,
                        "reason": reason,
                        "review_digest": digest,
                    }
                )
                if sufficient:
                    covered.append(locator)
            # All explicit occurrences must pass, including extra manual occurrences.
            sufficient = (
                bool(evaluated)
                and all(e["sufficient"] for e in evaluated)
                and not (Counter(c.get("locator_ref") for c in citations) - Counter(covered))
            )
            keep = ref in config.get("keep_sources", [])
            omitted = config["mode"] == "omit_complete_local" and sufficient and not keep
            result.append(
                {
                    "section_id": sid,
                    "source_ref": ref,
                    "sufficient": sufficient,
                    "omitted": omitted,
                    "reason": "explicit_keep"
                    if keep
                    else "complete_local"
                    if omitted
                    else "retained",
                    "displays": evaluated,
                }
            )
    # Report actual formal-section decisions, not merely eligible subsections.
    outline = dialect.formal_outline(
        policy["formal_report"]["structure"], [s["section_id"] for s in sections]
    )
    for row in result:
        entry = outline[row["section_id"]]
        scope = (entry["chapter"], entry["section"])
        peers = [
            other
            for other in result
            if other["source_ref"] == row["source_ref"]
            and (outline[other["section_id"]]["chapter"], outline[other["section_id"]]["section"])
            == scope
        ]
        if row["omitted"] and not all(p["sufficient"] for p in peers):
            row["omitted"] = False
            row["reason"] = "incomplete_scope"
    return result


def filter_references(refs, scope_ids, decisions):
    """A source is omitted only when every participating subsection permits it."""
    return [
        ref
        for ref in refs
        if not (
            (
                rows := [
                    r for r in decisions if r["source_ref"] == ref and r["section_id"] in scope_ids
                ]
            )
            and all(r["omitted"] for r in rows)
        )
    ]
