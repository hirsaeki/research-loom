from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping

from plugins.local_execution_store import LocalExecutionStoreIntegrityError

from .facade import LocalApplicationError
from .material_inventory_facade import (
    _ORIGINAL_ROLE,
    _TEXT_ROLE,
    _artifact_projection,
    _capture_projection,
)


_MATERIAL_SHOW_DEFAULT_BYTES = 64 * 1024
_MATERIAL_SHOW_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _ExportTarget:
    path: Path
    parent: Path
    parent_dev: int
    parent_ino: int
    managed_root: Path | None


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
    if original.provenance.get("parent_artifact_refs") != []:
        raise LocalExecutionStoreIntegrityError(
            "persisted external original capture has invalid parent provenance"
        )
    projection = _capture_projection(original, rendition)
    if projection["capture_id"] != capture_id or projection["run_id"] != run_id:
        raise LocalExecutionStoreIntegrityError(
            "persisted external capture identity does not match requested capture"
        )
    return run, original, rendition, projection


def _bounded_utf8_view(
    content: bytes,
    limit: int,
    *,
    total_bytes: int | None = None,
) -> Mapping[str, Any]:
    total = len(content) if total_bytes is None else total_bytes
    truncated = total > limit
    prefix = content[:limit]
    if not truncated:
        try:
            text = prefix.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LocalExecutionStoreIntegrityError(
                "persisted external text rendition is not valid UTF-8"
            ) from exc
        return {
            "encoding": "UTF-8",
            "content": text,
            "displayed_bytes": len(prefix),
            "total_bytes": total,
            "truncated": False,
        }
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
        "total_bytes": total,
        "truncated": True,
    }


def _export_target(workspace_root: Path | None, output_file: str | Path) -> _ExportTarget:
    if not isinstance(output_file, (str, Path)) or not str(output_file):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export output must be a non-empty path",
        )
    raw = Path(output_file).expanduser()
    absolute = Path.cwd() / raw if not raw.is_absolute() else raw
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export parent directory must already exist",
        ) from exc
    if not parent.is_dir():
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export parent directory must already exist",
        )
    target = parent / absolute.name
    if target.exists():
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export will not overwrite an existing path",
        )
    managed = None
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
    stat_result = parent.stat()
    return _ExportTarget(target, parent, stat_result.st_dev, stat_result.st_ino, managed)


def _is_within(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _windows_open_export_handle(path: Path) -> int:
    """Create one new Windows export file with write and delete rights."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_write = 0x40000000
    delete_access = 0x00010000
    create_new = 1
    file_attribute_normal = 0x00000080
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        generic_write | delete_access,
        0,
        None,
        create_new,
        file_attribute_normal,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    try:
        # Mark the native handle delete-pending before CRT ownership transfer.
        # If the legacy disposition class itself fails, keep ownership on this
        # native handle and use the newer handle-only class as cleanup fallback.
        try:
            _windows_set_handle_delete_disposition(handle, True)
        except Exception as exc:
            # The legacy disposition class can fail before ownership is moved
            # into a CRT fd. Fall back to the newer handle-only disposition
            # class so cleanup still targets this exact file object, never a
            # pathname that another process could replace.
            try:
                _windows_set_handle_delete_disposition_ex(handle)
            except Exception as cleanup_exc:
                raise cleanup_exc from exc
            raise
        return msvcrt.open_osfhandle(
            handle,
            os.O_WRONLY | getattr(os, "O_BINARY", 0),
        )
    except Exception:
        close_handle(handle)
        raise


def _windows_set_handle_delete_disposition(handle: int, delete: bool) -> None:
    """Toggle delete-on-close for one exact Windows native file handle."""
    import ctypes
    from ctypes import wintypes

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    func = kernel32.SetFileInformationByHandle
    func.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    func.restype = wintypes.BOOL
    info = _FileDispositionInfo(bool(delete))
    if not func(handle, 4, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetFileInformationByHandle failed")


def _windows_set_handle_delete_disposition_ex(handle: int) -> None:
    """Mark one exact Windows handle for cleanup using FileDispositionInfoEx."""
    import ctypes
    from ctypes import wintypes

    class _FileDispositionInfoEx(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    func = kernel32.SetFileInformationByHandle
    func.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    func.restype = wintypes.BOOL
    info = _FileDispositionInfoEx(0x00000001)  # FILE_DISPOSITION_FLAG_DELETE
    if not func(handle, 21, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetFileInformationByHandle(FileDispositionInfoEx) failed")


def _windows_set_delete_disposition(fd: int, delete: bool) -> None:
    """Toggle delete-on-close for the exact Windows fd owned by this export."""
    import msvcrt

    _windows_set_handle_delete_disposition(msvcrt.get_osfhandle(fd), delete)


def _windows_final_path(fd: int) -> Path:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    handle = msvcrt.get_osfhandle(fd)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    func = kernel32.GetFinalPathNameByHandleW
    func.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    func.restype = wintypes.DWORD
    size = func(handle, None, 0, 0)
    if size == 0:
        raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    buffer = ctypes.create_unicode_buffer(size + 1)
    written = func(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _write_exclusive_bytes(target: _ExportTarget, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd: int | None = None
    parent_fd: int | None = None
    created = False
    try:
        if (
            os.name != "nt"
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd
        ):
            try:
                parent_fd = os.open(
                    target.parent,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                )
            except OSError as exc:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-EXPORT-001",
                    "external material export parent changed before file creation",
                ) from exc
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) != (
                target.parent_dev,
                target.parent_ino,
            ):
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-EXPORT-001",
                    "external material export parent changed before file creation",
                )
            fd = os.open(
                target.path.name,
                flags | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            created = True
        elif os.name == "nt":
            fd = _windows_open_export_handle(target.path)
            created = True
            # The helper returns an fd whose exact native handle is already
            # delete-pending, so every failure from here is cleaned up by close.
            final_path = _windows_final_path(fd)
            final_parent = final_path.parent.resolve(strict=True)
            current_stat = final_parent.stat()
            expected_parent = target.parent.resolve(strict=True)
            if (
                os.path.normcase(str(final_parent)) != os.path.normcase(str(expected_parent))
                or (current_stat.st_dev, current_stat.st_ino)
                != (target.parent_dev, target.parent_ino)
                or _is_within(final_path, target.managed_root)
            ):
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-EXPORT-001",
                    "external material export parent changed before file creation",
                )
        else:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-EXPORT-001",
                "external material export cannot safely verify the output parent",
            )

        assert fd is not None
        if os.name == "nt":
            # Do not let fdopen close the fd until delete-pending is cleared only
            # after the complete verified payload is durable.
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _windows_set_delete_disposition(fd, False)
            created = False
        else:
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-EXPORT-001",
            "external material export will not overwrite an existing path",
        ) from exc
    except Exception:
        if fd is not None:
            os.close(fd)
            fd = None
        if created and parent_fd is not None:
            try:
                os.unlink(target.path.name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)


class ExternalMaterialContentService:
    """Explicit-dependency content reader used by the existing public facade."""

    def __init__(self, store, project_id: str, workspace_root: Path | None) -> None:
        self._store = store
        self._project_id = project_id
        self._workspace_root = workspace_root

    def show(
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
                self._store, self._project_id, run_id, capture_id
            )
            rendition_payload, total_bytes = self._store.load_artifact_verified_prefix(
                rendition.artifact_id,
                max_bytes=max_text_bytes,
            )
            view = _bounded_utf8_view(
                rendition_payload.content,
                max_text_bytes,
                total_bytes=total_bytes,
            )
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

    def export(
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
                self._store, self._project_id, run_id, capture_id
            )
            selected = original if kind == "original" else rendition
            payload = self._store.load_artifact_verified_once(selected.artifact_id)
            _write_exclusive_bytes(target, payload.content)
        except LocalApplicationError:
            raise
        except Exception as exc:
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
            "output_file": str(target.path),
            "byte_length": len(payload.content),
            "digest": payload.digest,
        }
