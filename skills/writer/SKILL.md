# Writer Skill

Use this Skill only after Research has produced a fixed Research Package and a Writer Composition version has been explicitly selected. It is a host-neutral transformation workflow; it does not own Research State.

## Public workflow

1. Export the selected sections with `writer-round-trip export-input` (or the equivalent public Facade operation).
2. Read only the detached `writer-input.json` and its embedded section inputs. Do not inspect private SQLite state, hidden workspace stores, or the legacy `research-profile/` tree to recover missing rules.
3. Draft each requested section from the supplied research objects/materials, citation scope, unresolved gaps, Narrative constraints, and communication brief.
4. Return a `writer_response` that matches `core/packages/writer-publication/writer-round-trip.schema.json`.
5. Import through `writer-round-trip import-response`. Treat an imported manuscript revision as an immutable writing artifact, not as research adoption or publication approval.

## Research authority boundary

- Do not create new Evidence, causal findings, support judgments, generalizations, Recommendations, or missing research links.
- Preserve supplied counterevidence, qualifiers, limitations, unresolved gaps, and uncertainty. If a stronger claim would require new research, return Writing Feedback rather than inventing the support.
- Candidate/working exhibits and synthetic material remain non-authoritative. A piece of text does not become Evidence because it was available to the Writer.
- Use citations only inside the exported citation scope. Keep necessary source names and technical terms; reader-facing cleanup must not erase research provenance or limitations.

## Profile-delivered Writer rules

A section input may contain `writer_profile`. If it is absent, do not invent Profile review. If present:

- use the exact `profile_pins`; do not select or compose another Profile version;
- read every delivered `WRITER_*` resource from the input itself;
- `WRITER_RULES` supplies the approved rule inventory; `WRITER_SOURCE_DOCUMENTS` supplies the approved Layer A source text referenced by each rule's `source.path` / `locator`;
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

## MISCO review responsibilities

The current MISCO rule inventory maps into eight delivered review groups. Review the actual rule bodies; these labels are only routing aids:

- `writer-input-contract` — use only approved/supplied inputs and return unresolved research needs instead of filling them in.
- `writer-pattern` — rhetorical pattern selection must fit the supplied section purpose and material.
- `writer-transform` — phase/style transformations must preserve the supplied research meaning and strength.
- `writer-terminology` — render internal vocabulary for readers without hiding necessary technical/source terminology.
- `narrative-guard` — do not invent causal claims, generalizations, fixed chapter/method patterns, counts, or unsupported relations.
- `writer-editorial-qa` — perform the approved editorial checklist where applicable.
- `writer-assembly-view` — respect assembly/return-to-research conditions; do not turn assembly order into Research authority.
- `writer-qa-boundary` — send validity/support/causal issues back as Writing Feedback rather than deciding them in prose.

## Figures requested during drafting

If a figure/table would clarify supplied meaning, return to the Host's existing Research Exhibit/Package path described in `../../docs/operations/late-visual-needs.md`. Do not invent new analysis or attach a visual outside the fixed source binding. Let the Host resolve origin/section IDs internally, preserve this revision, and return with newly exported Writer inputs. Reuse unaffected prose only when its meaning and source scope still match; keep required qualifiers and unresolved gaps.

## Partial revision

When revising one section, base the response on the exact current manuscript revision and return only the changed section. The round-trip service reuses unchanged sections from that exact base; never recreate or silently rewrite them.

See `references/detached-input.md` for the expected detached-input boundary.
