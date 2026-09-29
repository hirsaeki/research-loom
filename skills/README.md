# Skills

Canonical home for transformation workflows layered above canonical research state.

`writer/` contains the canonical host-neutral Writer Skill. It consumes selected detached Writer input and Profile-delivered rules. `publication/` contains the canonical host-neutral Publication Skill; it applies selected Publication resources plus explicitly sourced formal inputs and keeps diagnostic preview separate from release approval. Both communicate through versioned packages/contracts rather than direct access to internal research storage.

`research-conversation/` is the canonical host-facing operating contract for Loom-backed research conversations. It translates public Loom facts into ordinary research language without weakening authority/provenance semantics.

Writer and Publication are checkpoint consumers, not terminal-only phases: a host may create a composition, manuscript revision, or Publication preview from a saved Research Package while research is still ongoing, then return to Research. Those artifacts do not by themselves adopt research, declare research complete, or authorize release.
