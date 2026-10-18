"""Release request binding, recording and release of a finalized Publication build (#494)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from plugins._infra.atomic_write import write_durable
from plugins.application_errors import LocalApplicationError

from .publication_release_support import (
    _RENDERER,
    SCHEMA_VERSION,
    _canonical_bytes,
    _digest,
    _json_bytes,
    _safe,
    _sha,
    _verify_docx_bytes,
)


class PublicationReleaseRequestMixin:
    def _require_current_project_config(self, build: Mapping[str, Any]) -> None:
        pin = build.get("publication_policy", {}).get("project_config_pin")
        if not build.get("publication_policy", {}).get("coverage"):
            return
        from ..workspace.workspace import LocalWorkspace

        with LocalWorkspace.open(self.workspace) as opened:
            if (
                not pin
                or pin["configuration_digest"] != opened.project_config["configuration_digest"]
            ):
                raise LocalApplicationError(
                    "PROJECT-CONFIG-STALE-001",
                    "Publication formal output is bound to an older Project Config",
                )

    @staticmethod
    def _formal_output(build):
        format_ = "pdf" if build.get("publication_policy", {}).get("coverage") else "docx"
        return next((row for row in build["outputs"] if row["format"] == format_), None)

    @staticmethod
    def _release_checks_pass(build: Mapping[str, Any], preview: Mapping[str, Any]) -> bool:
        if preview.get("source_epistemic_status") != "EMPIRICAL_RESEARCH_STATE":
            return False
        required_checks = [
            "citation_resolution",
            "exhibit_resolution",
            "cross_reference_resolution",
            "render_verification",
        ]
        if build.get("publication_profile", {}).get("profile_id") == "misco.publication":
            required_checks.extend(["formal_specification", "editorial_qa"])
        if build.get("publication_policy", {}).get("coverage"):
            required_checks.extend(["final_pdf_machine", "final_pdf_human"])
            if PublicationReleaseRequestMixin._formal_output(build) is None:
                return False

        def accepted(key):
            value = build["verification"].get(key)
            if value == "passed":
                return True
            final = build.get("publication_policy", {}).get("final_pdf", {})
            return (
                key == "formal_specification"
                and value == "warning"
                and bool(final.get("documented_deviations"))
                and build["verification"].get("final_pdf_machine") == "passed"
                and build["verification"].get("final_pdf_human") == "passed"
            )

        if any(not accepted(key) for key in required_checks):
            return False
        return not any(
            value == "failed"
            for key, value in build["verification"].items()
            if key != "writing_feedback"
        )

    def _request_binding(
        self,
        build: Mapping[str, Any],
        preview: Mapping[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        formal = self._formal_output(build)
        return {
            "project_ref": self.facade.project_id,
            "human_actor_id": actor_id,
            "source_preview": {
                "preview_id": build["build_id"],
                "preview_digest": preview["content_digest"],
            },
            "source_manuscript": build["source_manuscript"],
            "snapshot_binding": build["research_provenance"]["research_snapshot"],
            "publication_profile": build["publication_profile"],
            "publication_policy_digest": _sha(
                _canonical_bytes(build.get("publication_policy", {}))
            ),
            "output_binding": {
                "format": formal["format"],
                "digest": formal["digest"],
                "size": formal["size"],
            },
            "allowed_dispositions": ["approve_release"],
            **(
                {
                    "required_human_review": "Inspect every rendered page, including table cells, images, captions, reference targets, layout, and the delivered Publication editorial/formal rules before approving these exact output bytes."
                }
                if "layout_verification" in build["verification"]
                else {}
            ),
        }

    @staticmethod
    def _require_current_renderer(preview: Mapping[str, Any]) -> None:
        if preview.get("renderer") != _RENDERER:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-REBUILD-REQUIRED-001",
                "Create a new preview with the current renderer before a new approval; retain historical releases unchanged",
            )

    @staticmethod
    def _read_release_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                f"stored Publication record is unreadable: {path.name}",
            ) from exc
        if not isinstance(value, dict):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                f"stored Publication record must be an object: {path.name}",
            )
        return value

    def _verify_release_binding(
        self,
        manifest: Mapping[str, Any],
        *,
        release_id: str,
        decision_id: str,
        request: Mapping[str, Any],
        build: Mapping[str, Any],
        preview: Mapping[str, Any],
    ) -> None:
        """Verify against the independently approved build, not only self-digests."""
        formal = self._formal_output(build)
        expected = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "release_manifest",
            "release_id": release_id,
            "source_preview": {
                "preview_id": build["build_id"],
                "preview_digest": preview["content_digest"],
            },
            "source_manuscript": build["source_manuscript"],
            "research_provenance": build["research_provenance"],
            "publication_profile": build["publication_profile"],
            "publication_policy_digest": _sha(
                _canonical_bytes(build.get("publication_policy", {}))
            ),
            "output": {
                "relative_path": "artifact." + formal["format"],
                "artifact_reference": f"publication/releases/{release_id}/artifact."
                + formal["format"],
                "media_type": formal["media_type"],
                "size": formal["size"],
                "digest": formal["digest"],
            },
            "verification": build["verification"],
            "research_state_mutation_performed": False,
        }
        decision = manifest.get("human_release_decision")
        expected_decision = {
            "decision_id": decision_id,
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_release",
            "actor": {"actor_id": request["human_actor_id"], "actor_type": "human"},
        }
        if (
            manifest.get("content_digest") != _digest(manifest, "content_digest")
            or any(manifest.get(key) != value for key, value in expected.items())
            or not isinstance(decision, Mapping)
            or any(decision.get(key) != value for key, value in expected_decision.items())
            or decision.get("decision_digest") != _digest(decision, "decision_digest")
            or not isinstance(decision.get("decided_at"), str)
            or not decision["decided_at"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "stored Release does not match its exact approved request and preview build",
            )

    @staticmethod
    def _request_operation_id(request_id: str) -> str:
        # New IDs carry a nonce; the stable prefix addresses their operation.
        # Legacy IDs remain readable without assigning new historical facts.
        match = re.fullmatch(r"(PUBRELREQ-[0-9a-f]{24})(?:-[0-9a-f]{32})?", request_id)
        return match.group(1) if match else _safe(request_id)

    def _operation_path(self, request_id: str) -> Path:
        return self.root / "release-operations" / f"{self._request_operation_id(request_id)}.json"

    def _checked_record_path(self, path: Path) -> Path:
        from plugins.local_workspace_layout import safe_locator as _safe_locator

        return _safe_locator(
            self.workspace, path.relative_to(self.workspace).as_posix(), require_exists=False
        )

    def _load_release_operation(self, request_id: str) -> dict[str, Any] | None:
        path = self._checked_record_path(self._operation_path(request_id))
        if not path.exists():
            return None
        record = self._read_release_json(path)
        request = record.get("request")
        if (
            record.get("object_type") != "publication_release_operation"
            or record.get("operation_digest") != _digest(record, "operation_digest")
            or record.get("phase") not in {"PENDING", "DECIDED"}
            or not isinstance(request, dict)
            or not isinstance(request.get("request_id"), str)
            or self._request_operation_id(request["request_id"])
            != self._request_operation_id(request_id)
            or request.get("request_digest") != _digest(request, "request_digest")
            or (record["phase"] == "DECIDED") != isinstance(record.get("release"), dict)
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication operation record does not verify; restore its exact backup or request a new approval with renewal_of",
            )
        return record

    def _atomic_release_write(self, path: Path, data: bytes, *, replace: bool = False) -> None:
        path = self._checked_record_path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not write_durable(path, data, prefix=".publication-", replace=replace):
                if path.read_bytes() != data:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Publication recovery refuses to replace different existing bytes",
                    )
        except OSError as exc:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-WRITE-001",
                "Publication record could not be persisted; retry the exact request after resolving the I/O error",
            ) from exc

    def _write_release_operation(self, request: Mapping[str, Any], manifest=None) -> None:
        record = {
            "object_type": "publication_release_operation",
            "phase": "PENDING" if manifest is None else "DECIDED",
            "request": deepcopy(dict(request)),
            "release": deepcopy(manifest),
            "operation_digest": "",
        }
        record["operation_digest"] = _digest(record, "operation_digest")
        self._atomic_release_write(
            self._operation_path(request["request_id"]), _json_bytes(record), replace=True
        )

    @staticmethod
    def _lost_release_facts() -> None:
        raise LocalApplicationError(
            "APPLICATION-PUBLICATION-RECOVERY-REQUIRED-001",
            "Original Publication request/decision facts are unavailable. Restore the exact operation record, "
            "or issue release-request with renewal_of set to the old request_id and obtain a new approval; "
            "do not recreate the old identity or timestamps",
        )

    def request_release(
        self,
        build_id: str,
        actor_id: str,
        *,
        renewal_of: str | None = None,
    ) -> Mapping[str, Any]:
        if not isinstance(actor_id, str) or not actor_id:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "human release actor_id is required",
            )
        shown = self.show_preview(build_id)
        build = shown["build"]
        preview = shown["preview_manifest"]
        self._require_current_project_config(build)
        if not self._release_checks_pass(build, preview):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-CHECK-001",
                "Publication release checks have not passed",
            )
        basis = {
            "project_ref": self.facade.project_id,
            "build_id": build_id,
            "preview_digest": preview["content_digest"],
            "actor_id": actor_id,
        }
        if renewal_of is not None:
            if not isinstance(renewal_of, str) or not renewal_of.startswith("PUBRELREQ-"):
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INPUT-001",
                    "renewal_of must be a Publication request ID",
                )
            basis["renewal_of"] = _safe(renewal_of)
        operation_id = "PUBRELREQ-" + _sha(_canonical_bytes(basis)).split(":", 1)[1][:24]
        with self._file_lock(f"request-{operation_id}"):
            operation = self._load_release_operation(operation_id)
            legacy_path = self._checked_record_path(self._release_request_path(operation_id))
            if operation is not None or legacy_path.exists():
                request = (
                    operation["request"] if operation else self._read_release_json(legacy_path)
                )
                expected = self._request_binding(build, preview, actor_id)
                if (
                    self._request_operation_id(str(request.get("request_id", ""))) != operation_id
                    or request.get("request_digest") != _digest(request, "request_digest")
                    or any(request.get(key) != value for key, value in expected.items())
                    or request.get("renewal_of") != renewal_of
                ):
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Publication release request does not match its exact operation binding",
                    )
                if operation is None and request.get("recovery_contract") == "release-operation-v1":
                    # The replica cannot prove whether approval already committed.
                    self._lost_release_facts()
                path = self._checked_record_path(self._release_request_path(request["request_id"]))
                if path.exists():
                    if self._read_release_json(path) != request:
                        raise LocalApplicationError(
                            "APPLICATION-PUBLICATION-INTEGRITY-001",
                            "Publication request differs from its operation record",
                        )
                    return {"status": "VERIFIED_REUSE", "decision_request": request}
                self._atomic_release_write(path, _json_bytes(request))
                return {
                    "status": "RESTORED",
                    "decision_request": request,
                    "recovered_at": self.facade._application.clock.now(),
                }

            self._require_current_renderer(preview)
            from uuid import uuid4

            request: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "publication_release_decision_request",
                "request_id": operation_id + "-" + uuid4().hex,
                **deepcopy(self._request_binding(build, preview, actor_id)),
                "issued_at": self.facade._application.clock.now(),
                "recovery_contract": "release-operation-v1",
                "renewal_of": renewal_of,
                "request_digest": "",
            }
            request["request_digest"] = _digest(request, "request_digest")
            # The operation is the write-ahead record for request/decision facts.
            # A response loss cannot invent another issued_at or decided_at.
            self._write_release_operation(request)
            self._atomic_release_write(
                self._release_request_path(request["request_id"]), _json_bytes(request)
            )
        return {"status": "PENDING", "decision_request": request}

    def _load_release_request(self, request_id: str) -> Mapping[str, Any]:
        operation = self._load_release_operation(request_id)
        path = self._checked_record_path(self._release_request_path(request_id))
        if not path.exists():
            # Older replicas used the complete nonce ID. Probe only the exact
            # caller-supplied identity; do not scan unrelated request history.
            legacy = self._checked_record_path(
                self.root / "release-requests" / f"{_safe(request_id)}.json"
            )
            if legacy.exists():
                path = legacy
        if operation is not None:
            request = operation["request"]
            if path.exists() and self._read_release_json(path) != request:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "Publication request differs from its operation record",
                )
        elif path.is_file():
            request = self._read_release_json(path)
        else:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication request is missing; restore the exact record or issue a new release-request and approval",
            )
        if request.get("request_id") != request_id or request.get("request_digest") != _digest(
            request, "request_digest"
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication release request identity/digest does not verify",
            )
        if request.get("project_ref") != self.facade.project_id:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release request belongs to another project",
            )
        return request

    def release(self, build_id: str, response: Mapping[str, Any]) -> Mapping[str, Any]:
        required = {"request_id", "request_digest", "disposition", "actor_id"}
        if not isinstance(response, Mapping) or set(response) != required:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "release requires the exact Publication release decision response",
            )
        request = self._load_release_request(str(response["request_id"]))
        if (
            response.get("request_digest") != request["request_digest"]
            or response.get("actor_id") != request["human_actor_id"]
            or response.get("disposition") != "approve_release"
            or response.get("disposition") not in request["allowed_dispositions"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release response does not match its exact decision request",
            )
        shown = self.show_preview(build_id)
        build = shown["build"]
        preview = shown["preview_manifest"]
        if not self._release_checks_pass(build, preview):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-CHECK-001",
                "Publication release checks have not passed",
            )
        if any(
            request.get(key) != value
            for key, value in self._request_binding(
                build, preview, str(response["actor_id"])
            ).items()
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-RELEASE-DECISION-001",
                "Publication release request is stale or bound to another build/output",
            )
        formal = self._formal_output(build)
        decision_id = (
            "PUBRELDEC-"
            + hashlib.sha256(
                (
                    request["request_digest"]
                    + str(response["actor_id"])
                    + str(response["disposition"])
                ).encode("utf-8")
            ).hexdigest()[:24]
        )
        release_id = (
            "REL-"
            + hashlib.sha256(
                (build_id + preview["content_digest"] + decision_id).encode("utf-8")
            ).hexdigest()[:24]
        )
        operation_id = self._request_operation_id(request["request_id"])
        with self._file_lock(f"request-{operation_id}"):
            operation = self._load_release_operation(request["request_id"])
            if operation is not None and operation["request"] != request:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "Publication operation changed its request identity",
                )
            target = self._checked_record_path(self.root / "releases" / release_id)
            manifest_path = self._checked_record_path(target / "release-manifest.json")
            artifact = self._checked_record_path(target / ("artifact." + formal["format"]))
            payload = (self._build_path(build_id) / formal["relative_path"]).read_bytes()
            if (
                len(payload) != int(formal["size"])
                or _sha(payload) != formal["digest"]
                or (formal["format"] == "docx" and not _verify_docx_bytes(payload))
            ):
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication DOCX does not match its exact approved preview build",
                )
            existing = self._read_release_json(manifest_path) if manifest_path.exists() else None
            if existing is not None:
                self._verify_release_binding(
                    existing,
                    release_id=release_id,
                    decision_id=decision_id,
                    request=request,
                    build=build,
                    preview=preview,
                )
            if artifact.exists():
                try:
                    matches = artifact.is_file() and artifact.read_bytes() == payload
                except OSError as exc:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "stored Release artifact is unreadable",
                    ) from exc
                if not matches:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "stored Release artifact differs from the exact approved output",
                    )

            fresh = operation is not None and operation["phase"] == "PENDING"
            operation_restored = False
            if operation is not None and operation["phase"] == "DECIDED":
                manifest = operation["release"]
                self._verify_release_binding(
                    manifest,
                    release_id=release_id,
                    decision_id=decision_id,
                    request=request,
                    build=build,
                    preview=preview,
                )
                if existing is not None and existing != manifest:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Release differs from its retained decision facts",
                    )
            elif existing is not None:
                if fresh:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Release exists before its recorded decision",
                    )
                # Supported legacy recovery: the original immutable manifest,
                # including its decision time, still exists and verifies.
                manifest = existing
                self._write_release_operation(request, manifest)
                operation_restored = True
            elif operation is None:
                self._lost_release_facts()
            else:
                self._require_current_renderer(preview)
                self._require_current_project_config(build)
                decision = {
                    "decision_id": decision_id,
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_release",
                    "actor": {"actor_id": str(response["actor_id"]), "actor_type": "human"},
                    "decided_at": self.facade._application.clock.now(),
                    "decision_digest": "",
                }
                decision["decision_digest"] = _digest(decision, "decision_digest")
                manifest = {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "release_manifest",
                    "release_id": release_id,
                    "source_preview": {
                        "preview_id": build_id,
                        "preview_digest": preview["content_digest"],
                    },
                    "source_manuscript": deepcopy(build["source_manuscript"]),
                    "research_provenance": deepcopy(build["research_provenance"]),
                    "publication_profile": deepcopy(build["publication_profile"]),
                    "publication_policy_digest": _sha(
                        _canonical_bytes(build.get("publication_policy", {}))
                    ),
                    "output": {
                        "relative_path": "artifact." + formal["format"],
                        "artifact_reference": f"publication/releases/{release_id}/artifact."
                        + formal["format"],
                        "media_type": formal["media_type"],
                        "size": len(payload),
                        "digest": _sha(payload),
                    },
                    "verification": deepcopy(build["verification"]),
                    "human_release_decision": decision,
                    "research_state_mutation_performed": False,
                    "content_digest": "",
                }
                manifest["content_digest"] = _digest(manifest, "content_digest")
                self._write_release_operation(request, manifest)

            restored = ["release-operation"] if operation_restored else []
            for part, data in (
                (self._release_request_path(request["request_id"]), _json_bytes(request)),
                (artifact, payload),
                (manifest_path, _json_bytes(manifest)),
            ):
                if not part.exists():
                    self._atomic_release_write(part, data)
                    restored.append(part.name)
            result = {
                "status": "RELEASED" if fresh else ("RESTORED" if restored else "VERIFIED_REUSE"),
                "release": manifest,
                "research_state_mutation_performed": False,
            }
            if restored and not fresh:
                result["restored_components"] = restored
                result["recovered_at"] = self.facade._application.clock.now()
            return result
