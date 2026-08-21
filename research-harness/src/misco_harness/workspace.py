from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from misco_harness.distribution import (
    DistributionError,
    collect_harness_files,
    collect_profile_files,
    copy_managed_files,
    initialize_git,
    make_lock,
    materialize_source,
    write_lock,
    write_workspace_gitignore,
)
from misco_harness.models import ArchiveManifest, ArtifactRegistry, OrchestratorState
from misco_harness.trace_store import TraceStore, sha256_file, sha256_tree, verify_hash

if TYPE_CHECKING:
    from misco_harness.orchestrator import DiscoveryOrchestrator


class WorkspaceLifecycleError(RuntimeError):
    pass


def archive_workspace(
    orchestrator: DiscoveryOrchestrator,
    destination: Path,
    *,
    created_by: str,
    reason: str,
    allow_incomplete: bool = False,
) -> ArchiveManifest:
    root = orchestrator.workspace
    state = orchestrator.status()
    if state.lifecycle_status == "ARCHIVED":
        raise WorkspaceLifecycleError("workspace is already archived")
    if not created_by.strip() or not reason.strip():
        raise WorkspaceLifecycleError("archive requires a Human actor and reason")
    has_incomplete_work = bool(
        state.pending_work or state.pending_decision_ids or state.pending_attention_drop_ids
    )
    if not allow_incomplete and has_incomplete_work:
        raise WorkspaceLifecycleError("pending Work, Human Decisions, or Attention drops require --allow-incomplete for archive")
    publication_lock = root / ".rh" / "locks" / "publication-transition.lock"
    if publication_lock.exists():
        raise WorkspaceLifecycleError("Publication transition lock is held; archive must wait for that transition")

    destination = destination.resolve()
    if destination == root or destination.is_relative_to(root):
        raise WorkspaceLifecycleError("archive destination must be outside the source workspace")
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise WorkspaceLifecycleError(f"archive destination must be a new empty directory: {destination}")
        destination.rmdir()
    destination.parent.mkdir(parents=True, exist_ok=True)

    archive_id = f"archive-{uuid.uuid4().hex[:12]}"
    stage = Path(tempfile.mkdtemp(prefix=f".{archive_id}-", dir=destination.parent))
    try:
        payload = stage / "payload"
        payload.mkdir()
        runtime = root / ".rh"
        if not runtime.is_dir():
            raise WorkspaceLifecycleError("workspace runtime .rh is missing")
        shutil.copytree(runtime, payload / ".rh", ignore=shutil.ignore_patterns("*.lock"))
        contracts = root / "contracts"
        if contracts.is_dir():
            shutil.copytree(contracts, payload / "contracts")

        registry = ArtifactRegistry.model_validate_json(
            (runtime / "registry" / "artifact_registry.json").read_text(encoding="utf-8")
        )
        artifact_files: list[dict[str, str]] = []
        artifacts_root = payload / "artifacts"
        for artifact in registry.artifacts:
            source = Path(artifact.path).resolve()
            if not source.is_file() or source.is_symlink():
                raise WorkspaceLifecycleError(f"registered artifact is not archivable: {artifact.artifact_id}")
            if artifact.sha256 is None:
                raise WorkspaceLifecycleError(f"registered artifact has no SHA-256: {artifact.artifact_id}")
            verify_hash(source, artifact.sha256)
            target = artifacts_root / artifact.artifact_id / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            verify_hash(target, artifact.sha256)
            artifact_files.append({
                "artifact_id": artifact.artifact_id,
                "path": str(target.relative_to(stage).as_posix()),
                "sha256": artifact.sha256,
            })

        payload_hash = sha256_tree(payload)
        manifest = ArchiveManifest(
            archive_id=archive_id,
            source_workspace=str(root),
            destination=str(destination),
            created_by=created_by,
            reason=reason,
            status="INCOMPLETE" if allow_incomplete and has_incomplete_work else "COMPLETE",
            basis_orchestrator_state_id=state.state_id,
            basis_orchestrator_state_sha256=sha256_file(runtime / "state" / "orchestrator" / "head.json"),
            payload_tree_sha256=payload_hash,
            artifact_ids=[item.artifact_id for item in registry.artifacts],
            artifact_files=artifact_files,
            run_count=len(list((runtime / "runs").glob("*/manifest.json"))),
            context_pack_count=len(list((runtime / "context_packs").glob("*/manifest.json"))),
            pending_work_run_id=state.pending_work.run_id if state.pending_work else None,
            pending_decision_ids=list(state.pending_decision_ids),
            pending_attention_drop_ids=list(state.pending_attention_drop_ids),
        )
        (stage / "archive_manifest.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, destination)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    try:
        verify_archive(destination)
    except Exception:
        # Keep the verified-or-failed bundle visible for investigation; the
        # source lifecycle remains ACTIVE because the freeze did not complete.
        raise

    # Lifecycle mutation occurs only after the verified bundle has been moved.
    updated = state.model_copy(update={
        "state_id": f"orchestrator-{uuid.uuid4().hex[:12]}",
        "lifecycle_status": "ARCHIVED",
        "completed_steps": [*state.completed_steps, "WORKSPACE_ARCHIVED"],
        "prior_snapshot_id": state.state_id,
    })
    store = TraceStore(root / ".rh")
    store.snapshot("orchestrator", updated.state_id, updated)
    store.write_head("state/orchestrator/head.json", updated)
    store.write_immutable(
        Path("lifecycle") / "archives" / f"{archive_id}.json",
        {"archive_id": archive_id, "manifest": str((destination / "archive_manifest.json").resolve()), "status": "ARCHIVED"},
    )
    return manifest


def verify_archive(destination: Path) -> ArchiveManifest:
    destination = destination.resolve()
    manifest_path = destination / "archive_manifest.json"
    if not manifest_path.is_file():
        raise WorkspaceLifecycleError(f"archive manifest is missing: {manifest_path}")
    manifest = ArchiveManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    payload = destination / "payload"
    if not payload.is_dir():
        raise WorkspaceLifecycleError("archive payload is missing")
    actual = sha256_tree(payload)
    if actual != manifest.payload_tree_sha256:
        raise WorkspaceLifecycleError(f"archive payload hash mismatch: expected {manifest.payload_tree_sha256}, got {actual}")
    for item in manifest.artifact_files:
        path = destination / item["path"]
        if not path.is_file():
            raise WorkspaceLifecycleError(f"archived artifact is missing: {path}")
        verify_hash(path, item["sha256"])
    return manifest


def new_workspace(
    target: Path,
    *,
    template_root: Path,
    theme: Path,
    expectations: Path,
    worker_backend: str,
    initial_drop: Path | None = None,
    profile_source: str | Path | None = None,
    profile_ref: str | None = None,
    init_git: bool = False,
) -> dict[str, object]:
    from misco_harness.orchestrator import DiscoveryOrchestrator

    target = target.resolve()
    template_root = template_root.resolve()
    if target.exists() and any(target.iterdir()):
        raise WorkspaceLifecycleError(f"new workspace target must be empty: {target}")
    if target == template_root or target.is_relative_to(template_root):
        raise WorkspaceLifecycleError("new workspace target must not be inside the template workspace")
    target.mkdir(parents=True, exist_ok=True)

    for label, source in (("theme", theme), ("expectations", expectations)):
        resolved = source.resolve()
        if not resolved.is_file() or resolved.is_symlink():
            raise WorkspaceLifecycleError(f"new workspace {label} input is missing or not a regular file: {resolved}")
    if initial_drop is not None and not initial_drop.resolve().exists():
        raise WorkspaceLifecycleError(f"new workspace initial drop is missing: {initial_drop.resolve()}")

    try:
        with materialize_source(template_root, ref=None, manifest_name="harness.manifest.json") as harness:
            harness_files = collect_harness_files(harness)
            profile = None
            profile_id = None
            profile_files = []
            if profile_source is not None:
                with materialize_source(profile_source, ref=profile_ref, manifest_name="profile.manifest.json") as prepared_profile:
                    profile = prepared_profile
                    profile_id, profile_files = collect_profile_files(prepared_profile)
                    copy_managed_files(prepared_profile.root, target, profile_files)
            copy_managed_files(harness.root, target, harness_files)
            harness_metadata = harness.metadata
            profile_metadata = profile.metadata if profile is not None else None
    except DistributionError as error:
        raise WorkspaceLifecycleError(str(error)) from error

    intake = target / "intake"
    drop_root = intake / "drop"
    drop_root.mkdir(parents=True, exist_ok=True)
    try:
        write_workspace_gitignore(target)
    except DistributionError as error:
        raise WorkspaceLifecycleError(str(error)) from error
    theme_target = intake / "theme.md"
    expectations_target = intake / "expectations.md"
    shutil.copyfile(theme.resolve(), theme_target)
    shutil.copyfile(expectations.resolve(), expectations_target)

    orchestrator = DiscoveryOrchestrator(target)
    orchestrator.initialize(
        theme=theme_target,
        expectations=expectations_target,
        attention_map=None,
        include_default_attention_map=False,
        worker_backend=worker_backend,
    )
    drop_id = None
    if initial_drop is not None:
        drop_target = drop_root / initial_drop.resolve().name
        if initial_drop.resolve().is_dir():
            shutil.copytree(initial_drop.resolve(), drop_target)
        else:
            shutil.copyfile(initial_drop.resolve(), drop_target)
        manifest = orchestrator.register_attention_drop(drop_target, registered_by="new")
        drop_id = manifest.drop_id
    lock = make_lock(
        harness=harness_metadata,
        harness_files=harness_files,
        profile=profile_metadata,
        profile_id=profile_id,
        profile_files=profile_files,
    )
    lock_path = write_lock(target, lock)
    if init_git:
        try:
            initialize_git(target)
        except DistributionError as error:
            raise WorkspaceLifecycleError(str(error)) from error
    return {
        "status": "INITIALIZED",
        "root": str(target),
        "attention_drop_id": drop_id,
        "lock": str(lock_path),
        "profile_id": profile_id,
        "git_initialized": init_git,
    }
