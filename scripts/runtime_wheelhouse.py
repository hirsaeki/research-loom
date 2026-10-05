#!/usr/bin/env python3
"""Create, verify, and install the exact offline Research Loom runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

SCHEMA = "research-loom-runtime-wheelhouse/v1"
TARGET = {"os": "linux", "arch": "x86_64", "python": "3.12"}


class WheelhouseError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "byte_length": path.stat().st_size,
        "sha256": sha256(path),
    }


def git_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise WheelhouseError(f"{label} is missing: {path}")


def create_manifest(repo: Path, bundle: Path) -> dict[str, object]:
    repo, bundle = repo.resolve(), bundle.resolve()
    requirements, wheels_dir = bundle / "requirements.txt", bundle / "wheels"
    require_file(repo / "pyproject.toml", "pyproject.toml")
    require_file(repo / "uv.lock", "uv.lock")
    require_file(requirements, "requirements.txt")
    if not wheels_dir.is_dir():
        raise WheelhouseError(f"wheel directory is missing: {wheels_dir}")
    wheels = sorted(path for path in wheels_dir.iterdir() if path.is_file())
    if not wheels or any(path.suffix != ".whl" for path in wheels):
        raise WheelhouseError("wheel directory must contain wheels only")
    manifest: dict[str, object] = {
        "schema_version": SCHEMA,
        "repository_head": git_head(repo),
        "target": TARGET,
        "repository_inputs": {
            "pyproject.toml": record(repo / "pyproject.toml", repo),
            "uv.lock": record(repo / "uv.lock", repo),
        },
        "requirements": record(requirements, bundle),
        "wheels": [record(path, bundle) for path in wheels],
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def load_manifest(bundle: Path) -> dict[str, object]:
    path = bundle / "manifest.json"
    require_file(path, "manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WheelhouseError(f"invalid manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise WheelhouseError("manifest must be a JSON object")
    return value


def verify_record(root: Path, value: object, label: str) -> str:
    if not isinstance(value, dict):
        raise WheelhouseError(f"{label} record is invalid")
    rel = value.get("path")
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise WheelhouseError(f"{label} path is invalid")
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise WheelhouseError(f"{label} path escapes its root") from exc
    require_file(path, label)
    if path.stat().st_size != value.get("byte_length") or sha256(path) != value.get("sha256"):
        raise WheelhouseError(f"{label} byte length mismatch or digest mismatch: {rel}")
    return rel


def verify_host() -> None:
    arch = platform.machine().lower()
    arch = "x86_64" if arch in {"x86_64", "amd64"} else arch
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.platform != "linux":
        raise WheelhouseError(f"wheelhouse requires Linux, current platform is {sys.platform}")
    if arch != TARGET["arch"] or python != TARGET["python"]:
        raise WheelhouseError(
            f"wheelhouse requires {TARGET['arch']} / Python {TARGET['python']}, current is {arch} / {python}"
        )


def verify_bundle(repo: Path, bundle: Path, *, check_host: bool = True) -> dict[str, object]:
    repo, bundle = repo.resolve(), bundle.resolve()
    manifest = load_manifest(bundle)
    if manifest.get("schema_version") != SCHEMA:
        raise WheelhouseError(f"unsupported wheelhouse schema: {manifest.get('schema_version')!r}")
    if manifest.get("target") != TARGET:
        raise WheelhouseError(f"unsupported wheelhouse target: {manifest.get('target')!r}")
    if check_host:
        verify_host()
    if manifest.get("repository_head") != git_head(repo):
        raise WheelhouseError("repository HEAD mismatch")

    inputs = manifest.get("repository_inputs")
    if not isinstance(inputs, dict):
        raise WheelhouseError("repository_inputs is missing")
    for name in ("pyproject.toml", "uv.lock"):
        verify_record(repo, inputs.get(name), f"repository input {name}")

    requirements = manifest.get("requirements")
    if verify_record(bundle, requirements, "requirements") != "requirements.txt":
        raise WheelhouseError("requirements path must be requirements.txt")

    wheels = manifest.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        raise WheelhouseError("wheel list is missing or empty")
    recorded = {verify_record(bundle, item, f"wheel[{index}]") for index, item in enumerate(wheels)}
    if len(recorded) != len(wheels) or any(not p.startswith("wheels/") or not p.endswith(".whl") for p in recorded):
        raise WheelhouseError("wheel records are invalid or duplicated")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in (bundle / "wheels").iterdir()
        if path.is_file()
    }
    if actual != recorded:
        raise WheelhouseError("wheel directory does not exactly match manifest")
    return manifest


def install_runtime(repo: Path, bundle: Path, target: Path) -> None:
    repo, bundle = repo.resolve(), bundle.resolve()
    target = (repo / target).resolve() if not target.is_absolute() else target.resolve()
    verify_bundle(repo, bundle)
    if target.exists():
        raise WheelhouseError(f"target already exists: {target}")
    staging = target.with_name(f"{target.name}.bootstrap")
    if staging.exists():
        shutil.rmtree(staging)
    env = os.environ.copy()
    env.update(PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(staging)], check=True)
        python = staging / "bin" / "python"
        subprocess.run(
            [
                str(python), "-m", "pip", "install", "--no-index", "--require-hashes",
                "--find-links", str(bundle / "wheels"), "-r", str(bundle / "requirements.txt"),
            ],
            check=True,
            env=env,
        )
        subprocess.run(
            [str(python), "-c", "import jsonschema, yaml, rfc3339_validator, rfc8785"],
            check=True,
            env=env,
        )
        os.replace(staging, target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create-manifest", "verify", "install"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path(".venv"))
    args = parser.parse_args(argv)
    try:
        if args.command == "create-manifest":
            create_manifest(args.repo, args.bundle)
        elif args.command == "verify":
            verify_bundle(args.repo, args.bundle)
        else:
            install_runtime(args.repo, args.bundle, args.target)
    except (WheelhouseError, OSError, subprocess.CalledProcessError) as exc:
        print(f"runtime wheelhouse error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
