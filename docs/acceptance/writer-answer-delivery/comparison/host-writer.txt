# Writer Skill

Use this Skill only after Research has produced a fixed Research Package and a Writer Composition version has been explicitly selected. It is a host-neutral transformation workflow; it does not own Research State.

## Public workflow

1. Export the selected sections with `writer-round-trip export-input` (or the equivalent public Application Facade operation).
2. Read only the detached `writer-input.json` and its embedded section inputs. Do not inspect private SQLite state, hidden workspace stores, or the archived migration material under `docs/migration/` to recover missing rules.
3. Draft each requested section from the supplied research objects/materials, citation scope, unresolved gaps, Narrative constraints, and communication brief. Apply `references/reader-flow.md` to give the reader a reason to begin, an advancing understanding through the middle, and a useful answer at the end.
4. Return a `writer_response` that matches `core/packages/writer-publication/writer-round-trip.schema.json`.
5. Import through `writer-round-trip import-response`. Treat an imported manuscript revision as an immutable writing artifact, not as research adoption or publication approval.

When reporting document-scoped review, use the public prepare-review target,
read the assembled manuscript and necessary fixed materials, then attach the
optional exact-target `document_review` described in `references/detached-input.md`.
Keep meaning and reader-experience findings separate and return concrete editing
actions through existing Writing Feedback. Unreviewed drafts remain importable;
never reuse a previous document review as proof for an edited manuscript.

## Research authority boundary

- Do not create new Evidence, causal findings, support judgments, generalizations, Recommendations, or missing research links.
- Preserve supplied counterevidence, qualifiers, limitations, unresolved gaps, and uncertainty. If a stronger claim would require new research, return Writing Feedback rather than inventing the support.
- Candidate/working exhibits and synthetic material remain non-authoritative. A piece of text does not become Evidence because it was available to the Writer.
- Use citations only inside the exported citation scope. Keep necessary source names and technical terms; reader-facing cleanup must not erase research provenance or limitations.

## Preserve conclusions, reasoning and strength

Preserve claim strength in both directions: do not strengthen supplied claims or weaken a supported central conclusion into mere possibility or “it depends”. Where supplied, organize the answer, principal evidence and warrant, and scope so readers understand the research judgement. Keep qualifications that change truth or strength near the conclusion; preserve counterevidence and substantive corrections. Do not replace the answer with caveats, a slogan without reasoning, or duplicate defensive/audit commentary.

If the central research judgement, warrant or applicability conditions are missing, return section-targeted Writing Feedback through the existing round-trip instead of inventing them. Ask the research host to inspect existing analysis and its links first; a missing writing-input connection does not by itself establish a need for additional research. This grants no authority to create Findings, causal claims, generalizations or Recommendations, adopt candidates, or bypass exact Human Decision/Confirmation.

Each paragraph must advance one question, claim or contrast. Treat competing paragraph roles as an editorial blocker requiring revision: do not interrupt the main argument with unrelated disclaimers, methodological supplements or repeated caveats. Coexistence of an argument and a qualification is not itself a violation; keep a necessary qualification or a contrast together when it constitutes the paragraph's point. Apply the placement choices and examples in `references/reader-flow.md`. This is an editing obligation, not a new Profile rule ID or a runtime gate blocking draft storage or Research.

This clarification does not silently amend approved Profile-delivered Writer rules. Keep the exact delivered inventory and pins; report a concrete conflict or missing rule through existing Writing Feedback for a separate regular Profile change.

## Profile-delivered Writer rules

A section input may contain `writer_profile`. If it is absent, do not invent Profile review. If present:

- use the exact `profile_pins`; do not select or compose another Profile version;
- read every delivered `WRITER_*` resource from the input itself;
- `WRITER_RULES` supplies the selected rule inventory; `WRITER_SOURCE_DOCUMENTS` supplies text referenced by each rule's `source.path` / `locator` and `additional_sources`. Preserve each source's authority: adopted design additions are not original approved Layer A clauses;
- only the exact IDs in `WRITER_RULES` / `review_plan` are Writer requirements. Each source document lists its `writer_rule_ids`; other clauses that happen to share the same approved source file are context, not additional Writer policy;
- do not fetch rule text from legacy storage or the network;
- synthetic few-shot material and Layer B/C audit/review support are not runtime instructions and must not appear in the delivered resources;
- complete every entry in `review_plan` in `profile_review`. The exact `rule_ids` for each review group must be preserved.

For each review group use one of:

- `conformant` — the applicable delivered rules in that group were checked and no violation was found;
- `violation` — one or more exact rule IDs were violated;
- `mixed` — the group contains both acceptable/not-applicable material and exact violated rules;
- `not_applicable` — the whole group does not apply to this section;
- `unevaluated` — the semantic/editorial check was not actually performed. This is never a PASS.

A `violation` or `mixed` result must name the exact `violated_rule_ids` and return section-targeted Writing Feedback whose `profile_rule_ids` include those IDs. Use `NARRATIVE_CONSTRAINT_CONFLICT` when a supplied meaning/preservation rule is broken; use another existing feedback category only when it more precisely describes the problem.

## Review groups

`review_plan` lists the review groups the selected Profile delivers, each with its exact `rule_ids`. Review every group against the bodies of its delivered `WRITER_RULES` items; a group's name is only a routing aid and adds no requirement of its own. A Profile may describe what its groups cover in its own resources, but the delivered rule text remains the authority.

For one concrete Profile's groups, see the example in `references/misco-profile.md`.

## Figures requested during drafting

If a figure/table would clarify supplied meaning, return to the Host's existing Research Exhibit/Package path described in `../../docs/operations/late-visual-needs.md`. Do not invent new analysis or attach a visual outside the fixed source binding. Let the Host resolve origin/section IDs internally, preserve this revision, and return with newly exported Writer inputs. Reuse unaffected prose only when its meaning and source scope still match; keep required qualifiers and unresolved gaps.

## Partial revision

When revising one section, base the response on the exact current manuscript revision and return only the changed section. The round-trip service reuses unchanged sections from that exact base; never recreate or silently rewrite them.

See `references/detached-input.md` for the expected detached-input boundary.

See `../../docs/architecture/versioned-writer-composition.md` for the Writer
Composition and round-trip contract, and `../../docs/operations/writer-document-review.md`
for document-scoped review.
