from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from threading import RLock, Thread
import tempfile
from typing import Any

from . import material_reacquisition_facade as _base
from .facade import LocalApplicationError


_PYPDF_VERSION = "6.16.2"
_PYPDF_BOUND_EXIT = 86
_INSTALL_LOCK = RLock()
_INSTALLED = False
_BASE_GENERATOR = _base._regenerate_text_rendition
_BASE_MATCHES_TARGET = _base.HistoricalMaterialReacquisitionService._matches_target


_PYPDF_SCRIPT = rf"""
import sys
from pypdf import PdfReader

source = sys.argv[1]
max_bytes = int(sys.argv[2])
written = 0
output = sys.stdout.buffer


def emit(chunk):
    global written
    if written + len(chunk) > max_bytes:
        raise SystemExit({_PYPDF_BOUND_EXIT})
    output.write(chunk)
    written += len(chunk)


reader = PdfReader(source)
for index, page in enumerate(reader.pages):
    if index:
        emit(b"\r\n\r\n")
    page_text = page.extract_text() or ""
    emit(page_text.replace("\n", "\r\n").encode("utf-8"))
emit(b"\r\n")
""".strip()


def _matches_current_target(child: Any, capture_id: str, kind: str) -> bool:
    return (
        child.capability_version == _base._CAPABILITY_VERSION
        and child.implementation_version == _base._IMPLEMENTATION_VERSION
        and _BASE_MATCHES_TARGET(child, capture_id, kind)
    )


def _run_historical_pypdf(
    original_content: bytes,
    exact_locator: str,
    *,
    max_bytes: int,
) -> _base.RetrievedMaterial:
    uv = shutil.which("uv")
    if not uv:
        raise _base.MaterialReacquisitionRetrievalError(
            "historical pypdf rendition regeneration requires uv to be available"
        )

    with tempfile.TemporaryDirectory(prefix="research-loom-pypdf-rendition-") as temporary:
        source = Path(temporary) / "source.pdf"
        source.write_bytes(original_content)
        try:
            process = subprocess.Popen(
                [
                    uv,
                    "run",
                    "--quiet",
                    "--isolated",
                    "--no-project",
                    "--with",
                    f"pypdf=={_PYPDF_VERSION}",
                    "python",
                    "-c",
                    _PYPDF_SCRIPT,
                    str(source),
                    str(max_bytes),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise _base.MaterialReacquisitionRetrievalError(
                "historical pypdf rendition regeneration could not start"
            ) from exc

        if process.stdout is None:
            process.kill()
            process.wait()
            raise _base.MaterialReacquisitionRetrievalError(
                "historical pypdf rendition regeneration did not expose bounded output"
            )

        content = bytearray()
        read_errors: list[Exception] = []

        def stop_process() -> None:
            try:
                process.kill()
            except OSError:
                pass

        def read_output() -> None:
            try:
                while len(content) <= max_bytes:
                    remaining = max_bytes + 1 - len(content)
                    chunk = process.stdout.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        stop_process()
                        break
            except Exception as exc:  # pragma: no cover - defensive I/O seam
                read_errors.append(exc)
                stop_process()

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        try:
            returncode = process.wait(timeout=60)
        except subprocess.TimeoutExpired as exc:
            stop_process()
            process.wait()
            reader.join(timeout=1)
            raise _base.MaterialReacquisitionRetrievalError(
                "historical pypdf rendition regeneration timed out"
            ) from exc
        reader.join(timeout=1)
        if reader.is_alive():
            stop_process()
            process.wait()
            raise _base.MaterialReacquisitionRetrievalError(
                "historical pypdf rendition output did not terminate cleanly"
            )
        if read_errors:
            raise _base.MaterialReacquisitionRetrievalError(
                "historical pypdf rendition output could not be read"
            ) from read_errors[0]
        if len(content) > max_bytes or returncode == _PYPDF_BOUND_EXIT:
            raise _base.MaterialReacquisitionRetrievalError(
                "regenerated rendition exceeds bounded material intake limit"
            )
        if returncode != 0:
            raise _base.MaterialReacquisitionRetrievalError(
                "historical pypdf rendition regeneration failed"
            )
        rendered = bytes(content)
        try:
            rendered.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _base.MaterialReacquisitionRetrievalError(
                "regenerated rendition is not valid UTF-8"
            ) from exc
        return _base.RetrievedMaterial(
            rendered,
            "text/plain",
            exact_locator,
            f"uv-pypdf/{_PYPDF_VERSION};newline=crlf",
            None,
        )


def _regenerate_text_rendition(
    original_content: bytes,
    original_media_type: str,
    exact_locator: str,
    *,
    max_bytes: int,
) -> _base.RetrievedMaterial:
    media_type = str(original_media_type).split(";", 1)[0].strip().lower()
    if media_type == "text/html":
        # Reuse the already-composed bounded/safe G1 renderer rather than
        # introducing a second HTML rendition contract for reacquisition.
        from . import new_material_continuation_service as continuation

        try:
            rendered = continuation._render_reacquired_html_rendition(
                original_content,
                original_media_type,
                max_bytes=max_bytes,
            )
        except LocalApplicationError as exc:
            raise _base.MaterialReacquisitionRetrievalError(
                f"historical HTML rendition regeneration failed: {exc}"
            ) from exc
        return _base.RetrievedMaterial(
            rendered,
            "text/plain",
            exact_locator,
            continuation._HTML_RENDITION_PROVIDER,
            None,
        )

    if media_type != "application/pdf":
        return _BASE_GENERATOR(
            original_content,
            original_media_type,
            exact_locator,
            max_bytes=max_bytes,
        )

    try:
        return _run_historical_pypdf(
            original_content,
            exact_locator,
            max_bytes=max_bytes,
        )
    except _base.MaterialReacquisitionRetrievalError as pypdf_error:
        if "exceeds bounded material intake limit" in str(pypdf_error):
            raise
        try:
            return _BASE_GENERATOR(
                original_content,
                original_media_type,
                exact_locator,
                max_bytes=max_bytes,
            )
        except _base.MaterialReacquisitionRetrievalError as fallback_error:
            raise _base.MaterialReacquisitionRetrievalError(
                f"historical pypdf provider failed: {pypdf_error}; fallback failed: {fallback_error}"
            ) from pypdf_error


def _install_provider() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _base._regenerate_text_rendition = _regenerate_text_rendition
        _base._IMPLEMENTATION_VERSION = "0.2.1"
        _base._CAPABILITY_VERSION = "0.2.1"
        _base.HistoricalMaterialReacquisitionService._matches_target = staticmethod(
            _matches_current_target
        )
        _INSTALLED = True


def ensure_material_reacquisition_action(
    application: Any, project_id: str, workspace_root: Path | None
) -> None:
    _install_provider()
    _base.ensure_material_reacquisition_action(application, project_id, workspace_root)
