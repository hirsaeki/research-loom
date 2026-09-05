from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from plugins.local_execution_store import LocalExecutionStoreIntegrityError

from .facade import LocalApplicationError
from .material_inventory_facade import (
    LocalApplicationFacade as _BaseLocalApplicationFacade,
    _ORIGINAL_ROLE,
    _TEXT_ROLE,
    _artifact_projection,
    _capture_projection,
)


_MATERIAL_SHOW_DEFAULT_BYTES = 64 * 1024
_MATERIAL_SHOW_MAX_BYTES = 1024 * 1024


def _artifact_pair_for_capture(store, project_id: str, run_id: str, capture_id: str):
    run = store.load_run(run_id)
    if (
        run is None
        or run.project_ref != project_id
        or run.capability_id != "desktop-research"
        or run.function_id != "investigate"
        or run.execution_mode != "real"
    ):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-404",
            "captured external material was not found in this project",
        )

    selected = [
        artifact
        for artifact in store.artifacts_for(run_id)
        if artifact.role in {_ORIGINAL_ROLE, _TEXT_ROLE}
        and artifact.provenance.get("capture_id") == capture_id
    ]
    originals = [item for item in selected if item.role == _ORIGINAL_ROLE]
    renditions = [item for item in selected if item.role == _TEXT_ROLE]
    if not originals and not renditions:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-404",
            "captured external material was not found in this project",
        )
    if len(originals) != 1 or len(renditions) != 1:
        raise LocalExecutionStoreIntegrityError(
            "persisted external capture pair is incomplete or ambiguous"
        )
    original, rendition = originals[0], renditions[0]
    projection = _capture_projection(original, rendition)
    if projection["capture_id"] != capture_id or projection["run_id"] != run_id:
        raise LocalExecutionStoreIntegrityError(
            "persisted external capture identity does not match requested capture"
        )
    return run, original, rendition, projection


def _bounded_utf8_view(content: bytes, limit: int) -> Mapping[str, Any]:
    try:
        full_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalExecutionStoreIntegrityError(
            "persisted external text rendition is not valid UTF-8"
        ) from exc
    if len(content) <= limit:
        return {
            "encoding": "UTF-8",
            "content": full_text,
            "displayed_bytes": len(content),
            "total_bytes": len(content),
            "truncated": False,
        }
    prefix = content[:limit]
    while prefix:
        try:
            text = prefix.decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            if exc.start < len(prefix) - 4:
                raise LocalExecutionStoreIntegrityError(
                    "persisted external text rendition is not valid UTF-8"
                ) from exc
            prefix = prefix[:exc.start]
    else:
        text = ""
    return {
        "encoding": "UTF-8",
        "content": text,
        "displayed_bytes": len(prefix),
        "total_bytes": len(content),
        "truncated": True,
    }


def _export_target(workspace_root: Path | None, output_file: str | Path) -> Path:
    if not isinstance(output_file, (str, Path)) or not str(output_file):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export output must be a non-empty path",
        )
    raw = Path(output_file).expanduser()
    target = (Path.cwd() / raw if not raw.is_absolute() else raw).resolve(strict=False)
    if target.exists():
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export will not overwrite an existing path",
        )
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export parent directory must already exist",
        )
    if workspace_root is not None:
        managed = (workspace_root / ".research-loom").resolve(strict=False)
        try:
            target.relative_to(managed)
        except ValueError:
            pass
        else:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-EXPORT-001",
                "external material export may not write inside managed workspace state",
            )
    return target


def _write_exclusive_bytes(target: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export will not overwrite an existing path",
        ) from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Verified public read/export surface for one persisted external capture."""

    def show_external_material(
        self,
        run_id: str,
        capture_id: str,
        *,
        max_text_bytes: int = _MATERIAL_SHOW_DEFAULT_BYTES,
    ) -> Mapping[str, Any]:
        if not isinstance(run_id, str) or not run_id or not isinstance(capture_id, str) or not capture_id:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INPUT-001",
                "external material show requires non-empty run_id and capture_id",
            )
        if (
            not isinstance(max_text_bytes, int)
            or isinstance(max_text_bytes, bool)
            or max_text_bytes <= 0
            or max_text_bytes > _MATERIAL_SHOW_MAX_BYTES
        ):
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INPUT-001",
                f"external material show max_text_bytes must be between 1 and {_MATERIAL_SHOW_MAX_BYTES}",
            )
        try:
            run, _original, rendition, capture = _artifact_pair_for_capture(
                self._application.execution_store, self._project_id, run_id, capture_id
            )
            rendition_payload = self._application.execution_store.load_artifact(rendition.artifact_id)
            view = _bounded_utf8_view(rendition_payload.content, max_text_bytes)
        except LocalApplicationError:
            raise
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INTEGRITY-001",
                "persisted external material content could not be verified",
            ) from exc
        return {
            "status": "OK",
            "project_id": self._project_id,
            "run": {
                "run_id": run.run_id,
                "status": run.status.value,
                "snapshot_id": run.snapshot_ref,
                "snapshot_digest": run.snapshot_digest,
            },
            "capture": capture,
            "text_rendition_view": view,
        }

    def export_external_material(
        self,
        run_id: str,
        capture_id: str,
        *,
        kind: str,
        output_file: str | Path,
    ) -> Mapping[str, Any]:
        if kind not in {"original", "rendition"}:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INPUT-001",
                "external material export kind must be original or rendition",
            )
        target = _export_target(self._workspace_root, output_file)
        try:
            run, original, rendition, capture = _artifact_pair_for_capture(
                self._application.execution_store, self._project_id, run_id, capture_id
            )
            selected = original if kind == "original" else rendition
            payload = self._application.execution_store.load_artifact(selected.artifact_id)
            _write_exclusive_bytes(target, payload.content)
        except LocalApplicationError:
            raise
        except Exception as exc:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-INTEGRITY-001",
                "persisted external material content could not be verified or exported",
            ) from exc
        return {
            "status": "EXPORTED",
            "project_id": self._project_id,
            "run_id": run.run_id,
            "capture_id": capture["capture_id"],
            "kind": kind,
            "artifact": _artifact_projection(selected),
            "output_file": str(target),
            "byte_length": len(payload.content),
            "digest": payload.digest,
        }
