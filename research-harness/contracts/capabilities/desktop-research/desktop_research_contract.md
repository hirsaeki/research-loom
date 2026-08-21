# Desktop Research Capability Contract v0.3

Status: ACTIVE CONTRACT CANDIDATE / NOT CANONICAL RESEARCH SPEC

## Purpose

Use Work's native research capability as the research engine while the Harness owns
bounded context, artifact access, schemas, trace capture, audit, reduction, and Human
Decision routing. This contract does not define search order, prescribe a research
algorithm, automate a browser, or assert that Work exposes a programmable API.

Human/interactive Work execution and any future verified adapter consume the same
immutable `DESKTOP_RESEARCH` Context Pack and return `DesktopResearchHandoff`.

## Authority boundaries

- A Question Candidate or provisional Seed is an object to test, not an answer or
  authoritative question. Authority requires a recorded Human Decision.
- Workers may report Question Impact, Evidence Gaps, and candidate next methods.
  They must not select Survey, Delphi, Case, or another research method.
- Supporting evidence alone is incomplete. Counterevidence, conflicts, nulls,
  limitations, unknowns, and unsuccessful coverage must remain explicit.
- Publication Drafts and Publication Feedback are not Research Evidence and are
  forbidden from Desktop Research runtime.
- Archive/provenance roles remain denied unless a separate explicit permitted event
  authorizes access. `DESKTOP_RESEARCH` is not such an event.
- Publication Writer RC materials and Clean Publication Sources are not Desktop
  Research inputs.

## Inputs

The Context Pack must include a `DesktopResearchContextSpec` containing the current
question and its status, allowed source types, retrieval scope, forbidden roles,
coverage dimensions, execution mode, and a bounded artifact limit. The Artifact
Registry and `runtime_artifact_policy.yaml` remain authoritative for actual access.

The default Desktop Research source set includes `WORKING_PAPER`, `PREPRINT`,
`INDUSTRY_REPORT`, `CORPORATE_PUBLICATION`, `SOCIAL_MEDIA`, `ONLINE_FORUM`,
and `OTHER` for exploratory coverage. Every Evidence Capture carries a
`source_quality` flag (`HIGH`, `MEDIUM`, `LOW_CONFIDENCE`, or `LOW_TRUST`).
For exploratory material, `LOW_CONFIDENCE` is a stronger category than
`LOW_TRUST`, but neither authorizes an independent effect conclusion by itself.
Working papers, preprints, industry reports, and corporate publications must be
flagged `LOW_CONFIDENCE`; they are contextual or lead evidence and cannot
support an independent or causal effect conclusion. Social-media and forum
material must be flagged `LOW_TRUST`; it may support only `DESCRIPTIVE_CONTEXT`
or `LEAD_ONLY`, cannot be the sole support for a material Finding, and cannot
resolve an Evidence Gap. Company blogs and press releases use
`COMPANY_PRIMARY` with `COMPANY_CLAIM` and never establish independent effect
on their own. The quality flag does not replace the required acquisition
timestamp, text snapshot, locator, or SHA-256 proof.

## Outputs

`DesktopResearchHandoff` must contain Question Impact, Findings, Counterevidence and
its search summary, Unknowns, Evidence Gaps, candidate next-method options, coverage
and stopping assessment, back-references, and Publication Eligibility. Important
claims must resolve to an Evidence Citation and its SourceCapture. Each
SourceCapture records the original artifact and an exact UTF-8 full-text
rendition, each with a SHA-256. Each Citation maps an internal excerpt to its
locator and records evidence status, study role, writer use mode, and
verbatim-use status. The legacy v0.2 Evidence Capture shape is readable only as
an immutable migration input.

## Stopping

Stopping depends on coverage, saturation, unresolved material Evidence Gaps, and
remaining information value. A fixed source count is never sufficient. A run cannot
recommend stopping while a material Evidence Gap remains or remaining information
value is high.

## Trace and handoff

Work returns a structured result file and one original plus `text.txt` per
SourceCapture under `.rh/work_exchange/<run-id>/source_captures/<capture-id>/`.
The Harness validates confinement, both SHA-256 values, UTF-8, and excerpt
containment, then copies them immutably to `.rh/runs/<run-id>/source_captures/`
before canonical Handoff and State reduction. State Reducer preserves
counterevidence, unknowns, and Evidence Gaps. Review roles cannot substitute
for uncollected original studies in material effect or causal claims.
Candidate methods become Decision Broker options. Publication Eligibility follows the
existing Human-approved snapshot contract and is never inferred from prose quality.
