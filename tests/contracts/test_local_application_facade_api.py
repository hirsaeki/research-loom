"""Public API snapshot of LocalApplicationFacade (#491).

The facade is being moved from a ~30-level inheritance chain to composition.
This snapshot is the compatibility gate: every public name keeps its kind and
signature. After an intentional API change, regenerate it with

    uv run --frozen python -m tests.contracts.test_local_application_facade_api --update
"""

from __future__ import annotations

import inspect
import json
import sys
import unittest
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).with_name("local_application_facade_api.json")


def facade_api() -> list[dict[str, Any]]:
    from plugins.local_application import LocalApplicationFacade

    entries = []
    for name in sorted(dir(LocalApplicationFacade)):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(LocalApplicationFacade, name)
        if isinstance(raw, property):
            entries.append({"name": name, "kind": "property"})
            continue
        if isinstance(raw, classmethod):
            kind = "classmethod"
        elif isinstance(raw, staticmethod):
            kind = "staticmethod"
        elif callable(raw):
            kind = "method"
        else:
            entries.append({"name": name, "kind": "attribute"})
            continue
        signature = str(inspect.signature(getattr(LocalApplicationFacade, name)))
        entries.append({"name": name, "kind": kind, "signature": signature})
    return entries


class LocalApplicationFacadeApiTests(unittest.TestCase):
    def test_public_api_matches_snapshot(self):
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        actual = facade_api()
        expected_by_name = {entry["name"]: entry for entry in expected}
        actual_by_name = {entry["name"]: entry for entry in actual}
        self.assertEqual(
            sorted(expected_by_name.keys() - actual_by_name.keys()), [], "public names removed"
        )
        self.assertEqual(
            sorted(actual_by_name.keys() - expected_by_name.keys()), [], "public names added"
        )
        changed = [
            name
            for name in sorted(expected_by_name)
            if expected_by_name[name] != actual_by_name.get(name)
        ]
        self.assertEqual([], changed, "public kind or signature changed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        SNAPSHOT.write_text(json.dumps(facade_api(), indent=2) + "\n", encoding="utf-8")
    else:
        unittest.main()
