"""Dependency direction between the local application subpackages (#493).

``plugins/local_application`` is split into feature subpackages, listed in
``LAYERS`` from the bottom up. A subpackage imports only itself and the
subpackages below it, never a module left directly in ``local_application``
(the composition root: CLI, facade and facade composition), and never another
subpackage's private names, not even inside a function. Only the composition
root (``ROOT_MODULES``) stays directly in ``local_application``.

A service that needs one of the partial facades defined in the composition root
gets it from the root as a ``_*_facade_class`` attribute rather than importing
the root (#591).
"""

from __future__ import annotations

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

# Modules left directly in local_application: the composition root and nothing else.
ROOT_MODULES = {"__init__", "__main__", "cli", "facade", "facade_composition"}


def _subpackage(module: str) -> str | None:
    """Subpackage of a module inside local_application, "" for a root module, None outside."""
    if module != PACKAGE and not module.startswith(PACKAGE + "."):
        return None
    rest = module[len(PACKAGE) + 1 :].split(".") if module != PACKAGE else []
    return rest[0] if rest and (PACKAGE_DIR / rest[0] / "__init__.py").is_file() else ""


def _violations(source: str, where: str, imports) -> list[str]:
    found = []
    for target, names, line in imports:
        dest = _subpackage(target)
        if dest is None or dest == source:
            continue
        if dest == "" or LAYERS.index(dest) > LAYERS.index(source):
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
            found += _violations(source, path.relative_to(ROOT).as_posix(), _imports(path))
    return found


class LocalApplicationLayeringTests(unittest.TestCase):
    def test_every_subpackage_is_a_declared_layer(self):
        subpackages = {path.parent.name for path in PACKAGE_DIR.glob("*/__init__.py")}
        self.assertEqual(set(), subpackages - set(LAYERS))

    def test_subpackages_import_only_lower_layers(self):
        self.assertEqual([], layering_violations(), "move the shared helper down a layer")

    def test_root_holds_only_the_composition_root(self):
        flat = {path.stem for path in PACKAGE_DIR.glob("*.py")}
        self.assertEqual(ROOT_MODULES, flat, "move feature modules into a subpackage")

    def test_composition_root_supplies_the_partial_facades(self):
        from plugins.local_application import facade_composition as composition

        expected = {
            "_continuation_facade_class": composition.ContinuationFacade,
            "_survey_analysis_facade_class": composition.SurveyAnalysisFacade,
            "_survey_response_facade_class": composition.SurveyResponseFacade,
        }
        for facade in composition._COMPOSED:
            for name, partial in expected.items():
                with self.subTest(facade=facade.__name__, attribute=name):
                    self.assertIs(partial, getattr(facade, name))

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
