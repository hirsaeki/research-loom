# Projects

Project-specific configuration and inputs belong here: concrete research questions, scope, selected profiles, communication brief, project data/source references, and generated artifacts.

Reusable research methodology, organization rules, narrative rules, and publication rules belong under `profiles/`, not in project configuration.

Canonical Project Config contracts are under [`projects/contracts/`](contracts/). Synthetic executable fixtures are under [`projects/fixtures/`](fixtures/).

Project Config is declarative project input, not authoritative Research State or runtime database state. It may reference Core objects and directly request Profiles, but dependency resolution/composition remains owned by the canonical Profile contracts.

## Production MISCO project

`misco-ai-2026/` contains the production **fresh-start** Project Config for the MISCO AI research project plus its deterministic production Profile resolution. It is distinct from `projects/fixtures/` and from the historical `%TEMP%\misco-ai-2026-probe2` Workspace, whose project identity remains `PRJ-1` during Profile-only migration. See [`misco-ai-2026/README.md`](misco-ai-2026/README.md) for fresh init and existing-Workspace advancement.
