from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import ClassVar

from misco_harness.models import (
    AttentionDistillationHandoff,
    ContextPackManifest,
    DesktopResearchHandoff,
    IndependentQuestionFormationHandoff,
    ProvenanceAuditHandoff,
    RunManifest,
    SeedComparisonHandoff,
    WorkerResult,
    WorkExecutionRequest,
)
from misco_harness.trace_store import sha256_file, sha256_tree


class WorkResearchExchangeError(RuntimeError):
    pass


class DesktopEvidenceSnapshotError(WorkResearchExchangeError):
    pass


class InteractiveWorkResearchBoundary:
    """Boundary for human/interactive Work execution; this is not a Work API client."""

    def prepare(
        self,
        context_pack: Path,
        manifest: ContextPackManifest,
        run_manifest: RunManifest,
        exchange_directory: Path,
    ) -> WorkExecutionRequest:
        if manifest.event != "DESKTOP_RESEARCH" or manifest.desktop_research_spec is None:
            raise WorkResearchExchangeError("Work Desktop Research requires a bounded DESKTOP_RESEARCH Context Pack")
        return _prepare_exchange(
            context_pack, manifest, run_manifest, exchange_directory, DesktopResearchHandoff,
            required_work=[
                "Execute bounded Desktop Research for the approved Question and protocol.",
                "Capture each source once under source_captures/<capture-id>/, preserving the original artifact and a UTF-8 full-text rendition before creating Evidence Citations.",
                "For every Evidence Citation, reference a Source Capture, preserve a verbatim internal excerpt and locator, and record evidence status, study role, writer use mode, and verbatim use status.",
                "Do not count a review as independent primary evidence; do not infer causal or effectiveness claims from narrative or scoping reviews alone.",
                "Flag WORKING_PAPER, PREPRINT, INDUSTRY_REPORT, and CORPORATE_PUBLICATION sources LOW_CONFIDENCE; use them as contextual or lead evidence, never as a sole basis for an effect conclusion.",
                "Classify every source with source_quality; SOCIAL_MEDIA, ONLINE_FORUM, and any other low-trust source must be flagged LOW_TRUST.",
                "Use LOW_TRUST material only for DESCRIPTIVE_CONTEXT or LEAD_ONLY; it cannot be the sole support for a material Finding or resolve an Evidence Gap.",
                "Report counterevidence, unknowns, Evidence Gaps, study-role coverage, overlap, stopping assessment, and non-binding next-method options.",
            ],
        )

    def collect(self, request: WorkExecutionRequest, result_path: Path) -> DesktopResearchHandoff:
        _validate_result_path(request, result_path)
        handoff = DesktopResearchHandoff.model_validate_json(result_path.read_text(encoding="utf-8"))
        if handoff.run_id != request.run_id:
            raise WorkResearchExchangeError("Desktop Research Handoff run_id does not match the pending Work run")
        if handoff.source_captures or handoff.evidence_citations:
            validate_source_capture_exchange(handoff, request)
        else:
            validate_desktop_snapshot_exchange(handoff, request)
        return handoff


class InteractiveWorkProvenanceBoundary:
    """Human/interactive boundary for explicit PROVENANCE_AUDIT runs."""

    def prepare(
        self,
        context_pack: Path,
        manifest: ContextPackManifest,
        run_manifest: RunManifest,
        exchange_directory: Path,
    ) -> WorkExecutionRequest:
        if manifest.event != "PROVENANCE_AUDIT":
            raise WorkResearchExchangeError("Provenance Work requires a PROVENANCE_AUDIT Context Pack")
        return _prepare_exchange(
            context_pack,
            manifest,
            run_manifest,
            exchange_directory,
            ProvenanceAuditHandoff,
            required_work=[
                "Repair only the closed-world Evidence IDs listed in the task plan; do not alter research meaning or source qualification.",
                "Use the v0.3 two-phase path when reacquiring: capture each source once under source_captures/<capture-id>/, then create citations with study role and use eligibility.",
                "For every resolved record, provide an acquisition timestamp in timezone-aware UTC, exact UTF-8 text snapshot, snapshot path, SHA-256, and excerpt-locator pairs.",
                "Preserve evidence_id, source_id, source_type, locator, captured_statement, evidence_kind, support_scope, material, limitations, and independent support references.",
                "Return unavailable or unverifiable sources as explicit UNRESOLVED_GAP records; do not infer publication dates as acquisition times and do not substitute sources.",
                "Do not select a research method, change a Question, Finding, Evidence Gap meaning, or Publication status.",
                "Follow the retrieval rules and target partition recorded in the explicitly registered provenance-audit-plan artifact; do not add targets or replacement sources.",
            ],
        )

    def collect(self, request: WorkExecutionRequest, result_path: Path) -> ProvenanceAuditHandoff:
        _validate_result_path(request, result_path)
        handoff = ProvenanceAuditHandoff.model_validate_json(result_path.read_text(encoding="utf-8"))
        if handoff.run_id != request.run_id:
            raise WorkResearchExchangeError("Provenance Audit Handoff run_id does not match the pending Work run")
        if handoff.source_captures or handoff.evidence_citations:
            validate_source_capture_exchange(handoff, request)
        else:
            validate_provenance_snapshot_exchange(handoff, request)
        return handoff


class InteractiveWorkAttentionBoundary:
    """Bounded Work exchange for Human-supplied Attention distillation."""

    def prepare(
        self,
        context_pack: Path,
        manifest: ContextPackManifest,
        run_manifest: RunManifest,
        exchange_directory: Path,
    ) -> WorkExecutionRequest:
        if manifest.event != "ATTENTION_DISTILLATION":
            raise WorkResearchExchangeError("Attention Work requires an ATTENTION_DISTILLATION Context Pack")
        return _prepare_exchange(
            context_pack,
            manifest,
            run_manifest,
            exchange_directory,
            AttentionDistillationHandoff,
            required_work=[
                "Distill only the registered drop batch into a candidate Attention Map.",
                "Preserve conflicts, uncertainty, duplicate concepts, exclusions, and source back-references.",
                "Do not select a Research method, assert a Finding, determine an answer, or adopt the candidate Map.",
                "Set candidate_map_sha256 to the SHA-256 of candidate_map_markdown encoded as UTF-8.",
            ],
        )

    def collect(self, request: WorkExecutionRequest, result_path: Path) -> AttentionDistillationHandoff:
        _validate_result_path(request, result_path)
        handoff = AttentionDistillationHandoff.model_validate_json(result_path.read_text(encoding="utf-8"))
        if handoff.run_id != request.run_id:
            raise WorkResearchExchangeError("Attention Distillation Handoff run_id does not match the pending Work run")
        actual_hash = hashlib.sha256(handoff.candidate_map_markdown.encode("utf-8")).hexdigest()
        if actual_hash != handoff.candidate_map_sha256:
            raise WorkResearchExchangeError(
                f"Attention candidate Map SHA-256 mismatch: expected {handoff.candidate_map_sha256}, got {actual_hash}"
            )
        if len({item.attention_id for item in handoff.items}) != len(handoff.items):
            raise WorkResearchExchangeError("Attention candidate IDs must be unique")
        return handoff


class InteractiveWorkDiscoveryBoundary:
    """Human-interactive Work boundary for discovery runs; no Work API is assumed."""

    _schemas: ClassVar[dict[str, type]] = {
        "QUESTION_FORMATION": IndependentQuestionFormationHandoff,
        "SEED_COMPARISON": SeedComparisonHandoff,
        "RESEARCH_PLANNING": WorkerResult,
    }

    def prepare(
        self,
        context_pack: Path,
        manifest: ContextPackManifest,
        run_manifest: RunManifest,
        exchange_directory: Path,
    ) -> WorkExecutionRequest:
        schema = self._schemas.get(manifest.event)
        if schema is None:
            raise WorkResearchExchangeError("Interactive discovery Work requires QUESTION_FORMATION or SEED_COMPARISON")
        required_work = {
            "QUESTION_FORMATION": [
                "Form independent Question Candidates from the bounded inputs without using the quarantined Seed.",
                "Report uncertainty, scope limits, overlaps, counterevidence, and Evidence Gap hypotheses.",
            ],
            "SEED_COMPARISON": [
                "Compare the immutable independent candidate snapshot with the Seed.",
                "Report matches, mismatches, missing and over-scoped elements, then emit typed proposed baseline options.",
            ],
            "RESEARCH_PLANNING": [
                "Prepare a bounded Desktop Research protocol for the Human-approved Question Baseline.",
                "Report protocol limits, uncertainty, counterevidence concerns, and unresolved Evidence Gaps without selecting another method.",
            ],
        }[manifest.event]
        return _prepare_exchange(
            context_pack, manifest, run_manifest, exchange_directory, schema,
            required_work=required_work,
        )

    def collect(self, request: WorkExecutionRequest, result_path: Path) -> WorkerResult:
        _validate_result_path(request, result_path)
        event = ContextPackManifest.model_validate_json(Path(request.manifest).read_text(encoding="utf-8")).event
        handoff = self._schemas[event].model_validate_json(result_path.read_text(encoding="utf-8"))
        if isinstance(handoff, WorkerResult):
            return handoff
        if isinstance(handoff, IndependentQuestionFormationHandoff):
            return WorkerResult(
                run_id=handoff.run_id,
                observed=[item.model_dump(mode="json") for item in handoff.candidates],
                interpreted=[{"attention_map_authority": handoff.attention_map_authority}],
                counterevidence=handoff.counterevidence,
                unknown=handoff.uncertainty,
                scope_limits=handoff.scope_limits,
                question_overlaps=handoff.question_overlaps,
                evidence_gap_hypotheses=[item.model_dump(mode="json") for item in handoff.evidence_gap_hypotheses],
                question_delta_candidate=[{
                    "candidate_id": item.candidate_id,
                    "question": item.question,
                    "reason": item.rationale,
                } for item in handoff.candidates],
                back_references=handoff.back_references,
            )
        return WorkerResult(
            run_id=handoff.run_id,
            observed=[{"matches": handoff.matches, "mismatches": handoff.mismatches}],
            derived=[{"missing": handoff.missing, "over_scoped": handoff.over_scoped}],
            interpreted=[{"attention_map_authority": handoff.attention_map_authority}],
            counterevidence=handoff.counterevidence,
            unknown=handoff.uncertainty,
            scope_limits=handoff.scope_limits,
            question_overlaps=handoff.question_overlaps,
            evidence_gap_hypotheses=[item.model_dump(mode="json") for item in handoff.evidence_gap_hypotheses],
            question_delta_candidate=[item.model_dump(mode="json") for item in handoff.proposed_baselines],
            back_references=handoff.back_references,
        )


def _prepare_exchange(
    context_pack: Path,
    manifest: ContextPackManifest,
    run_manifest: RunManifest,
    exchange_directory: Path,
    schema: type,
    *,
    required_work: list[str],
) -> WorkExecutionRequest:
    exchange_directory.mkdir(parents=True, exist_ok=False)
    if schema in {DesktopResearchHandoff, ProvenanceAuditHandoff}:
        if schema is DesktopResearchHandoff and manifest.desktop_research_spec and manifest.desktop_research_spec.research_brief:
            (exchange_directory / "source_captures").mkdir()
            # Compatibility directory only; v0.3 never writes per-evidence snapshots here.
            (exchange_directory / "evidence_snapshots").mkdir()
        else:
            (exchange_directory / "evidence_snapshots").mkdir()
            (exchange_directory / "source_captures").mkdir()
    schema_path = exchange_directory / f"{schema.__name__}.schema.json"
    result_path = exchange_directory / "result.json"
    task_path = exchange_directory / "TASK.md"
    schema_document = schema.model_json_schema()
    if schema in {DesktopResearchHandoff, ProvenanceAuditHandoff}:
        schema_document.setdefault("properties", {}).setdefault("schema_version", {})["default"] = "0.3"
        schema_document["x-evidence-model"] = "SourceCapture + EvidenceCitation"
    schema_path.write_text(
        json.dumps(schema_document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    required = "\n".join(f"- {item}" for item in required_work)
    forbidden = "\n".join(f"- `{item}`" for item in manifest.forbidden_context) or "- None declared."
    snapshot_requirement = ""
    if schema in {DesktopResearchHandoff, ProvenanceAuditHandoff}:
        if schema is DesktopResearchHandoff:
            legacy_note = " Legacy v0.2 exchanges may use evidence_snapshots/<evidence-id>.txt." if not (
                manifest.desktop_research_spec and manifest.desktop_research_spec.research_brief
            ) else ""
            snapshot_requirement = (
                f"- Write each SourceCapture original to "
                f"{(exchange_directory / 'source_captures').resolve()}/<capture-id>/original and its "
                f"UTF-8 full-text rendition to <capture-id>/text.txt.{legacy_note}"
            )
        else:
            snapshot_requirement = (
                f"- Write each exact UTF-8 Evidence text snapshot to "
                f"{(exchange_directory / 'evidence_snapshots').resolve()}/<evidence-id>.txt "
                "and set snapshot_path to that file. For v0.3 reacquisition, use "
                f"{(exchange_directory / 'source_captures').resolve()}/<capture-id>/original and text.txt."
            )
    brief_text = _research_brief_text(manifest)
    task_path.write_text(
        f"""# Work Task: {run_manifest.task_type}

## Objective

{run_manifest.objective}

## Authority boundaries

- Use only the bounded Context Pack and allowed retrieval pointers.
- The Attention Map is guidance only; it is not answer or method authority.
- Do not select or approve a research method, Question Baseline, Finding, Model, Recommendation, or Publication status.
- Publication materials are not Research Evidence.

## Required work

{required}

## Forbidden context

{forbidden}

## Output requirements

- Validate the result against `{schema_path.resolve()}`.
- Write only the structured result to `{result_path.resolve()}`.
- Preserve counterevidence, uncertainty/unknowns, scope limits, overlaps, and Evidence Gaps where the schema provides them.
{snapshot_requirement}

## Context Pack

- Open `{context_pack.resolve()}`.
- Manifest: `{(context_pack / 'manifest.json').resolve()}`.
{brief_text}
""",
        encoding="utf-8",
    )
    return WorkExecutionRequest(
        run_id=manifest.run_id,
        context_pack=str(context_pack.resolve()),
        manifest=str((context_pack / "manifest.json").resolve()),
        context_pack_sha256=sha256_tree(context_pack),
        exchange_directory=str(exchange_directory.resolve()),
        task_file=str(task_path.resolve()),
        expected_output_schema=schema.__name__,
        expected_output_schema_file=str(schema_path.resolve()),
        expected_output_file=str(result_path.resolve()),
    )


def _research_brief_text(manifest: ContextPackManifest) -> str:
    brief = manifest.desktop_research_spec.research_brief if manifest.desktop_research_spec else None
    if brief is None:
        return ""
    return (
        "\n## Research Brief (Human-approved execution contract)\n\n"
        "```json\n"
        + json.dumps(brief.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n"
        "Work may choose its own retrieval order, but must satisfy this evidence portfolio, "
        "counterevidence, prohibited-inference, and stopping contract.\n"
    )
def _validate_result_path(request: WorkExecutionRequest, result_path: Path) -> None:
    if result_path.is_symlink():
        raise WorkResearchExchangeError("Work result must be a regular file, not a symbolic link")
    if result_path.resolve() != Path(request.expected_output_file).resolve():
        raise WorkResearchExchangeError(f"Work result must be collected from: {request.expected_output_file}")
    if not result_path.is_file():
        raise WorkResearchExchangeError(f"Work result file does not exist: {result_path}")


def validate_desktop_snapshot_exchange(
    handoff: DesktopResearchHandoff,
    request: WorkExecutionRequest,
) -> None:
    """Validate Work-provided evidence snapshots before Harness collection."""
    exchange = Path(request.exchange_directory).resolve()
    snapshot_root = (exchange / "evidence_snapshots").resolve()
    if not snapshot_root.is_dir():
        raise DesktopEvidenceSnapshotError("Desktop Research evidence_snapshots directory is missing")
    for evidence in handoff.evidence:
        path = Path(evidence.snapshot_path)
        if ".." in path.parts or not path.is_absolute() or path.resolve().parent != snapshot_root:
            raise DesktopEvidenceSnapshotError(
                f"snapshot_path must be under exactly {snapshot_root}"
            )
    validate_desktop_snapshot_directory(handoff, snapshot_root)


def validate_source_capture_exchange(
    handoff: DesktopResearchHandoff,
    request: WorkExecutionRequest,
) -> None:
    """Validate one immutable original and UTF-8 rendition per SourceCapture."""
    exchange = Path(request.exchange_directory).resolve()
    raw_root = exchange / "source_captures"
    capture_root = raw_root.resolve()
    if raw_root.is_symlink() or capture_root.parent != exchange or not capture_root.is_dir():
        raise DesktopEvidenceSnapshotError("Desktop Research source_captures directory is missing")
    seen: set[Path] = set()
    captures = {item.capture_id: item for item in handoff.source_captures}
    for capture in handoff.source_captures:
        raw_directory = capture_root / capture.capture_id
        if raw_directory.is_symlink():
            raise DesktopEvidenceSnapshotError(f"SourceCapture directory is a symbolic link: {raw_directory}")
        directory = raw_directory.resolve()
        if directory.parent != capture_root or not directory.is_dir():
            raise DesktopEvidenceSnapshotError(f"SourceCapture directory is invalid: {directory}")
        original = Path(capture.original_path)
        text_path = Path(capture.text_snapshot_path)
        expected_original = directory / "original"
        expected_text = directory / "text.txt"
        if original.resolve() != expected_original or text_path.resolve() != expected_text:
            raise DesktopEvidenceSnapshotError(
                f"SourceCapture paths must be exactly {expected_original} and {expected_text}"
            )
        for path in (original, text_path):
            if path.is_symlink() or not path.is_file():
                raise DesktopEvidenceSnapshotError(f"SourceCapture artifact is not a regular file: {path}")
        if original.resolve() in seen or text_path.resolve() in seen:
            raise DesktopEvidenceSnapshotError(f"SourceCapture artifact path is duplicated: {capture.capture_id}")
        seen.update({original.resolve(), text_path.resolve()})
        if sha256_file(original) != capture.original_sha256:
            raise DesktopEvidenceSnapshotError(f"SourceCapture original SHA-256 mismatch: {original}")
        if sha256_file(text_path) != capture.text_snapshot_sha256:
            raise DesktopEvidenceSnapshotError(f"SourceCapture text SHA-256 mismatch: {text_path}")
        try:
            text = text_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise DesktopEvidenceSnapshotError(f"SourceCapture text is not UTF-8: {text_path}") from error
        for citation in handoff.evidence_citations:
            if citation.capture_id == capture.capture_id and citation.excerpt not in text:
                raise DesktopEvidenceSnapshotError(
                    f"Evidence Citation excerpt is absent from SourceCapture text: {citation.evidence_id}"
                )
    missing = sorted({item.capture_id for item in handoff.evidence_citations}.difference(captures))
    if missing:
        raise DesktopEvidenceSnapshotError(f"Evidence Citations reference missing Source Captures: {missing}")


def validate_provenance_snapshot_exchange(
    handoff: ProvenanceAuditHandoff,
    request: WorkExecutionRequest,
) -> None:
    """Validate only resolved Provenance Audit snapshots inside the exchange."""
    exchange = Path(request.exchange_directory).resolve()
    raw_snapshot_root = exchange / "evidence_snapshots"
    snapshot_root = raw_snapshot_root.resolve()
    if raw_snapshot_root.is_symlink() or snapshot_root.parent != exchange or not snapshot_root.is_dir():
        raise DesktopEvidenceSnapshotError("Provenance Audit evidence_snapshots directory is missing")
    validate_provenance_snapshot_directory(handoff, snapshot_root)


def validate_desktop_snapshot_directory(
    handoff: DesktopResearchHandoff,
    snapshot_root: Path,
) -> None:
    """Validate snapshot files whose parent directory is already trusted."""
    snapshot_root = snapshot_root.resolve()
    seen: set[Path] = set()
    for evidence in handoff.evidence:
        path = Path(evidence.snapshot_path)
        resolved = path.resolve()
        expected_name = f"{evidence.evidence_id}.txt"
        if resolved.parent != snapshot_root or resolved.name != expected_name:
            raise DesktopEvidenceSnapshotError(
                f"snapshot_path must be exactly {snapshot_root / expected_name}"
            )
        if path.is_symlink() or not path.is_file():
            raise DesktopEvidenceSnapshotError(f"Desktop Research snapshot is not a regular file: {path}")
        if resolved in seen:
            raise DesktopEvidenceSnapshotError(f"Desktop Research snapshot path is duplicated: {path}")
        seen.add(resolved)
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DesktopEvidenceSnapshotError(f"Desktop Research snapshot is not UTF-8: {path}") from error
        if text != evidence.text_snapshot:
            raise DesktopEvidenceSnapshotError(
                f"Desktop Research text_snapshot does not match snapshot file: {path}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != evidence.snapshot_sha256:
            raise DesktopEvidenceSnapshotError(
                f"Desktop Research snapshot SHA-256 mismatch for {path}: expected {evidence.snapshot_sha256}, got {actual_hash}"
            )


def validate_provenance_snapshot_directory(
    handoff: ProvenanceAuditHandoff,
    snapshot_root: Path,
) -> None:
    """Validate resolved snapshots whose parent directory is already trusted."""
    snapshot_root = snapshot_root.resolve()
    seen: set[Path] = set()
    for evidence in handoff.evidence:
        path = Path(evidence.snapshot_path)
        resolved = path.resolve()
        expected_name = f"{evidence.evidence_id}.txt"
        if ".." in path.parts or not path.is_absolute() or resolved.parent != snapshot_root or resolved.name != expected_name:
            raise DesktopEvidenceSnapshotError(
                f"Provenance Audit snapshot_path must be exactly {snapshot_root / expected_name}"
            )
        if path.is_symlink() or not path.is_file():
            raise DesktopEvidenceSnapshotError(f"Provenance Audit snapshot is not a regular file: {path}")
        if resolved in seen:
            raise DesktopEvidenceSnapshotError(f"Provenance Audit snapshot path is duplicated: {path}")
        seen.add(resolved)
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DesktopEvidenceSnapshotError(f"Provenance Audit snapshot is not UTF-8: {path}") from error
        if text != evidence.text_snapshot:
            raise DesktopEvidenceSnapshotError(
                f"Provenance Audit text_snapshot does not match snapshot file: {path}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != evidence.snapshot_sha256:
            raise DesktopEvidenceSnapshotError(
                f"Provenance Audit snapshot SHA-256 mismatch for {path}: expected {evidence.snapshot_sha256}, got {actual_hash}"
            )
