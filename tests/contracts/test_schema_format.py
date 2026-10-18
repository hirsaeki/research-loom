"""Every JSON Schema keeps one reviewable format (#502).

The canonical form is ``json.dumps(schema, indent=2, ensure_ascii=False)``
plus a trailing newline, with keys in their written order. Rewrite a schema
with ``python -m tests.contracts.test_schema_format --write``.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_TREES = ("core", "profiles", "projects")
# Schemas whose exact bytes are a recorded digest, so they keep their historical format.
FROZEN = {
    # file_digest() of this schema feeds the Survey Virtual Runner runner_digest, which
    # prior runs are matched on; reformatting it would break their lineage.
    "core/packages/survey/survey-response.schema.json",
}


def schema_paths() -> list[Path]:
    return sorted(path for tree in SCHEMA_TREES for path in (ROOT / tree).rglob("*.schema.json"))


def canonical(text: str) -> str:
    return json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"


def unformatted() -> list[str]:
    found = []
    for path in schema_paths():
        where = path.relative_to(ROOT).as_posix()
        # A Windows checkout may turn LF into CRLF; the format is about content, not EOLs.
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if where not in FROZEN and text != canonical(text):
            found.append(where)
    return found


class SchemaFormatTests(unittest.TestCase):
    def test_schemas_use_the_canonical_format(self):
        self.assertEqual(
            [], unformatted(), "run: python -m tests.contracts.test_schema_format --write"
        )

    def test_frozen_schemas_still_exist(self):
        for where in FROZEN:
            with self.subTest(path=where):
                self.assertTrue((ROOT / where).is_file(), "remove the stale FROZEN entry")

    def test_canonical_form_keeps_key_order_and_non_ascii(self):
        self.assertEqual('{\n  "b": 1,\n  "a": "表"\n}\n', canonical('{"b":1,"a":"表"}'))


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        for name in unformatted():
            path = ROOT / name
            path.write_text(
                canonical(path.read_bytes().decode("utf-8")), encoding="utf-8", newline="\n"
            )
            print("formatted", name)
    else:
        unittest.main()
