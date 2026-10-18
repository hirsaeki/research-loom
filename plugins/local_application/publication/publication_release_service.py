from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from plugins._infra.file_lock import lock_byte, unlock_byte, write_sentinel_if_empty
from plugins.application_errors import LocalApplicationError
from plugins.local_durable_store import register_optional_path, require_optional_available

from .publication_dialect import PublicationDialect, dialect_for
from .publication_exhibits import prepare_exhibits, render_input_digest
from .publication_input import inspect_inputs
from .publication_release_requests import PublicationReleaseRequestMixin
from .publication_release_support import (
    _RENDERER,
    _STYLE_MAP_PIN,
    _TEMPLATE_PIN,
    MAX_OUTPUT_BYTES,
    SCHEMA_VERSION,
    SERVICE_VERSION,
    _canonical_bytes,
    _digest,
    _json_bytes,
    _publication_policy,
    _safe,
    _sha,
    _validate_preview_manifest,
    _validate_publication_inputs,
    _verify_docx_bytes,
)
from .publication_render import PublicationRenderMixin


class PublicationReleaseService(PublicationReleaseRequestMixin, PublicationRenderMixin):
    def __init__(self, facade, *, dialects: Mapping[str, PublicationDialect] | None = None) -> None:
        if facade._workspace_root is None:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-WORKSPACE-001",
                "Publication requires a local workspace",
            )
        self.facade = facade
        self.workspace = Path(facade._workspace_root)
        self.root = self.workspace / ".research-loom" / "publication"
        require_optional_available(self.root, LocalApplicationError)
        self.dialects = dict(dialects or {})

    def _dialect(self, profile: Mapping[str, Any]) -> PublicationDialect:
        return dialect_for(profile, self.dialects)

    @contextmanager
    def _file_lock(self, name: str):
        require_optional_available(self.root, LocalApplicationError)
        lock_root = self.root / "locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        register_optional_path(self.root)
        path = lock_root / f"{_safe(name)}.lock"
        handle = path.open("a+b")
        try:
            write_sentinel_if_empty(handle.fileno(), fsync=False)
            lock_byte(handle.fileno(), blocking=True)
            try:
                yield
            finally:
                unlock_byte(handle.fileno())
        finally:
            handle.close()

    def _profile_pin(self, package: Mapping[str, Any]) -> Mapping[str, Any]:
        pins = package.get("effective_profile_set", {}).get("profile_pins", [])
        rows = [
            row
            for row in pins
            if isinstance(row, Mapping) and row.get("profile_type") == "publication"
        ]
        if len(rows) != 1:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-PROFILE-001",
                "exactly one pinned Publication Profile is required",
            )
        row = rows[0]
        digest = str(row.get("content_digest") or row.get("manifest_sha256") or "")
        if digest and not digest.startswith("sha256:"):
            digest = "sha256:" + digest
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-PROFILE-001",
                "Publication Profile digest is invalid",
            )
        return {
            "profile_id": str(row["profile_id"]),
            "profile_version": str(row["profile_version"]),
            "content_digest": digest,
        }

    def _build_path(self, build_id: str) -> Path:
        return self.root / "builds" / _safe(build_id)

    def _release_request_path(self, request_id: str) -> Path:
        # One request replica per operation, addressed without scanning nonce IDs.
        # The full immutable request ID remains in the document and is verified.
        return self.root / "release-requests" / f"{self._request_operation_id(request_id)}.json"

    @staticmethod
    def _validation_checks(
        checks: Mapping[str, str], issues: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        code_for_check = {
            "citation_resolution": {"UNRESOLVED_CITATION"},
            "exhibit_resolution": {
                "MISSING_EXHIBIT",
                "UNSUPPORTED_EXHIBIT",
                "VISUAL_ASSET_UNAVAILABLE",
            },
            "cross_reference_resolution": {"UNRESOLVED_CROSS_REFERENCE"},
            "render_verification": {item["code"] for item in issues if item["blocking"]},
            "layout_verification": set(),
            "writing_feedback": {"WRITING_FEEDBACK_OPEN"},
            "formal_specification": {
                "PUBLICATION_FORMAL_INPUT_MISSING",
                "PUBLICATION_FORMAL_VALUE_UNSUPPORTED",
            },
            "editorial_qa": set(),
            "final_pdf_machine": set(),
            "final_pdf_human": set(),
        }
        result = []
        for check_id, status in checks.items():
            issue_code = code_for_check[check_id]
            refs = [str(issue["defect_id"]) for issue in issues if issue.get("code") in issue_code]
            result.append(
                {
                    "check_id": check_id.replace("_", "-"),
                    "status": status,
                    "defect_refs": refs,
                }
            )
        return result

    def _preview_manifest(
        self,
        *,
        build_id: str,
        revision: Mapping[str, Any],
        package: Mapping[str, Any],
        profile: Mapping[str, Any],
        docx: bytes,
        issues: list[Mapping[str, Any]],
        checks: Mapping[str, str],
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        generated_at = str(
            revision.get("created_at")
            or package.get("provenance", {}).get("generated_at")
            or "1970-01-01T00:00:00Z"
        )
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "preview_artifact_manifest",
            "preview_id": build_id,
            "source_manuscript": {
                "manuscript_id": str(revision["revision_id"]),
                "manuscript_digest": str(revision["revision_digest"]),
            },
            "source_epistemic_status": str(package["source_epistemic_status"]),
            "publication_profile": deepcopy(dict(profile)),
            "template_pin": deepcopy(_TEMPLATE_PIN),
            "style_map_pin": deepcopy(_STYLE_MAP_PIN),
            "renderer": deepcopy(_RENDERER),
            "outputs": [
                {
                    "format": "docx",
                    "path": "formal.docx",
                    "output_digest": _sha(docx),
                    "input_template_digest": _TEMPLATE_PIN["content_digest"],
                    "input_style_map_digest": _STYLE_MAP_PIN["content_digest"],
                }
            ],
            "validation_checks": self._validation_checks(checks, issues),
            "preview_only": True,
            "release_eligible": False,
            "published_artifact": False,
            "release_manifest": False,
            "content_digest": "",
            "provenance": {
                "generated_at": generated_at,
                "tool_id": "research-loom.publication",
                "tool_version": SERVICE_VERSION,
                "input_digests": [
                    str(revision["revision_digest"]),
                    str(package["package_digest"]),
                    str(profile["content_digest"]),
                    _TEMPLATE_PIN["content_digest"],
                    _STYLE_MAP_PIN["content_digest"],
                ],
            },
        }
        manifest["content_digest"] = _digest(manifest, "content_digest")
        _validate_preview_manifest(manifest)
        return manifest

    def _build_receipt(
        self,
        *,
        build_id: str,
        key_digest: str,
        composition_id: str,
        revision: Mapping[str, Any],
        package: Mapping[str, Any],
        profile: Mapping[str, Any],
        preview_manifest: Mapping[str, Any],
        markdown: bytes,
        docx: bytes,
        issues: list[Mapping[str, Any]],
        checks: Mapping[str, str],
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "publication_build_receipt",
            "build_id": build_id,
            "build_key_digest": key_digest,
            "preview_manifest_digest": preview_manifest["content_digest"],
            "source_manuscript": {
                "composition_id": composition_id,
                "revision_id": revision["revision_id"],
                "revision_digest": revision["revision_digest"],
            },
            "research_provenance": {
                "research_package_id": package["package_id"],
                "research_package_digest": package["package_digest"],
                "research_snapshot": deepcopy(package["source_research_snapshot"]),
            },
            "publication_profile": deepcopy(dict(profile)),
            "publication_policy": deepcopy(dict(policy)),
            "outputs": [
                {
                    "format": "markdown",
                    "relative_path": "preview.md",
                    "media_type": "text/markdown",
                    "size": len(markdown),
                    "digest": _sha(markdown),
                },
                {
                    "format": "docx",
                    "relative_path": "formal.docx",
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "size": len(docx),
                    "digest": _sha(docx),
                },
            ],
            "verification": deepcopy(dict(checks)),
            "verification_scope": "Native DOCX structure, literal table cells, exact PNG parts, captions and resolved reference text; rendered layout requires human review.",
            "issues": deepcopy(list(issues)),
            "research_state_mutation_performed": False,
            "content_digest": "",
        }
        receipt["content_digest"] = _digest(receipt, "content_digest")
        return receipt

    def _load_build(self, build_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
        target = self._build_path(build_id)
        receipt_path = target / "build-receipt.json"
        manifest_path = target / "preview-manifest.json"
        if not receipt_path.is_file() or not manifest_path.is_file():
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-404", "Publication preview build does not exist"
            )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("content_digest") != _digest(receipt, "content_digest"):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication build receipt digest does not verify",
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_preview_manifest(manifest)
        if manifest.get("content_digest") != _digest(manifest, "content_digest"):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication preview manifest digest does not verify",
            )
        if (
            manifest.get("preview_id") != build_id
            or receipt.get("preview_manifest_digest") != manifest.get("content_digest")
            or receipt.get("source_manuscript", {}).get("revision_digest")
            != manifest.get("source_manuscript", {}).get("manuscript_digest")
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication build and canonical preview manifest binding mismatch",
            )
        for output in receipt.get("outputs", []):
            path = target / str(output["relative_path"])
            if not path.is_file():
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication output is missing",
                )
            payload = path.read_bytes()
            if len(payload) != int(output["size"]) or _sha(payload) != output["digest"]:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "stored Publication output no longer matches its build receipt",
                )
        formal = next((row for row in receipt["outputs"] if row.get("format") == "docx"), None)
        canonical = next((row for row in manifest["outputs"] if row.get("format") == "docx"), None)
        if (
            formal is None
            or canonical is None
            or formal["digest"] != canonical["output_digest"]
            or formal["relative_path"] != canonical["path"]
        ):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "Publication formal output binding does not verify",
            )
        if not _verify_docx_bytes((target / formal["relative_path"]).read_bytes()):
            raise LocalApplicationError(
                "APPLICATION-PUBLICATION-INTEGRITY-001",
                "stored Publication DOCX failed structural XML verification",
            )
        final_pdf = receipt.get("publication_policy", {}).get("final_pdf")
        if final_pdf:
            pdf = next((row for row in receipt["outputs"] if row.get("format") == "pdf"), None)
            canonical_pdf = next(
                (row for row in manifest["outputs"] if row.get("format") == "pdf"), None
            )
            if (
                pdf is None
                or canonical_pdf is None
                or pdf["digest"] != canonical_pdf["output_digest"]
                or pdf["relative_path"] != canonical_pdf["path"]
                or pdf["digest"] != final_pdf.get("pdf_digest")
            ):
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-INTEGRITY-001",
                    "Publication final PDF and review/manifest binding does not verify",
                )
        return receipt, manifest, target

    def build_preview(
        self,
        composition_id: str,
        revision_id: str | None = None,
        publication_inputs: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        publication_inputs = _validate_publication_inputs(publication_inputs)
        inspection = inspect_inputs(self.facade, composition_id, revision_id)
        package = inspection["source_package_document"]
        profile = self._profile_pin(package)
        from ..workspace.workspace import LocalWorkspace

        with LocalWorkspace.open(self.workspace) as opened:
            project_config = deepcopy(dict(opened.project_config))
        dialect = self._dialect(profile)
        policy = _publication_policy(
            package, profile, publication_inputs, project_config, dialect=dialect
        )
        revision = inspection["revision"]
        inspection["publication_policy"] = policy
        inspection["publication_profile"] = profile
        inspection["exhibit_blocks"] = prepare_exhibits(inspection, self.workspace, dialect=dialect)
        build_key = {
            "manuscript_revision_id": revision["revision_id"],
            "manuscript_revision_digest": revision["revision_digest"],
            "research_package_id": package["package_id"],
            "research_package_digest": package["package_digest"],
            "publication_profile": profile,
            "template_pin": _TEMPLATE_PIN,
            "style_map_pin": _STYLE_MAP_PIN,
            "renderer": _RENDERER,
            "publication_inputs": publication_inputs,
            "publication_policy": policy,
            "render_inputs": render_input_digest(
                inspection["exhibit_blocks"], inspection["visual_diagnostics"]
            ),
        }
        key_digest = _sha(_canonical_bytes(build_key))
        build_id = "PUB-" + key_digest.split(":", 1)[1][:24]
        with self._file_lock(f"build-{build_id}"):
            target = self._build_path(build_id)
            if (target / "build-receipt.json").is_file():
                existing, manifest, _ = self._load_build(build_id)
                if existing.get("build_key_digest") != key_digest:
                    raise LocalApplicationError(
                        "APPLICATION-PUBLICATION-INTEGRITY-001",
                        "Publication build identity conflicts with stored content",
                    )
                return {
                    "status": "VERIFIED_REUSE",
                    "build": existing,
                    "preview_manifest": manifest,
                    "research_state_mutation_performed": False,
                }

            markdown, docx, issues, checks = self._render(inspection)
            manifest = self._preview_manifest(
                build_id=build_id,
                revision=revision,
                package=package,
                profile=profile,
                docx=docx,
                issues=issues,
                checks=checks,
                policy=policy,
            )
            build_receipt = self._build_receipt(
                build_id=build_id,
                key_digest=key_digest,
                composition_id=composition_id,
                revision=revision,
                package=package,
                profile=profile,
                preview_manifest=manifest,
                markdown=markdown,
                docx=docx,
                issues=issues,
                checks=checks,
                policy=policy,
            )
            self.root.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{build_id}.", dir=target.parent))
            try:
                (staging / "preview.md").write_bytes(markdown)
                (staging / "formal.docx").write_bytes(docx)
                (staging / "preview-manifest.json").write_bytes(_json_bytes(manifest))
                (staging / "build-receipt.json").write_bytes(_json_bytes(build_receipt))
                os.rename(staging, target)
            except OSError as exc:
                raise LocalApplicationError(
                    "APPLICATION-PUBLICATION-WRITE-001",
                    "Publication preview could not be persisted",
                ) from exc
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        return {
            "status": "BUILT",
            "build": build_receipt,
            "preview_manifest": manifest,
            "research_state_mutation_performed": False,
        }

    def show_preview(self, build_id: str) -> Mapping[str, Any]:
        build, manifest, root = self._load_build(build_id)
        return {
            "status": "OK",
            "build": build,
            "preview_manifest": manifest,
            "preview_markdown": (root / "preview.md").read_text(encoding="utf-8"),
            "output_root": str(root),
            "research_state_mutation_performed": False,
        }

    def finalize_pdf(self, build_id: str, input_: Mapping[str, Any]) -> Mapping[str, Any]:
        """Import a Host-rendered PDF into a new immutable, reviewed build."""
        from plugins.local_workspace_layout import safe_locator as _safe_locator

        from .publication_pdf import coverage_review, inspect_pdf

        allowed = {
            "pdf_path",
            "pdf_digest",
            "source_docx_digest",
            "project_config_digest",
            "host_receipt",
            "review",
        }
        if not isinstance(input_, Mapping) or set(input_) != allowed:
            raise LocalApplicationError(
                "PUBLICATION-PDF-INPUT",
                "PDF finalization requires exact output/config bindings, Host receipt and per-output review",
            )
        source, source_manifest, root = self._load_build(build_id)
        policy = source.get("publication_policy", {})
        dialect = self._dialect(source.get("publication_profile", {}))
        if (
            not dialect.formal_report_requested(policy)
            or policy.get("document_mode") != "formal_report"
            or not policy.get("coverage")
            or policy.get("missing_inputs")
            or policy.get("final_pdf")
        ):
            raise LocalApplicationError(
                "PUBLICATION-PDF-INPUT",
                "PDF finalization requires a complete formal-report draft under a coverage Profile",
            )
        self._require_current_renderer(source_manifest)
        self._require_current_project_config(source)
        docx = next(row for row in source["outputs"] if row["format"] == "docx")
        if (
            input_["source_docx_digest"] != docx["digest"]
            or input_["project_config_digest"]
            != policy["project_config_pin"]["configuration_digest"]
        ):
            raise LocalApplicationError(
                "PUBLICATION-PDF-BINDING",
                "PDF finalization does not match the pinned DOCX and Project Config",
            )
        path = _safe_locator(self.workspace, str(input_["pdf_path"]))
        try:
            if path.stat().st_size > MAX_OUTPUT_BYTES:
                raise LocalApplicationError(
                    "PUBLICATION-PDF-INPUT", "PDF exceeds the supported bound"
                )
            payload = path.read_bytes()
        except OSError as exc:
            raise LocalApplicationError(
                "PUBLICATION-PDF-INPUT", "PDF is missing or unreadable"
            ) from exc
        if _sha(payload) != input_["pdf_digest"]:
            raise LocalApplicationError(
                "PUBLICATION-PDF-BINDING", "PDF digest differs from the exact input binding"
            )
        host = input_["host_receipt"]
        if (
            not isinstance(host, Mapping)
            or set(host)
            != {
                "source_docx_digest",
                "pdf_digest",
                "software",
                "software_version",
                "fields_updated",
                "page_ranges",
            }
            or host.get("source_docx_digest") != docx["digest"]
            or host.get("pdf_digest") != _sha(payload)
            or host.get("software") != "Microsoft Word"
            or not str(host.get("software_version", "")).strip()
            or host.get("fields_updated") is not True
        ):
            raise LocalApplicationError(
                "PUBLICATION-PDF-BINDING",
                "Host receipt must bind the Word rendering with updated fields to these DOCX/PDF bytes",
            )
        native = (root / docx["relative_path"]).read_bytes()
        failures = dialect.inspect_formal_report(
            native,
            policy["formal_report"],
            policy["research_group_type"],
            policy["formal_spec_profile"]["docx_layout"],
        )
        if failures:
            raise LocalApplicationError("PUBLICATION-FORMAL-RENDER-001", "; ".join(failures))
        with zipfile.ZipFile(io.BytesIO(native)) as archive:
            document = ElementTree.fromstring(archive.read("word/document.xml"))
            word_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            required = []
            for paragraph in document.iter("{%s}p" % word_ns):
                if len(list(paragraph.iter("{%s}p" % word_ns))) > 1:
                    continue
                texts = [t.text or "" for t in paragraph.iter("{%s}t" % word_ns)]
                if paragraph.find(".//{%s}footnoteReference" % word_ns) is not None:
                    required.extend(value for value in texts if value != "*")
                else:
                    required.append("".join(texts))
        required = [value for value in required if value and value != "要更新"]
        for footnote in policy["formal_report"].get("footnotes", []):
            required.append(footnote["text"])
        expected_parts = [
            node.get("{urn:research-loom:publication}part")
            for node in document.iter("{%s}sectPr" % word_ns)
        ]
        machine = inspect_pdf(
            payload,
            required_text=required,
            page_ranges=host["page_ranges"],
            expected_parts=expected_parts,
        )
        review = input_["review"]
        if (
            not isinstance(review, Mapping)
            or not {"pdf_digest", "reviewer_id", "reviewed_at", "checks", "pages"} <= set(review)
            or set(review)
            - {"pdf_digest", "reviewer_id", "reviewed_at", "checks", "pages", "presentation_review"}
        ):
            raise LocalApplicationError(
                "PUBLICATION-PDF-INPUT",
                "Review requires exact PDF digest, reviewer/time, checks and every page",
            )
        human = coverage_review(
            policy["coverage"],
            policy,
            review,
            _sha(payload),
            machine["page_count"],
            page_ranges=host["page_ranges"],
            dialect=dialect,
        )
        key = _sha(
            _canonical_bytes(
                {"source_build_digest": source["content_digest"], "finalization": dict(input_)}
            )
        )
        final_id = "PUBPDF-" + key.removeprefix("sha256:")[:24]
        target = self._build_path(final_id)
        with self._file_lock(final_id):
            if target.exists():
                existing, manifest, _ = self._load_build(final_id)
                return {
                    "status": "VERIFIED_REUSE",
                    "build": existing,
                    "preview_manifest": manifest,
                    "research_state_mutation_performed": False,
                }
            receipt = deepcopy(source)
            manifest = deepcopy(source_manifest)
            receipt.update({"build_id": final_id, "build_key_digest": key})
            receipt["publication_policy"]["final_pdf"] = {
                "source_build_id": build_id,
                "source_build_digest": source["content_digest"],
                "host_receipt": deepcopy(host),
                "machine_inspection": {k: v for k, v in machine.items() if k != "page_text"},
                "human_review": human,
                "pdf_digest": _sha(payload),
                "submission_status": "not_submitted",
            }
            receipt["outputs"].append(
                {
                    "format": "pdf",
                    "relative_path": "final.pdf",
                    "media_type": "application/pdf",
                    "size": len(payload),
                    "digest": _sha(payload),
                }
            )
            receipt["verification"]["final_pdf_machine"] = (
                "failed" if machine["problems"] else "passed"
            )
            receipt["verification"]["final_pdf_human"] = "failed" if human["problems"] else "passed"
            receipt["verification"]["formal_specification"] = (
                "failed" if machine["problems"] or human["problems"] else "passed"
            )
            deviations = [
                row["check_id"]
                for row in human["applicability"]
                if row["applicable"]
                and row["force"] == "should"
                and row["review"]
                and row["review"]["status"] == "warning"
            ]
            receipt["publication_policy"]["final_pdf"]["documented_deviations"] = deviations
            if deviations and receipt["verification"]["formal_specification"] == "passed":
                receipt["verification"]["formal_specification"] = "warning"
            receipt["verification"]["editorial_qa"] = "failed" if human["problems"] else "passed"
            receipt["verification"]["layout_verification"] = (
                "failed" if machine["problems"] or human["problems"] else "passed"
            )
            receipt["verification_scope"] = (
                "Native formal structure/styles and exact PDF size/page counts/text/fonts; individual original-clause checks and every rendered page explicitly reviewed by the named reviewer."
            )
            manifest["preview_id"] = final_id
            manifest["outputs"].append(
                {
                    "format": "pdf",
                    "path": "final.pdf",
                    "output_digest": _sha(payload),
                    "input_template_digest": _TEMPLATE_PIN["content_digest"],
                    "input_style_map_digest": _STYLE_MAP_PIN["content_digest"],
                }
            )
            manifest["validation_checks"] = self._validation_checks(
                receipt["verification"], receipt["issues"]
            )
            manifest["content_digest"] = _digest(manifest, "content_digest")
            _validate_preview_manifest(manifest)
            receipt["preview_manifest_digest"] = manifest["content_digest"]
            receipt["content_digest"] = _digest(receipt, "content_digest")
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix="." + final_id + ".", dir=target.parent))
            try:
                for output in source["outputs"]:
                    (staging / output["relative_path"]).write_bytes(
                        (root / output["relative_path"]).read_bytes()
                    )
                (staging / "final.pdf").write_bytes(payload)
                (staging / "preview-manifest.json").write_bytes(_json_bytes(manifest))
                (staging / "build-receipt.json").write_bytes(_json_bytes(receipt))
                os.rename(staging, target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        return {
            "status": "BUILT",
            "build": receipt,
            "preview_manifest": manifest,
            "research_state_mutation_performed": False,
        }
