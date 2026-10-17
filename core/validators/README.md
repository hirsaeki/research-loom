# Core validators

[`non-overridable-invariants.yaml`](non-overridable-invariants.yaml) is the normative catalog of hard research invariants established by PR 3.

This directory holds that declarative catalog only; it contains no executable validators. The checks that enforce it live in `core/runtime/` (for example `state_validation.py` and `authority_validation.py`) and in the storage adapters. The directory keeps its name because Profile contracts and schemas reference this path.

These rules are intentionally separate from JSON Schema because most of them require graph or history checks across multiple objects. An implementation may enforce them in Python, SQL, a graph validator, an import boundary, or another mechanism, but the result must be equivalent.

## Override rule

Profiles, project configuration, plugins, skills, CLI flags, and storage adapters may add stricter rules. They must not disable or weaken a rule in the catalog.

Examples of **profile-owned** rules rather than Core invariants include:

- a Finding must have two independent Evidence items;
- a Finding must always contain limitations;
- a specific source type cannot support a specific causal claim;
- a particular research method or Counter Review lens is mandatory;
- a specific gate must pass before writing starts.

Those rules may be excellent policy for a given methodology or organization, but they are not universal research invariants.
