# PROVENANCE_AUDIT — Evidence 0.1/0.2 to 0.3 repair contract

`PROVENANCE_AUDIT` is an explicit IMPLEMENTATION event. It is not ordinary
Research, and it never reduces a repair handoff directly into `ResearchState`.

## Input boundary

- The Harness accepts one explicitly supplied `PROVENANCE_REPAIR_RUN_PLAN`.
- The plan names a closed-world Evidence ID set and an immutable baseline
  Research State SHA-256.
- Only the registered baseline, plan, active contracts, source policy, and the
  exact locators listed by the plan may be used. Archive and Publication Lane
  material remain forbidden.
- A changed baseline hash, a changed source identity, or a source outside the
  plan is a blocker.

## Work output

For every resolved Evidence record, Work must return schema `0.2` with:

- timezone-aware UTC `acquired_at` (never a publication/update date);
- exact UTF-8 `text_snapshot` and an exchange-local snapshot file;
- the file's lower-case 64-character SHA-256;
- one or more verbatim `excerpt_locator_pairs`;
- source metadata and an explicit verification status.

Unavailable or unverifiable sources are returned as `UNRESOLVED_GAP` with a
reason. They are not silently dropped, replaced, or upgraded.

For v0.3 reacquisition, the same closed-world target is handled in two phases:
one immutable `SourceCapture` per source under `source_captures/<capture-id>/`
followed by one or more `EvidenceCitation` records. Capture success,
verification status, lead-only status, claim-not-supported, and unavailable
sources are counted separately. A changed original SHA creates a new Capture;
the old run remains immutable.

## Harness finalization

The Harness validates the Work result, source back-references, semantic
preservation, snapshot path confinement, UTF-8 content, hash, excerpts, and
the exact target partition. Only after all checks pass are snapshots copied
immutably to `.rh/runs/<run-id>/evidence_snapshots/` and the handoff paths
normalized to that run directory.

Failed submissions are retained only under `runs/<run-id>/submissions/`.
They do not create a canonical handoff, completion, or Research State change.
The coordinator may discard the failed run and prepare a fresh Work exchange;
the original run and failure trace remain immutable.

`PROVENANCE_AUDIT` does not select a method, approve a question, change a
Finding, alter an Evidence Gap, or grant Publication eligibility.
