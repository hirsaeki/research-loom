# Input Contract, Eligibility, Status, Feedback, and Stop Logic

This reference compiles the Human Approved Layer A I/O contract plus Research Harness interoperability controls into runtime selection rules. It does not add research or style rules.

## Approval semantics

Layer A permits only information that is approved **at that point in time**. For this Skill, `approved` means approved for Publication use as the current Research State snapshot. It does not imply final validation or Research freeze.

A research object may therefore be `CANDIDATE`, `REFINED`, `PROVISIONAL MODEL`, or another explicitly supplied non-final state and still be written when Publication Eligibility is `ELIGIBLE`. The Writer must preserve the supplied status and uncertainty and must not make a candidate object read as final.

## Publication Eligibility gate

Preferred metadata:

```yaml
publication_eligibility:
  status: ELIGIBLE | NOT_ELIGIBLE
  approved_by: optional
  decision_id: optional
  scope: optional
research_state_status: optional
```

- `ELIGIBLE`: use within the approved eligibility scope.
- `NOT_ELIGIBLE`: do not use as research content; stop dependent prose with `[NEEDS_INPUT]`.
- Metadata absent: allow backward compatibility only when the bundle is unambiguously represented as an approved Research State for Publication use.
- Unlabeled ideas/speculative notes are not approved inputs.

## Functional field map

| Function | Approved inputs normally needed | If absent |
|---|---|---|
| Background → purpose | problem, research purpose, scope, approved external materials/relations | Do not create a problem/gap; `[NEEDS_INPUT]` if the requested section cannot be written |
| Method introduction | methods, scope, constraints/uncertainties | Do not invent method rationale or RQ |
| Quantitative result | observations/results; interpretation only if approved; sample/limit metadata when applicable | Observation-only prose if interpretation absent; stop if the result itself is missing |
| Case | case facts, selection reason/role, permission/anonymization; approved interpretation if used | Do not invent comparison/generalization |
| Cross-case | approved comparison axes + approved comparison results + approved generalization range if any | Do not discover commonalities/differences yourself |
| Model | approved model, components/relations, formation reason, scope | Skip model phase if no approved model |
| Model revision | old approved model + revised approved model + approved changes/reasons + unresolved uncertainty | If revision reason/content is missing: `[NEEDS_INPUT]` + `MODEL_REVISION_UNRESOLVED` Feedback |
| Recommendation | approved recommendation + approved links to prior analysis; supplied actor/action/conditions/effect as available | Never create recommendation/count/pillars/effect |
| Final synthesis | approved purpose, observations/conclusions, recommendations, limits/uncertainty as present | Do not create implications/future work |
| Formal rendering | `formal_spec_profile`; conditional group type, permissions, figure/citation metadata, URL profile | `[NEEDS_INPUT]` with internal `HUMAN_DECISION_REQUIRED` |

## Publication Status ownership

```yaml
publication_status_authorization:
  stable_authorized: false
  final_authorized: false
  decision_id: optional
```

State space: `SCAFFOLD → PROVISIONAL → REVISED → INTEGRATED → STABLE → FINAL`.

- PHASE_DRAFT default: `PROVISIONAL`.
- REVISION default: `REVISED`.
- FINAL_EDITORIAL default: `INTEGRATED`.
- `STABLE`: only with explicit `stable_authorized: true`.
- `FINAL`: only with explicit `final_authorized: true` representing Human Release authorization.
- Never infer either authorization from prose quality, elapsed phases, or a request to “finish” the manuscript.
- FORMAL_RENDERING preserves status and cannot upgrade it by itself.

## Academic QA boundary

Use `[NEEDS_ACADEMIC_QA: ...]` when the task would require deciding whether:

- evidence actually entails a claim;
- an association is causal;
- a statistic permits generalization;
- a citation supports the proposed statement;
- an RQ/hypothesis/proposition/model/claim is supported, refuted, or valid.

The Writer may **render a supplied approved judgment**, but may not make the judgment.

## Formal-metadata boundary

Human decisions HD-01–HD-04 are already closed. Missing runtime values are input gaps, not unresolved policy. Specifically:

- page/font/indent and other formal settings come from the current formal specification profile;
- reference-list placement follows that formal specification;
- body citation placement and external-source footnote style come from the approved citation/formal profile, not historical examples;
- long raw URL display requires the human-approved URL display profile;
- color-chart QA applies only when color charts are actually used.

## Primary Exposition Location control

Preferred field: `primary_exposition_map`. Legacy alias: `home_chapter_map`.

A Primary Exposition Location is where a major method result/Finding is first explained sufficiently to the reader; it does not mean the result “belongs” to that chapter in the Research State.

When both fields exist, `primary_exposition_map` takes precedence. If they conflict, retain the primary map and record the conflict in QA/trace metadata; add `PRIMARY_EXPOSITION_CONFLICT` Publication Feedback when useful.

Outside the Primary Exposition Location, later chapters may cite/refer to the approved result/finding and state its **supplied** effect on later propositions/models/recommendations, but must not re-run or re-read the method evidence there.

## Publication Feedback

Publication Feedback reports composition-discovered gaps to the Orchestrator without turning the draft into research evidence or changing Research State.

Allowed types:

- `ARGUMENT_GAP`
- `QUESTION_SCOPE_AMBIGUITY`
- `MISSING_RESEARCH_INPUT`
- `ACADEMIC_QA_REQUIRED`
- `MODEL_REVISION_UNRESOLVED`
- `PRIMARY_EXPOSITION_CONFLICT`
- `FORMAL_METADATA_MISSING`
- `OTHER`

Each item may include `feedback_id`, `location`, `problem`, `missing_or_conflicting_state`, `suggested_destination`, and `blocking`.

Use Feedback separately from reader-facing prose. It is not Evidence/Finding/Claim. A Feedback item may mirror a `[NEEDS_INPUT]` or `[NEEDS_ACADEMIC_QA]` stop, or may be non-blocking when independent prose can still be written.

## Traceability

Internal IDs may be retained under `QA / trace metadata`. They are not deleted; they are compiled out of normal reader-facing prose unless the research-method section genuinely requires them.
