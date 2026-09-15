from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import http.client
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
from threading import RLock, Thread
import tempfile
import time
from typing import Any, Callable, Mapping
from urllib.parse import urljoin, urlparse
import uuid

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.execution import CapabilityRunRecord, ExecutionIssue, RunLifecycleEvent, RunStatus
from plugins.local_execution_store import (
    LocalExecutionStoreIntegrityError,
    bind_controlled_import_root,
    child_runs_for_parent,
    diagnostics_for,
)

from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture
from .material_recovery_facade import _canonical_artifact_binding_for_capture


_ACTION_TYPE = "desktop_research.material.reacquire"
_PAYLOAD_CONTRACT = "desktop-research-material-reacquisition@0.2.0"
_ACTION_REGISTRATION_LOCK = RLock()
_IMPLEMENTATION_ID = "plugin.local-application.material-reacquisition"
_IMPLEMENTATION_VERSION = "0.2.0"
_CAPABILITY_ID = "desktop-research-material-reacquisition"
_CAPABILITY_VERSION = "0.2.0"
_RESULT_DIAGNOSTIC = "historical_material_reacquisition"
_NEW_MATERIAL_ROLES = {
    "original": "desktop_research.reacquired_original",
    "rendition": "desktop_research.reacquired_rendition",
}


@dataclass(frozen=True)
class RetrievedMaterial:
    content: bytes
    media_type: str
    final_locator: str
    provider: str
    status_code: int | None = None


class MaterialReacquisitionRetrievalError(RuntimeError):
    pass


def material_recovery_action_guidance() -> list[dict[str, Any]]:
    return [
        {
            "action_type": "desktop_research.material.recover",
            "when": "operator has exact retained bytes",
            "caller_fields": ["run_id", "capture_id", "kind", "source_file"],
        },
        {
            "action_type": _ACTION_TYPE,
            "when": (
                "exact retained bytes are unavailable; reacquire the historical "
                "original or regenerate a rendition candidate under exact identity checks"
            ),
            "caller_fields": ["historical_run_id", "capture_id", "kind"],
        },
    ]


def material_reacquisition_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    required = {"historical_run_id", "capture_id", "kind"}
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise ValueError(
            "desktop_research.material.reacquire requires only historical_run_id, capture_id, and kind"
        )
    run_id = payload.get("historical_run_id")
    capture_id = payload.get("capture_id")
    kind = payload.get("kind")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("historical_run_id must be a non-empty string")
    if not isinstance(capture_id, str) or not capture_id:
        raise ValueError("capture_id must be a non-empty string")
    if not isinstance(kind, str) or kind not in {"original", "rendition"}:
        raise ValueError("kind must be original or rendition")
    return {
        "historical_run_id": run_id,
        "capture_id": capture_id,
        "kind": kind,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _identity_digest(*parts: str) -> str:
    return "sha256:" + hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _historical_equivalent(
    expected_digest: str,
    expected_size: int,
    actual_digest: str,
    actual_size: int,
) -> bool:
    """The sole classification guard between historical restoration and new material."""
    return expected_digest == actual_digest and expected_size == actual_size


def _regenerate_text_rendition(
    original_content: bytes,
    original_media_type: str,
    exact_locator: str,
    *,
    max_bytes: int,
) -> RetrievedMaterial:
    """Produce a bounded current rendition candidate; identity is decided only by digest/size."""
    media_type = str(original_media_type).split(";", 1)[0].strip().lower()
    if media_type == "text/plain":
        try:
            original_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MaterialReacquisitionRetrievalError(
                "verified text/plain original is not valid UTF-8"
            ) from exc
        if len(original_content) > max_bytes:
            raise MaterialReacquisitionRetrievalError(
                "regenerated rendition exceeds bounded material intake limit"
            )
        return RetrievedMaterial(
            original_content,
            "text/plain",
            exact_locator,
            "verified-original-utf8",
            None,
        )

    if media_type != "application/pdf":
        raise MaterialReacquisitionRetrievalError(
            f"no trusted rendition generator is available for media type {original_media_type!r}"
        )

    tool = shutil.which("pdftotext")
    if not tool:
        raise MaterialReacquisitionRetrievalError(
            "PDF rendition regeneration requires pdftotext to be available"
        )
    with tempfile.TemporaryDirectory(prefix="research-loom-rendition-") as temporary:
        source = Path(temporary) / "source.pdf"
        source.write_bytes(original_content)
        try:
            process = subprocess.Popen(
                [tool, "-enc", "UTF-8", str(source), "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise MaterialReacquisitionRetrievalError(
                "pdftotext rendition regeneration failed"
            ) from exc
        if process.stdout is None:
            process.kill()
            process.wait()
            raise MaterialReacquisitionRetrievalError(
                "pdftotext rendition regeneration did not expose bounded output"
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
            returncode = process.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            stop_process()
            process.wait()
            reader.join(timeout=1)
            raise MaterialReacquisitionRetrievalError(
                "pdftotext rendition regeneration timed out"
            ) from exc
        reader.join(timeout=1)
        if reader.is_alive():
            stop_process()
            process.wait()
            raise MaterialReacquisitionRetrievalError(
                "pdftotext rendition output did not terminate cleanly"
            )
        if read_errors:
            raise MaterialReacquisitionRetrievalError(
                "pdftotext rendition output could not be read"
            ) from read_errors[0]
        if len(content) > max_bytes:
            raise MaterialReacquisitionRetrievalError(
                "regenerated rendition exceeds bounded material intake limit"
            )
        if returncode != 0:
            raise MaterialReacquisitionRetrievalError(
                "pdftotext rendition regeneration failed"
            )
        content = bytes(content)
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MaterialReacquisitionRetrievalError(
                "regenerated rendition is not valid UTF-8"
            ) from exc
    return RetrievedMaterial(
        content,
        "text/plain",
        exact_locator,
        "pdftotext",
        None,
    )


def _resolve_public_https_locator(locator: str):
    try:
        parsed = urlparse(locator)
        port = parsed.port or 443
    except ValueError as exc:
        raise MaterialReacquisitionRetrievalError(
            "historical locator is not a valid public HTTPS URL"
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MaterialReacquisitionRetrievalError(
            "historical locator must be a public HTTPS URL"
        )
    try:
        resolved = socket.getaddrinfo(
            parsed.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise MaterialReacquisitionRetrievalError(
            "historical locator hostname could not be resolved"
        ) from exc
    if not resolved:
        raise MaterialReacquisitionRetrievalError(
            "historical locator hostname resolved to no addresses"
        )

    addresses: list[str] = []
    for entry in resolved:
        raw_address = str(entry[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise MaterialReacquisitionRetrievalError(
                "historical locator resolved to an invalid address"
            ) from exc
        if not address.is_global:
            raise MaterialReacquisitionRetrievalError(
                "historical locator resolves to a non-public address"
            )
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    return parsed, tuple(addresses)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to one pre-validated IP while preserving TLS hostname checks."""

    def __init__(
        self,
        hostname: str,
        connect_address: str,
        port: int,
        *,
        timeout: float,
    ) -> None:
        self._connect_address = connect_address
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _request_target(parsed) -> str:
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    return target


def _host_header(hostname: str, port: int) -> str:
    host = f"[{hostname}]" if ":" in hostname else hostname
    return host if port == 443 else f"{host}:{port}"


def _retrieve_exact_locator(locator: str, *, max_bytes: int) -> RetrievedMaterial:
    current_locator = locator
    redirect_statuses = {301, 302, 303, 307, 308}
    for _redirect_count in range(6):
        parsed, addresses = _resolve_public_https_locator(current_locator)
        hostname = str(parsed.hostname)
        port = parsed.port or 443
        last_error: Exception | None = None
        redirect_locator: str | None = None

        for address in addresses:
            connection = _PinnedHTTPSConnection(
                hostname,
                address,
                port,
                timeout=30,
            )
            try:
                connection.request(
                    "GET",
                    _request_target(parsed),
                    headers={
                        "Host": _host_header(hostname, port),
                        "User-Agent": "Research-Loom historical-material-reacquisition/0.1",
                        "Connection": "close",
                    },
                )
                response = connection.getresponse()
                status = int(response.status)
                if status in redirect_statuses:
                    location = response.getheader("Location")
                    if not location:
                        raise MaterialReacquisitionRetrievalError(
                            "historical locator redirect omitted Location"
                        )
                    redirect_locator = urljoin(current_locator, str(location))
                    break
                if status < 200 or status >= 300:
                    raise MaterialReacquisitionRetrievalError(
                        f"historical locator returned HTTP {status}"
                    )

                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise MaterialReacquisitionRetrievalError(
                                "reacquired response exceeds bounded material intake limit"
                            )
                    except ValueError:
                        pass
                content = response.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise MaterialReacquisitionRetrievalError(
                        "reacquired response exceeds bounded material intake limit"
                    )
                media_type = (
                    response.headers.get_content_type()
                    if hasattr(response.headers, "get_content_type")
                    else "application/octet-stream"
                )
                return RetrievedMaterial(
                    content=content,
                    media_type=media_type or "application/octet-stream",
                    final_locator=current_locator,
                    provider="http.client.pinned-https",
                    status_code=status,
                )
            except MaterialReacquisitionRetrievalError:
                raise
            except Exception as exc:
                last_error = exc
            finally:
                connection.close()

        if redirect_locator is not None:
            current_locator = redirect_locator
            continue
        if last_error is not None:
            raise MaterialReacquisitionRetrievalError(
                str(last_error) or type(last_error).__name__
            ) from last_error
        raise MaterialReacquisitionRetrievalError(
            "historical locator could not be retrieved from approved addresses"
        )

    raise MaterialReacquisitionRetrievalError("historical locator exceeded redirect limit")

def _transition(store, run: CapabilityRunRecord, status: RunStatus, reason: str, *, failure=None):
    events = store.events_for(run.run_id)
    sequence = len(events) + 1
    now = _utc_now()
    changes: dict[str, Any] = {}
    if status is RunStatus.RUNNING:
        changes["started_at"] = now
    if status in {RunStatus.COMPLETED, RunStatus.FAILED}:
        changes["completed_at"] = now
    if failure is not None:
        changes["failure"] = failure
    updated = run.with_status(status, **changes)
    event = RunLifecycleEvent(run.run_id, sequence, run.status, status, now, reason)
    if not store.transition_run(run.status, updated, event):
        raise LocalExecutionStoreIntegrityError("reacquisition Run lifecycle changed concurrently")
    return updated


class HistoricalMaterialReacquisitionService:
    def __init__(
        self,
        store,
        project_id: str,
        workspace_root: Path | None,
        *,
        retriever: Callable[[str], RetrievedMaterial] | None = None,
    ) -> None:
        self._store = store
        self._project_id = project_id
        self._workspace_root = workspace_root
        self._retriever = retriever

    @staticmethod
    def _matches_target(child, capture_id: str, kind: str) -> bool:
        if child.capability_id != _CAPABILITY_ID:
            return False
        target = child.provenance.get("historical_target")
        return (
            isinstance(target, Mapping)
            and target.get("capture_id") == capture_id
            and target.get("kind") == kind
        )

    def _previous_success(
        self,
        historical_run_id: str,
        capture_id: str,
        kind: str,
        historical_artifact_id: str,
    ):
        for child in reversed(child_runs_for_parent(self._store, historical_run_id, limit=100)):
            if child.status is not RunStatus.COMPLETED:
                continue
            if not self._matches_target(child, capture_id, kind):
                continue
            for item in diagnostics_for(self._store, child.run_id, limit=20):
                if item.get("kind") != _RESULT_DIAGNOSTIC:
                    continue
                payload = item.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                status = payload.get("status")
                try:
                    if status == "IDENTICAL_REACQUISITION":
                        if payload.get("historical_artifact_id") != historical_artifact_id:
                            continue
                        if (
                            self._store.diagnose_artifact_content(
                                historical_artifact_id
                            ).get("status")
                            != "verified"
                        ):
                            continue
                    elif status == "NEW_MATERIAL_VERSION":
                        new_artifact_id = payload.get("new_artifact_id")
                        if not isinstance(new_artifact_id, str) or not any(
                            artifact.artifact_id == new_artifact_id
                            for artifact in self._store.artifacts_for(child.run_id)
                        ):
                            continue
                        if (
                            self._store.diagnose_artifact_content(new_artifact_id).get(
                                "status"
                            )
                            != "verified"
                        ):
                            continue
                    else:
                        continue
                except Exception:
                    continue
                return child, dict(payload)
        return None

    @contextmanager
    def _target_lock(self, historical_run_id: str, capture_id: str, kind: str):
        if self._workspace_root is None:
            raise LocalExecutionStoreIntegrityError(
                "historical material reacquisition requires a workspace-bound facade"
            )
        lock_root = self._workspace_root / ".research-loom" / "material-reacquisition-locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha256(
            f"{historical_run_id}\0{capture_id}\0{kind}".encode("utf-8")
        ).hexdigest()
        lock_path = lock_root / f"{token}.lock"
        fd = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0),
            0o600,
        )
        locked = False
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                    os.fsync(fd)
                os.lseek(fd, 0, os.SEEK_SET)
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError as exc:
                        if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise
                        time.sleep(0.05)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
                locked = True
            yield
        finally:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _new_run(self, historical, capture_id: str, kind: str, exact_locator: str):
        token = uuid.uuid4().hex
        now = _utc_now()
        invocation_digest = _identity_digest(
            historical.run_id, capture_id, kind, exact_locator, token
        )
        run = CapabilityRunRecord(
            run_id=f"RUN-MRA-{token}",
            invocation_id=f"INV-MRA-{token}",
            invocation_digest=invocation_digest,
            capability_id=_CAPABILITY_ID,
            capability_version=_CAPABILITY_VERSION,
            descriptor_digest=_identity_digest(_CAPABILITY_ID, _CAPABILITY_VERSION),
            implementation_id=_IMPLEMENTATION_ID,
            implementation_version=_IMPLEMENTATION_VERSION,
            function_id="reacquire",
            execution_mode="real",
            context_pack_id=f"CTX-MRA-{token}",
            context_pack_digest=_identity_digest(
                historical.snapshot_digest, exact_locator, capture_id, kind
            ),
            project_ref=historical.project_ref,
            lineage_ref=historical.lineage_ref,
            snapshot_ref=historical.snapshot_ref,
            snapshot_digest=historical.snapshot_digest,
            attempt=len(child_runs_for_parent(self._store, historical.run_id, limit=100)) + 1,
            parent_run_id=historical.run_id,
            status=RunStatus.PREPARED,
            prepared_at=now,
            provenance={
                "trace_kind": "historical_material_reacquisition",
                "historical_target": {
                    "run_id": historical.run_id,
                    "capture_id": capture_id,
                    "kind": kind,
                    "exact_locator": exact_locator,
                },
            },
        )
        self._store.create_run(run)
        self._store.append_run_event(
            RunLifecycleEvent(run.run_id, 1, None, RunStatus.PREPARED, now, "bounded historical material reacquisition prepared")
        )
        return _transition(
            self._store,
            run,
            RunStatus.RUNNING,
            "historical exact locator retrieval started",
        )

    def _record_result(self, child_run_id: str, payload: Mapping[str, Any]) -> None:
        self._store.store_diagnostic(child_run_id, _RESULT_DIAGNOSTIC, dict(payload))

    def _restore_identical(self, artifact_id: str, content: bytes):
        if self._workspace_root is None:
            raise LocalExecutionStoreIntegrityError(
                "historical material reacquisition requires a workspace-bound facade"
            )
        bind_controlled_import_root(self._store, self._workspace_root)
        fd, name = tempfile.mkstemp(
            prefix=".research-loom-reacquired-",
            dir=self._workspace_root,
        )
        path = Path(name)
        try:
            with open(fd, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
            return self._store.restore_missing_artifact_from_file(artifact_id, path)
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def reacquire(self, historical_run_id: str, capture_id: str, *, kind: str):
        if kind not in {"original", "rendition"}:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-REACQUISITION-INPUT-001",
                "historical material reacquisition kind must be original or rendition",
            )
        if self._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-REACQUISITION-001",
                "historical material reacquisition requires a workspace-bound facade",
            )
        try:
            historical, original, _rendition, capture = _artifact_pair_for_capture(
                self._store, self._project_id, historical_run_id, capture_id
            )
            artifact = _canonical_artifact_binding_for_capture(
                self._store, historical_run_id, capture_id, kind
            )
        except LocalApplicationError:
            raise
        except Exception as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-REACQUISITION-BINDING-001",
                "historical material reacquisition target is incomplete or ambiguous",
            ) from exc

        diagnosis = self._store.diagnose_artifact_content(artifact.artifact_id)
        if diagnosis.get("status") == "verified":
            return {
                "status": "ALREADY_VERIFIED",
                "historical_run_id": historical_run_id,
                "capture_id": capture_id,
                "kind": kind,
                "artifact_id": artifact.artifact_id,
                "historical_metadata_rewritten": False,
                "research_state_mutation_performed": False,
            }
        if diagnosis.get("status") != "content_missing":
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-REACQUISITION-001",
                "only missing historical material is eligible for locator reacquisition",
            )

        exact_locator = str(capture["source_locator"])
        with self._target_lock(historical_run_id, capture_id, kind):
            # A caller may have waited behind another reacquisition of the same
            # historical target. Re-read physical health before deciding whether
            # another execution fact is necessary.
            diagnosis = self._store.diagnose_artifact_content(artifact.artifact_id)
            if diagnosis.get("status") == "verified":
                return {
                    "status": "ALREADY_VERIFIED",
                    "historical_run_id": historical_run_id,
                    "capture_id": capture_id,
                    "kind": kind,
                    "artifact_id": artifact.artifact_id,
                    "historical_metadata_rewritten": False,
                    "research_state_mutation_performed": False,
                }
            if diagnosis.get("status") != "content_missing":
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-REACQUISITION-001",
                    "only missing historical material is eligible for locator reacquisition",
                )

            previous = self._previous_success(
                historical_run_id,
                capture_id,
                kind,
                artifact.artifact_id,
            )
            if previous is not None:
                child, payload = previous
                return {
                    **payload,
                    "reacquisition_run_id": child.run_id,
                    "idempotent_reuse": True,
                }

            historical_acquired_at = str(capture["acquired_at"])
            child = self._new_run(historical, capture_id, kind, exact_locator)
            max_bytes = int(self._store.config.max_artifact_bytes)
            reacquired_at = _utc_now()
            try:
                if int(artifact.size) > max_bytes:
                    raise MaterialReacquisitionRetrievalError(
                        "historical material exceeds bounded reacquisition size limit"
                    )
                if kind == "original":
                    if self._retriever is None:
                        retrieved = _retrieve_exact_locator(exact_locator, max_bytes=max_bytes)
                    else:
                        retrieved = self._retriever(exact_locator)
                    reacquisition_mode = "network_exact_locator"
                    derivation_source = None
                else:
                    original_diagnosis = self._store.diagnose_artifact_content(
                        original.artifact_id
                    )
                    if original_diagnosis.get("status") != "verified":
                        raise MaterialReacquisitionRetrievalError(
                            "historical rendition regeneration requires the historical original to be verified first"
                        )
                    if int(original.size) > max_bytes:
                        raise MaterialReacquisitionRetrievalError(
                            "historical original exceeds bounded rendition regeneration limit"
                        )
                    original_payload = self._store.load_artifact(original.artifact_id)
                    retrieved = _regenerate_text_rendition(
                        original_payload.content,
                        original.media_type,
                        exact_locator,
                        max_bytes=max_bytes,
                    )
                    reacquisition_mode = "regenerated_from_verified_historical_original"
                    derivation_source = {
                        "artifact_id": original.artifact_id,
                        "digest": original.digest,
                        "size": original.size,
                    }
                if not isinstance(retrieved, RetrievedMaterial):
                    raise MaterialReacquisitionRetrievalError(
                        "reacquisition provider returned invalid material"
                    )
                if len(retrieved.content) > max_bytes:
                    raise MaterialReacquisitionRetrievalError(
                        "reacquired response exceeds bounded material intake limit"
                    )
                if kind == "rendition":
                    if str(retrieved.media_type).split(";", 1)[0].strip().lower() != "text/plain":
                        raise MaterialReacquisitionRetrievalError(
                            "rendition provider must return text/plain"
                        )
                    try:
                        retrieved.content.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise MaterialReacquisitionRetrievalError(
                            "rendition provider must return valid UTF-8"
                        ) from exc
                actual_digest = _sha256(retrieved.content)
                actual_size = len(retrieved.content)

                common = {
                    "contract": _PAYLOAD_CONTRACT,
                    "historical_run_id": historical_run_id,
                    "historical_capture_id": capture_id,
                    "historical_artifact_id": artifact.artifact_id,
                    "kind": kind,
                    "historical_acquired_at": historical_acquired_at,
                    "reacquired_at": reacquired_at,
                    "requested_exact_locator": exact_locator,
                    "final_locator": retrieved.final_locator,
                    "provider": retrieved.provider,
                    "http_status": retrieved.status_code,
                    "reacquisition_mode": reacquisition_mode,
                    "derivation_source": derivation_source,
                    "expected_digest": artifact.digest,
                    "expected_size": artifact.size,
                    "actual_digest": actual_digest,
                    "actual_size": actual_size,
                    "historical_metadata_rewritten": False,
                    "research_state_mutation_performed": False,
                }

                if _historical_equivalent(
                    artifact.digest, artifact.size, actual_digest, actual_size
                ):
                    restored = self._restore_identical(
                        artifact.artifact_id, retrieved.content
                    )
                    payload = {
                        **common,
                        "status": "IDENTICAL_REACQUISITION",
                        "verification_status": "verified",
                        "historical_restore_status": restored["status"],
                    }
                else:
                    version_token = uuid.uuid4().hex
                    if kind == "original":
                        new_capture_id = f"CAP-MRA-{version_token}"
                        artifact_id = f"{child.run_id}.{new_capture_id}.original"
                        relation = "reacquired_version_of_historical_capture"
                        rendition_role = "original"
                        parent_refs = (artifact.artifact_id,)
                        version_fields = {"new_capture_id": new_capture_id}
                        provenance_capture_id = new_capture_id
                        media_type = retrieved.media_type or original.media_type
                    else:
                        new_rendition_version_id = f"REN-MRA-{version_token}"
                        artifact_id = f"{child.run_id}.{new_rendition_version_id}.text"
                        relation = "regenerated_version_of_historical_rendition"
                        rendition_role = "text"
                        parent_refs = (original.artifact_id, artifact.artifact_id)
                        version_fields = {
                            "new_rendition_version_id": new_rendition_version_id
                        }
                        provenance_capture_id = capture_id
                        media_type = "text/plain"
                    new_artifact = self._store.put_bytes(
                        child,
                        role=_NEW_MATERIAL_ROLES[kind],
                        media_type=media_type,
                        content=retrieved.content,
                        artifact_id=artifact_id,
                        provenance={
                            "capture_id": provenance_capture_id,
                            "source_category": capture["source_category"],
                            "exact_locator": exact_locator,
                            "acquired_at": reacquired_at,
                            "rendition_role": rendition_role,
                            "relation": relation,
                            "historical_run_id": historical_run_id,
                            "historical_capture_id": capture_id,
                            "historical_artifact_id": artifact.artifact_id,
                            "historical_acquired_at": historical_acquired_at,
                            "provider": retrieved.provider,
                            "reacquisition_mode": reacquisition_mode,
                            "derivation_source": derivation_source,
                            "requested_exact_locator": exact_locator,
                            "final_locator": retrieved.final_locator,
                        },
                        parent_artifact_refs=parent_refs,
                    )
                    payload = {
                        **common,
                        "status": "NEW_MATERIAL_VERSION",
                        **version_fields,
                        "new_artifact_id": new_artifact.artifact_id,
                        "new_material_kind": kind,
                        "old_material_restored": False,
                        "requires_new_canonical_research_result": True,
                    }

                self._record_result(child.run_id, payload)
                child = _transition(
                    self._store,
                    child,
                    RunStatus.COMPLETED,
                    f"historical material reacquisition completed: {payload['status']}",
                )
                return {
                    **payload,
                    "reacquisition_run_id": child.run_id,
                    "idempotent_reuse": False,
                }
            except Exception as exc:
                issue = ExecutionIssue(
                    "MATERIAL_REACQUISITION_FAILED",
                    str(exc) or type(exc).__name__,
                    True,
                )
                failure_payload = {
                    "contract": _PAYLOAD_CONTRACT,
                    "status": "REACQUISITION_FAILED",
                    "historical_run_id": historical_run_id,
                    "historical_capture_id": capture_id,
                    "historical_artifact_id": artifact.artifact_id,
                    "kind": kind,
                    "historical_acquired_at": historical_acquired_at,
                    "reacquired_at": reacquired_at,
                    "requested_exact_locator": exact_locator,
                    "failure_reason": issue.message,
                    "historical_metadata_rewritten": False,
                    "research_state_mutation_performed": False,
                }
                self._record_result(child.run_id, failure_payload)
                child = _transition(
                    self._store,
                    child,
                    RunStatus.FAILED,
                    "historical material reacquisition failed",
                    failure=issue,
                )
                return {
                    **failure_payload,
                    "reacquisition_run_id": child.run_id,
                    "idempotent_reuse": False,
                }



class HistoricalMaterialReacquisitionHandler:
    def __init__(self, application, project_id: str, workspace_root: Path | None) -> None:
        self._service = HistoricalMaterialReacquisitionService(
            application.execution_store, project_id, workspace_root
        )

    def execute(self, payload: Mapping[str, Any], *, state: Any, actor: Any, proposal: Mapping[str, Any]):
        del state, actor, proposal
        result = self._service.reacquire(
            str(payload["historical_run_id"]),
            str(payload["capture_id"]),
            kind=str(payload["kind"]),
        )
        return HarnessServiceResult(
            result_reference=str(result.get("reacquisition_run_id") or result["artifact_id"]),
            data=result,
            research_state_mutation_performed=False,
        )


def ensure_material_reacquisition_action(application, project_id: str, workspace_root: Path | None) -> None:
    coordinator = application.coordinator
    action_registry = coordinator._actions
    service_registry = coordinator._services
    with _ACTION_REGISTRATION_LOCK:
        existing = {definition.action_type: definition for definition in coordinator.action_definitions()}
        definition = existing.get(_ACTION_TYPE)
        if definition is None:
            action_registry.register(
                ActionDefinition(
                    _ACTION_TYPE,
                    _PAYLOAD_CONTRACT,
                    "read_only",
                    "harness_service",
                    False,
                    human_decision_required=False,
                    service_id=_ACTION_TYPE,
                    payload_validator=material_reacquisition_payload,
                )
            )
        elif (
            definition.payload_contract != _PAYLOAD_CONTRACT
            or definition.effect != "read_only"
            or definition.route_kind != "harness_service"
            or definition.confirmation_required
            or definition.service_id != _ACTION_TYPE
        ):
            raise RuntimeError("desktop_research.material.reacquire action registration conflict")
        try:
            service_registry.resolve(_ACTION_TYPE)
        except ConversationRuntimeError as exc:
            if exc.code != "CONV-ROUTE-001":
                raise
            service_registry.register(
                _ACTION_TYPE,
                HistoricalMaterialReacquisitionHandler(application, project_id, workspace_root),
            )
