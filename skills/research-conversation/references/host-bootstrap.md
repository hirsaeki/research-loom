# Host bootstrap

The repository does not assume that either host automatically discovers `skills/research-conversation/SKILL.md`. Load it explicitly for research-conversation tasks.

## Codex

For a task whose goal is to conduct or resume research through Loom, first read:

1. `skills/research-conversation/SKILL.md`;
2. the referenced public-surface/interaction notes needed for the task;
3. the current public `resume` output for the target workspace when resuming persisted work.

Do not load this skill merely because Codex is editing, reviewing, testing, or maintaining the research-loom repository.

## ChatGPT Work

In Work mode, explicitly open/read `skills/research-conversation/SKILL.md` from the repository/project before conducting Loom-backed research. Do not assume the `skills/` directory is automatically installed or discovered. Then use Loom through its public CLI/Facade while Work owns natural-language reasoning and presentation.

## Live acceptance record

A live host probe records: repository HEAD, Skill commit/digest, host, visible model/config, scenario ID, supplied fixture/context, actual response, rubric result, and date. No provider SDK, API key, local model server, or LLM judge is part of the repository test dependency.
