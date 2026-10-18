"""Dependency direction between the local application subpackages (#493).

``plugins/local_application`` is split into feature subpackages, listed in
``LAYERS`` from the bottom up. A subpackage imports only itself and the
subpackages below it, never a module left directly in ``local_application``
(the composition root: CLI, facade and facade composition), and never another
subpackage's private names. Only the composition root (``ROOT_MODULES``) stays
directly in ``local_application``.

``ROOT_CALLBACKS`` lists the few places where a service builds one of the partial
facades defined in the composition root. Each is allowed only as an import made
inside a function, so the root still loads after the layer it imports.
"""

from __future__ import annotations

import ast
import unittest

from tests.contracts.test_plugin_layering import ROOT, _imports, _is_private, _module_name

PACKAGE = "plugins.local_application"
PACKAGE_DIR = ROOT / "plugins" / "local_application"
LAYERS = (
    "support",
    "workspace",
    "research_package",
    "writer",
    "publication",
    "research",
    "material",
    "survey",
    "virtual_runner",
    "misco",
)


COMPOSITION = f"{PACKAGE}.facade_composition"
ROOT_CALLBACKS = {
    (f"{PACKAGE}.material.new_material_continuation_service", COMPOSITION): (
        "continuation services submit actions through ContinuationFacade"
    ),
    (f"{PACKAGE}.survey.survey_analysis_actions", COMPOSITION): (
        "Survey analysis action handlers run through SurveyAnalysisFacade"
    ),
    (f"{PACKAGE}.survey.survey_response_facade", COMPOSITION): (
        "Survey response action handlers run through SurveyResponseFacade"
    ),
}
# Modules left directly in local_application: the composition root and nothing else.
ROOT_MODULES = {"__init__", "__main__", "cli", "facade", "facade_composition"}


def _lazy_import_lines(path) -> set[int]:
    """Lines of imports made inside a function rather than at module or class level."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.lineno
        for func in ast.walk(tree)
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(func)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }


def _subpackage(module: str) -> str | None:
    """Subpackage of a module inside local_application, "" for a root module, None outside."""
    if module != PACKAGE and not module.startswith(PACKAGE + "."):
        return None
    rest = module[len(PACKAGE) + 1 :].split(".") if module != PACKAGE else []
    return rest[0] if rest and (PACKAGE_DIR / rest[0] / "__init__.py").is_file() else ""


def _violations(
    source: str, where: str, imports, *, module: str = "", lazy_lines: frozenset[int] = frozenset()
) -> list[str]:
    found = []
    for target, names, line in imports:
        dest = _subpackage(target)
        if dest is None or dest == source:
            continue
        callback = (module, target) in ROOT_CALLBACKS and line in lazy_lines
        if (dest == "" and not callback) or (dest and LAYERS.index(dest) > LAYERS.index(source)):
            found.append(f"{where}:{line} {source} -> {target}")
        # A private submodule counts whether it is named in the module path
        # (`import ...support._m`, `from ...support._m import y`) or imported as a name.
        if any(map(_is_private, target.split(".")[3:])):
            found.append(f"{where}:{line} {source} -> {target} (private)")
        found.extend(
            f"{where}:{line} {source} -> {target}.{name} (private)"
            for name in names
            if _is_private(name)
        )
    return found


def layering_violations() -> list[str]:
    found = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        module = _module_name(path)
        source = _subpackage(module)
        if source:
            found += _violations(
                source,
                path.relative_to(ROOT).as_posix(),
                _imports(path),
                module=module,
                lazy_lines=frozenset(_lazy_import_lines(path)),
            )
    return found


def _module_path(module: str):
    return ROOT.joinpath(*module.split(".")).with_suffix(".py")


class LocalApplicationLayeringTests(unittest.TestCase):
    def test_every_subpackage_is_a_declared_layer(self):
        subpackages = {path.parent.name for path in PACKAGE_DIR.glob("*/__init__.py")}
        self.assertEqual(set(), subpackages - set(LAYERS))

    def test_subpackages_import_only_lower_layers(self):
        self.assertEqual([], layering_violations(), "move the shared helper down a layer")

    def test_root_holds_only_the_composition_root(self):
        flat = {path.stem for path in PACKAGE_DIR.glob("*.py")}
        self.assertEqual(ROOT_MODULES, flat, "move feature modules into a subpackage")

    def test_root_callbacks_are_lazy_and_still_needed(self):
        for module, target in ROOT_CALLBACKS:
            path = _module_path(module)
            with self.subTest(module=module):
                lazy = _lazy_import_lines(path)
                lines = [line for t, _n, line in _imports(path) if t == target]
                self.assertTrue(lines, "remove the stale ROOT_CALLBACKS entry")
                self.assertTrue(set(lines) <= lazy, "a root callback must be imported lazily")

    def test_guard_classifies_modules(self):
        self.assertEqual("support", _subpackage(f"{PACKAGE}.support.stages"))
        self.assertEqual("support", _subpackage(f"{PACKAGE}.support"))
        self.assertEqual("", _subpackage(f"{PACKAGE}.facade"))
        self.assertEqual("", _subpackage(f"{PACKAGE}.cli"))
        self.assertEqual("", _subpackage(PACKAGE))
        self.assertIsNone(_subpackage("plugins.application_errors"))

    def test_guard_detects_private_and_upward_imports(self):
        imports = [
            (f"{PACKAGE}.support._m", [], 1),
            (f"{PACKAGE}.support._m", ["x"], 2),
            (f"{PACKAGE}.support.stages", ["_hidden"], 3),
            (f"{PACKAGE}.support.stages", ["run_stages"], 4),
            (f"{PACKAGE}.facade", ["LocalApplicationFacadeCore"], 5),
        ]
        self.assertEqual(
            [
                f"w:1 workspace -> {PACKAGE}.support._m (private)",
                f"w:2 workspace -> {PACKAGE}.support._m (private)",
                f"w:3 workspace -> {PACKAGE}.support.stages._hidden (private)",
                f"w:5 workspace -> {PACKAGE}.facade",
            ],
            _violations("workspace", "w", imports),
        )


if __name__ == "__main__":
    unittest.main()
