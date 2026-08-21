# Attention Intake and Distillation Contract v0.1

The intake drop is an untriaged Human-supplied batch. Its existence does not
grant Research or Publication access. The Harness registers one explicit batch,
freezes its files and hashes, and exposes only that bounded batch to the
`ATTENTION_DISTILLATION` Work task.

Interactive Work may organize and distill the supplied material into a
candidate Attention Map. Work may not adopt the candidate, delete an existing
Attention, choose a Research method, assert a Finding, or determine a Research
answer. The Harness audits the structured Handoff and stops at a typed Human
Decision before the candidate can become active guidance.

The active Map is guidance only. It is not Research Evidence, method authority,
answer authority, or Publication release authority. Every Map version and its
source drop remain immutable and are referenced by ID and SHA-256.

## Boundary

```text
Human drop -> explicit ingest -> immutable Drop Batch
  -> bounded Context Pack -> Work Handoff
  -> independent audit -> Human Map Decision
  -> immutable Map version + active pointer
```

The Harness does not scan a repository drop directory implicitly and does not
assume a Work API or automate the Work UI. The existing Coordinator transport
(`next` -> generated `TASK.md` -> exact result path -> `submit`) is reused.

## Required Handoff properties

- `run_id` and `drop_id` must match the pending Work request.
- Every frozen drop artifact must be listed as used or explicitly excluded
  with a reason.
- Candidate items must preserve source back-references, uncertainty,
  conflicts, duplicates, and proposed removals.
- The candidate Map must have a verified UTF-8 SHA-256.
- `evidence_eligible`, method authority, and answer authority are false.
- A failed schema, path, hash, or audit check remains an immutable failed Run;
  the active Map and Research State are unchanged.

## Human decision

The declared choices are `ADOPT_CANDIDATE_MAP`, `KEEP_CURRENT_MAP`, and
`REQUEST_REVISION`. Adoption creates a new immutable Map artifact and updates
only the active Map pointer. Prior Maps, Runs, Decisions, and Publication
snapshots remain immutable.
