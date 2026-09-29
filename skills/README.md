# Skills

Canonical home for transformation workflows layered above canonical research state.

`writer/` contains the canonical host-neutral Writer Skill. It consumes selected detached Writer input and Profile-delivered rules; `publication/` remains a separate responsibility. Both communicate through versioned packages/contracts rather than direct access to internal research storage.

`research-conversation/` is the canonical host-facing operating contract for Loom-backed research conversations. It translates public Loom facts into ordinary research language without weakening authority/provenance semantics.
