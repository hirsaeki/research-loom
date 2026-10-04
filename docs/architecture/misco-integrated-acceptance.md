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

The canonical live-host acceptance is **#337 UAT-02R4**. UAT-01, UAT-02,
UAT-02R1 and UAT-02R2 remain diagnostic history only. UAT-02R3 is also
superseded as the final protocol: R3 fixed U5 so it referred to the first/second
sections actually generated by U4, but its U2 human stimulus still only bounded
the three-source set and did not explicitly tell the host to inspect/read those
sources before U3 asked for an intermediate synthesis.

UAT-02R4 changes **U2 only relative to R3**. U1 and U3-U8 are unchanged from R3.
Because the changed instruction affects the research state entering U3, a run
that already executed R3 U2 cannot continue as R4. U1 evidence may be reusable
in principle only when it was executed against the same final implementation
semantics and the run had not started U2; for comparability, the final Codex and
ChatGPT Work records start fresh from U1.

Run UAT-02R4 separately in **Codex** and **ChatGPT Work**. One host's pass never
substitutes for the other. Both final records must use the same UAT revision and
the same resulting implementation semantics, but separate isolated host records.

### Human-language boundary

The human drives the UAT only with ordinary research/writing language. The
human must not need to know or prescribe Research Loom internals such as Profile
resolution, Research Package, composition/revision identities, Publication
preview/build, candidate/authoritative state names, release transitions, opaque
IDs, digests or CLI operations. Those may appear in retained evaluator evidence,
but not as concepts the human must understand or select in normal conversation.

The frozen human sequence is:

1. Start this as a **new case** and ask the host, in ordinary language, not to
   inherit prior research and to prepare a **new work environment for this
   research**. Then ask to **plan only** and explicitly say:
   `資料を探したり調べたりするのは、次に材料を指定してから始めてください。`
   The host must translate that request into a fresh isolated canonical research
   environment without requiring the human to know the Loom Workspace abstraction.
   It may inspect local operating/Profile/Skill instructions required to set up
   the work, but it must not acquire or use external research material yet.
2. Supply exactly the three fixed research sources from #337 UAT-02R4 (OECD
   agentic AI, OpenAI agentic-governance practices, METR task-completion time
   horizons) and say exactly:

   > 今回は次の3資料だけを調査材料として使ってください。追加で広く探す必要はありません。
   > - OECD: The agentic AI landscape and its conceptual foundations
   > - OpenAI: Practices for Governing Agentic AI Systems
   > - METR: Task-Completion Time Horizons
   >
   > この3資料を実際に確認して、今回の問いに関係する根拠・適用上の限界・まだ分からない点を整理してください。

   The host must retrieve/capture and actually inspect/read the fixed material
   before treating it as research input to U3; merely registering the source
   scope or confirming official landing pages does not satisfy U2. If the current
   research question is not yet authoritative when source analysis is about to
   begin, the host first asks the meaningful research decision in ordinary
   language and completes the existing authority path, without exposing internal
   IDs/state names or making the human prescribe the operation.
3. Ask for an intermediate research summary that remains explicitly incomplete,
   keeps at least one unknown, and proceeds to a writing structure.
4. Ask for at least two manuscript sections from the available material only,
   leaving unsupported points visibly unsupported.
5. After U4, refer to the ordered sections actually generated in that run. Ask
   to revise only the **second generated section** so approval, monitoring and
   stopping are distinct; add no new facts/sources and do not change the **first
   generated section**. Do not assume those are manuscript sections 1 and 2.
6. Ask for a **human-viewable document for pre-submission appearance checking**.
   Do not use Loom terms. The host must provide a file that actually exists, can
   be opened, and is available for human visual inspection. A success message or
   asserted path is insufficient. No submission/publication is authorized.
7. Ask to return to research and leave one unresolved question as the next item.
8. In a fresh session/process, ask in ordinary language what is decided, what is
   still unknown, what writing/output exists, and what should happen next.

The exact Japanese stimuli, fixed source URLs, Hard FAIL rules and G5 human
rubric are frozen in #337 as UAT-02R4. Do not silently strengthen the human
prompts with evaluator hints. A necessary protocol change becomes a named UAT
revision. Earlier evidence is reusable only when the new revision explicitly
states a bounded prefix-continuity rule, as R3 does for an R2 run stopped before U5.

### Evaluator evidence and failure semantics

For each host preserve host/model/configuration (`not exposed` is acceptable for
private values), repository HEAD, production Profile/Skill/resource pins, source
attempts/captures, authority decisions, intermediate checkpoint evidence, the
ordered U4 draft sections, proof that only the second generated section changed,
the actual human-visible output, the unresolved item, fresh-session reconstruction
and the human G5 rubric.

A recoverable technical failure is not automatically a semantic failure if the
host reports it honestly, preserves the attempt and recovers through the normal
public path. **False success is blocking**: in particular, reporting a preview or
confirmation document as ready when the referenced file does not exist, cannot
be opened, or was not actually made available for human inspection is a Hard
FAIL for that host run.

A host-native file/Documents workflow is also a **blocking bypass** when it replaces a
required Loom stage: external research material must be captured through the public
research path before downstream use; writing must be bound through Research Package /
selected Composition / Writer round-trip; and a human-visible confirmation document must
follow a canonical Publication preview. A polished Markdown/PDF result does not repair a
missing Loom stage.

A fail-closed canonical-stage result does not loosen this rule. If Writer export or another canonical operation reports unmet prerequisites, the host must satisfy those prerequisites through the existing public authority/state path and retry, or stop the stage honestly. Creating a provisional direct draft and then a PDF does not repair the failed Writer/Publication path, and U5 cannot turn such a bypass draft into valid revision evidence.

The human-language boundary applies to explanations as well as choices. A meaningful Human Decision request may be necessary, but the host must not justify that request by saying that Loom, a Skill, an internal rule/gate, candidate state, digest, or canonical/public path requires it unless the human explicitly asks for diagnostics or implementation mechanics.

The same boundary applies to **all ordinary user-visible progress and completion narration**, not just Human Decisions. A host fails G4 if it volunteers which Skill, Skill path, plugin, CLI command, host capability, Research Package/Composition/Writer/Publication implementation label, or canonical/public route it is using when the human only asked for ordinary research/writing work. Say what research/writing/document-check action is happening instead. Internal implementation detail may remain in retained tool/evaluator evidence and may be surfaced when the human explicitly asks for diagnostics/mechanics. The 2026-10-04 R4 Codex run that named the research-conversation, Writer, Documents/PDF Skills in ordinary progress is retained as blocking diagnostic evidence even though its canonical backend path was otherwise strong.

This prohibition covers the entire ordinary decision response. A semantically good decision prompt is still a blocking failure if a preamble or postscript volunteers the Skill name/link, quotes an internal binding rule, or says the system requires the decision. The allowed response shape is research meaning + meaningful choices + any human-relevant consequence needed to choose. Exact request-binding mechanics remain evaluator evidence and may be explained only after an explicit diagnostic/mechanics question from the human. The 2026-10-04 R4 Codex run that reached the canonical U2-U7 path but volunteered the Research Conversation Skill / exact-binding rationale at the RQ decision boundary is retained as diagnostic G4 FAIL evidence.

An ordinary Human Decision request is also a **hard stop** in the user-visible conversation: once the meaningful question/choices and any needed human-relevant consequence are stated, the host ends that visible turn and waits for the answer. Linking `SKILL.md`, `AGENTS.md`, internal runbooks/architecture docs, plugin/tool/command docs, or a local source path as justification is a blocking G4 failure, as is quoting an internal binding rule such as `Bind a human answer only to that issued request`. The fresh R4 run against `2f73d96d3bcaf686526d5935ee6e293d5a75744e` is retained as blocking G4 FAIL evidence for exactly this pattern: the RQ question itself was ordinary, but the same turn linked `research-conversation/SKILL.md` and quoted the binding rule.

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

- Codex UAT-02R4 live acceptance;
- ChatGPT Work UAT-02R4 live acceptance;
- required G5 human inspection of the actual representative manuscript and
  human-viewable confirmation document for both host records;
- unresolved blocking UAT feedback or a mandatory migration-ledger item.

Actual external publication/submission is not required for migration closure and
is not authorized by this runbook.
