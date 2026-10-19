"""docs/test-map.md matches the tests that import each production module (#507)."""

from __future__ import annotations

import unittest

from scripts import test_map


class TestMapTests(unittest.TestCase):
    def test_committed_map_is_current(self):
        committed = test_map.MAP.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(
            test_map.render(),
            committed,
            "run: uv run --frozen python scripts/test_map.py",
        )

    def test_unit_tests_live_under_tests_unit(self):
        stray = sorted(
            path.relative_to(test_map.ROOT).as_posix()
            for path in (test_map.ROOT / "tests" / "runtime").glob("test_unit_*.py")
        )
        self.assertEqual([], stray, "move unit tests to tests/unit/<package>/")


if __name__ == "__main__":
    unittest.main()
