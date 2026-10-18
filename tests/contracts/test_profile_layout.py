"""Production Profiles share one layout and declare their duplicate resources (#498).

Every production manifest lives at ``profiles/<profile_type>/<name>/<version>/profile.json``.
Versions do not share resource files: a manifest pins its resources by path relative
to itself, and rewriting that path to share a file would change the manifest digest of
an already pinned id/version. Byte-identical copies are therefore allowed, but each
must be listed in ``KNOWN_DUPLICATES`` so a new copy is a visible decision.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "profiles"
# Synthetic contract material, not production Profiles.
NON_PROFILE_TREES = ("contracts", "fixtures")
KNOWN_DUPLICATES = {
    # misco.publication 1.4.0 kept the 1.3.0 rules, sources and URL policy unchanged.
    frozenset(
        {
            "publication/misco/1.3.0/resources/publication-clean-rules.json",
            "publication/misco/1.4.0/resources/publication-clean-rules.json",
        }
    ),
    frozenset(
        {
            "publication/misco/1.3.0/resources/publication-clean-source-documents.json",
            "publication/misco/1.4.0/resources/publication-clean-source-documents.json",
        }
    ),
    frozenset(
        {
            "publication/misco/1.3.0/resources/publication-url-display.json",
            "publication/misco/1.4.0/resources/publication-url-display.json",
        }
    ),
}


def production_manifests() -> list[Path]:
    return sorted(
        path
        for path in PROFILES.rglob("profile.json")
        if path.relative_to(PROFILES).parts[0] not in NON_PROFILE_TREES
    )


def layout_errors(manifests: list[Path]) -> list[str]:
    errors = []
    for path in manifests:
        where = path.relative_to(PROFILES).as_posix()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        parts = path.relative_to(PROFILES).parts
        expected = (str(manifest["profile_type"]), str(manifest["profile_version"]))
        if len(parts) != 4 or (parts[0], parts[2]) != expected:
            errors.append(f"{where}: expected {expected[0]}/<name>/{expected[1]}/profile.json")
    return errors


def duplicate_groups(manifests: list[Path]) -> set[frozenset[str]]:
    by_digest: dict[str, set[str]] = defaultdict(set)
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for resource in manifest.get("resources", []):
            file = path.parent / resource["path"]
            digest = hashlib.sha256(file.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            by_digest[digest].add(file.relative_to(PROFILES).as_posix())
    return {frozenset(paths) for paths in by_digest.values() if len(paths) > 1}


class ProfileLayoutTests(unittest.TestCase):
    def test_manifests_use_the_category_name_version_layout(self):
        manifests = production_manifests()
        self.assertTrue(manifests)
        self.assertEqual([], layout_errors(manifests))

    def test_byte_identical_resources_are_declared(self):
        self.assertEqual(
            KNOWN_DUPLICATES,
            duplicate_groups(production_manifests()),
            "list an intended copy in KNOWN_DUPLICATES, or remove a stale entry",
        )

    def test_readme_lists_every_production_version(self):
        readme = (PROFILES / "README.md").read_text(encoding="utf-8")
        for path in production_manifests():
            where = path.relative_to(PROFILES).as_posix()
            with self.subTest(manifest=where):
                self.assertIn(f"`{where}`", readme)


if __name__ == "__main__":
    unittest.main()
