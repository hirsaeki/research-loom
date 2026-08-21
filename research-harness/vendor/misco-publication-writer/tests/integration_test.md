# Integration-like Synthetic Test — Acceptance Criteria RC1.1

Input/outputs are in `../examples/integration_like_flow.md`.

## Flow under test

Publication-eligible Candidate Phase Draft → Later approved Research Update → Revision → Manuscript Delta → Final Editorial → Human Stable authorization

## Acceptance criteria

| Check | Expected | Observed | Result |
|---|---|---|---|
| Candidate snapshot is eligible for early writing | CANDIDATE remains visibly non-final | Provisional wording retained | PASS |
| Phase draft remains provisional | No self-finalization | PROVISIONAL | PASS |
| Later Research State overrides prior prose | Old elegant statement is rewritten | Old single-factor wording removed | PASS |
| Counterevidence survives revision | Case C/D remain visible | Preserved in result/model prose | PASS |
| Approved model revision is explicit | Retain/add/change/unresolved are readable | All visible | PASS |
| Model is not repaired by Writer | All changes come from R1 | No extra change added | PASS |
| Manuscript Delta identifies affected sections | Ch3/Ch4/Ch5/summary mapped | Yes | PASS |
| Delta does not invent downstream impact | Only supplied trace used | Explicitly stated | PASS |
| Primary Exposition prevents result scattering | Raw survey not re-analyzed in Ch5 | Yes | PASS |
| Recommendation remains traceable | New recommendation linked to approved Case C/model update | Yes | PASS |
| Final Editorial integrates without re-analysis | Coherent prose, same approved facts | Yes | PASS |
| Final Editorial without Human Publication Stable authorization | `INTEGRATED` emitted | INTEGRATED | PASS |
| Explicit `stable_authorized=true` | `STABLE` permitted | STABLE | PASS |
| `final_authorized=false` | FINAL not emitted | Not emitted | PASS |
| Draft/Feedback reverse-flow guard | Neither becomes Research Evidence | Preserved | PASS |

**Integration-like synthetic test result: PASS**
