"""Markdown links resolve, and every document is reachable from docs/index.md (#504).

Relative links in tracked Markdown files must point at an existing file, and a
``#fragment`` into a Markdown file must name one of its headings (GitHub anchor
rules). External URLs are not fetched. The legacy archive keeps its files byte for
byte, so its links are not checked.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs/index.md"
# Byte-identical legacy copies pinned by the migration ledger (#499); never edited.
FROZEN_TREES = ("docs/migration/misco-legacy-sources/",)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def markdown_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        names = [name for name in out.decode("utf-8").split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        names = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*.md")
            if not {".git", ".venv"}.intersection(path.relative_to(ROOT).parts)
        ]
    return [ROOT / name for name in sorted(names) if not name.startswith(FROZEN_TREES)]


def _prose(text: str) -> str:
    return INLINE_CODE.sub("", FENCE.sub("", text))


def links(path: Path) -> list[str]:
    return LINK.findall(_prose(path.read_text(encoding="utf-8")))


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    result = set()
    for heading in HEADING.findall(FENCE.sub("", path.read_text(encoding="utf-8"))):
        text = re.sub(r"`([^`]*)`", r"\1", heading)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def resolve(source: Path, target: str) -> tuple[Path | None, str]:
    """Local file a link points at (None for external) and its fragment."""
    if SCHEME.match(target):
        return None, ""
    location, _, fragment = target.partition("#")
    if not location:
        return source, fragment
    base = ROOT if location.startswith("/") else source.parent
    return (base / location.lstrip("/")).resolve(), fragment


def broken_links(files: list[Path]) -> list[str]:
    found = []
    for source in files:
        where = source.relative_to(ROOT).as_posix()
        for target in links(source):
            path, fragment = resolve(source, target)
            if path is None:
                continue
            if not path.exists():
                found.append(f"{where}: {target} (missing file)")
            elif fragment and path.suffix == ".md" and fragment.lower() not in anchors(path):
                found.append(f"{where}: {target} (missing heading)")
    return found


def reachable_from(start: Path) -> set[Path]:
    seen = {start}
    queue = [start]
    while queue:
        source = queue.pop()
        for target in links(source):
            path, _ = resolve(source, target)
            if path and path.suffix == ".md" and path.is_file() and path not in seen:
                seen.add(path)
                queue.append(path)
    return seen


class DocsLinkTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        self.assertEqual([], broken_links(markdown_files()))

    def test_every_document_is_reachable_from_the_index(self):
        reached = reachable_from(INDEX)
        missing = [
            path.relative_to(ROOT).as_posix()
            for path in markdown_files()
            if path.is_relative_to(ROOT / "docs") and path not in reached
        ]
        self.assertEqual([], missing, "link the document from docs/index.md")

    def test_guard_reports_missing_files_and_headings_only(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            probe = Path(temp) / "probe.md"
            probe.write_text(
                "# Probe `title`\n\n## Same name\n\n## Same name\n\n"
                "[ok](#probe-title) [dup](#same-name-1) [index](../docs/index.md#decisions)\n"
                "[web](https://example.com/x.md) `[code](nowhere.md)`\n\n"
                "```\n[fenced](nowhere.md)\n```\n\n"
                "[file](nowhere.md) [heading](#no-such-heading)\n",
                encoding="utf-8",
            )
            where = probe.relative_to(ROOT).as_posix()
            self.assertEqual(
                [
                    f"{where}: nowhere.md (missing file)",
                    f"{where}: #no-such-heading (missing heading)",
                ],
                broken_links([probe]),
            )


if __name__ == "__main__":
    unittest.main()
