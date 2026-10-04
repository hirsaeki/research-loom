# Host bootstrap

The repository does not assume that either host automatically discovers `skills/research-conversation/SKILL.md`. Load it explicitly for research-conversation tasks.

## Shared operating bootstrap

After loading the canonical Skill, use Loom through public CLI/Facade calls. For **ordinary** live research progress, explicitly request the conversation view on supported surfaces, for example `resume --view conversation --json`, rather than feeding default/detail output into the host.

When an actual Human Decision is about to be presented or resolved, follow the exact reference from that conversation result and read `decision show --request-id ... --json` (and `candidate show --candidate-id ... --json` when the full saved target is needed). Explicit diagnostic requests may similarly use these exact reads or `--view detail`. Return to a fresh conversation-view read for later ordinary progress when current state matters; do not reuse raw detail already present in session context as current approval state.

Do not inspect private SQLite or internal store paths. Do not repeat a mutating operation merely to recover detail after a lost response or projection failure.

## Codex

For a task whose goal is to conduct or resume research through Loom, first read:

1. `skills/research-conversation/SKILL.md`;
2. the referenced public-surface/interaction notes needed for the task;
3. the current public `resume --view conversation` output for the target workspace when resuming persisted work.

Do not load this skill merely because Codex is editing, reviewing, testing, or maintaining the research-loom repository.

## ChatGPT Work

In Work mode, explicitly open/read `skills/research-conversation/SKILL.md` from the repository/project before conducting Loom-backed research. Do not assume the `skills/` directory is automatically installed or discovered. Then use Loom through its public CLI/Facade with the same view-selection boundary while Work owns natural-language reasoning and presentation.

### Work non-bypass route

Work may use its browser, filesystem, Documents capability, PDF tooling, and other host
tools as helpers, but those tools do not replace the Loom public operations for a Loom-backed
research session. Keep the human-facing conversation in ordinary research/writing language
while following this internal route. **Do not narrate this route to the human.** Ordinary visible
progress should name the domain action/outcome (checking the specified sources, drafting the requested
sections, preparing an appearance-check document), not the Skill, plugin, CLI command, capability,
Research Package/Composition/Writer/Publication implementation label, or canonical/public path used
to do it. This applies to preambles, progress updates, and completion summaries. Exact mechanics
belong in tool/evaluator evidence unless the human explicitly asks for diagnostics or implementation
details.

Internal route:

1. **External research material:** prepare/execute the existing Desktop Research path, retain
   retrieval attempts, capture the exact original + trustworthy UTF-8 rendition, complete the
   attempt, and collect the result. Before using the source in downstream analysis or prose,
   verify it through `external materials list --workspace PATH --json` / material detail. A browser-visible or
   downloaded source that was never captured is still host working context, not persisted Loom
   research material.
2. **Research to writing:** before drafting, use the public Research Package and Writer path
   (`research-package build/show`, `writer-composition capture/select`, then
   `writer-round-trip export-input/import-response/inspect`) and load `skills/writer/SKILL.md`.
   Do not replace this with direct Markdown or document-file authoring.
3. **Appearance check:** before reporting a human-viewable pre-submission document as ready,
   load `skills/publication/SKILL.md` and use `publication preview` followed by
   `publication show`. Documents/PDF/LibreOffice may render the already-bound manuscript/preview for human
   inspection, but they are downstream presentation helpers, not a substitute Publication path.

If a required Loom operation fails, preserve and report that failure. Do not make a direct
workspace file or host-generated document and call the corresponding Loom-backed stage
complete merely because the human can open it.

### Work recovery after a canonical stage block

Treat a fail-closed Writer/Publication result as a state to resolve, not a signal to fall back
to direct authoring. In particular, when Writer export reports unmet Narrative prerequisites:

1. read the selected Composition through the public `writer-composition show` surface and
   inspect its validation diagnostics / `unmet_requires`;
2. use only existing public research/authority operations to satisfy the missing prerequisite.
   A saved Finding/other research candidate may be adopted only through its exact
   `state.apply_candidate` flow and any issued Confirmation/Human Decision; an Argument is
   proposed through `research.argument.propose` from current authoritative support and then
   adopted through the same authority semantics when required;
3. take a fresh public state read after authority changes, rebuild the Research Package,
   recapture/reselect the Composition, and retry `writer-round-trip export-input`;
4. if the prerequisite cannot be satisfied from current persisted research, stop that writing
   stage honestly. Do not create a direct Markdown/text/Documents draft and continue U4/U5 as
   though Writer succeeded.

Publication has the same gate: do not claim a successful appearance-check stage unless a
canonical Writer revision exists and `publication preview` / `publication show` succeeds. A
direct PDF is not a recovery path for a blocked Writer or Publication operation.

Keep this recovery machinery out of the normal human interface. When asking for a Human
Decision, ask about the research content and choices only; do not explain that Loom, a Skill,
or an internal rule requires the decision unless the human explicitly asks for diagnostics or
implementation mechanics.

For an ordinary decision turn, this restriction applies to the **whole user-visible response**, not only the sentence containing the question. Do not prepend or append a diagnostic rationale such as “the Research Conversation Skill requires this”, a Skill link, an internal exact-binding quotation, or “the system requires confirmation”. The response may contain only the decision's research meaning, meaningful choices, and any human-relevant consequence needed to choose. Keep implementation rationale in retained evaluator/tool evidence. Only a later explicit human request for diagnostics/mechanics unlocks that explanation.

## Supplied attachment intake

When the human supplies a file during a research conversation and asks Loom-backed
research to use it, do not leave the only copy in host/session context.

1. Materialize the host attachment beneath the opened workspace, preferably under
   `intake/chat/<host-attachment-id>/`. This is staging, not research authority.
2. Choose the semantic route explicitly from the human's intent.
3. Use the existing public ingress for that route.
4. Verify the durable public read before treating the attachment as persisted. The
   staging file may be removed after that verification.

### Project framing/context

Use `research-input register`. Workspace-relative `file` locators are resolved against
the opened workspace, so a host does not need to expose an arbitrary absolute host
path.

```json
{
  "file": "intake/chat/ATT-123/project-brief.md",
  "role": "project_brief",
  "expected_snapshot_id": "<current snapshot id>",
  "expected_snapshot_digest": "<current snapshot digest>",
  "provenance": {
    "source": "host_attachment",
    "host_attachment_id": "ATT-123"
  }
}
```

Register through `research-input register`, then verify with `research-input show`.
This is Project Input provenance, not Evidence.

### Research source

Use the existing Desktop Research flow. The host provides both the exact original and
a UTF-8 rendition inside the workspace staging directory, starts a bounded retrieval
attempt against the already prepared RUNNING Run, captures the pair with `external
capture`, and completes the attempt as `source_captured`. Final research candidates
still come through `external collect`.

```text
desktop_research.investigate -> RUNNING Run
  -> external attempt start
  -> host materializes original + UTF-8 rendition
  -> external capture
  -> external attempt complete(source_captured)
  -> external collect
```

If no trustworthy UTF-8 rendition can be produced, do not call a successful capture
with invented text. Complete the attempt as `failed`, `blocked`, or `unavailable` as
appropriate and preserve the reason as a gap/coverage limitation.

Do not put raw attachments under `intake/material-sources`; that directory is the
staging boundary for already-captured portable material imported from another Loom
workspace.

## Live acceptance record

A live host probe records: repository HEAD, Skill Git blob, fixture/runbook revision, host, visible model/config, scenario ID, supplied fixture/context, exact public sequence and selected view, any exact-detail lookup performed, actual response, rubric result, and date. No provider SDK, API key, local model server, or LLM judge is part of the repository test dependency.
