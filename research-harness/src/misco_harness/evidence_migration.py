"""Evidence model v0.2 -> v0.3 migration helpers.

The migration is deliberately additive: the old Research State is never
rewritten, while a new state carries SourceCapture/EvidenceCitation records
and explicit gaps for snapshot-less legacy evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from misco_harness.models import (
    EvidenceCitation,
    EvidenceKind,
    EvidenceModelMigrationReceipt,
    EvidenceStatus,
    ResearchState,
    SourceCapture,
    SourceQuality,
    SourceType,
    StudyRole,
    SupportScope,
    VerbatimUseStatus,
    WriterUseMode,
    utc_now,
)
from misco_harness.trace_store import sha256_file


def _capture_id(canonical_locator: str, original_sha256: str) -> str:
    digest = hashlib.sha256(f"{canonical_locator}\0{original_sha256}".encode()).hexdigest()[:24]
    return f"capture-{digest}"


def _state_digest(state: ResearchState) -> str:
    payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def migrate_research_state(
    state: ResearchState,
    *,
    destination_root: Path,
    run_id: str,
    new_state_id: str,
) -> tuple[ResearchState, EvidenceModelMigrationReceipt]:
    """Convert legacy evidence snapshots into shared captures and citations."""
    destination_root = destination_root.resolve()
    capture_root = destination_root / "source_captures"
    capture_root.mkdir(parents=True, exist_ok=True)
    captures: dict[str, SourceCapture] = {}
    citations: list[EvidenceCitation] = []
    gaps: list[dict[str, Any]] = []
    reasons: list[str] = []

    for raw in state.evidence:
        if not isinstance(raw, dict):
            reasons.append("non-object legacy evidence could not be converted")
            continue
        evidence_id = str(raw.get("evidence_id") or f"legacy-{len(citations) + len(gaps) + 1}")
        snapshot_path_value = raw.get("snapshot_path")
        snapshot_sha = str(raw.get("snapshot_sha256") or "")
        if not snapshot_path_value or len(snapshot_sha) != 64:
            gaps.append({
                "gap_id": f"migration-gap-{evidence_id}",
                "description": "Legacy 0.1 evidence has no immutable text snapshot; reacquire externally.",
                "material": bool(raw.get("material", True)),
                "resolved_by_evidence_ids": [],
            })
            reasons.append(f"{evidence_id}: snapshot missing, converted to Evidence Gap")
            continue
        source_path = Path(str(snapshot_path_value))
        if not source_path.is_absolute():
            source_path = (destination_root.parent / source_path)
        source_path = source_path.resolve()
        if not source_path.is_file() or sha256_file(source_path) != snapshot_sha:
            gaps.append({
                "gap_id": f"migration-gap-{evidence_id}",
                "description": "Legacy snapshot is unavailable or its SHA-256 no longer matches; reacquire externally.",
                "material": bool(raw.get("material", True)),
                "resolved_by_evidence_ids": [],
            })
            reasons.append(f"{evidence_id}: snapshot unavailable or hash mismatch, converted to Evidence Gap")
            continue
        try:
            text = source_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            gaps.append({
                "gap_id": f"migration-gap-{evidence_id}",
                "description": "Legacy snapshot is not UTF-8; reacquire and extract a UTF-8 rendition.",
                "material": bool(raw.get("material", True)),
                "resolved_by_evidence_ids": [],
            })
            reasons.append(f"{evidence_id}: non-UTF-8 snapshot, converted to Evidence Gap")
            continue
        canonical_locator = str(raw.get("canonical_locator") or raw.get("source_id") or raw.get("locator") or source_path.name)
        source_id = str(raw.get("source_id") or evidence_id)
        capture_key = f"{canonical_locator}\0{snapshot_sha}"
        capture_id = _capture_id(canonical_locator, snapshot_sha)
        if capture_key not in captures:
            target = capture_root / capture_id
            target.mkdir(parents=True, exist_ok=True)
            original = target / "original"
            text_target = target / "text.txt"
            for destination in (original, text_target):
                if destination.exists():
                    if sha256_file(destination) != snapshot_sha:
                        raise ValueError(f"migration capture collision with different content: {destination}")
                else:
                    shutil.copyfile(source_path, destination)
            captures[capture_key] = SourceCapture(
                capture_id=capture_id,
                source_id=source_id,
                canonical_locator=canonical_locator,
                acquired_at=utc_now(),
                original_path=str(original.resolve()),
                original_sha256=snapshot_sha,
                original_media_type="text/plain",
                text_snapshot_path=str(text_target.resolve()),
                text_snapshot_sha256=sha256_file(text_target),
                extractor_name="legacy-snapshot-migration",
                extractor_version="0.3",
            )
        capture = captures[capture_key]
        pairs = raw.get("excerpt_locator_pairs") or []
        pair = pairs[0] if pairs and isinstance(pairs[0], dict) else None
        excerpt = str((pair or {}).get("excerpt") or raw.get("captured_statement") or "")
        locator = str((pair or {}).get("locator") or raw.get("locator") or "legacy snapshot")
        if not excerpt or excerpt not in text:
            gaps.append({
                "gap_id": f"migration-gap-{evidence_id}",
                "description": "Legacy snapshot exists but its stored excerpt cannot be re-anchored; reacquire externally.",
                "material": bool(raw.get("material", True)),
                "resolved_by_evidence_ids": [],
            })
            reasons.append(f"{evidence_id}: excerpt not contained in snapshot, converted to Evidence Gap")
            continue
        citations.append(EvidenceCitation(
            evidence_id=evidence_id,
            capture_id=capture.capture_id,
            captured_statement=str(raw.get("captured_statement") or excerpt),
            excerpt=excerpt,
            excerpt_locator=locator,
            evidence_status=EvidenceStatus.VERIFIED,
            evidence_kind=EvidenceKind(str(raw.get("evidence_kind") or EvidenceKind.SUPPORTING.value)),
            support_scope=SupportScope(str(raw.get("support_scope") or SupportScope.DESCRIPTIVE_CONTEXT.value)),
            source_type=SourceType(str(raw.get("source_type") or SourceType.OTHER.value)),
            source_quality=SourceQuality(str(raw.get("source_quality") or SourceQuality.MEDIUM.value)),
            study_role=StudyRole(str(raw.get("study_role") or StudyRole.NOT_APPLICABLE.value)),
            material=bool(raw.get("material", True)),
            independent_support_source_ids=list(raw.get("independent_support_source_ids") or []),
            limitations=list(raw.get("limitations") or []),
            writer_use_mode=WriterUseMode.ATTRIBUTED_PARAPHRASE,
            verbatim_use_status=VerbatimUseStatus.REVIEW_REQUIRED,
            attribution=canonical_locator,
        ))

    converted = state.model_copy(update={
        "schema_version": "0.3",
        "state_id": new_state_id,
        "source_captures": [item.model_dump(mode="json") for item in captures.values()],
        "evidence_citations": [item.model_dump(mode="json") for item in citations],
        "evidence_gaps": [*state.evidence_gaps, *gaps],
        "prior_snapshot_id": state.state_id,
    })
    citation_count = len(citations)
    capture_count = len(captures)
    receipt = EvidenceModelMigrationReceipt(
        run_id=run_id,
        prior_state_id=state.state_id,
        new_state_id=new_state_id,
        prior_state_sha256=_state_digest(state),
        new_state_sha256=_state_digest(converted),
        capture_count=capture_count,
        citation_count=citation_count,
        shared_capture_count=max(0, citation_count - capture_count),
        lead_only_count=sum(1 for item in citations if item.evidence_status is EvidenceStatus.LEAD_ONLY),
        gap_count=len(gaps),
        conversion_reasons=reasons,
        immutable_history_refs=[state.state_id],
    )
    return converted, receipt
