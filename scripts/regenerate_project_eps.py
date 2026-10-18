#!/usr/bin/env python3
"""Regenerate the checked-in MISCO Effective Profile Set (#503).

``projects/misco-ai-2026/effective-profile-set.json`` is a deterministic
projection of the Project Config through the production resolver. It stays in
the repository because ``research-loom init`` consumes it; this script rebuilds
it, and ``--check`` fails when the committed bytes differ from a fresh build.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.local_application.workspace.profile_resolution import (  # noqa: E402
    resolve_effective_profile_set,
)

PROJECT_CONFIG = ROOT / "projects/misco-ai-2026/project-config.json"
PROJECT_EPS = ROOT / "projects/misco-ai-2026/effective-profile-set.json"
PROFILE_MANIFESTS = (
    ROOT / "profiles/narrative/misco/1.1.0/profile.json",
    ROOT / "profiles/publication/misco/1.3.0/profile.json",
)


def build() -> bytes:
    """Exact bytes of a fresh resolution of the Project Config."""
    config = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
    eps = resolve_effective_profile_set(config, list(PROFILE_MANIFESTS))
    return (json.dumps(eps, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def committed() -> bytes:
    # A Windows checkout may turn LF into CRLF; compare content, not EOLs.
    return PROJECT_EPS.read_bytes().replace(b"\r\n", b"\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args(argv)
    fresh = build()
    where = PROJECT_EPS.relative_to(ROOT).as_posix()
    if args.check:
        if committed() != fresh:
            print(
                f"{where} is stale; run: uv run --frozen python scripts/regenerate_project_eps.py"
            )
            return 1
        print(f"{where} is current")
        return 0
    PROJECT_EPS.write_bytes(fresh)
    print("wrote", where)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
