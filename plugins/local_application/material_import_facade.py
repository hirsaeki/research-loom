from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research import DesktopResearchCaptureService
from plugins.local_execution_store import (
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
    open_read_only_execution_store,
)

from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture
from .retention_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


_INTAKE_RELATIVE = Path("intake") / "material-sources"
_STAGE_MANIFEST = "stage.json"
_ORIGINAL_ROLE = "desktop_research.original_capture"
_TEXT_ROLE = "desktop_research.text_rendition"


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _resolve_source_execution_root(source: str | Path) -> Path:
    if not isinstance(source, (str, Path)) or not str(source):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-STAGE-001",
            "material source path must be a non-empty path",
        )
    raw = Path(source).expanduser()
    if _link_like(raw):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-STAGE-001",
            "material source root may not be a link or junction",
        )
    try:
        source_root = raw.resolve(strict=True)
    except OSError as exc:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-STAGE-001",
            "material source path does not exist",
        ) from exc
    candidates = []
    for candidate in (
        source_root,
        source_root / "execution",
        source_root / ".research-loom" / "execution",
    ):
        if candidate.is_dir() and (candidate / "execution.db").is_file():
            resolved = candidate.resolve()
            if resolved not in candidates:
                candidates.append(resolved)
    if len(candidates) != 1:
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-STAGE-001",
            "material source must resolve unambiguously to one execution/material child root",
        )
    return candidates[0]


def _assert_link_free(root: Path) -> None:
    if _link_like(root):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-STAGE-001",
            "staged material source may not be a link or junction",
        )
    for path in root.rglob("*"):
        if _link_like(path):
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-STAGE-001",
                "staged material source contains a link or junction",
            )


def _stage_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).name != value
        or value in {".", ".."}
    ):
        raise LocalApplicationError(
            "APPLICATION-MATERIAL-IMPORT-001",
            "stage_id is invalid",
        )
    return value


def _source_filename(provenance: Mapping[str, Any], key: str) -> str | None:
    value = provenance.get(key)
    if not isinstance(value, str) or not value:
        return None
    return Path(value).name


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Stage a portable source root, then copy verified material into current durability."""

    def _material_intake_root(self) -> Path:
        if self._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-STAGE-001",
                "staged material import requires a workspace-backed application",
            )
        workspace = self._workspace_root.resolve()
        current = workspace
        for part in _INTAKE_RELATIVE.parts:
            current = current / part
            if (current.exists() or current.is_symlink()) and _link_like(current):
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-STAGE-001",
                    "material intake path may not contain a link or junction",
                )
        managed = (workspace / ".research-loom").resolve(strict=False)
        intake = (workspace / _INTAKE_RELATIVE).resolve(strict=False)
        try:
            intake.relative_to(managed)
        except ValueError:
            pass
        else:  # pragma: no cover - constant layout guard
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-STAGE-001",
                "material intake must remain outside the Parent Durable Store Root",
            )
        return intake

    def stage_external_material_source(self, source: str | Path) -> Mapping[str, Any]:
        source_execution = _resolve_source_execution_root(source)
        intake = self._material_intake_root()
        intake.mkdir(parents=True, exist_ok=True)
        stage_id = self._application.ids.new("MSTG-")
        stage_root = intake / stage_id
        execution_root = stage_root / "execution"
        if stage_root.exists():
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-STAGE-001",
                "material stage identity already exists",
            )
        try:
            shutil.copytree(
                source_execution,
                execution_root,
                symlinks=True,
                ignore=shutil.ignore_patterns("staging", "large-original-locks", "*.lock"),
            )
            _assert_link_free(execution_root)
            with open_read_only_execution_store(execution_root):
                pass
            manifest = {
                "schema_version": "0.1.0",
                "stage_id": stage_id,
                "staged_at": self._application.clock.now(),
                "source_kind": "portable_execution_material_root",
                "execution_root": "execution",
            }
            (stage_root / _STAGE_MANIFEST).write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            shutil.rmtree(stage_root, ignore_errors=True)
            if isinstance(exc, LocalApplicationError):
                raise
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-STAGE-001",
                "material source could not be staged as a readable portable root",
            ) from exc
        return {
            "status": "MATERIAL_SOURCE_STAGED",
            "stage_id": stage_id,
            "staged_source": {
                "root": str(_INTAKE_RELATIVE / stage_id),
                "execution_root": str(_INTAKE_RELATIVE / stage_id / "execution"),
            },
            "durable_state_registered": False,
        }

    def _open_staged_material_source(self, stage_id: str):
        stage_id = _stage_id(stage_id)
        stage_root = self._material_intake_root() / stage_id
        if _link_like(stage_root):
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-IMPORT-001",
                "staged material source may not be a link or junction",
            )
        manifest_path = stage_root / _STAGE_MANIFEST
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-IMPORT-001",
                "staged material source manifest is missing or invalid",
            ) from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("stage_id") != stage_id
            or manifest.get("source_kind") != "portable_execution_material_root"
            or manifest.get("execution_root") != "execution"
        ):
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-IMPORT-001",
                "staged material source manifest does not match the requested stage",
            )
        execution_root = stage_root / "execution"
        _assert_link_free(execution_root)
        try:
            return open_read_only_execution_store(execution_root)
        except (OSError, ValueError, LocalExecutionStoreError) as exc:
            raise LocalApplicationError(
                "APPLICATION-MATERIAL-IMPORT-001",
                "staged material source cannot be opened read-only",
            ) from exc

    def import_staged_external_material(
        self,
        stage_id: str,
        *,
        source_run_id: str,
        source_capture_id: str,
        destination_run_id: str,
    ) -> Mapping[str, Any]:
        for name, value in (
            ("source_run_id", source_run_id),
            ("source_capture_id", source_capture_id),
            ("destination_run_id", destination_run_id),
        ):
            if not isinstance(value, str) or not value:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-001",
                    f"{name} must be a non-empty string",
                )

        destination_run, context_extension = self._desktop_external_run(destination_run_id)
        destination_store = self._application.execution_store
        with self._open_staged_material_source(stage_id) as source_store:
            source_run = source_store.load_run(source_run_id)
            if (
                source_run is None
                or source_run.capability_id != "desktop-research"
                or source_run.function_id != "investigate"
                or source_run.execution_mode != "real"
            ):
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-404",
                    "source Run is not a real Desktop Research investigate Run",
                )
            try:
                _, original, rendition, projection = _artifact_pair_for_capture(
                    source_store,
                    source_run.project_ref,
                    source_run_id,
                    source_capture_id,
                )
            except LocalApplicationError:
                raise
            except (
                KeyError,
                FileNotFoundError,
                LocalExecutionStoreIntegrityError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-VERIFY-001",
                    "selected staged material is missing, corrupt, unreadable, or incorrectly bound",
                ) from exc

            source_category = str(projection["source_category"])
            allowed_categories = {
                str(item)
                for item in context_extension.get("allowed_source_categories", ())
            }
            if source_category not in allowed_categories:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-001",
                    f"source_category is not allowed by destination Desktop Research Run: {source_category}",
                )
            budget = context_extension.get("budget")
            if not isinstance(budget, Mapping):
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-001",
                    "destination Desktop Research Run has no valid capture budget",
                )
            try:
                capture_limit = int(budget["max_acquired_source_captures"])
                text_limit = int(budget["max_text_rendition_bytes"])
                artifact_limit = int(budget.get("max_capture_artifacts", 2 * capture_limit))
                original_declared = budget.get("max_original_capture_bytes")
                original_limit = (
                    destination_store.config.max_artifact_bytes
                    if original_declared is None
                    else int(original_declared)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-001",
                    "destination Desktop Research capture budget is malformed",
                ) from exc
            if min(capture_limit, text_limit, artifact_limit, original_limit) < 0:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-001",
                    "destination Desktop Research capture budget is malformed",
                )
            pair_limit = min(capture_limit, artifact_limit // 2)
            if (
                pair_limit <= 0
                or original.size > original_limit
                or rendition.size > text_limit
            ):
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-001",
                    "selected material exceeds destination Desktop Research capture budget",
                )
            try:
                original_path = source_store.verified_artifact_path(original.artifact_id)
                text_payload = source_store.load_artifact_verified_once(rendition.artifact_id)
                text_payload.content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-VERIFY-001",
                    "selected text rendition is not valid UTF-8",
                ) from exc
            except (
                KeyError,
                FileNotFoundError,
                LocalExecutionStoreIntegrityError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-VERIFY-001",
                    "selected staged material is missing, corrupt, unreadable, or incorrectly bound",
                ) from exc

            imported_at = self._application.clock.now()
            import_provenance = {
                "material_import": {
                    "stage_id": stage_id,
                    "imported_at": imported_at,
                    "historical_source_run_id": source_run_id,
                    "historical_source_capture_id": source_capture_id,
                    "historical_original_artifact_id": original.artifact_id,
                    "historical_text_artifact_id": rendition.artifact_id,
                    "historical_original_digest": original.digest,
                    "historical_text_digest": rendition.digest,
                }
            }
            original_name = _source_filename(
                original.provenance, "original_source_filename"
            )
            text_name = _source_filename(
                rendition.provenance, "text_rendition_source_filename"
            )
            if original_name is not None:
                import_provenance["original_source_filename"] = original_name
            if text_name is not None:
                import_provenance["text_rendition_source_filename"] = text_name

            trusted = {
                "capture_id": source_capture_id,
                "source_category": source_category,
                "exact_locator": str(projection["source_locator"]),
                "acquired_at": str(projection["acquired_at"]),
                **deepcopy(import_provenance),
            }
            original_id = f"{destination_run.run_id}.{source_capture_id}.original"
            text_id = f"{destination_run.run_id}.{source_capture_id}.text"
            role_byte_limits = {_TEXT_ROLE: text_limit}
            if original_declared is not None:
                role_byte_limits[_ORIGINAL_ROLE] = original_limit
            else:
                role_byte_limits[_ORIGINAL_ROLE] = destination_store.config.max_artifact_bytes
            role_count_limits = {
                _ORIGINAL_ROLE: pair_limit,
                _TEXT_ROLE: pair_limit,
            }
            try:
                imported_original, imported_text = (
                    destination_store.put_desktop_research_capture_files(
                        destination_run,
                        original_path=original_path,
                        original_media_type=original.media_type,
                        original_artifact_id=original_id,
                        original_provenance={**trusted, "rendition_role": "original"},
                        text_content=text_payload.content,
                        text_artifact_id=text_id,
                        text_provenance={**trusted, "rendition_role": "text"},
                        max_original_bytes=original_limit,
                        role_byte_limits=role_byte_limits,
                        role_count_limits=role_count_limits,
                        expected_status=RunStatus.RUNNING,
                        expected_original_digest=original.digest,
                        expected_original_size=original.size,
                        expected_text_digest=rendition.digest,
                        expected_text_size=rendition.size,
                    )
                )
            except (
                LocalExecutionStoreError,
                LocalExecutionStoreIntegrityError,
                PermissionError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                raise LocalApplicationError(
                    "APPLICATION-MATERIAL-IMPORT-VERIFY-001",
                    "verified staged material could not be copied into destination durability",
                ) from exc

        detail = DesktopResearchCaptureService._detail(
            source_capture_id,
            source_category,
            str(projection["source_locator"]),
            str(projection["acquired_at"]),
            imported_original,
            imported_text,
        )
        return {
            "status": "MATERIAL_IMPORTED",
            "stage_id": stage_id,
            "source_material": {
                "run_id": source_run_id,
                "capture_id": source_capture_id,
                "original_digest": original.digest,
                "text_rendition_digest": rendition.digest,
            },
            "destination": {
                "run_id": destination_run_id,
                "capture": deepcopy(dict(detail)),
            },
            "research_state_mutation_performed": False,
            "source_authority_imported": False,
        }
