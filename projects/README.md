# Projects

Project-specific configuration and inputs belong here: concrete research questions, scope, selected profiles, communication brief, project data/source references, and generated artifacts.

Reusable research methodology, organization rules, narrative rules, and publication rules belong under `profiles/`, not in project configuration.

Canonical Project Config contracts are under [`projects/contracts/`](contracts/). Synthetic executable fixtures are under [`projects/fixtures/`](fixtures/).

Project Config is declarative project input, not authoritative Research State or runtime database state. It may reference Core objects and directly request Profiles, but dependency resolution/composition remains owned by the canonical Profile contracts.
