#!/usr/bin/env python3
"""Select and balance CI test shards.

Test modules opt into the Windows CI lane with a module-level constant::

    CI_WINDOWS = True

Modules that branch on the platform must declare the constant explicitly
(``True`` or ``False``); ``tests/contracts/test_ci_test_selection.py``
enforces this so new Windows-sensitive tests cannot silently miss CI.

Shards are balanced by recorded per-module durations
(``tests/ci_durations.json``) using longest-processing-time-first packing.
Refresh the durations with ``measure`` after large test changes.
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = ROOT / "tests" / "ci_durations.json"
# The Linux lane runs every runtime module; contracts run in their own job.
LINUX_ROOTS = ("tests/runtime",)
WINDOWS_ROOTS = ("tests/runtime", "tests/contracts")
MARKER = "CI_WINDOWS"


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def test_modules(roots: tuple[str, ...]) -> list[Path]:
    return sorted(path for root in roots for path in (ROOT / root).glob("test_*.py"))


def windows_marker(path: Path) -> bool | None:
    """Return the module's CI_WINDOWS value, or None when it is not declared."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == MARKER for t in targets):
                value = node.value
                if not (isinstance(value, ast.Constant) and isinstance(value.value, bool)):
                    raise ValueError(f"{path}: {MARKER} must be a literal True or False")
                return value.value
    return None


def lane_modules(platform: str) -> list[str]:
    if platform == "linux":
        return [module_name(path) for path in test_modules(LINUX_ROOTS)]
    return [module_name(path) for path in test_modules(WINDOWS_ROOTS) if windows_marker(path)]


def load_durations() -> dict[str, float]:
    if not DURATIONS.is_file():
        return {}
    return {str(k): float(v) for k, v in json.loads(DURATIONS.read_text(encoding="utf-8")).items()}


def shards(modules: list[str], count: int, durations: dict[str, float]) -> list[list[str]]:
    """Longest-processing-time-first packing; unknown modules cost the median."""
    known = [durations[m] for m in modules if m in durations]
    default = statistics.median(known) if known else 1.0
    bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(count)]
    for module in sorted(modules, key=lambda m: (-durations.get(m, default), m)):
        index = min(range(count), key=lambda i: (bins[i][0], i))
        total, members = bins[index]
        bins[index] = (total + durations.get(module, default), [*members, module])
    return [sorted(members) for _, members in bins]


def measure(modules: list[str], jobs: int) -> dict[str, float]:
    def run(module: str) -> tuple[str, float]:
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-m", "unittest", module],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = round(time.monotonic() - started, 1)
        if result.returncode != 0:
            print(f"warning: {module} exited {result.returncode}", file=sys.stderr)
        return module, elapsed

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return dict(sorted(pool.map(run, modules)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select", help="print the dotted test modules for one shard")
    select.add_argument("--platform", choices=("linux", "windows"), required=True)
    select.add_argument("--shards", type=int, required=True)
    select.add_argument("--index", type=int, required=True)
    plan = sub.add_parser("plan", help="print every shard with its estimated duration")
    plan.add_argument("--platform", choices=("linux", "windows"), required=True)
    plan.add_argument("--shards", type=int, required=True)
    timing = sub.add_parser("measure", help="time every lane module and rewrite durations")
    timing.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)

    if args.command == "measure":
        modules = sorted(set(lane_modules("linux")) | set(lane_modules("windows")))
        durations = measure(modules, args.jobs)
        DURATIONS.write_text(json.dumps(durations, indent=2) + "\n", encoding="utf-8")
        print(f"recorded {len(durations)} modules in {DURATIONS.relative_to(ROOT)}")
        return 0

    if args.shards < 1:
        parser.error("--shards must be at least 1")
    durations = load_durations()
    planned = shards(lane_modules(args.platform), args.shards, durations)
    if args.command == "plan":
        for index, members in enumerate(planned):
            estimate = sum(durations.get(m, 0.0) for m in members)
            print(f"shard {index}: {len(members)} modules, ~{estimate:.0f}s")
        return 0
    if not 0 <= args.index < args.shards:
        parser.error("--index must be within [0, --shards)")
    print("\n".join(planned[args.index]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
