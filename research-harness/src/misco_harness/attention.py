from __future__ import annotations

import uuid
from pathlib import Path

from misco_harness.context_builder import ArtifactAccessPolicy
from misco_harness.models import ArtifactRecord, DropBatchManifest, DropFileRecord, Lane
from misco_harness.trace_store import TraceStore, sha256_file, sha256_tree


class AttentionIntakeError(RuntimeError):
    pass


def register_drop(
    workspace: Path,
    source_path: Path,
    *,
    registered_by: str,
    policy: ArtifactAccessPolicy,
) -> tuple[DropBatchManifest, list[ArtifactRecord]]:
    """Freeze one explicitly selected drop batch and return Registry records."""

    workspace = workspace.resolve()
    runtime = (workspace / ".rh").resolve()
    source = source_path.resolve()
    if not source.exists():
        raise AttentionIntakeError(f"attention drop does not exist: {source}")
    if source.is_symlink() or source == runtime or source.is_relative_to(runtime):
        raise AttentionIntakeError("attention drop must not be a symlink or reside under .rh")
    if not source.is_relative_to(workspace):
        raise AttentionIntakeError("attention drop must be inside the workspace")
    if not registered_by.strip():
        raise AttentionIntakeError("registered_by is required")

    for manifest_path in (runtime / "intake" / "drops").glob("*/manifest.json"):
        try:
            previous = DropBatchManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if previous.source_path == str(source):
            raise AttentionIntakeError(f"attention drop was already registered: {source}")

    ignored_paths: list[str] = []
    if source.is_file():
        files = [(source.name, source)]
    elif source.is_dir():
        files = []
        for candidate in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            if candidate.is_symlink():
                raise AttentionIntakeError(f"attention drop contains a symlink: {candidate}")
            if candidate.is_file():
                files.append((candidate.relative_to(source).as_posix(), candidate))
            elif not candidate.is_dir():
                ignored_paths.append(f"{candidate.relative_to(source).as_posix()}: unsupported non-regular entry")
        if not files:
            raise AttentionIntakeError("attention drop contains no regular files")
    else:
        raise AttentionIntakeError(f"attention drop is not a regular file or directory: {source}")

    drop_id = f"drop-{uuid.uuid4().hex[:12]}"
    store = TraceStore(runtime)
    stored_root = runtime / "intake" / "drops" / drop_id / "files"
    records: list[ArtifactRecord] = []
    file_records: list[DropFileRecord] = []
    role = "ATTENTION_INTAKE_DROP"
    runtime_policy = policy.runtime_policy_for_role(role)

    for index, (relative_path, original) in enumerate(files, start=1):
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise AttentionIntakeError(f"unsafe attention drop path: {relative_path!r}")
        target_relative = Path("intake") / "drops" / drop_id / "files" / relative
        target = store.copy_immutable_file(original, target_relative)
        digest = sha256_file(original)
        file_records.append(DropFileRecord(
            relative_path=relative.as_posix(),
            stored_path=str(target.resolve()),
            sha256=digest,
            size_bytes=original.stat().st_size,
        ))
        records.append(ArtifactRecord(
            artifact_id=f"{drop_id}-file-{index}",
            path=str(target.resolve()),
            sha256=digest,
            role=role,
            authority="HUMAN_SUPPLIED_UNTRIAGED_INTAKE",
            lane=Lane.CONTROL_PLANE,
            runtime_policy=runtime_policy,
        ))

    tree_digest = sha256_tree(stored_root)
    manifest = DropBatchManifest(
        drop_id=drop_id,
        source_path=str(source),
        registered_by=registered_by,
        files=file_records,
        ignored_paths=ignored_paths,
        tree_sha256=tree_digest,
    )
    manifest_path = store.write_immutable(
        Path("intake") / "drops" / drop_id / "manifest.json",
        manifest,
    )
    records.insert(0, ArtifactRecord(
        artifact_id=f"{drop_id}-manifest",
        path=str(manifest_path.resolve()),
        sha256=sha256_file(manifest_path),
        role=role,
        authority="HUMAN_SUPPLIED_UNTRIAGED_INTAKE",
        lane=Lane.CONTROL_PLANE,
        runtime_policy=runtime_policy,
    ))
    return manifest, records
