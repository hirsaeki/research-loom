"""core.*.testing holds test doubles; production code must not import it (#497)."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_TREES = ("core", "plugins", "scripts")


def _imported_modules(path: Path) -> list[tuple[str, int]]:
    """Absolute module names imported by a file, with their lines."""
    module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    package = module.rpartition(".")[0] if path.name != "__init__.py" else module
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            found.append((target, node.lineno))
            found.extend((f"{target}.{alias.name}", node.lineno) for alias in node.names)
    return found


def production_imports_of_testing_doubles() -> list[str]:
    offenders = []
    for tree in PRODUCTION_TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            if path.name == "testing.py" and path.parent.parent == ROOT / "core":
                continue
            for target, line in _imported_modules(path):
                parts = target.split(".")
                if len(parts) >= 3 and parts[0] == "core" and parts[2] == "testing":
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line} {target}")
    return sorted(set(offenders))


class CoreTestingDoublesTests(unittest.TestCase):
    def test_production_code_does_not_import_core_testing_doubles(self):
        self.assertEqual([], production_imports_of_testing_doubles())


if __name__ == "__main__":
    unittest.main()
