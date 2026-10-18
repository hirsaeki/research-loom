# Documentation index

Every document under `docs/` is reachable from this page; `tests/contracts/test_docs_links.py` checks that and that relative links resolve. Many `architecture/` documents began as the record of one PR or issue (#504 separates current specifications from those records).

Start with the [repository README](../README.md), the [target monorepo structure](architecture/monorepo-structure.md), and the [contributor guide](../CONTRIBUTING.md).

## Decisions

- [ADR 0001: Two persistence tiers with shared conventions](architecture/adr-0001-persistence-tiers.md)

## Core research contracts and runtime

- [Canonical research contract convergence](architecture/research-contract-convergence.md)
- [Research State runtime / State Reducer convergence (PR20)](architecture/research-state-runtime.md)
- [Canonical SQLite Research State persistence](architecture/sqlite-research-state-persistence.md)
- [Research Lineage / Fork / Recovery convergence (PR19)](architecture/research-lineage-fork-recovery.md)
- [Research Capability contract convergence](architecture/research-capability-convergence.md)
- [Research Method Capability convergence](architecture/research-method-capability-convergence.md)
- [Canonical Research Capability execution runtime](capability-execution-runtime.md)
- [Work Conversation / Research Coordinator convergence](architecture/work-conversation-convergence.md)
- [Production Work Conversation / Research Coordinator runtime (PR25)](architecture/work-conversation-runtime.md)

## Profiles and Project Config

- [Canonical Profile contract convergence](architecture/profile-contract-convergence.md)
- [Project Config contract convergence](architecture/project-config-convergence.md)
- [Project / Profile generation advancement](architecture/profile-generation-advancement.md)
- [Canonical Research Profile quality-policy convergence](architecture/research-quality-policy-convergence.md)
- [Research quality Profile application](architecture/research-quality-profile-application.md)
- [Narrative Profile convergence](architecture/narrative-profile-convergence.md)
- [MISCO Writer Profile application](architecture/misco-writer-profile-application.md)
- [MISCO Publication Profile application](architecture/misco-publication-profile-application.md)
- [Writer rule adoption and review scope (Issue 464)](architecture/writer-rule-adoption.md)

## Local Workspace, application and persistence

- [Production local workspace, application facade, and JSON CLI](architecture/production-local-workspace-application-cli.md)
- [Production Human Decision Gate](architecture/production-human-decision-gate.md)
- [Production research resume context](architecture/production-research-resume-context.md)
- [Durable payload ownership and portable store tree](architecture/managed-payload-ownership-inventory.md)
- [Portable execution/material child Durable Store Root](architecture/portable-execution-material-store.md)
- [Optional durable child health and local degradation](architecture/optional-durable-health.md)
- [Quiesced Parent backup and restore](architecture/parent-backup-restore.md)
- [Exact managed-payload recovery](architecture/exact-payload-repair.md)
- [Project Input snapshot reuse](architecture/project-input-snapshot-reuse.md)

## Research questions, attention, arguments and exhibits

- [Production Research Question adoption](architecture/production-research-question-adoption.md)
- [Production iterative Research Question review](architecture/production-research-question-review.md)
- [Production Research Attention lifecycle](architecture/production-research-attention-lifecycle.md)
- [Public Research Argument proposal](architecture/research-argument-proposal.md)
- [Research Exhibit registry](architecture/research-exhibit-registry.md)
- [Research-backed visual semantics](architecture/research-visual-semantics.md)

## Desktop Research and external material

- [Desktop Research capability convergence](architecture/desktop-research-capability-convergence.md)
- [Production Desktop Research (PR24)](architecture/production-desktop-research.md)
- [Desktop Research retention edge cases](desktop-research-retention.md)
- [External Desktop Research submission assembly and preflight](architecture/external-desktop-research-submission-preflight.md)
- [External material exact-content read and export](architecture/external-material-content-read.md)
- [Staged verified material import](architecture/staged-material-import.md)
- [Historical Desktop Research Finding recovery diagnosis](architecture/historical-finding-recovery.md)

## Survey, Delphi, Case Study and Virtual Runner

- [Survey Capability convergence (PR13, production projection in PR40)](architecture/survey-capability-convergence.md)
- [Production Survey Response and Response Dataset boundary](architecture/production-survey-response-dataset.md)
- [Production REAL Survey response intake](architecture/production-survey-real-response-intake.md)
- [Production shared Survey aggregation](architecture/production-survey-shared-aggregation.md)
- [Production Survey Virtual Runner](architecture/production-survey-virtual-runner.md)
- [Production LLM Survey Virtual Respondent](architecture/production-survey-llm-virtual-respondent.md)
- [Virtual Runner and VIRTUAL→REAL cutover convergence (PR17)](architecture/virtual-runner-cutover-convergence.md)
- [Delphi Capability convergence](architecture/delphi-capability-convergence.md)
- [Production two-round Delphi lifecycle](architecture/production-delphi-two-round.md)
- [Case Study capability convergence](architecture/case-study-capability-convergence.md)

## Research Package, Writer and Publication

- [Production self-contained Research Package](architecture/production-research-package.md)
- [Versioned evidence-linked Writer Composition](architecture/versioned-writer-composition.md)
- [Writer continuity and interrupted persistence](architecture/writer-recovery.md)
- [Writer / Publication preview convergence (PR18)](architecture/writer-publication-preview-convergence.md)
- [Deterministic Publication preview and release](architecture/deterministic-publication-release.md)
- [Publication request and release recovery](architecture/publication-recovery.md)

## Operations

- [ChatGPT Work runtime, file delivery, and continuity](operations/work-host-runtime.md)
- [Interrupted Workspace initialization](operations/interrupted-workspace-initialization.md)
- [Workspace and Profile locks](operations/workspace-profile-locks.md)
- [Package and Writer inventory](operations/item-inventory.md)
- [現稿へ結び付いた文書レビュー](operations/writer-document-review.md)
- [Bounded research charts](operations/research-charts.md)
- [Generated explanatory visuals](operations/generated-explanations.md)
- [Generated visuals in Publication](operations/generated-publication-visuals.md)
- [Native Publication exhibits (renderer 0.2)](operations/native-publication-exhibits.md)
- [Late visual needs](operations/late-visual-needs.md)
- [MISCO formal Publication (Issue #456)](operations/misco-formal-publication.md)
- [Issue #456 implementation validation](operations/misco-formal-validation.md)

## Migration records

- [MISCO legacy Profile migration ledger](migration/misco-profile-migration-ledger.md)
- [Archived legacy sources pinned by the ledger](migration/misco-legacy-sources/README.md)

## Acceptance records

- [MISCO integrated acceptance and migration closure](architecture/misco-integrated-acceptance.md)
- [Research Package acceptance evidence (Issue #77)](architecture/research-package-acceptance.md)
- [Late visual live acceptance (#409)](acceptance/late-visual-live-uat.md)
- [Writer reader-quality trial and evaluation preparation](acceptance/writer-reader-quality/README.md)
- [#466 現稿レビューの対象一致と部分改稿](acceptance/writer-document-review/README.md)
