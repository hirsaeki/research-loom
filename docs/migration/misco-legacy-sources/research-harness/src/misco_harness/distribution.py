from __future__ import annotations

import json
import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from misco_harness.trace_store import TraceStore, TraceStoreError, atomic_write_json, sha256_file, sha256_tree


class DistributionError(RuntimeError):
    pass


CORE_MANIFEST_NAME = "harness.manifest.json"
PROFILE_MANIFEST_NAME = "profile.manifest.json"
LOCK_NAME = "harness.lock.json"

CORE_MANAGED_PATHS = (
    "src",
    "contracts",
    "pyproject.toml",
    "uv.lock",
    "WORK_RESEARCH_COORDINATOR.md",
)

PROFILE_TARGET_ROOTS = (
    "maps",
    "project_feedback",
    "publication/authority",
    "profile",
)

WORKSPACE_GITIGNORE = """# Harness runtime and generated caches
.rh/
.venv/
.pytest_cache/
.ruff_cache/
.testdeps/
__pycache__/
*.py[cod]

# Raw research intake is preserved by the Harness but not committed by default
intake/drop/*
!intake/drop/.gitkeep

# Local secrets and machine-specific files
.env
.env.*
.vscode/
.idea/
.DS_Store
Thumbs.db
"""


@dataclass(frozen=True)
class SourceMetadata:
    source_kind: str
    source_label: str
    locator: str | None
    ref: str | None
    commit: str | None
    archive_sha256: str | None
    tree_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind,
            "source_label": self.source_label,
            "locator": self.locator,
            "ref": self.ref,
            "commit": self.commit,
            "archive_sha256": self.archive_sha256,
            "tree_sha256": self.tree_sha256,
        }


@dataclass(frozen=True)
class ManagedFile:
    owner: str
    source: str
    target: str
    sha256: str
    role: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {
            "owner": self.owner,
            "source": self.source,
            "target": self.target,
            "sha256": self.sha256,
        }
        if self.role is not None:
            result["role"] = self.role
        return result


@dataclass(frozen=True)
class PreparedSource:
    root: Path
    metadata: SourceMetadata
    temporary_root: Path | None = None


def is_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@contextmanager
def materialize_source(
    source: str | Path,
    *,
    ref: str | None,
    manifest_name: str,
    require_clean: bool = False,
) -> Iterator[PreparedSource]:
    source_value = str(source)
    if is_url(source_value):
        with tempfile.TemporaryDirectory(prefix="rh-source-") as temporary:
            archive_name = Path(urllib.parse.urlparse(source_value).path).name or "source.archive"
            archive_path = Path(temporary) / archive_name
            _download_archive(source_value, archive_path)
            yield _prepare_archive(archive_path, ref=ref, manifest_name=manifest_name, locator=source_value, temporary_root=Path(temporary))
        return

    local = Path(source).resolve()
    if local.is_dir():
        yield _prepare_directory(local, ref=ref, require_clean=require_clean, manifest_name=manifest_name)
        return
    if not local.is_file():
        raise DistributionError(f"distribution source does not exist: {local}")
    with tempfile.TemporaryDirectory(prefix="rh-source-") as temporary:
        yield _prepare_archive(local, ref=ref, manifest_name=manifest_name, locator=None, temporary_root=Path(temporary))


def load_harness_manifest(root: Path) -> dict[str, object]:
    path = root / CORE_MANIFEST_NAME
    if not path.is_file():
        return {"schema_version": "1", "kind": "HARNESS", "managed_paths": list(CORE_MANAGED_PATHS)}
    value = _read_object(path, CORE_MANIFEST_NAME)
    if value.get("kind") != "HARNESS":
        raise DistributionError(f"{CORE_MANIFEST_NAME} must declare kind=HARNESS")
    managed_paths = value.get("managed_paths")
    if not isinstance(managed_paths, list) or not managed_paths or not all(isinstance(item, str) for item in managed_paths):
        raise DistributionError(f"{CORE_MANIFEST_NAME} managed_paths must be a non-empty string list")
    return value


def load_profile_manifest(root: Path) -> dict[str, object]:
    path = root / PROFILE_MANIFEST_NAME
    if not path.is_file():
        raise DistributionError(f"Profile source is missing {PROFILE_MANIFEST_NAME}: {root}")
    value = _read_object(path, PROFILE_MANIFEST_NAME)
    if value.get("kind") != "PROFILE":
        raise DistributionError(f"{PROFILE_MANIFEST_NAME} must declare kind=PROFILE")
    if not isinstance(value.get("profile_id"), str) or not value["profile_id"].strip():
        raise DistributionError("Profile manifest requires a non-empty profile_id")
    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        raise DistributionError("Profile manifest requires a non-empty entries list")
    return value


def collect_harness_files(source: PreparedSource) -> list[ManagedFile]:
    manifest = load_harness_manifest(source.root)
    result: list[ManagedFile] = []
    for raw_path in manifest["managed_paths"]:
        relative = _safe_relative_path(raw_path, "Harness managed path")
        path = source.root / relative
        if not path.exists():
            raise DistributionError(f"Harness managed path is missing: {relative}")
        if path.is_symlink():
            raise DistributionError(f"Harness managed path may not be a symlink: {relative}")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_symlink():
                    raise DistributionError(f"Harness managed path contains a symlink: {child.relative_to(source.root)}")
                if child.is_file():
                    child_relative = child.relative_to(source.root).as_posix()
                    result.append(ManagedFile("harness", child_relative, child_relative, sha256_file(child)))
        elif path.is_file():
            result.append(ManagedFile("harness", relative, relative, sha256_file(path)))
        else:
            raise DistributionError(f"Harness managed path is not a regular file or directory: {relative}")
    return _unique_targets(result)


def collect_profile_files(source: PreparedSource) -> tuple[str, list[ManagedFile]]:
    manifest = load_profile_manifest(source.root)
    profile_id = str(manifest["profile_id"])
    result: list[ManagedFile] = []
    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            raise DistributionError("Profile manifest entries must be objects")
        raw_source = entry.get("source")
        raw_target = entry.get("target", raw_source)
        if not isinstance(raw_source, str) or not isinstance(raw_target, str):
            raise DistributionError("Profile entry source and target must be strings")
        source_relative = _safe_relative_path(raw_source, "Profile source path")
        target_relative = _safe_relative_path(raw_target, "Profile target path")
        if not _is_profile_target(target_relative):
            raise DistributionError(f"Profile target is outside the allowed profile boundary: {target_relative}")
        role = entry.get("role")
        if role is not None and not isinstance(role, str):
            raise DistributionError("Profile entry role must be a string")
        path = source.root / source_relative
        if path.is_symlink():
            raise DistributionError(f"Profile entry may not be a symlink: {source_relative}")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_symlink():
                    raise DistributionError(f"Profile entry contains a symlink: {child.relative_to(source.root)}")
                if not child.is_file():
                    continue
                child_source = child.relative_to(source.root).as_posix()
                child_suffix = child.relative_to(path).as_posix()
                child_target = f"{target_relative.rstrip('/')}/{child_suffix}"
                if not _is_profile_target(child_target):
                    raise DistributionError(f"Profile target is outside the allowed profile boundary: {child_target}")
                result.append(ManagedFile("profile", child_source, child_target, sha256_file(child), role))
        elif path.is_file():
            result.append(ManagedFile("profile", source_relative, target_relative, sha256_file(path), role))
        else:
            raise DistributionError(f"Profile entry is not a regular file or directory: {source_relative}")
    return profile_id, _unique_targets(result)


def _is_profile_target(value: str) -> bool:
    return any(value == root or value.startswith(f"{root}/") for root in PROFILE_TARGET_ROOTS)


def copy_managed_files(source_root: Path, target_root: Path, files: list[ManagedFile]) -> None:
    for item in files:
        source = source_root / item.source
        target = target_root / item.target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def workspace_file_hashes(root: Path, files: list[ManagedFile]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in files:
        path = root / item.target
        if not path.is_file() or path.is_symlink():
            raise DistributionError(f"managed workspace file is missing or invalid: {item.target}")
        hashes[item.target] = sha256_file(path)
    return hashes


def make_lock(
    *,
    harness: SourceMetadata,
    harness_files: list[ManagedFile],
    profile: SourceMetadata | None,
    profile_id: str | None,
    profile_files: list[ManagedFile],
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "harness": harness.as_dict(),
        "profile": (
            None
            if profile is None
            else {"profile_id": profile_id, **profile.as_dict()}
        ),
        "managed_files": [item.as_dict() for item in [*harness_files, *profile_files]],
    }


def write_lock(root: Path, lock: dict[str, object]) -> Path:
    path = root / LOCK_NAME
    atomic_write_json(path, lock)
    return path


def read_lock(root: Path) -> dict[str, object]:
    path = root / LOCK_NAME
    if not path.is_file():
        raise DistributionError(f"workspace lock is missing: {path}")
    value = _read_object(path, LOCK_NAME)
    if value.get("schema_version") != "1":
        raise DistributionError(f"unsupported {LOCK_NAME} schema")
    files = value.get("managed_files")
    if not isinstance(files, list) or not files:
        raise DistributionError(f"{LOCK_NAME} managed_files is missing or empty")
    return value


def write_workspace_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    if path.exists():
        raise DistributionError(f"workspace .gitignore already exists: {path}")
    path.write_text(WORKSPACE_GITIGNORE, encoding="utf-8", newline="\n")
    (root / "intake" / "drop" / ".gitkeep").write_text("", encoding="utf-8", newline="\n")


def initialize_git(root: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(root), "init"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise DistributionError(f"git init failed: {detail}")


def _prepare_directory(
    root: Path,
    *,
    ref: str | None,
    require_clean: bool,
    manifest_name: str,
) -> PreparedSource:
    commit = _git_commit(root)
    if require_clean and commit is not None and _git_has_tracked_changes(root):
        raise DistributionError(f"distribution source checkout has tracked changes: {root}")
    if manifest_name == CORE_MANIFEST_NAME:
        manifest = load_harness_manifest(root)
        tree_hash = _managed_tree_sha256(root, [str(item) for item in manifest["managed_paths"]])
    else:
        try:
            tree_hash = sha256_tree(root)
        except TraceStoreError as error:
            raise DistributionError(f"Profile source contains an unsafe tree: {root}: {error}") from error
    metadata = SourceMetadata(
        source_kind="directory",
        source_label=root.name,
        locator=None,
        ref=ref,
        commit=commit,
        archive_sha256=None,
        tree_sha256=tree_hash,
    )
    return PreparedSource(root, metadata)


def _prepare_archive(
    archive: Path,
    *,
    ref: str | None,
    manifest_name: str,
    locator: str | None,
    temporary_root: Path,
) -> PreparedSource:
    extraction_root = temporary_root / "extracted"
    extraction_root.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        _safe_extract_zip(archive, extraction_root)
    elif tarfile.is_tarfile(archive):
        _safe_extract_tar(archive, extraction_root)
    else:
        raise DistributionError(f"unsupported distribution archive: {archive}")
    root = _find_archive_root(extraction_root, manifest_name)
    metadata = SourceMetadata(
        source_kind="archive",
        source_label=archive.name,
        locator=locator,
        ref=ref,
        commit=None,
        archive_sha256=sha256_file(archive),
        tree_sha256=sha256_tree(root),
    )
    return PreparedSource(root, metadata, temporary_root)


def _download_archive(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "misco-research-harness"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 256 * 1024 * 1024:
                    raise DistributionError("distribution archive exceeds the 256 MiB limit")
                output.write(chunk)
    except DistributionError:
        raise
    except Exception as error:  # noqa: BLE001 - source boundary converts transport failures.
        raise DistributionError(f"failed to download distribution archive: {url}: {error}") from error


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            relative = _safe_archive_member(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise DistributionError(f"distribution archive contains a symlink: {info.filename}")
            target = destination / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            relative = _safe_archive_member(member.name)
            if not (member.isdir() or member.isfile()):
                raise DistributionError(f"distribution archive contains an unsupported member: {member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = bundle.extractfile(member)
            if source is None:
                raise DistributionError(f"distribution archive member cannot be read: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _find_archive_root(extraction_root: Path, manifest_name: str) -> Path:
    if (extraction_root / manifest_name).is_file():
        return extraction_root
    children = [item for item in extraction_root.iterdir() if item.is_dir()]
    if len(children) == 1 and (children[0] / manifest_name).is_file():
        return children[0]
    raise DistributionError(f"archive does not contain {manifest_name} at its root")


def _managed_tree_sha256(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for raw_path in paths:
        relative = _safe_relative_path(raw_path, "Harness managed path")
        path = root / relative
        if path.is_symlink():
            raise DistributionError(f"managed source path may not be a symlink: {relative}")
        if path.is_dir():
            files.extend(child for child in path.rglob("*") if child.is_file())
        elif path.is_file():
            files.append(path)
        else:
            raise DistributionError(f"managed source path is missing: {relative}")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise DistributionError(f"managed source file may not be a symlink: {path.relative_to(root)}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _safe_archive_member(value: str) -> Path:
    normalized = value.replace("\\", "/")
    relative = Path(normalized)
    if relative.is_absolute() or ".." in relative.parts or not normalized.strip("/"):
        raise DistributionError(f"archive member escapes its extraction root: {value!r}")
    if any(part.lower() == ".git" for part in relative.parts):
        raise DistributionError(f"archive member may not contain .git: {value!r}")
    return relative


def _safe_relative_path(value: str, label: str) -> str:
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts or normalized.startswith("/"):
        raise DistributionError(f"{label} must be relative and confined: {value!r}")
    if any(part.lower() == ".git" for part in path.parts):
        raise DistributionError(f"{label} may not contain .git: {value!r}")
    return path.as_posix()


def _unique_targets(files: list[ManagedFile]) -> list[ManagedFile]:
    result: dict[str, ManagedFile] = {}
    for item in files:
        if item.target in result:
            raise DistributionError(f"duplicate managed target path: {item.target}")
        result[item.target] = item
    return [result[key] for key in sorted(result)]


def _read_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DistributionError(f"invalid {label}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise DistributionError(f"{label} must contain a JSON object")
    return value


def _git_commit(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _git_has_tracked_changes(root: Path) -> bool:
    for args in (("diff", "--quiet", "HEAD", "--"), ("diff", "--cached", "--quiet", "HEAD", "--")):
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode not in {0, 1}:
            raise DistributionError(f"could not inspect source checkout: {root}")
        if completed.returncode == 1:
            return True
    return False


def new_upgrade_id() -> str:
    return f"upgrade-{uuid.uuid4().hex[:12]}"


def upgrade_workspace(
    root: Path,
    *,
    harness_source: str | Path | None,
    harness_ref: str | None,
    profile_source: str | Path | None = None,
    profile_ref: str | None = None,
) -> dict[str, object]:
    root = root.resolve()
    lock = read_lock(root)
    blockers = _upgrade_blockers(root)
    if blockers:
        raise DistributionError("workspace is not at an upgrade boundary: " + "; ".join(blockers))

    old_files = _managed_files_from_lock(lock)
    _verify_current_managed_files(root, old_files)
    old_by_target = {item.target: item for item in old_files}
    old_harness_files = [item for item in old_files if item.owner == "harness"]
    old_profile_files = [item for item in old_files if item.owner == "profile"]

    if harness_source is None and profile_source is None:
        raise DistributionError("upgrade requires --harness-source or --profile-source")
    if harness_source is not None and not harness_ref:
        raise DistributionError("--harness-ref is required when --harness-source is supplied")
    harness_context = (
        materialize_source(harness_source, ref=harness_ref, manifest_name=CORE_MANIFEST_NAME, require_clean=True)
        if harness_source is not None
        else _existing_harness_source(root, lock)
    )
    with harness_context as harness:
        new_harness_files = collect_harness_files(harness)
        _require_same_targets(old_harness_files, new_harness_files, "Harness")
        new_profile_metadata = lock.get("profile")
        new_profile_id = None
        new_profile_files = old_profile_files
        if profile_source is not None:
            if profile_ref is None:
                raise DistributionError("--profile-ref is required when --profile-source is supplied")
            with materialize_source(profile_source, ref=profile_ref, manifest_name=PROFILE_MANIFEST_NAME, require_clean=True) as profile:
                new_profile_id, new_profile_files = collect_profile_files(profile)
                old_profile_id = _profile_id_from_lock(lock)
                if old_profile_id is not None and old_profile_id != new_profile_id:
                    raise DistributionError(
                        f"Profile identity change requires a new workspace: {old_profile_id} -> {new_profile_id}"
                    )
                if old_profile_id is not None:
                    _require_same_targets(old_profile_files, new_profile_files, "Profile")
                elif {item.target for item in new_harness_files} & {item.target for item in new_profile_files}:
                    raise DistributionError("Profile managed paths overlap Harness managed paths")
                new_profile_metadata = {"profile_id": new_profile_id, **profile.metadata.as_dict()}
                return _apply_upgrade(
                    root,
                    lock=lock,
                    old_files=old_files,
                    old_by_target=old_by_target,
                    harness=harness,
                    harness_files=new_harness_files,
                    profile=profile,
                    profile_files=new_profile_files,
                    profile_metadata=new_profile_metadata,
                    profile_id=new_profile_id,
                )
        profile_id = _profile_id_from_lock(lock)
        return _apply_upgrade(
            root,
            lock=lock,
            old_files=old_files,
            old_by_target=old_by_target,
            harness=harness,
            harness_files=new_harness_files,
            profile=None,
            profile_files=new_profile_files,
            profile_metadata=new_profile_metadata,
            profile_id=profile_id,
        )


@contextmanager
def _existing_harness_source(root: Path, lock: dict[str, object]) -> Iterator[PreparedSource]:
    raw = lock.get("harness")
    if not isinstance(raw, dict):
        raise DistributionError(f"{LOCK_NAME} harness record is invalid")
    yield PreparedSource(root, _source_metadata_from_dict(raw))


def _source_metadata_from_dict(raw: dict[str, object]) -> SourceMetadata:
    required = ("source_kind", "source_label", "tree_sha256")
    if not all(isinstance(raw.get(key), str) for key in required):
        raise DistributionError(f"{LOCK_NAME} source metadata is invalid")
    return SourceMetadata(
        source_kind=str(raw["source_kind"]),
        source_label=str(raw["source_label"]),
        locator=raw.get("locator") if isinstance(raw.get("locator"), str) else None,
        ref=raw.get("ref") if isinstance(raw.get("ref"), str) else None,
        commit=raw.get("commit") if isinstance(raw.get("commit"), str) else None,
        archive_sha256=raw.get("archive_sha256") if isinstance(raw.get("archive_sha256"), str) else None,
        tree_sha256=str(raw["tree_sha256"]),
    )


def _apply_upgrade(
    root: Path,
    *,
    lock: dict[str, object],
    old_files: list[ManagedFile],
    old_by_target: dict[str, ManagedFile],
    harness: PreparedSource,
    harness_files: list[ManagedFile],
    profile: PreparedSource | None,
    profile_files: list[ManagedFile],
    profile_metadata: dict[str, object] | None,
    profile_id: str | None,
) -> dict[str, object]:
    new_files = [*harness_files, *profile_files]
    stage = Path(tempfile.mkdtemp(prefix=".rh-upgrade-", dir=root.parent))
    runtime_backup = stage / "runtime-backup"
    files_backup = stage / "files-backup"
    new_root = stage / "new"
    old_lock = root / LOCK_NAME
    old_lock_backup = stage / "old-lock.json"
    shutil.copyfile(old_lock, old_lock_backup)
    if (root / ".rh").is_dir():
        shutil.copytree(root / ".rh", runtime_backup)
    try:
        for item in new_files:
            source_root = harness.root if item.owner == "harness" else (profile.root if profile is not None else root)
            source = source_root / (item.source if profile is not None or item.owner == "harness" else item.target)
            staged = new_root / item.target
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, staged)

        for item in old_files:
            backup = files_backup / item.target
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / item.target, backup)

        for item in new_files:
            _atomic_copyfile(new_root / item.target, root / item.target)

        contract_changed = any(
            item.owner == "harness"
            and item.target.startswith("contracts/")
            and old_by_target[item.target].sha256 != item.sha256
            for item in harness_files
        )
        if contract_changed:
            from misco_harness.orchestrator import DiscoveryOrchestrator

            DiscoveryOrchestrator(root).refresh_contract_registry()

        new_lock = make_lock(
            harness=harness.metadata,
            harness_files=harness_files,
            profile=(
                None
                if profile_metadata is None
                else SourceMetadata(
                    source_kind=str(profile_metadata["source_kind"]),
                    source_label=str(profile_metadata["source_label"]),
                    locator=profile_metadata.get("locator") if isinstance(profile_metadata.get("locator"), str) else None,
                    ref=profile_metadata.get("ref") if isinstance(profile_metadata.get("ref"), str) else None,
                    commit=profile_metadata.get("commit") if isinstance(profile_metadata.get("commit"), str) else None,
                    archive_sha256=profile_metadata.get("archive_sha256") if isinstance(profile_metadata.get("archive_sha256"), str) else None,
                    tree_sha256=str(profile_metadata["tree_sha256"]),
                )
            ),
            profile_id=profile_id,
            profile_files=profile_files,
        )
        write_lock(root, new_lock)
        upgrade_id = new_upgrade_id()
        receipt = {
            "upgrade_id": upgrade_id,
            "status": "COMPLETED",
            "prior_lock": lock,
            "new_lock": new_lock,
            "contract_registry_refreshed": contract_changed,
        }
        TraceStore(root / ".rh").write_immutable(Path("lifecycle") / "upgrades" / f"{upgrade_id}.json", receipt)
        return {
            "status": "UPGRADED",
            "upgrade_id": upgrade_id,
            "lock": str(root / LOCK_NAME),
            "contract_registry_refreshed": contract_changed,
        }
    except Exception:
        _restore_upgrade(root, old_files, files_backup, old_lock_backup, runtime_backup)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _restore_upgrade(root: Path, old_files: list[ManagedFile], files_backup: Path, old_lock_backup: Path, runtime_backup: Path) -> None:
    for item in old_files:
        backup = files_backup / item.target
        if backup.is_file():
            _atomic_copyfile(backup, root / item.target)
    if old_lock_backup.is_file():
        _atomic_copyfile(old_lock_backup, root / LOCK_NAME)
    runtime = root / ".rh"
    if runtime.exists():
        shutil.rmtree(runtime)
    if runtime_backup.is_dir():
        shutil.copytree(runtime_backup, runtime)


def _atomic_copyfile(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def _upgrade_blockers(root: Path) -> list[str]:
    state_path = root / ".rh" / "state" / "orchestrator" / "head.json"
    if not state_path.is_file():
        raise DistributionError(f"workspace is not initialized: {root}")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DistributionError(f"cannot read workspace state: {state_path}: {error}") from error
    blockers: list[str] = []
    if state.get("lifecycle_status") == "ARCHIVED":
        blockers.append("workspace is archived")
    if state.get("pending_work"):
        blockers.append("pending Work")
    if state.get("pending_decision_ids"):
        blockers.append("pending Human Decisions")
    if state.get("pending_attention_drop_ids"):
        blockers.append("pending Attention drops")
    for name in ("discovery-transition.lock", "publication-transition.lock"):
        if (root / ".rh" / "locks" / name).exists():
            blockers.append(f"transition lock held: {name}")
    return blockers


def _managed_files_from_lock(lock: dict[str, object]) -> list[ManagedFile]:
    raw_files = lock.get("managed_files")
    if not isinstance(raw_files, list):
        raise DistributionError(f"{LOCK_NAME} managed_files is invalid")
    result: list[ManagedFile] = []
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise DistributionError(f"{LOCK_NAME} contains an invalid managed file")
        owner = raw.get("owner")
        source = raw.get("source")
        target = raw.get("target")
        digest = raw.get("sha256")
        if owner not in {"harness", "profile"} or not all(isinstance(value, str) for value in (source, target, digest)):
            raise DistributionError(f"{LOCK_NAME} contains an invalid managed file record")
        _safe_relative_path(target, "lock target")
        result.append(ManagedFile(str(owner), str(source), str(target), str(digest), raw.get("role") if isinstance(raw.get("role"), str) else None))
    return _unique_targets(result)


def _verify_current_managed_files(root: Path, files: list[ManagedFile]) -> None:
    for item in files:
        path = root / item.target
        if not path.is_file():
            raise DistributionError(f"managed file is missing before upgrade: {item.target}")
        actual = sha256_file(path)
        if actual != item.sha256:
            raise DistributionError(f"managed file was modified outside Harness: {item.target}")


def _require_same_targets(old_files: list[ManagedFile], new_files: list[ManagedFile], label: str) -> None:
    old_targets = {item.target for item in old_files}
    new_targets = {item.target for item in new_files}
    if old_targets != new_targets:
        removed = sorted(old_targets - new_targets)
        added = sorted(new_targets - old_targets)
        raise DistributionError(f"{label} managed path set changed; migration is required (removed={removed}, added={added})")


def _profile_id_from_lock(lock: dict[str, object]) -> str | None:
    profile = lock.get("profile")
    if profile is None:
        return None
    if not isinstance(profile, dict) or not isinstance(profile.get("profile_id"), str):
        raise DistributionError(f"{LOCK_NAME} profile record is invalid")
    return str(profile["profile_id"])
