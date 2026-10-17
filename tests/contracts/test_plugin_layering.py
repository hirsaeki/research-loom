"""Guards for the dependency direction between plugin packages (#490).

Each top-level entry under ``plugins/`` (a package or a single module) is one
unit. Every import is counted, including imports inside functions, relative
imports and ``from plugins import x``.
"""

from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = ROOT / "plugins"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _unit(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "plugins" else None


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _imports(path: Path) -> list[tuple[str, list[str], int]]:
    """Return (absolute target module, imported names, line) for each import."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            names = [alias.name for alias in node.names]
            if target == "plugins":
                found.extend((f"plugins.{name}", [], node.lineno) for name in names)
            else:
                found.append((target, names, node.lineno))
        elif isinstance(node, ast.Import):
            found.extend((alias.name, [], node.lineno) for alias in node.names)
    return found


def plugin_edges() -> dict[str, dict[str, list[str]]]:
    """Map unit -> imported unit -> ["path:line", ...] for cross-unit imports."""
    edges: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path in sorted(PLUGINS.rglob("*.py")):
        source = _unit(_module_name(path))
        for target, _names, line in _imports(path):
            dest = _unit(target)
            if source and dest and dest != source:
                edges[source][dest].append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    return edges


def cycles(edges: dict[str, dict[str, list[str]]]) -> list[list[str]]:
    """Strongly connected components with more than one unit (Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for succ in edges.get(node, {}):
            if succ not in index:
                visit(succ)
                low[node] = min(low[node], low[succ])
            elif succ in on_stack:
                low[node] = min(low[node], index[succ])
        if low[node] == index[node]:
            component = []
            while True:
                item = stack.pop()
                on_stack.discard(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    nodes = set(edges) | {dest for targets in edges.values() for dest in targets}
    for node in sorted(nodes):
        if node not in index:
            visit(node)
    return found


class PluginLayeringTests(unittest.TestCase):
    def test_plugin_units_have_no_import_cycles(self):
        edges = plugin_edges()
        details = [
            f"{' <-> '.join(component)}: "
            + "; ".join(
                f"{a} -> {b} at {edges[a][b][0]}"
                for a in component
                for b in component
                if b in edges.get(a, {})
            )
            for component in cycles(edges)
        ]
        self.assertEqual([], details, "plugin packages must not import each other in a cycle")

    def test_no_private_names_imported_across_plugin_units(self):
        offenders = []
        for path in sorted(PLUGINS.rglob("*.py")):
            source = _unit(_module_name(path))
            for target, names, line in _imports(path):
                dest = _unit(target)
                if not dest or dest == source:
                    continue
                # Private submodules count too, whether named in the module path
                # (`import plugins.x._m`, `from plugins.x._m import y`) or as an
                # imported name. The unit name itself (e.g. `_infra`) is public.
                private = [target] if any(map(_is_private, target.split(".")[2:])) else []
                private += [f"{target}.{name}" for name in names if _is_private(name)]
                offenders.extend(
                    f"{path.relative_to(ROOT).as_posix()}:{line} {item}" for item in private
                )
        self.assertEqual([], offenders, "import a public name or move the helper to a shared layer")

    def test_infra_imports_no_other_plugin(self):
        self.assertEqual({}, {k: dict(v) for k, v in plugin_edges().get("_infra", {}).items()})

    def test_guard_detects_a_cycle(self):
        edges = {"a": {"b": ["x:1"]}, "b": {"c": ["y:1"]}, "c": {"a": ["z:1"]}, "d": {"a": ["w:1"]}}
        self.assertEqual([["a", "b", "c"]], cycles(edges))


if __name__ == "__main__":
    unittest.main()
