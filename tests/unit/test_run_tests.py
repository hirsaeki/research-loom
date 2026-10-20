"""Full local test selection and parallel result aggregation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_tests

CI_WINDOWS = True


class RunTestsTests(unittest.TestCase):
    def test_plan_matches_full_discovery_without_duplicates(self):
        plan = run_tests.build_plan(4)
        self.assertEqual(plan["test_count"], plan["unique_test_count"])
        self.assertEqual(plan["test_count"], sum(plan["counts"].values()))
        self.assertEqual(5, len(plan["groups"]))

    def test_incomplete_selection_is_rejected_before_execution(self):
        with patch.object(run_tests.partitioner, "lane_modules", return_value=[]):
            with self.assertRaisesRegex(ValueError, "differs from full discovery"):
                run_tests.build_plan(4)

    def test_all_worker_results_and_logs_are_kept_when_one_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, assertion in (("passing", "True"), ("failing", "False")):
                (root / f"{name}.py").write_text(
                    "import unittest\nclass Example(unittest.TestCase):\n"
                    f"    def test_example(self): self.assertTrue({assertion})\n",
                    encoding="utf-8",
                )
            plan = {
                "test_count": 2,
                "groups": {"first": ["passing"], "second": ["failing"]},
                "counts": {"first": 1, "second": 1},
            }
            output = root / "logs"
            result = run_tests.run_plan(plan, output, 2, root)
            self.assertFalse(result["successful"])
            self.assertEqual([0, 1], [item["exit_code"] for item in result["results"]])
            self.assertIn("OK", (output / "first.log").read_text(encoding="utf-8"))
            self.assertIn("FAILED", (output / "second.log").read_text(encoding="utf-8"))
            self.assertEqual(result, json.loads((output / "summary.json").read_text()))
            self.assertEqual(plan, json.loads((output / "selection.json").read_text()))
            with self.assertRaises(FileExistsError):
                run_tests.run_plan(plan, output, 2, root)

    def test_success_requires_all_workers_to_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "passing.py").write_text(
                "import unittest\nclass Example(unittest.TestCase):\n"
                "    def test_example(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            plan = {"test_count": 1, "groups": {"only": ["passing"]}, "counts": {"only": 1}}
            self.assertTrue(run_tests.run_plan(plan, root / "logs", 1, root)["successful"])


if __name__ == "__main__":
    unittest.main()
