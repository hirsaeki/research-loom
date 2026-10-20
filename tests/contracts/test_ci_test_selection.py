"""Guards for CI test selection (scripts/ci_test_shards.py)."""

from __future__ import annotations

import importlib.util
import json
import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("ci_test_shards", ROOT / "scripts/ci_test_shards.py")
assert _SPEC is not None and _SPEC.loader is not None
shards_tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shards_tool)

# Source that branches on the platform. Such modules must say whether they
# belong in the Windows CI lane instead of silently running on Linux only.
PLATFORM_SIGNAL = re.compile(
    r"os\.name\s*[!=]=\s*[\"']nt[\"']|sys\.platform|platform\.system\(|\bmsvcrt\b|\bwin32api\b"
)


class CiTestSelectionTests(unittest.TestCase):
    def test_full_discovery_does_not_repeat_test_ids(self):
        def ids(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from ids(item)
                else:
                    yield item.id()

        loader = unittest.TestLoader()
        counts = Counter(ids(loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))))
        self.assertEqual([], loader.errors)
        self.assertEqual(
            {},
            {name: count for name, count in counts.items() if count > 1},
            "import supporting test modules, not their TestCase classes; "
            "unittest also collects imported classes, even with underscore aliases",
        )

    def test_platform_sensitive_modules_declare_windows_lane(self):
        undeclared = [
            shards_tool.module_name(path)
            for path in shards_tool.test_modules(shards_tool.WINDOWS_ROOTS)
            if PLATFORM_SIGNAL.search(path.read_text(encoding="utf-8"))
            and shards_tool.windows_marker(path) is None
        ]
        self.assertEqual(
            [],
            undeclared,
            "declare CI_WINDOWS = True (or False with a reason) in these modules",
        )

    def test_markers_are_literal_booleans(self):
        for path in shards_tool.test_modules(shards_tool.WINDOWS_ROOTS):
            with self.subTest(module=shards_tool.module_name(path)):
                shards_tool.windows_marker(path)  # raises on a non-literal value

    def test_shards_partition_each_lane(self):
        durations = shards_tool.load_durations()
        for platform, count in (("linux", 4), ("windows", 4)):
            with self.subTest(platform=platform):
                lane = shards_tool.lane_modules(platform)
                planned = shards_tool.shards(lane, count, durations)
                flat = [module for shard in planned for module in shard]
                self.assertEqual(sorted(lane), sorted(flat))
                self.assertEqual(len(flat), len(set(flat)))
                self.assertTrue(all(planned), "every shard must receive at least one module")

    def test_windows_lane_is_not_empty(self):
        self.assertGreater(len(shards_tool.lane_modules("windows")), 0)

    def test_recorded_durations_name_existing_lane_modules(self):
        if not shards_tool.DURATIONS.is_file():
            self.skipTest("no recorded durations")
        recorded = set(json.loads(shards_tool.DURATIONS.read_text(encoding="utf-8")))
        lanes = set(shards_tool.lane_modules("linux")) | set(shards_tool.lane_modules("windows"))
        self.assertEqual(set(), recorded - lanes, "stale entries in tests/ci_durations.json")


if __name__ == "__main__":
    unittest.main()
