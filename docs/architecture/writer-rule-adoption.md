# Writer rule adoption and review scope (Issue 464)

## Authority and versions

This is the generalized design adopted in Issues #463/#464 on 2026-10-13.
It is not an original clause of the Human-approved Clean Source Pack, research
Evidence, or adoption of a research conclusion. The private papers, data,
figures and audit examples are not distributed. The analysis artifact is
identified by SHA-256 `9c4a4bcaac6b95cb043d4ae19f4812f6d2784932b8f9278e180cb6f5bf38aff8`;
no private artifact is needed at runtime.

`profiles/narrative/misco/1.1.0/profile.json` remains the immutable 1.1.0 selection.
Select `misco.writer` version `1.2.0` with manifest
`profiles/narrative/misco/1.2.0/profile.json` through ordinary Profile resolution.
No project configuration or existing Workspace is migrated. Existing input
receipts and no-Profile operation retain their contracts.

## Rule correspondence

The sole runtime inventory remains WRITER_RULES. Every existing ID is retained;
NG and QA entries remain views of the same rules rather than additional policy.
The following six rows clarify existing rules in the new version. Each carries
its original source plus this adopted design source; neither origin replaces
the other. Other rules are maintained and receive review classification only.

| Invariant | Canonical rule | Existing review group | Scope |
| --- | --- | --- | --- |
| Direction, certainty, scope and conditions | PUB-EV-04 | writer-qa-boundary | section |
| Observation, interpretation, concept, trial and completed validation | PUB-EV-05 | writer-qa-boundary | section |
| Decision-changing counterresults and failures | PUB-EV-06 | writer-qa-boundary | section |
| Evidence and reason for selecting judgment/action | PUB-RC-02 | writer-transform | section |
| Summary, body and final recommendations agree | PUB-RC-04 | writer-transform | document |
| No implicit research or normative adoption | QA-A | writer-editorial-qa | section |

### PUB-EV-04

Preserve the direction, certainty, scope and major conditions of supplied
conclusions in both directions: do not strengthen or weaken them. Clear prose
must neither invent certainty nor turn a supported answer into empty caution.

### PUB-EV-05

Distinguish observation, interpretation, concept, trial plan and completed
validation. A proposed intervention is not demonstrated effectiveness. A
conceptual study can be complete without validating every recommendation.

### PUB-EV-06

Retain supplied counterresults and unsuccessful outcomes that change the
decision, along with limitations and alternative explanations. Do not hide
them in an appendix or remove them for brevity. Required reference coverage
is structural; accurate interpretation still requires semantic review.

### PUB-RC-02

Major judgments and recommendations must preserve both their evidence and
the supplied reason for choosing that judgment/action. Missing reasons return
as Writing Feedback, not invention. Unknown budgets, deadlines, KPIs and
effects remain unknown; no fixed element count or PoC requirement applies.

### PUB-RC-04

Across any sections that summarize, develop or recommend, preserve agreement
of conclusions and important conditions. Determine these roles from content,
not chapter numbers, section IDs or Japanese heading matches. A section-only
review cannot establish document conformance. Definitions and methods need
no fabricated conclusion.

### QA-A

Writer must not implicitly adopt a new research conclusion or normative
judgment. Preserve the existing Human Decision and candidate boundaries;
missing decisions are returned through existing Feedback.

## Classification and outcomes

Each 1.2.0 item has `review` metadata: `check_kind`, `normativity`, `scope`,
`applicability` and `violation_action`. It is carried inside the existing pinned
WRITER_RULES resource, not a second rule registry or policy engine.
Input-contract references are structural; semantic content requires actual
Host/Human interpretation; editorial recommendations produce improvement
observations and do not alone stop draft storage or unrelated research.
Existing assembly procedures remain procedures, not new substantive criteria.
Classification does not promote optional/conditional source wording to must.

`profile_review.rule_results` covers exact delivered IDs in each group for
1.2.0: outcome, applicability, method and rationale. An applicable semantic
conformant result needs method `semantic`; structural ID presence cannot
substitute. Missing material or inspection is `unevaluated`, never N/A.
N/A needs `not_applicable` applicability and a content-based rationale.
Group N/A is legal only when all its rule results are N/A. Any unevaluated
rule prevents group conformance. These are declared review results, not proof
of independent review, Human approval or machine understanding.
Document-scoped results stay unevaluated in a section review. Issue #466 owns
target-bound document review and completion, using these same IDs/resources.
Issue #465 owns composition/writing procedure; this issue supplies its rules.

For 1.2.0, citation requirements explicitly selected in the section contract
must occur in the response's citation records (including a required locator).
The allowed Source inventory is not a usage checklist. Drafts with unresolved
semantic concerns remain importable as unevaluated/violation plus Feedback;
identity or explicit required-reference violations retain structural refusal.

## Recommendations and rejected promotions

PUB-EV-02 (topic/conclusion-first as appropriate), PUB-EV-10 (repetition),
PUB-AR-05/06 (connections), PUB-RC-01 (headings) and PUB-QT-03 (table exposition)
remain editorial recommendations. Do not promote fixed chapter/recommendation
counts, imperative wording, every-paragraph conclusion-first, or all-PoC
validation to hard rules. Existing terminology/first-explanation protections
from #448/#450 remain in place.

## Publication interface

Issue #457's official QA inventory remains the source for formal output,
format, rights and submission conditions. Writer content review corresponds
to semantic editorial QA, not `formal_specification` or comprehensive
Publication PASS. Neither Writer import nor exact pins certify full meaning
or formal compliance. Publication consumes target-matching review results;
it does not duplicate this rule inventory or adopt research conclusions.
