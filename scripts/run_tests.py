#!/usr/bin/env python3
"""Run the complete unittest suite with CI's duration-balanced module shards."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Also support direct execution: python scripts/run_tests.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_test_shards as partitioner  # noqa: E402


def test_ids(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def collect(loader: unittest.TestLoader, suite: unittest.TestSuite) -> collections.Counter[str]:
    result = collections.Counter(test_ids(suite))
    if loader.errors:
        raise ValueError("Test collection failed:\n" + "\n".join(loader.errors))
    return result


def build_plan(jobs: int) -> dict:
    # "linux" means every runtime/unit module, even when running on Windows.
    # The Windows CI lane is only an opt-in subset and cannot replace full discovery.
    groups = {
        "contracts": [
            partitioner.module_name(path) for path in partitioner.test_modules(("tests/contracts",))
        ]
    }
    groups.update(
        {
            f"shard-{index}": modules
            for index, modules in enumerate(
                partitioner.shards(
                    partitioner.lane_modules("linux"), jobs, partitioner.load_durations()
                )
            )
            if modules
        }
    )
    loader = unittest.TestLoader()
    complete = collect(
        loader,
        loader.discover(
            str(partitioner.ROOT / "tests"),
            pattern="test_*.py",
            top_level_dir=str(partitioner.ROOT),
        ),
    )
    selected: collections.Counter[str] = collections.Counter()
    counts = {}
    for group, modules in groups.items():
        loader = unittest.TestLoader()
        cases = collect(loader, loader.loadTestsFromNames(modules))
        counts[group] = cases.total()
        selected.update(cases)
    if selected != complete:
        raise ValueError(
            f"Shard selection differs from full discovery: "
            f"missing={dict(complete - selected)}, extra={dict(selected - complete)}"
        )
    return {
        "test_count": complete.total(),
        "unique_test_count": len(complete),
        "test_ids_sha256": hashlib.sha256(
            json.dumps(sorted(complete.items())).encode("utf-8")
        ).hexdigest(),
        "groups": groups,
        "counts": counts,
    }


def run_plan(plan: dict, output: Path, jobs: int, root: Path) -> dict:
    # Refuse existing evidence directories rather than overwriting another run.
    output.mkdir(parents=True, exist_ok=False)
    (output / "selection.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    def run(group: str, modules: list[str]) -> dict:
        started = time.monotonic()
        log = output / f"{group}.log"
        print(f"START {group}: {plan['counts'][group]} tests; {log}", flush=True)
        with log.open("wb") as stream:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "-v", *modules],
                cwd=root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        record = {
            "group": group,
            "exit_code": result.returncode,
            "wall_seconds": round(time.monotonic() - started, 3),
            "log": str(log),
        }
        print(f"DONE {group}: exit {result.returncode}, {record['wall_seconds']}s", flush=True)
        return record

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run, group, modules) for group, modules in plan["groups"].items()]
        results = [future.result() for future in as_completed(futures)]
    summary = {
        "successful": all(result["exit_code"] == 0 for result in results),
        "test_count": plan["test_count"],
        "wall_seconds": round(time.monotonic() - started, 3),
        "results": sorted(results, key=lambda result: result["group"]),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4, help="parallel workers/shards (default: 4)")
    parser.add_argument("--output", type=Path, help="new directory for logs and JSON summaries")
    parser.add_argument(
        "--plan", action="store_true", help="verify and print selection without running"
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    plan = build_plan(args.jobs)
    if args.plan:
        print(json.dumps(plan, indent=2))
        return 0
    output = args.output
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="research-loom-tests-")) / "run"
    output = output.resolve()
    print(f"Verified full discovery: {plan['test_count']} tests; logs: {output}", flush=True)
    summary = run_plan(plan, output, args.jobs, partitioner.ROOT)
    print(json.dumps(summary, indent=2))
    return 0 if summary["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
