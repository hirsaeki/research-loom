# MISCO integrated acceptance and migration closure

Issue #337 is the final acceptance layer for the legacy MISCO Profile migration.
It does not add another research workflow or policy engine. It composes the
production Project/Profile inputs and the existing public Research, Writer and
Publication paths already accepted by #333-#336.

## Operating boundary

The migration has three deliberately different data paths:

1. **Approved legacy rule/configuration assets** may be migrated into the
   responsibility-specific production Profile / Project Config path with their
   provenance preserved.
2. **Legacy-only research data** (RQ, Evidence, Finding, material, prior virtual
   run feedback, etc.) is migration-validation input only. Formal transfer into
   a new current Loom Workspace uses the normal intake/capture -> candidate ->
   Human Decision path. Direct DB/root-JSON copying is not a migration path.
3. **Research already authoritative in a current Loom Workspace** is not
   re-intaken merely because Profiles advance. Profile generation advancement
   preserves those existing RQ/material/Decision/Attention bindings and changes
   only the current/future Profile binding.

## Research is not a one-way publication pipeline

Narrative, Writer and Publication are available at saved research checkpoints;
they are not reserved for a terminal "research complete" state.

```text
current Research State
        |
        v
Research Package checkpoint
        |
        v
Narrative / composition -> Writer draft -> Writer revision -> Publication preview
        |                                                        |
        +----------------------- return to Research <-------------+
```

The checkpoint/output meanings remain distinct:

- a saved candidate is not an adopted Finding;
- a Research Package is a pinned checkpoint, not a completion declaration;
- Writer output is a manuscript revision, not Research State;
- Publication preview/render success is not editorial approval or release;
- external release remains a separate Human Decision.

`tests/runtime/test_misco_integrated_acceptance.py` exercises this loop with the
checked-in production `misco-m3-2026` Project Config / EPS and deterministic
synthetic current-workspace material. It builds a Package, selects a two-section
composition, imports a two-section Writer response, revises only one section,
builds a formal Publication preview, verifies release remains unavailable
without editorial approval, then proposes new Research Attention after the
preview. The Research Snapshot digest stays unchanged through Writer and
Publication operations, and the Writer revision/preview can be reread after
Workspace reopen.

## Reused acceptance evidence

The final integration deliberately reuses the narrower child-Issue evidence
instead of duplicating every negative case:

| Responsibility | Primary deterministic evidence |
| --- | --- |
| migration inventory / rule ownership | `tests/contracts/test_misco_profile_migration_ledger.py` |
| production Profile resolution / detached resources | `tests/contracts/test_misco_production_profiles.py`, `tests/runtime/test_misco_production_profile_delivery.py` |
| Research / Organization quality application | `tests/runtime/test_research_quality_application.py` |
| Narrative / Writer application and one-section revision | `tests/runtime/test_misco_writer_profile_application.py` |
| Publication formal spec / full URL / QA / release boundary | `tests/runtime/test_misco_publication_profile_application.py` |
| fresh production project / existing Workspace Profile advancement | `tests/contracts/test_misco_production_project.py`, `tests/runtime/test_misco_project_migration.py` |
| host-facing language / authority behavior | `tests/runtime/test_issue294_research_conversation_skill.py` plus the live-host records below |
| cross-stage mid-research checkpoint | `tests/runtime/test_misco_integrated_acceptance.py` |

The child Issues already contain bounded ablations for Profile delivery,
consumer application, formal rendering and Workspace continuity. #337 adds only
the cross-stage checkpoint proof; it does not create another bypass mode solely
for an integration test.

## Original missing inputs — closure status

The #331 ledger is historical migration inventory and is not rewritten to hide
what was unknown at that time. Final status is recorded here instead:

| Ledger input | Final status |
| --- | --- |
| `INPUT-FORMAL-SPEC` | resolved in #335 from the corrected 2026-09-30 MISCO / 業際研 formal archive; exact 8-member archive pins and unchanged machine-applied body values are pinned by `misco.publication@1.3.0` |
| `INPUT-URL-DISPLAY` | resolved by Human Decision: long URLs are, in principle, displayed in full in references; canonical locators remain preserved |
| `INPUT-RESEARCH-GROUP-TYPE` | current formal profile pins `research_group_type_required=false`; no value is guessed. A future formal profile that requires it must obtain an explicit runtime value |
| `INPUT-PERMISSION` | remains material-conditional. Publication of affected non-public/interview/internal material is blocked without explicit permission/anonymization/original-review input; it is not a blocker for unrelated research or preview work |

## Real Workspace operator acceptance

CI/synthetic success does not satisfy #336 F7 / #337 G3. The original Windows
Workspace `%TEMP%\misco-ai-2026-probe2` was probed through the checked-in public
script and failed before Profile resolution because OS temporary-storage cleanup
had removed required Parent files including `workspace-binding.json` and Research
State. The remaining child directories/profile fragments are not sufficient to
reconstruct authoritative Research State, and that historical failure is kept as
negative live evidence. Do not hand-build missing binding/SQLite state and do not
claim continuity for that lost Workspace.

The replacement live migration acceptance is therefore a **durable real local
Workspace** under an operator-controlled non-TEMP path. Run:

```powershell
.\projects\misco-ai-2026\New-MiscoMigrationProbe.ps1 `
  -ExpectedHead <40-character-main-HEAD> `
  -Workspace D:\wsroot\scratch\loom-workspaces\probes\misco-profile-migration
```

The probe uses only public Loom operations for managed state. It reconstructs the
exact prior production generation (`misco.publication@1.2.0`) from pinned Git
history, creates a bounded real Workspace state without inventing Evidence or
Findings, records public before evidence, advances the Publication request to
`misco.publication@1.3.0`, reopens, and records public after evidence. Required
checks include:

1. the same project identity, lineage and Research Snapshot remain current;
2. the adopted migration RQ remains authoritative;
3. the active Attention map remains active and an unactivated candidate remains
   stored/inactive;
4. the operator-supplied Project Input is unchanged;
5. the historical Research Package and two-section Writer Composition remain
   exact and continue to pin their `1.2.0` source generation;
6. the current archived generation exposes Writer `1.1.0` + Publication `1.3.0`;
7. the first run appends exactly one Profile advancement event with
   `research_state_mutation_performed=false`;
8. an exact rerun returns `NOOP` and appends no event.

The generated `probe-result.json`, `before/`, `after/`, `target-generation/` and
per-command records are the replacement #336 F7 / #337 G3 operator evidence.
The original lost TEMP Workspace remains explicitly unresolved historical
continuity rather than being silently substituted by this replacement probe.

## Codex / ChatGPT Work live acceptance

Run the following separately in **Codex** and **ChatGPT Work**. One host's pass
never substitutes for the other. Use a fresh appropriate Workspace/session for
each host and record the exact repository HEAD and Profile pins.

1. Load the canonical `skills/research-conversation/` operating contract; load
   Writer/Publication skills only when the checkpoint reaches those operations.
2. Start from current operator input or formally intaken material, not from
   legacy-only research data copied into the Workspace.
3. Ask the host to explain current research state in ordinary research language.
   Internal Loom IDs may appear as trace detail when useful but must not be the
   choices the human is asked to make.
4. Create/adopt an RQ and gather representative material through public paths.
5. At an intentionally **incomplete** point, build/verify a Research Package
   checkpoint, create/select a Narrative composition, produce at least two
   Writer sections, and revise only one section.
6. Build a Publication preview using the production formal Profile. Human review
   must inspect the actual output; preview must not be described as release.
7. Return to Research from that preview and add/follow up an unresolved research
   item. Confirm no Writer/Publication action silently adopted new research.
8. Reopen from a different session/process and explain what is saved,
   authoritative, pending, manuscript-only, preview-only, and not yet evaluated.

For each live record preserve: host/model/configuration (private values may be
`not exposed`), Workspace identity, action sequence, selected Profile/policy
pins, relevant public outputs/artifacts, human rubric result, and unresolved
items. A model self-report alone is not a PASS record.

## Close gate

Deterministic CI can establish code/contract behavior, but #337 and Epic #330
remain open while any of the following is missing or failed:

- actual operator re-probe of the intended existing Loom Workspace;
- Codex live acceptance;
- ChatGPT Work live acceptance;
- required human inspection of representative Writer/Publication output;
- an unresolved mandatory migration-ledger item.

Actual external publication/submission is not required for migration closure and
is not authorized by this runbook.
