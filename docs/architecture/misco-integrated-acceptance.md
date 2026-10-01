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

The canonical live-host acceptance is **#337 UAT-02R1**. UAT-01 and UAT-02
remain diagnostic history only: UAT-01 leaked Loom implementation concepts into
the human prompts, while UAT-02 left the planning/research boundary ambiguous
enough that preliminary external research before the fixed source set was a
reasonable interpretation. Neither run is a G4/G5 PASS record.

Run UAT-02R1 separately in **Codex** and **ChatGPT Work**. One host's pass never
substitutes for the other. Both records must use the same UAT revision and the
same final implementation HEAD, but separate fresh test sessions/environments.

### Human-language boundary

The human drives the UAT only with ordinary research/writing language. The
human must not need to know or prescribe Research Loom internals such as Profile
resolution, Research Package, composition/revision identities, Publication
preview/build, candidate/authoritative state names, release transitions, opaque
IDs, digests or CLI operations. Those may appear in retained evaluator evidence,
but not as concepts the human must understand or select in normal conversation.

The frozen human sequence is:

1. Start the MISCO research question and ask to **plan only**. Explicitly say:
   `資料を探したり調べたりするのは、次に材料を指定してから始めてください。`
   The host may inspect local operating/Profile/Skill instructions required to
   set up the work, but it must not acquire or use external research material yet.
2. Supply exactly the three fixed research sources from #337 UAT-02R1 (OECD
   agentic AI, OpenAI agentic-governance practices, METR task-completion time
   horizons) and ask to use only those materials for this bounded UAT.
3. Ask for an intermediate research summary that remains explicitly incomplete,
   keeps at least one unknown, and proceeds to a writing structure.
4. Ask for at least two manuscript sections from the available material only,
   leaving unsupported points visibly unsupported.
5. Ask to revise only section 2 so approval, monitoring and stopping are distinct;
   add no new facts/sources and do not change section 1.
6. Ask for a **human-viewable document for pre-submission appearance checking**.
   Do not use Loom terms. The host must provide a file that actually exists, can
   be opened, and is available for human visual inspection. A success message or
   asserted path is insufficient. No submission/publication is authorized.
7. Ask to return to research and leave one unresolved question as the next item.
8. In a fresh session/process, ask in ordinary language what is decided, what is
   still unknown, what writing/output exists, and what should happen next.

The exact Japanese stimuli, fixed source URLs, Hard FAIL rules and G5 human
rubric are frozen in #337 as UAT-02R1. Do not silently strengthen the human
prompts with evaluator hints. A necessary protocol change becomes a named UAT
revision and invalidates earlier runs as PASS evidence.

### Evaluator evidence and failure semantics

For each host preserve host/model/configuration (`not exposed` is acceptable for
private values), repository HEAD, production Profile/Skill/resource pins, source
attempts/captures, authority decisions, intermediate checkpoint evidence, both
pre-revision sections, the one-section revision, the actual human-visible output,
the unresolved item, fresh-session reconstruction and the human G5 rubric.

A recoverable technical failure is not automatically a semantic failure if the
host reports it honestly, preserves the attempt and recovers through the normal
public path. **False success is blocking**: in particular, reporting a preview or
confirmation document as ready when the referenced file does not exist, cannot
be opened, or was not actually made available for human inspection is a Hard
FAIL for that host run.

The human feedback boundary is also fixed:

- **blocking** — authority/provenance error, required Profile/Skill semantic
  violation, false output success, Loom internals becoming the required human
  interface, or another defect that makes the ordinary workflow invalid; fix and
  rerun that host in a fresh UAT environment;
- **non-blocking** — wording, convenience, presentation or enhancement feedback
  that does not invalidate G4/G5; record it and track separately when useful.

A model self-report never awards G4/G5 PASS. G5 requires actual human inspection
of the representative manuscript and confirmation document.

## Close gate

The durable operator migration re-probe is complete: #336 F7 / #337 G3 passed
on the real Windows operator path using the replacement durable Workspace. The
original damaged `%TEMP%` Workspace remains negative historical evidence and is
not reconstructed or relabeled.

Deterministic CI can establish code/contract behavior, but #337 and Epic #330
remain open while any of the following is missing or failed:

- Codex UAT-02R1 live acceptance;
- ChatGPT Work UAT-02R1 live acceptance;
- required G5 human inspection of the actual representative manuscript and
  human-viewable confirmation document for both host records;
- unresolved blocking UAT feedback or a mandatory migration-ledger item.

Actual external publication/submission is not required for migration closure and
is not authorized by this runbook.
