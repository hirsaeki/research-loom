"""MISCO behavior lives only in plugins/local_application/misco (#495).

Generic code under ``core/`` and ``plugins/`` must not name MISCO in a string
literal, so it cannot branch on a MISCO Profile id, check id or label. It reaches
MISCO behavior through the Publication dialect, which only the composition root
maps to the ``misco.publication`` Profile.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.contracts.test_core_testing_doubles import _imported_modules

ROOT = Path(__file__).resolve().parents[2]
GENERIC_TREES = ("core", "plugins")
MISCO_LAYER = ROOT / "plugins" / "local_application" / "misco"
MISCO_PACKAGE = "plugins.local_application.misco"
# Composition-root modules that may import the MISCO layer to wire it in.
ROOT_IMPORTERS = {ROOT / "plugins" / "local_application" / "facade.py"}
# Literals that only record history and must keep their exact bytes.
FROZEN_LITERALS = {
    (
        "plugins/local_application/publication/publication_release_support.py",
        # The renderer tool digest pins existing builds; changing it would re-key them.
        b"research-loom.deterministic-docx@0.3.0;misco-formal-sections;exact-pdf-review;provenance-v2",
    ),
}


def _generic_files() -> list[Path]:
    return [
        path
        for tree in GENERIC_TREES
        for path in sorted((ROOT / tree).rglob("*.py"))
        if MISCO_LAYER not in path.parents
    ]


def _misco_literals_in(source: str, where: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
            continue
        value = node.value
        text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        if "misco" in text.lower() and (where, node.value) not in FROZEN_LITERALS:
            found.append(f"{where}:{node.lineno} {text[:60]!r}")
    return found


def misco_literals() -> list[str]:
    return [
        found
        for path in _generic_files()
        for found in _misco_literals_in(
            path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix()
        )
    ]


def misco_layer_imports() -> list[str]:
    found = []
    for path in _generic_files():
        if path in ROOT_IMPORTERS:
            continue
        for target, line in _imported_modules(path):
            if target == MISCO_PACKAGE or target.startswith(MISCO_PACKAGE + "."):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{line} -> {target}")
    return found


class MiscoIsolationTests(unittest.TestCase):
    def test_generic_code_names_no_misco_literal(self):
        self.assertEqual([], misco_literals(), "move MISCO values into the misco/ dialect")

    def test_only_the_composition_root_imports_the_misco_layer(self):
        self.assertEqual([], misco_layer_imports(), "reach MISCO behavior through the dialect")

    def test_frozen_literals_are_still_needed(self):
        for where, literal in FROZEN_LITERALS:
            with self.subTest(path=where):
                tree = ast.parse((ROOT / where).read_text(encoding="utf-8"))
                values = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
                self.assertIn(literal, values, "remove the stale FROZEN_LITERALS entry")

    def test_guard_detects_ids_and_labels_but_not_frozen_literals(self):
        source = 'def f(p):\n    return p["profile_id"] == "misco.publication" or "MISCO-QA"\n'
        self.assertEqual(2, len(_misco_literals_in(source, "probe.py")))
        where, literal = next(iter(FROZEN_LITERALS))
        self.assertEqual([], _misco_literals_in(f"X = {literal!r}\n", where))


if __name__ == "__main__":
    unittest.main()
