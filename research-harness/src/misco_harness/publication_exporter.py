from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from misco_harness.models import (
    ArtifactRecord,
    ArtifactRef,
    ArtifactRegistry,
    PublicationBundleManifest,
    PublicationEligibility,
    PublicationState,
)
from misco_harness.trace_store import atomic_write_json, sha256_file, verify_hash


class PublicationExportError(RuntimeError):
    pass


_INTERNAL_EVIDENCE_KEYS = {
    "original_path", "original_sha256", "text_snapshot_path", "text_snapshot_sha256",
    "snapshot_path", "snapshot_sha256", "text_snapshot", "excerpt_locator_pairs",
}


def build_writer_evidence_payload(value: object) -> object:
    """Return only the publication-safe observation envelope for v0.3 evidence."""
    if isinstance(value, dict):
        citations = value.get("evidence_citations")
        if isinstance(citations, list):
            safe: list[dict[str, object]] = []
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                status = str(citation.get("evidence_status", "UNVERIFIED"))
                if status in {"UNVERIFIED", "CLAIM_NOT_SUPPORTED", "CAPTURE_UNAVAILABLE"}:
                    continue
                item: dict[str, object] = {
                    "evidence_id": citation.get("evidence_id"),
                    "verified_observation": citation.get("captured_statement"),
                    "attribution": citation.get("attribution"),
                    "study_role": citation.get("study_role"),
                    "evidence_status": status,
                    "writer_use_mode": citation.get("writer_use_mode"),
                    "verbatim_use_status": citation.get("verbatim_use_status"),
                    "limitations": citation.get("limitations", []),
                    "source_back_reference": citation.get("capture_id"),
                }
                if citation.get("writer_use_mode") == "DIRECT_QUOTE" and citation.get("verbatim_use_status") in {"QUOTABLE", "LICENSED"}:
                    item["approved_excerpt"] = citation.get("excerpt")
                    item["excerpt_locator"] = citation.get("excerpt_locator")
                safe.append(item)
            return {
                "schema_version": "0.3",
                "research_state_id": value.get("state_id"),
                "writer_evidence": safe,
                "findings": value.get("findings", []),
                "evidence_gaps": value.get("evidence_gaps", []),
                "counterevidence": value.get("counterevidence", []),
                "unknowns": value.get("unknowns", []),
            }
        if "source_captures" in value or any(key in value for key in _INTERNAL_EVIDENCE_KEYS):
            return {key: build_writer_evidence_payload(item) for key, item in value.items() if key not in _INTERNAL_EVIDENCE_KEYS and key != "source_captures"}
        return value
    if isinstance(value, list):
        return [build_writer_evidence_payload(item) for item in value]
    return value


_ALLOWED_WRITER_ROLES = {
    "RESEARCH_STATE",
    "SOURCE_EVIDENCE",
    "CLEAN_PUBLICATION_SOURCE",
    "FORMAL_PUBLICATION_SPEC",
    "ATTENTION_PUBLICATION_MAP",
    "DECISION_RECORD",
}
_REQUIRES_APPROVAL = {"RESEARCH_STATE", "SOURCE_EVIDENCE"}


class PublicationExporter:
    def __init__(self, output_root: Path):
        self.output_root = output_root.resolve()

    def export(
        self,
        *,
        bundle_id: str,
        research_snapshot_id: str,
        publication_state: PublicationState,
        eligibility: PublicationEligibility,
        registry: ArtifactRegistry,
        artifact_ids: list[str],
        approved_artifact_ids: set[str],
        primary_exposition_map: dict[str, str],
    ) -> Path:
        if eligibility.status != "ELIGIBLE" or not eligibility.decision_id or not eligibility.approved_by:
            raise PublicationExportError("publication export requires recorded Human-approved eligibility")
        if (
            publication_state.source_research_state_id is not None
            and publication_state.source_research_state_id != research_snapshot_id
        ):
            raise PublicationExportError("Publication State does not reference the requested Research snapshot")
        if (
            publication_state.publication_eligibility is not None
            and publication_state.publication_eligibility != eligibility
        ):
            raise PublicationExportError("Publication State eligibility does not match the export approval")
        if publication_state.status in {"STALE", "REVIEW_REQUIRED", "REVOKED_PENDING_REVIEW"}:
            raise PublicationExportError(
                f"Publication State {publication_state.state_id} is {publication_state.status}; Human review is required before export"
            )
        records = {item.artifact_id: item for item in registry.artifacts}
        selected: list[ArtifactRecord] = []
        for artifact_id in artifact_ids:
            artifact = records.get(artifact_id)
            if artifact is None:
                raise PublicationExportError(f"unregistered artifact {artifact_id!r}")
            if artifact.role not in _ALLOWED_WRITER_ROLES:
                raise PublicationExportError(f"role {artifact.role!r} cannot enter a Writer Input Bundle")
            if artifact.role in _REQUIRES_APPROVAL and artifact_id not in approved_artifact_ids:
                raise PublicationExportError(f"research artifact {artifact_id!r} is not approved for publication")
            if artifact.sha256 is None:
                raise PublicationExportError(f"artifact {artifact_id!r} has no SHA-256")
            selected.append(artifact)

        target = self.output_root / "publication" / "bundles" / bundle_id
        if target.exists():
            raise PublicationExportError(f"immutable publication bundle already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{bundle_id}.", dir=target.parent))
        try:
            refs: list[ArtifactRef] = []
            for artifact in selected:
                source = Path(artifact.path).resolve()
                verify_hash(source, artifact.sha256)
                if artifact.role == "SOURCE_EVIDENCE" and source.suffix.lower() != ".json":
                    raise PublicationExportError(
                        "raw Source Evidence (original/full-text binary) cannot enter a Publication Context Pack"
                    )
                relative = Path("inputs") / artifact.artifact_id / source.name
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if artifact.role in {"RESEARCH_STATE", "SOURCE_EVIDENCE"} and source.suffix.lower() == ".json":
                    try:
                        payload = json.loads(source.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise PublicationExportError(f"research evidence artifact is not readable JSON: {artifact.artifact_id}") from error
                    sanitized = build_writer_evidence_payload(payload)
                    atomic_write_json(destination, sanitized)  # Publication firewall: no original/fulltext/excerpt internals.
                    destination_hash = sha256_file(destination)
                else:
                    shutil.copyfile(source, destination)
                    verify_hash(destination, artifact.sha256)
                    destination_hash = artifact.sha256
                refs.append(ArtifactRef(
                    artifact_id=artifact.artifact_id,
                    path=relative.as_posix(),
                    sha256=destination_hash,
                    approval_state="HUMAN_APPROVED" if artifact.artifact_id in approved_artifact_ids else None,
                ))
            manifest = PublicationBundleManifest(
                bundle_id=bundle_id,
                research_snapshot_id=research_snapshot_id,
                publication_state_id=publication_state.state_id,
                eligibility=eligibility,
                input_refs=refs,
                primary_exposition_map=primary_exposition_map,
                publication_structure_id=(
                    publication_state.structure.structure_id
                    if publication_state.structure is not None else None
                ),
                provisional_draft_id=(
                    publication_state.draft.draft_id
                    if publication_state.draft is not None else None
                ),
            )
            atomic_write_json(staging / "publication_state.json", publication_state)
            if publication_state.structure is not None:
                atomic_write_json(staging / "publication_structure.json", publication_state.structure)
            if publication_state.draft is not None:
                atomic_write_json(staging / "publication_draft.json", publication_state.draft)
            atomic_write_json(staging / "manifest.json", manifest)
            os.replace(staging, target)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)
