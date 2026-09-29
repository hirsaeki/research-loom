# MISCO Writer Profile application

Issue #334 connects the production Narrative/Writer Profile to the existing Writer Composition and round-trip paths. It does not add a composition engine, a research-quality oracle, or a publication renderer.

## Production boundary

`misco.writer@1.1.0` is resolved through the normal Profile resolver. Its canonical Narrative constraints continue to drive stage, dependency, section-purpose, preservation, and research-connection checks in Writer Composition. The Profile also carries two verified runtime resources:

- `WRITER_RULES` — the 127 approved Writer-facing migration items from #331.
- `WRITER_SOURCE_DOCUMENTS` — the normalized UTF-8 bytes of the eight Human-approved Layer A documents referenced by those items, with the exact `writer_rule_ids` applicable from each shared document.

The source-document resource exists so a detached host can inspect the actual approved rule text. It is not a second policy identity set. Only IDs present in `WRITER_RULES` / `review_plan` and listed in a document's `writer_rule_ids` are Writer requirements; other clauses in a shared source document are not promoted into Writer policy. Synthetic few-shot material, Layer B audit provenance, and Layer C review/decision support are excluded from both resources.

A selected section is exported with an optional `writer_profile` block. When present, it contains exact Profile pins, the verified `WRITER_*` resources from the Research Package, and a deterministic review plan. The host must use that detached input only; it must not recover rules from `research-profile/`, private SQLite state, or the network.

## Responsibility mapping

The 127 runtime items are mapped by their #331 responsibility class. The section-input builder derives this mapping from the delivered inventory, so a new parallel registry is unnecessary.

| Review group | Runtime input | Host/Human responsibility | Violation route | Acceptance |
| --- | --- | --- | --- | --- |
| `writer-input-contract` | rule inventory + Layer A source text | use only supplied/approved inputs; return unresolved research needs | section Writing Feedback with exact `profile_rule_ids` | D2, D4, D5 |
| `writer-pattern` | same | select a rhetorical pattern compatible with the supplied section purpose/material | Writing Feedback when the rule cannot be satisfied without changing research | D5 |
| `writer-transform` | same | apply approved phase/style transformations without changing research meaning or claim strength | Writing Feedback | D5 |
| `writer-terminology` | same | render internal wording for readers while retaining necessary technical terms and source names | Writing Feedback for actual rule violations; no blanket term deletion | D5, D6 |
| `narrative-guard` | same + canonical Narrative constraints | preserve counterevidence/qualifiers/limitations and do not add unsupported causality/generalization/relations | `NARRATIVE_CONSTRAINT_CONFLICT` or a more precise existing category | D1, D4, D5 |
| `writer-editorial-qa` | same | perform the approved editorial checklist where applicable | Writing Feedback | D5 |
| `writer-assembly-view` | same | respect assembly/return-to-research conditions without turning layout/order into Research authority | Writing Feedback | D5 |
| `writer-qa-boundary` | same | return research-validity/support questions upstream instead of deciding them in prose | Writing Feedback | D4, D5 |

The backend verifies pins, resource integrity, exact review-group/rule-ID coverage, immutable revision lineage, and Feedback linkage. It does not infer whether prose is stylistically or semantically conformant. A host may report `conformant`, `violation`, `mixed`, `not_applicable`, or `unevaluated`; `unevaluated` is never treated as PASS.

## Round trip and authority

The existing public Writer round trip remains authoritative for writing artifacts only:

```text
fixed Research Package + selected Writer Composition
  -> detached section inputs
  -> external Writer / human host
  -> response + Profile review + Writing Feedback
  -> immutable manuscript revision
```

Partial revision reuses unchanged section content from the exact current manuscript revision. Earlier revision bytes, Research Package pins, Profile pins, and Research State remain unchanged. Import success is not publication approval and does not create Evidence, Findings, causal support, generalizations, or Recommendations.

## Ablation

The acceptance test holds the Research Package and canonical Narrative constraints fixed and removes only `WRITER_RULES` from an otherwise identical package copy. Writer-specific delivery and its review plan disappear, while canonical Narrative constraints remain identical. This demonstrates the added delivery effect without weakening Core/Narrative guards.

No deterministic test claims that MISCO prose style becomes better. Semantic/style effects require actual Host/Human review; when such review is not performed, the recorded outcome is `unevaluated`.

## Host smoke

On 2026-09-29, the ChatGPT text host (GPT-5.6 Sol) loaded `skills/writer/SKILL.md` and the detached production input `WRI-59437087e3bce14fbb77ea12` (`sha256:d35fe09d8d7336ce91d4938cc66cdc9f7e60a83af9cfd2d0472ae99e40306478`). The host read the delivered Layer A source text for the Writer input contract, terminology firewall, and narrative guards, drafted both exported sections without adding a Finding, causal conclusion, or generalization, and reported only those three review groups as `conformant`. The other five groups were deliberately recorded as `unevaluated`; import success was therefore not treated as an all-rules PASS.

The response was imported through the public application facade as immutable manuscript revision `WMR-a70dd5256dd877384c118151-6d8405eee8ef4269b71a047f49617cf9` with digest `sha256:dc726fa3a37837c38372da3fb933886104e8a7c6dfca03d343a25908e2d1ef4e`. Re-submitting the exact response returned `VERIFIED_REUSE`. The Research State content digest remained `sha256:6c8933aaa2a2180831b4fe51e09949056de6a5bf33d64ede12424252c858e81a` before and after, and the revision records `research_state_mutation_performed: false`.

This is a representative real-host execution for #334, not a measurement that MISCO style is better. No comparative human style score was performed, so no style-effect claim is made. It also does not substitute for the Codex/Work integrated acceptance in #337.
