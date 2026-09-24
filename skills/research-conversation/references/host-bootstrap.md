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

## Live acceptance record

A live host probe records: repository HEAD, Skill Git blob, fixture/runbook revision, host, visible model/config, scenario ID, supplied fixture/context, exact public sequence and selected view, any exact-detail lookup performed, actual response, rubric result, and date. No provider SDK, API key, local model server, or LLM judge is part of the repository test dependency.
