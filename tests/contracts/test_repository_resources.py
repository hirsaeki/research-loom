"""Repository resources are located through core.resources only (#496)."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from core.resources import REPOSITORY_ROOT, resource_path

ROOT = Path(__file__).resolve().parents[2]
CODE_TREES = ("core", "plugins")
LOCATOR = ROOT / "core" / "resources.py"


def _python_files() -> list[Path]:
    return [path for tree in CODE_TREES for path in sorted((ROOT / tree).rglob("*.py"))]


def _is_file_parents(node: ast.AST) -> bool:
    """`Path(__file__)...parents[...]`, the pattern that derives the repository root."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and "__file__" in ast.unparse(node.value)
    )


def _resource_literals(tree: ast.AST) -> list[tuple[str, int]]:
    return [
        (node.args[0].value, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "resource_path"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]


class RepositoryResourceTests(unittest.TestCase):
    def test_only_the_locator_derives_the_repository_root(self):
        offenders = [
            f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
            for path in _python_files()
            if path != LOCATOR
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if _is_file_parents(node)
        ]
        self.assertEqual([], offenders, "use core.resources.resource_path")

    def test_every_named_resource_exists(self):
        missing = [
            f"{path.relative_to(ROOT).as_posix()}:{line} {relative}"
            for path in _python_files()
            for relative, line in _resource_literals(ast.parse(path.read_text(encoding="utf-8")))
            if not resource_path(relative).exists()
        ]
        self.assertEqual([], missing)

    def test_locator_resolves_inside_the_repository(self):
        self.assertEqual(REPOSITORY_ROOT, ROOT)
        self.assertEqual(resource_path("core/README.md"), ROOT / "core" / "README.md")
        for bad in ("/etc/passwd", "../outside", "", "core/../.."):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resource_path(bad)


if __name__ == "__main__":
    unittest.main()
